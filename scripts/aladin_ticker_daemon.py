"""
ALADIN local tick daemon (Module A) - runs on YOUR PC during market hours and serves only you.

  python scripts/aladin_ticker_daemon.py            # then open the desk and type TICKS ON in the command line

What it does, and the limits it works inside (all measured against the real NSE site, not assumed):

* Data source "nse-web": the free NSE website feed, polled every ~3 s (never faster than 2 s) through a
  self-healing, rate-limited session (<= 3 requests/s). Each poll round makes 5 small calls, ~0.1-0.3 s each:
  /api/allIndices, /api/live-analysis-variations (gainers and losers) and /api/live-analysis-most-active-
  securities (volume and value). That is the index levels plus the ~100-200 stocks currently on NSE's own
  movers / most-active lists. The bulk "NIFTY 500 in one call" endpoint (/api/equity-stockIndices) now returns
  404 and the per-stock /api/quote-equity returns 403, so stocks outside those lists get NO live price here -
  the desk keeps showing their delayed price with its age. This is a hard limit of the free feed, not a bug.
* Data source "angel" (Angel One SmartAPI WebSocket) would cover every stock sub-second, but needs the
  account holder's login and TOTP keys. Not built in this version; --source angel says so and exits.
* Intraday Liquidity Sweep Engine: 15-minute bars from the ticks (volume = difference of cumulative traded
  quantity), levels from completed daily candles, sweeps scored with a 45-minute half-life. It only sees the
  stocks that appear in the feed above.
* Serves ws://127.0.0.1:8787/ws/ticks (loopback only, Origin-checked) in the same tick shape as relay/relay.py
  [ltp, open, high, low, prev_close, volume, exchange_ms], plus /health, and writes data/live_extra/ticks.json
  every 2 s (gitignored, never published - NSE's website terms restrict redistributing this feed).

Never log secrets. Never go faster than the rate limit. If NSE blocks this machine the daemon says so and
backs off; it does not try to evade the block.
"""

import argparse
import asyncio
import collections
import http
import json
import math
import os
import random
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))
BAR_MS = 15 * 60 * 1000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
ALLOWED_ORIGINS = ["https://atharvatyagi-gif.github.io", "http://127.0.0.1:8765", "http://localhost:8765", None]  # None = non-browser client (curl, tests)


def load_cfg():
    base = {"sweep": {"tf_min": 15, "relvol_min": 1.8, "wick_min": 0.55, "eq_tol": 0.0015, "breach_min": 0.0002,
                      "half_life_min": 45, "min_value_cr": 5}, "ws_port": 8787}
    try:
        j = json.loads((ROOT / "data" / "config" / "aladin_config.json").read_text(encoding="utf-8"))
        base["sweep"].update(j.get("sweep", {})); base["ws_port"] = j.get("ws_port", base["ws_port"])
    except (OSError, ValueError):
        pass
    return base


# ------------------------------------------------------------------ time helpers

def parse_ts(text):
    """NSE timestamp string (IST) -> epoch ms, or None. NSE uses three different formats across endpoints."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(datetime.strptime(str(text).strip(), fmt).replace(tzinfo=IST).timestamp() * 1000)
        except (ValueError, TypeError):
            continue
    return None


def market_window(now_ms):
    """Mon-Fri 09:00-15:45 IST."""
    t = datetime.fromtimestamp(now_ms / 1000, IST)
    return t.weekday() < 5 and (9, 0) <= (t.hour, t.minute) < (15, 45)


def ist_date(ms):
    return datetime.fromtimestamp(ms / 1000, IST).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ WAF-safe session

class NseError(Exception):
    pass


class NseSession:
    """cookie warm-up, auto-heal, backoff, circuit breaker, <= rate_per_s requests/s. Clock/sleep are injectable
    so the behaviour can be tested deterministically against a mock server."""

    def __init__(self, base="https://www.nseindia.com", rate_per_s=3.0, ua=UA, clock=time.monotonic, sleep=time.sleep,
                 jitter=random.uniform, warm_path="/market-data/live-equity-market", rewarm_s=480, breaker_fails=5, breaker_pause_s=300):
        self.base, self.rate, self.ua, self.clock, self.sleep, self.jitter = base, rate_per_s, ua, clock, sleep, jitter
        self.warm_path, self.rewarm_s, self.breaker_fails, self.breaker_pause_s = warm_path, rewarm_s, breaker_fails, breaker_pause_s
        self._window = collections.deque()
        self._s = None
        self._warmed_at = None
        self.heals = 0
        self.consecutive_fail = 0
        self.paused_until = 0.0
        self.last_ok = None
        self.requests_made = 0

    def _enc(self):
        try:
            import brotli  # noqa: F401
            return "gzip, deflate, br"
        except ImportError:
            return "gzip, deflate"          # without brotli, requests can't decode "br" - so don't advertise it

    def _new_session(self):
        s = requests.Session()
        s.headers.update({"User-Agent": self.ua, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
                          "Accept-Encoding": self._enc(), "Connection": "keep-alive"})
        return s

    def _throttle(self):
        while True:
            now = self.clock()
            while self._window and now - self._window[0] >= 1.0:
                self._window.popleft()
            if len(self._window) < self.rate:
                self._window.append(now)
                return
            self.sleep(max(0.001, 1.0 - (now - self._window[0])))

    def _warm(self):
        self._s = self._new_session()
        self._throttle()
        r = self._s.get(self.base + self.warm_path, headers={"Referer": self.base + "/"}, timeout=15)
        self.requests_made += 1
        self._warmed_at = self.clock()
        return r.status_code < 500

    def heal(self, reason):
        self.heals += 1
        self._s = None
        self.sleep(self.jitter(1.5, 4.0))
        try:
            self._warm()
        except requests.RequestException:
            pass

    @property
    def status(self):
        now = self.clock()
        paused = now < self.paused_until
        return {"ok": self.consecutive_fail == 0 and not paused, "paused": paused, "heals": self.heals,
                "consecutive_fail": self.consecutive_fail, "last_ok_age_s": None if self.last_ok is None else round(now - self.last_ok, 1),
                "paused_for_s": round(self.paused_until - now, 1) if paused else 0}

    def get_json(self, path, params=None, referer=None, max_tries=4):
        if self.clock() < self.paused_until:
            raise NseError("circuit breaker open: paused after repeated failures")
        if self._s is None or (self._warmed_at is not None and self.clock() - self._warmed_at > self.rewarm_s):
            try:
                self._warm()
            except requests.RequestException as e:
                self._fail(); raise NseError(f"warm-up failed: {type(e).__name__}")
        back, err = 1.0, "no attempt"
        for _ in range(max_tries):
            self._throttle()
            try:
                r = self._s.get(self.base + path, params=params, headers={"Referer": referer or self.base + self.warm_path}, timeout=15)
                self.requests_made += 1
            except requests.RequestException as e:
                err = type(e).__name__
                self.sleep(back); back = min(60.0, back * 2); continue
            if r.status_code in (401, 403):
                err = f"HTTP {r.status_code}"; self.heal(err); continue
            if r.status_code == 429 or r.status_code >= 500:
                err = f"HTTP {r.status_code}"; self.sleep(back); back = min(60.0, back * 2); continue
            if r.status_code != 200:
                err = f"HTTP {r.status_code}"; break
            try:
                j = r.json()
            except ValueError:
                err = "non-JSON body"; self.heal(err); continue
            self.consecutive_fail = 0; self.last_ok = self.clock()
            return j
        self._fail()
        raise NseError(err)

    def _fail(self):
        self.consecutive_fail += 1
        if self.consecutive_fail >= self.breaker_fails:
            self.paused_until = self.clock() + self.breaker_pause_s
            self.consecutive_fail = 0           # the pause is the penalty; a fresh run of failures must follow a recovery


# ------------------------------------------------------------------ parsers (real response shapes in tests/fixtures)

def _num(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def parse_variations(js):
    """/api/live-analysis-variations -> {SYM: [ltp, open, high, low, prev_close, cum_volume, exchange_ms]}"""
    out = {}
    for k, g in (js or {}).items():
        if not isinstance(g, dict) or "data" not in g:
            continue
        ms = parse_ts(g.get("timestamp"))
        for r in g["data"]:
            t = [_num(r.get("ltp")), _num(r.get("open_price")), _num(r.get("high_price")), _num(r.get("low_price")),
                 _num(r.get("prev_price")), _num(r.get("trade_quantity")), ms]
            if r.get("symbol") and t[0] is not None and t[5] is not None:
                prev = out.get(r["symbol"])
                if not prev or (t[5] or 0) >= (prev[5] or 0):
                    out[r["symbol"]] = t
    return out


def parse_most_active(js):
    out = {}
    for r in (js or {}).get("data", []):
        t = [_num(r.get("lastPrice")), _num(r.get("open")), _num(r.get("dayHigh")), _num(r.get("dayLow")),
             _num(r.get("previousClose")), _num(r.get("totalTradedVolume")), parse_ts(r.get("lastUpdateTime"))]
        if r.get("symbol") and t[0] is not None and t[5] is not None:
            out[r["symbol"]] = t
    return out


def parse_indices(js):
    ms = parse_ts((js or {}).get("timestamp"))
    out = {}
    for r in (js or {}).get("data", []):
        name = r.get("index")
        t = [_num(r.get("last")), _num(r.get("open")), _num(r.get("high")), _num(r.get("low")), _num(r.get("previousClose")), 0, ms]
        if name and t[0] is not None:
            out[name] = t
    return out


# ------------------------------------------------------------------ bars, levels, sweeps

@dataclass
class Level:
    kind: str       # PDH PDL SWH SWL EQH EQL
    price: float
    w: float


@dataclass
class Bar:
    sym: str
    t0: int
    o: float
    h: float
    l: float
    c: float
    v: int
    closed: bool
    partial: bool = False     # the daemon started mid-bar, so this bar's open/volume are incomplete: never confirms a sweep


@dataclass
class Sweep:
    sym: str
    dir: int
    level: Level
    bar_t0: int
    rvol: float
    wick: float
    strength: float
    confirmed: bool
    ts_ms: int


class BarBuilder:
    """15-minute bars from 09:15 IST out of ticks. Bar volume = difference of cumulative traded quantity between
    ticks (never negative; a day change or a counter reset starts a fresh baseline)."""

    def __init__(self):
        self._cur, self._cum, self._day = {}, {}, {}

    def developing(self, sym):
        c = self._cur.get(sym)
        return None if c is None else Bar(sym, c["t0"], c["o"], c["h"], c["l"], c["c"], c["v"], False, c["partial"])

    def on_tick(self, sym, price, cum_vol, ts_ms):
        t = datetime.fromtimestamp(ts_ms / 1000, IST)
        if not ((9, 15) <= (t.hour, t.minute) < (15, 30)):
            return []
        day = t.strftime("%Y-%m-%d")
        t0 = ts_ms - (ts_ms % BAR_MS)
        closed = []
        had_baseline = self._day.get(sym) == day and sym in self._cum and cum_vol >= self._cum[sym]
        delta = (cum_vol - self._cum[sym]) if had_baseline else 0
        self._cum[sym], self._day[sym] = cum_vol, day
        cur = self._cur.get(sym)
        if cur is not None and (cur["t0"] != t0 or cur["day"] != day):
            closed.append(Bar(sym, cur["t0"], cur["o"], cur["h"], cur["l"], cur["c"], cur["v"], True, cur["partial"]))
            cur = None
        if cur is None:
            self._cur[sym] = {"t0": t0, "day": day, "o": price, "h": price, "l": price, "c": price, "v": max(0, delta),
                              "partial": (not had_baseline) or (ts_ms - t0 > 60_000 and not had_baseline)}
        else:
            cur["h"], cur["l"], cur["c"] = max(cur["h"], price), min(cur["l"], price), price
            cur["v"] += max(0, delta)
        return closed


def _dedupe(levels):
    best = {}
    for L in levels:
        k = round(L.price, 4)
        if k not in best or L.w > best[k].w:
            best[k] = L
    return list(best.values())


def build_levels(rows, today=None, eq_tol=0.0015):
    """rows = daily candles [[date, o, h, l, c, v], ...] oldest first. Only sessions strictly before `today` count."""
    rows = [r for r in rows if today is None or r[0] < today]
    if len(rows) < 3:
        return []
    last_close = rows[-1][4]
    L = [Level("PDH", rows[-1][2], 0.6), Level("PDL", rows[-1][3], 0.6)]
    w20 = rows[-20:]
    L += [Level("SWH", max(r[2] for r in w20), 0.8), Level("SWL", min(r[3] for r in w20), 0.8)]
    w60 = rows[-60:]
    ph = [w60[i][2] for i in range(2, len(w60) - 2) if all(w60[i][2] > w60[i + d][2] for d in (-2, -1, 1, 2))]
    pl = [w60[i][3] for i in range(2, len(w60) - 2) if all(w60[i][3] < w60[i + d][3] for d in (-2, -1, 1, 2))]

    def clusters(vals):
        vals, out, cur = sorted(vals), [], []
        for v in vals:
            if cur and abs(v - cur[-1]) / min(v, cur[-1]) <= eq_tol:
                cur.append(v)
            else:
                if len(cur) >= 2:
                    out.append(cur)
                cur = [v]
        if len(cur) >= 2:
            out.append(cur)
        return out
    L += [Level("EQH", max(c), 1.0) for c in clusters(ph)] + [Level("EQL", min(c), 1.0) for c in clusters(pl)]
    L = [x for x in _dedupe(L) if abs(x.price / last_close - 1) <= 0.05]
    up = sorted([x for x in L if x.price >= last_close], key=lambda x: x.price)[:6]
    dn = sorted([x for x in L if x.price < last_close], key=lambda x: -x.price)[:6]
    return up + dn


def dkey(sym):
    return "".join(c if re.match(r"[A-Za-z0-9]", c) else "_" + format(ord(c), "x") for c in sym)


class LevelBook:
    def __init__(self, root=ROOT, cfg=None):
        self.root, self.cfg, self._cache = root, cfg or load_cfg(), {}

    def clear(self):
        self._cache.clear()

    def build(self, sym, today=None):
        if sym in self._cache:
            return self._cache[sym]
        try:
            rows = json.loads((self.root / "data" / "terminal" / "daily" / f"{dkey(sym)}.json").read_text(encoding="utf-8"))["d"]
            self._cache[sym] = build_levels(rows, today, self.cfg["sweep"]["eq_tol"])
        except (OSError, ValueError, KeyError):
            self._cache[sym] = []
        return self._cache[sym]


class SlotVolumes:
    """Mean volume of the same 15-minute slot over the last <=5 earlier sessions, from data/terminal/intra/<shard>.json['w']."""

    def __init__(self, root=ROOT):
        self.root, self._shards = root, {}

    def mean(self, sym, hhmm, today):
        sh = sym[0].upper() if sym[0].isalpha() else "0"
        if sh not in self._shards:
            try:
                self._shards[sh] = json.loads((self.root / "data" / "terminal" / "intra" / f"{sh}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._shards[sh] = {}
        w = (self._shards[sh].get(sym) or {}).get("w") or []
        vols = [r[5] for r in w if r[0][:10] < today and r[0][11:16] == hhmm and r[5]]
        return statistics.mean(vols[-5:]) if vols else None


class SweepDetector:
    def __init__(self, cfg=None):
        self.c = (cfg or load_cfg())["sweep"]

    def evaluate(self, bar, levels, base_vol, now_ms=None):
        c = self.c
        if not base_vol or base_vol <= 0 or bar.h <= bar.l or bar.c <= 0 or (bar.h - bar.l) / bar.c < 0.002:
            return []
        rvol = bar.v / base_vol
        if rvol <= c["relvol_min"]:
            return []
        rng = bar.h - bar.l
        up_wick, lo_wick = (bar.h - max(bar.o, bar.c)) / rng, (min(bar.o, bar.c) - bar.l) / rng
        ts = bar.t0 + BAR_MS if bar.closed else (now_ms or bar.t0)
        out = []
        for L in levels:
            if L.kind.endswith("H") and bar.h > L.price * (1 + c["breach_min"]) and bar.c < L.price and up_wick > c["wick_min"]:
                d, wick = -1, up_wick
            elif L.kind.endswith("L") and bar.l < L.price * (1 - c["breach_min"]) and bar.c > L.price and lo_wick > c["wick_min"]:
                d, wick = 1, lo_wick
            else:
                continue
            s = min(1.0, max(0.1, 0.5 * min(1, (rvol - c["relvol_min"]) / 1.2) + 0.5 * min(1, (wick - c["wick_min"]) / 0.35))) * L.w
            out.append(Sweep(bar.sym, d, L, bar.t0, rvol, wick, s, bar.closed, ts))
        return out


def s_sweep(sweeps, now_ms, half_life_min=45):
    """Today's confirmed sweeps -> a score in [-100, +100] with exponential decay (resets with the list each session)."""
    tot = sum(s.dir * 100 * s.strength * math.exp(-max(0.0, (now_ms - s.ts_ms) / 60000) / half_life_min) for s in sweeps if s.confirmed)
    return max(-100.0, min(100.0, tot))


# ------------------------------------------------------------------ hub

class Hub:
    def __init__(self, cfg=None, levelbook=None, slotvols=None, value_ok=None, sweep_log_dir=None, clock=time.time):
        self.cfg = cfg or load_cfg()
        self.levels = levelbook or LevelBook(cfg=self.cfg)
        self.slots = slotvols or SlotVolumes()
        self.value_ok = value_ok or (lambda sym: True)
        self.log_dir = sweep_log_dir
        self.clock = clock
        self.bars, self.det = BarBuilder(), SweepDetector(self.cfg)
        self.ticks, self.kind, self.pending, self.ts_seen = {}, {}, {}, {}
        self.confirmed, self.forming, self.done_vols = {}, {}, {}
        self.new_sweeps, self._day = [], None
        self.src_name, self.src_status = "nse-web", {}

    def _now_ms(self):
        return int(self.clock() * 1000)

    def on_tick(self, sym, ltp, o, h, l, pc, vol, ts_ms, kind="stock"):
        if ltp is None:
            return False
        prev = self.ticks.get(sym)
        if prev and prev[0] == ltp and prev[5] == vol:
            return False
        ts = ts_ms or self._now_ms()
        t = [ltp, o, h, l, pc, vol, ts]
        self.ticks[sym] = t; self.pending[sym] = t; self.kind[sym] = kind; self.ts_seen[sym] = ts
        if kind == "stock" and vol is not None:
            self._bars(sym, ltp, vol, ts)
        return True

    def _bars(self, sym, ltp, vol, ts):
        day = ist_date(ts)
        if day != self._day:
            self._day, self.confirmed, self.forming, self.done_vols = day, {}, {}, {}
        for bar in self.bars.on_tick(sym, ltp, vol, ts):
            base = self._base(sym, bar)
            if not bar.partial:
                self.done_vols.setdefault(sym, collections.deque(maxlen=8)).append(bar.v)
            if bar.partial or not self.value_ok(sym):
                continue
            for sw in self.det.evaluate(bar, self.levels.build(sym, day), base):
                key = (sw.level.kind, sw.level.price, sw.bar_t0)
                if all((x.level.kind, x.level.price, x.bar_t0) != key for x in self.confirmed.get(sym, [])):
                    self.confirmed.setdefault(sym, []).append(sw); self.new_sweeps.append(sw); self._log(sw, bar)
        dev = self.bars.developing(sym)
        if dev and not dev.partial and self.value_ok(sym):
            self.forming[sym] = self.det.evaluate(dev, self.levels.build(sym, day), self._base(sym, dev), ts)

    def _base(self, sym, bar):
        hhmm = datetime.fromtimestamp(bar.t0 / 1000, IST).strftime("%H:%M")
        m = self.slots.mean(sym, hhmm, ist_date(bar.t0))
        if m:
            return m
        d = self.done_vols.get(sym)
        return statistics.median(d) if d and len(d) >= 8 else None

    def _log(self, sw, bar):
        if not self.log_dir:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_dir / f"{ist_date(sw.ts_ms)}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sym": sw.sym, "dir": sw.dir, "lvl": sw.level.kind, "px": sw.level.price, "close": bar.c,
                                    "rvol": round(sw.rvol, 2), "wick": round(sw.wick, 2), "score": round(sw.dir * 100 * sw.strength), "ts": sw.ts_ms}) + "\n")
        except OSError:
            pass

    def drain(self):
        ch, ns = self.pending, self.new_sweeps
        self.pending, self.new_sweeps = {}, []
        return ch, ns

    def sweep_msg(self, sweeps):
        now = self._now_ms()
        rows = [{"sym": s.sym, "dir": s.dir, "lvl": s.level.kind, "px": round(s.level.price, 2), "rvol": round(s.rvol, 2), "wick": round(s.wick, 2),
                 "score": round(s.dir * 100 * s.strength), "confirmed": s.confirmed, "ts": s.ts_ms} for s in sweeps]
        agg = {sym: round(s_sweep(v, now, self.cfg["sweep"]["half_life_min"])) for sym, v in self.confirmed.items()}
        return {"type": "sweeps", "s": rows, "agg": agg}

    def stale(self):
        now = self._now_ms()
        return market_window(now) and any(now - ts > 120_000 for ts in self.ts_seen.values()) if self.ts_seen else False

    def market(self):
        now = self._now_ms()
        if not market_window(now):
            return "closed"
        freshest = max(self.ts_seen.values(), default=None)
        return "closed" if freshest is not None and ist_date(freshest) != ist_date(now) else "open"        # data still from an earlier day = holiday

    def static_dump(self):
        now = self._now_ms()
        sw = {sym: {"s": round(s_sweep(v, now, self.cfg["sweep"]["half_life_min"])), "ev": [{"lvl": x.level.kind, "dir": x.dir, "ts": x.ts_ms} for x in v]}
              for sym, v in self.confirmed.items()}
        return {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "src": self.src_name, "q": self.ticks, "sweeps": sw}


# ------------------------------------------------------------------ source + server

class NseWebSource:
    name = "nse-web"

    def __init__(self, session, interval=3.0):
        self.s, self.interval = session, max(2.0, interval)
        self.latency_ms, self.last_ok_ms = None, None

    @property
    def status(self):
        return {**self.s.status, "latency_ms": self.latency_ms, "source": self.name}

    def poll_once(self):
        """One round of 5 small requests. Returns {SYM: tick} of everything seen this round, split by kind."""
        stocks, idx = {}, {}
        t0 = time.monotonic()
        idx.update(parse_indices(self.s.get_json("/api/allIndices")))
        for which in ("gainers", "loosers"):
            stocks.update(parse_variations(self.s.get_json("/api/live-analysis-variations", {"index": which})))
        for which in ("volume", "value"):
            stocks.update(parse_most_active(self.s.get_json("/api/live-analysis-most-active-securities", {"index": which})))
        self.latency_ms = round((time.monotonic() - t0) * 1000)
        return stocks, idx


async def run_source(source, hub, broadcast_fn, stop):
    while not stop.is_set():
        now = int(time.time() * 1000)
        try:
            if market_window(now):
                stocks, idx = await asyncio.to_thread(source.poll_once)
                for sym, t in stocks.items():
                    hub.on_tick(sym, t[0], t[1], t[2], t[3], t[4], t[5], t[6], "stock")
                for sym, t in idx.items():
                    hub.on_tick(sym, *t, kind="index")
                delay = source.interval - (source.latency_ms or 0) / 1000
            else:
                idx = parse_indices(await asyncio.to_thread(source.s.get_json, "/api/allIndices"))
                for sym, t in idx.items():
                    hub.on_tick(sym, *t, kind="index")
                delay = 60
        except NseError as e:
            print(f"[{datetime.now(IST):%H:%M:%S}] NSE: {e} (session {source.s.status})", file=sys.stderr)
            delay = 30 if "paused" in str(e) else 5
        hub.src_status = source.status
        await broadcast_fn()
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.5, delay))
        except asyncio.TimeoutError:
            pass


def health_json(hub, source, clients, port):
    return {"src": hub.src_name, "market": hub.market(), "session": hub.src_status or source.status, "symbols_tracked": len(hub.ticks),
            "stale": hub.stale(), "clients": len(clients), "port": port, "poll_latency_ms": source.latency_ms}


async def serve(hub, source, port, *, host="127.0.0.1", dump_path=None, stop=None):
    from websockets.asyncio.server import serve as ws_serve, broadcast
    stop = stop or asyncio.Event()
    clients = set()
    hello = lambda: {"type": "hello", "ok": True, "src": hub.src_name, "port": port, "market": hub.market(), "stale": hub.stale()}

    async def handler(ws):
        clients.add(ws)
        try:
            await ws.send(json.dumps(hello()))
            await ws.send(json.dumps({"type": "snap", "q": hub.ticks}, separators=(",", ":")))
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if m.get("type") == "focus":
                    missing = [s for s in (m.get("syms") or [])[:50] if s not in hub.ticks]
                    if missing:
                        await ws.send(json.dumps({"type": "warn", "msg": "NSE's free feed only carries the movers / most-active lists: no live price for " + ", ".join(missing[:5]) + ("..." if len(missing) > 5 else "")}))
        finally:
            clients.discard(ws)

    def process_request(conn, request):
        if request.path.split("?")[0] == "/health":
            resp = conn.respond(http.HTTPStatus.OK, json.dumps(health_json(hub, source, clients, port)))
            resp.headers["Content-Type"] = "application/json"
            return resp
        return None

    async def broadcast_fn():
        ch, ns = hub.drain()
        if ch and clients:
            broadcast(clients, json.dumps({"type": "ticks", "q": ch}, separators=(",", ":")))
        if ns and clients:
            broadcast(clients, json.dumps(hub.sweep_msg(ns), separators=(",", ":")))

    async def dumper():
        while not stop.is_set():
            if dump_path:
                try:
                    dump_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dump_path.with_suffix(".tmp"); tmp.write_text(json.dumps(hub.static_dump(), separators=(",", ":")), encoding="utf-8")
                    os.replace(tmp, dump_path)
                except OSError:
                    pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass

    async with ws_serve(handler, host, port, origins=ALLOWED_ORIGINS, process_request=process_request):
        await asyncio.gather(run_source(source, hub, broadcast_fn, stop), dumper())


def main(argv=None):
    import aladin_env
    aladin_env.load_env()                                  # so ALADIN_WS_PORT / ALADIN_SOURCE in .env apply to the defaults below
    ap = argparse.ArgumentParser(description="ALADIN local tick daemon (loopback only)")
    ap.add_argument("--source", default=os.environ.get("ALADIN_SOURCE", "auto"), choices=["auto", "nse-web", "angel"])
    ap.add_argument("--port", type=int, default=int(os.environ.get("ALADIN_WS_PORT", 0)) or None)
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between poll rounds (min 2)")
    a = ap.parse_args(argv)
    import aladin_env
    aladin_env.announce("aladin_ticker_daemon")
    cfg = load_cfg()
    port = a.port or cfg["ws_port"]
    if a.source == "angel":
        print("The Angel One source isn't built in this version: it needs the account holder's SmartAPI login and TOTP keys.\n"
              "Run without --source (or --source nse-web) to use NSE's free web feed.", file=sys.stderr)
        return 2
    if os.environ.get("ANGEL_API_KEY") and a.source == "auto":
        print("ANGEL_* keys found, but the Angel One source isn't built yet - using nse-web.")
    uni = {}
    try:
        uni = {s["s"]: s for s in json.loads((ROOT / "data" / "terminal" / "universe.json").read_text(encoding="utf-8"))["stocks"]}
    except (OSError, ValueError, KeyError):
        pass
    min_val = cfg["sweep"]["min_value_cr"] * 1e7
    value_ok = lambda sym: bool(uni.get(sym)) and (uni[sym].get("avgv20") or 0) * (uni[sym].get("c") or 0) >= min_val
    hub = Hub(cfg, value_ok=value_ok, sweep_log_dir=ROOT / "data" / "aladin_cache" / "sweep_log")
    source = NseWebSource(NseSession(), a.interval)
    print(f"ALADIN ticker daemon | source nse-web | ws://127.0.0.1:{port}/ws/ticks | window Mon-Fri 09:00-15:45 IST | poll {source.interval:.0f}s")
    print("Covers index levels + the stocks on NSE's own movers / most-active lists (the free feed has nothing wider). Ctrl+C to stop.")
    try:
        asyncio.run(serve(hub, source, port, dump_path=ROOT / "data" / "live_extra" / "ticks.json"))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
