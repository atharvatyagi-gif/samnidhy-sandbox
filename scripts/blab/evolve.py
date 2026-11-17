"""B-Lab Technical division: the self-evolving desk of simple strategies (docs/blab/STRATEGY_EVIDENCE.md, rules written there
2026-11-17 before any test). Replaces the old ranking lab.

  candidates  simple rules from the research (trend filter, moving-average distance, 52-week high, crossover, channel breakout,
              RSI bounce) in many settings, plus rules bred from survivors and rules the AI paper scout proposes
  simulate    each candidate runs its own Rs 1 lakh paper account on every tradable NSE stock: signals at the close, fills at
              the next open, full Indian costs, at most 10 equal positions, long only
  select      every 21 sessions: eligible after 126 sessions of record; score = deflated Sharpe (Bailey & Lopez de Prado) of
              the last 252 sessions, penalised for every candidate ever tried; top 3 with probability >= 0.5 go live, equal
              money; empty places follow the blend of all candidates; 3 re-picks under 0.1 in a row = retired; up to 3 bred
  replay      the whole selector re-run over 2010-2026 with no future data, against the blend of all candidates and NIFTY 50
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

from .core import DATA, ROOT

TERM = DATA / "terminal"
STORE = DATA / "blab" / "store"
CAPITAL, SLOTS, REBAL = 100_000.0, 10, 21
MIN_PRICE, MIN_HIST, MIN_VALUE = 10.0, 260, 1e7            # Rs 10, 260 sessions, Rs 1 Cr average daily traded value
START = "2010-01-01"
MIN_RECORD, LOOKBACK, TOP, P_LIVE, P_RETIRE, RETIRE_AFTER, BREED, MIN_POOL = 126, 252, 3, 0.5, 0.1, 6, 3, 15   # see the 2026-11-17 change in STRATEGY_EVIDENCE.md
SWITCH_COST = 0.004                                       # a replaced live strategy: its third of the money pays a round trip
HOLDOUT_DAYS = 730

GRID = {
    "trend": {"n": [100, 150, 200, 250]},
    "mad": {"s": [10, 21, 50], "l": [150, 200, 250]},
    "hi52": {"n": [126, 252]},
    "cross": {"s": [20, 50], "l": [100, 150, 200]},
    "breakout": {"inn": [20, 50, 100], "out": [10, 20, 50]},
    "rsi": {"lo": [25, 30], "hi": [50, 55, 60], "k": [10, 20]},
}
RANKING = {"mad", "hi52"}
STATE_RULES = {"trend", "cross"}                           # rules that describe a state (usable as a filter in a combination)
DEFAULTS = {"trend": {"n": 200}, "mad": {"s": 21, "l": 200}, "hi52": {"n": 252}, "cross": {"s": 50, "l": 200},
            "breakout": {"inn": 50, "out": 20}, "rsi": {"lo": 30, "hi": 55, "k": 10}}
LABEL = {"trend": "Trend filter", "mad": "Moving-average distance", "hi52": "52-week high", "cross": "Moving-average crossover",
         "breakout": "Channel breakout", "rsi": "RSI bounce"}


def valid(fam, p):
    if fam == "mad" or fam == "cross":
        return p["s"] < p["l"]
    if fam == "breakout":
        return p["out"] < p["inn"]
    return True


def cid(fam, p, filt=None):
    s = fam + "_" + "_".join(f"{k}{p[k]}" for k in sorted(p))
    return s + (f"+{cid(*filt)}" if filt else "")


def describe(fam, p, filt=None):
    t = {"trend": lambda: f"hold while the close is above its {p['n']}-day average",
         "mad": lambda: f"hold the 10 stocks whose {p['s']}-day average is furthest above their {p['l']}-day average (monthly)",
         "hi52": lambda: f"hold the 10 stocks closest to their {p['n']}-session high (monthly)",
         "cross": lambda: f"in when the {p['s']}-day average crosses above the {p['l']}-day, out when it falls back below",
         "breakout": lambda: f"in on a close above the {p['inn']}-day high, out on a close below the {p['out']}-day low",
         "rsi": lambda: f"in when RSI(14) closes back above {p['lo']}, out at {p['hi']} or after {p['k']} sessions"}[fam]()
    return t + (f", only while {describe(*filt)}" if filt else "")


def grid_candidates():
    import itertools
    out = []
    for fam, g in GRID.items():
        keys = sorted(g)
        for vals in itertools.product(*(g[k] for k in keys)):
            p = dict(zip(keys, vals))
            if valid(fam, p):
                out.append({"id": cid(fam, p), "fam": fam, "p": p, "filt": None, "origin": "research grid"})
    return out


# ------------------------------------------------------------------ data

def _rows(p):
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return d.get("d", d) if isinstance(d, dict) else d


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def universe_symbols():
    try:
        u = json.loads((TERM / "universe.json").read_text(encoding="utf-8")).get("stocks", [])
        return sorted(s["s"] for s in u if s.get("board") == "Main" and s.get("series") == "EQ" and not s.get("etf"))
    except (OSError, ValueError):
        return sorted(p.stem for p in (TERM / "daily").glob("*.json"))


class Market:
    """Dates x stocks matrices of open, close and 20-day average traded value (Rs), joined archive + daily at their overlap."""

    def __init__(self, syms=None, start="2008-01-01"):
        import numpy as np
        from .technical import joined
        n50 = joined("_5eNSEI.json", _rows(TERM / "idx" / "out" / "d" / "Nifty_2050.json"))
        self.dates = [d for d in sorted(n50) if d >= start]
        self.n50 = np.array([n50[d] for d in self.dates], float)
        idx = {d: i for i, d in enumerate(self.dates)}
        syms = syms or universe_symbols()
        T, cols, O, C, V = len(self.dates), [], [], [], []
        for s in syms:
            old = {r[0]: r for r in _rows(TERM / "archive" / f"{key(s)}.json") if len(r) >= 6}
            new = {r[0]: r for r in _rows(TERM / "daily" / f"{key(s)}.json") if len(r) >= 6}
            if not new and not old:
                continue
            common = sorted(set(old) & set(new))
            k = new[common[-1]][4] / old[common[-1]][4] if common and old[common[-1]][4] else 1.0
            rows = {d: (r[1] * k, r[4] * k, r[5] / k if k else r[5]) for d, r in old.items() if not new or d < min(new)}
            rows.update({d: (r[1], r[4], r[5]) for d, r in new.items()})
            o, c, v = np.full(T, np.nan, np.float32), np.full(T, np.nan, np.float32), np.full(T, np.nan, np.float32)
            n = 0
            for d, (oo, cc, vv) in rows.items():
                i = idx.get(d)
                if i is not None and cc and cc > 0:
                    o[i], c[i], v[i] = oo if oo and oo > 0 else cc, cc, (vv or 0) * cc; n += 1
            if n >= MIN_HIST:
                cols.append(s); O.append(o); C.append(c); V.append(v)
        self.syms = cols
        self.O, self.C, self.TV = (np.stack(x, 1) if x else np.zeros((T, 0), np.float32) for x in (O, C, V))
        self._cache = {}
        self._prep()

    def _prep(self):
        import numpy as np
        import pandas as pd
        C = pd.DataFrame(self.C)
        self.Cf = C.ffill().to_numpy(np.float32)                                     # last known close (for marking held positions)
        tv = pd.DataFrame(self.TV).rolling(20, min_periods=15).mean().to_numpy(np.float32)
        count = np.cumsum(~np.isnan(self.C), 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            jump = np.vstack([np.zeros((1, self.C.shape[1]), bool), np.abs(self.Cf[1:] / self.Cf[:-1] - 1) > 0.45])
        recent_jump = pd.DataFrame(jump.astype(np.float32)).rolling(20, min_periods=1).max().to_numpy() > 0   # a one-day move beyond 45%: a data error until shown otherwise
        self.elig = (self.C >= MIN_PRICE) & (count >= MIN_HIST) & (tv >= MIN_VALUE) & ~recent_jump
        self.tv = np.nan_to_num(tv, nan=0.0)
        self.pdC = C

    def sma(self, n):
        import numpy as np
        k = ("sma", n)
        if k not in self._cache:
            self._cache[k] = self.pdC.rolling(n, min_periods=n).mean().to_numpy(np.float32)
        return self._cache[k]

    def hi(self, n, lag=1):
        import numpy as np
        k = ("hi", n, lag)
        if k not in self._cache:
            self._cache[k] = self.pdC.rolling(n, min_periods=n).max().shift(lag).to_numpy(np.float32)
        return self._cache[k]

    def lo(self, n, lag=1):
        import numpy as np
        k = ("lo", n, lag)
        if k not in self._cache:
            self._cache[k] = self.pdC.rolling(n, min_periods=n).min().shift(lag).to_numpy(np.float32)
        return self._cache[k]

    def rsi(self):
        import numpy as np
        if "rsi" not in self._cache:
            d = self.pdC.diff()
            up, dn = d.clip(lower=0), (-d).clip(lower=0)
            au, ad = up.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean(), dn.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
            self._cache["rsi"] = (100 - 100 / (1 + au / ad)).to_numpy(np.float32)
        return self._cache["rsi"]


# ------------------------------------------------------------------ signals

def signals(M, fam, p):
    """-> (kind, a, b): ranking: ("rank", score, None); in/out: ("io", entry, exit) boolean matrices; exit may include a hold limit
    (returned as ("io", entry, exit, k))."""
    import numpy as np
    C = M.C
    with np.errstate(invalid="ignore", divide="ignore"):
        if fam == "trend":
            s = M.sma(p["n"]); return ("io", C > s, C < s, None)
        if fam == "cross":
            a, b = M.sma(p["s"]), M.sma(p["l"])
            up = a > b
            prev = np.vstack([np.zeros((1, C.shape[1]), bool), up[:-1]])
            return ("io", up & ~prev, a < b, None)
        if fam == "breakout":
            return ("io", C > M.hi(p["inn"]), C < M.lo(p["out"]), None)
        if fam == "rsi":
            r = M.rsi()
            prev = np.vstack([np.full((1, C.shape[1]), np.nan, np.float32), r[:-1]])
            return ("io", (prev < p["lo"]) & (r >= p["lo"]), r >= p["hi"], p["k"])
        if fam == "mad":
            sc = M.sma(p["s"]) / M.sma(p["l"]); return ("rank", np.where(sc > 1, sc, np.nan), None, None)
        if fam == "hi52":
            return ("rank", C / M.hi(p["n"], lag=0), None, None)
    raise ValueError(fam)


def state_of(M, fam, p):
    """A state rule as a filter: True while the rule is 'in'."""
    import numpy as np
    with np.errstate(invalid="ignore"):
        if fam == "trend":
            return M.C > M.sma(p["n"])
        if fam == "cross":
            return M.sma(p["s"]) > M.sma(p["l"])
    raise ValueError(fam)


# ------------------------------------------------------------------ the paper account

def simulate(M, cand, cfg, start=START):
    """One candidate's paper account from `start` to the last day. -> {"eq": [...], "dates": [...], "trades": [...], "orders": [...]}.
    Orders decided at day t's close fill at day t+1's open; nothing uses data after the day it is decided on."""
    import numpy as np
    sys.path.insert(0, str(ROOT / "scripts"))
    import aladin_e as AE
    kind, A, B, K = signals(M, cand["fam"], cand["p"])
    if cand.get("filt"):
        F = state_of(M, *cand["filt"])
        A = A & F
        B = B | ~F
    t0 = next((i for i, d in enumerate(M.dates) if d >= start), len(M.dates))
    cash, pos = CAPITAL, {}                                   # j -> [shares, entry_px, entry_t, buy_cost]
    eq, trades, pending = [], [], []
    for t in range(t0, len(M.dates)):
        # 1. fill yesterday's orders at today's open
        for side, j in pending:
            px = float(M.O[t, j])
            if not np.isfinite(px) or px <= 0:
                continue
            if side == "exit" and j in pos:
                sh, epx, et, bc = pos.pop(j)
                g = sh * px; c = AE.sell_cost(g, float(M.tv[t - 1, j]), cfg)
                cash += g - c
                trades.append([M.dates[t], M.syms[j], "exit", round(px, 2), sh, round((g - c) / (sh * epx + bc) - 1, 4), M.dates[et]])
            elif side == "enter" and j not in pos and len(pos) < SLOTS:
                val = equity_prev / SLOTS
                sh = math.floor(min(val, cash) / (px * 1.003))
                if sh <= 0:
                    continue
                c = AE.buy_cost(sh * px, float(M.tv[t - 1, j]), cfg)
                cash -= sh * px + c
                pos[j] = [sh, px, t, c]
                trades.append([M.dates[t], M.syms[j], "enter", round(px, 2), sh, None, None])
        pending = []
        # 2. mark to market at today's close
        mark = sum(sh * float(M.Cf[t, j]) for j, (sh, *_r) in pos.items())
        equity_prev = cash + mark
        eq.append(equity_prev)
        if t == len(M.dates) - 1:
            pass                                           # still decide: these are the orders for the next open
        # 3. decide at today's close
        held = set(pos)
        if kind == "rank":
            if (t - t0) % REBAL == 0:
                sc = np.where(M.elig[t], A[t], np.nan)
                ok = np.isfinite(sc)
                top = set(np.argsort(-np.where(ok, sc, -np.inf))[:SLOTS][: int(ok.sum())].tolist())
                pending += [("exit", j) for j in held - top] + [("enter", j) for j in sorted(top - held, key=lambda j: -sc[j])]
        else:
            exits = [j for j in held if B[t, j] or (K and t - pos[j][2] >= K)]
            pending += [("exit", j) for j in exits]
            free = SLOTS - len(held) + len(exits)
            if free > 0:
                cand_j = np.nonzero(A[t] & M.elig[t])[0]
                cand_j = [j for j in cand_j if j not in held]
                cand_j.sort(key=lambda j: -M.tv[t, j])
                pending += [("enter", j) for j in cand_j[:free]]
    orders = [[side, M.syms[j]] for side, j in pending]
    return {"dates": M.dates[t0:], "eq": eq, "trades": trades, "orders": orders,
            "positions": [[M.syms[j], sh, round(epx, 2), M.dates[et]] for j, (sh, epx, et, _c) in pos.items()]}


# ------------------------------------------------------------------ statistics

def stats(eq, dates, n50=None, n50_dates=None, a=None, b=None):
    import numpy as np
    d = np.array(dates); e = np.array(eq, float)
    m = np.ones(len(d), bool)
    if a: m &= d >= a
    if b: m &= d <= b
    e = e[m]
    if len(e) < 30:
        return None
    r = e[1:] / e[:-1] - 1
    yrs = len(e) / 252
    out = {"cagr_pct": round(((e[-1] / e[0]) ** (1 / yrs) - 1) * 100, 2), "worst_fall_pct": round(float((e / np.maximum.accumulate(e) - 1).min()) * 100, 2),
           "sharpe": round(float(r.mean() / r.std() * math.sqrt(252)), 2) if r.std() > 0 else None, "from": str(d[m][0]), "to": str(d[m][-1])}
    return out


def deflated_p(r, sr_all, n_tried):
    """Probability that the true Sharpe ratio of daily returns r is above the best one expected by luck among n_tried
    candidates (Bailey & Lopez de Prado 2014). sr_all: the current daily Sharpe ratios of the eligible candidates."""
    import numpy as np
    from statistics import NormalDist
    N = NormalDist()
    r = np.asarray(r, float)
    T = len(r)
    if T < 30 or r.std() == 0:
        return 0.0
    sr = r.mean() / r.std()
    g3 = float(((r - r.mean()) ** 3).mean() / r.std() ** 3)
    g4 = float(((r - r.mean()) ** 4).mean() / r.std() ** 4)
    v = float(np.var(sr_all)) if len(sr_all) > 1 else 0.0
    n = max(2, n_tried)
    emc = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - emc) * N.inv_cdf(1 - 1 / n) + emc * N.inv_cdf(1 - 1 / (n * math.e))) if v > 0 else 0.0
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2
    if den <= 0:
        return 0.0
    return float(N.cdf((sr - sr0) * math.sqrt(T - 1) / math.sqrt(den)))


def neighbours(c):
    """One step on each setting's grid; combinations with a live state rule are bred in `breed`."""
    out = []
    g = GRID[c["fam"]]
    for k, vals in g.items():
        if c["p"][k] in vals:
            i = vals.index(c["p"][k])
            for j in (i - 1, i + 1):
                if 0 <= j < len(vals):
                    p = dict(c["p"]); p[k] = vals[j]
                    if valid(c["fam"], p) and not (c.get("filt") and c["filt"][0] == c["fam"]):
                        out.append({"id": cid(c["fam"], p, c.get("filt")), "fam": c["fam"], "p": p, "filt": c.get("filt"), "origin": f"bred from {c['id']}"})
    return out


def breed(live, pool_ids):
    """Up to BREED new candidates: neighbours of the live ones, then an in/out live rule filtered by a live state rule."""
    new = []
    for c in live:
        for n in neighbours(c):
            if n["id"] not in pool_ids and n["id"] not in {x["id"] for x in new}:
                new.append(n)
    states = [c for c in live if c["fam"] in STATE_RULES and not c.get("filt")]
    for c in live:
        if c["fam"] not in RANKING and not c.get("filt"):
            for s in states:
                if s["fam"] != c["fam"]:                                       # a rule filtered by its own family adds nothing
                    n = {"id": cid(c["fam"], c["p"], (s["fam"], s["p"])), "fam": c["fam"], "p": c["p"], "filt": (s["fam"], s["p"]), "origin": f"bred: {c['id']} AND {s['id']}"}
                    if n["id"] not in pool_ids and n["id"] not in {x["id"] for x in new}:
                        new.append(n)
    return new[:BREED]


def replay(M, cfg, extra=(), log=print):
    """Run every candidate, then the selector month by month with no future data. -> the full record."""
    import numpy as np
    dates = M.dates
    t0 = next(i for i, d in enumerate(dates) if d >= START)
    first = dates[t0]
    pool = {c["id"]: dict(c, born=max(first, c.get("born") or first)) for c in list(grid_candidates()) + list(extra)}
    runs = {}

    def run(cid_, born):
        if cid_ not in runs:
            c = pool[cid_]
            runs[cid_] = simulate(M, c, cfg, start=born)
            e = np.array(runs[cid_]["eq"], float)
            runs[cid_]["ret"] = dict(zip(runs[cid_]["dates"][1:], (e[1:] / e[:-1] - 1).tolist()))
        return runs[cid_]

    for k in list(pool):
        run(k, pool[k]["born"])
    log(f"evolve: {len(pool)} starting candidates simulated ({len(extra)} from the AI paper scout)")
    tried = len(pool)
    status = {k: {"low": 0, "retired": None} for k in pool}
    picks_log, live, sel_ret, blend_ret, last_scores = [], [], {}, {}, {}
    days = dates[t0:]
    for i in range(MIN_RECORD, len(days), REBAL):
        day = days[i]
        hist = days[max(0, i - LOOKBACK) + 1: i + 1]
        active = [k for k in pool if not status[k]["retired"] and pool[k]["born"] <= day]
        elig = {}
        for k in active:
            rr = [runs[k]["ret"].get(d) for d in hist if d > pool[k]["born"]]
            rr = [x for x in rr if x is not None]
            if len(rr) >= MIN_RECORD:
                elig[k] = rr
        srs = [np.mean(v) / np.std(v) for v in elig.values() if np.std(v) > 0]
        score = {k: deflated_p(v, srs, tried) for k, v in elig.items()}
        for k, p in score.items():
            status[k]["low"] = status[k]["low"] + 1 if p < P_RETIRE else 0
        n_active = len(active)
        for k in sorted(score, key=lambda k: score[k]):                       # weakest first; the pool never falls below MIN_POOL
            if status[k]["low"] >= RETIRE_AFTER and n_active > MIN_POOL:
                status[k]["retired"] = day; n_active -= 1
        ranked = sorted((k for k in score if not status[k]["retired"]), key=lambda k: -score[k])
        new_live = [k for k in ranked if score[k] >= P_LIVE][:TOP]
        switched = len(set(new_live) - set(live)) if live else 0
        picks_log.append({"date": day, "live": new_live, "scores": {k: round(score[k], 3) for k in ranked[:10]}, "eligible": len(score), "tried": tried})
        last_scores = {k: round(score[k], 3) for k in score}
        live = new_live
        # the next 21 sessions: live thirds, empty thirds follow the blend; a replaced third pays a round trip
        nxt = days[i + 1: i + 1 + REBAL]
        act_now = [k for k in pool if not status[k]["retired"] and pool[k]["born"] <= day]
        for n_, d in enumerate(nxt):
            b = [runs[k]["ret"].get(d) for k in act_now]
            b = [x for x in b if x is not None]
            bl = float(np.mean(b)) if b else 0.0
            parts = [runs[k]["ret"].get(d, 0.0) for k in live] + [bl] * (TOP - len(live))
            r = float(np.mean(parts))
            if n_ == 0 and switched:
                r -= SWITCH_COST * switched / TOP
            sel_ret[d], blend_ret[d] = r, bl
        # breed for the next round: from the live ones, or (nothing live) from the three best scores, so evolution keeps exploring
        parents = live or [k for k in ranked[:TOP]]
        for c in breed([pool[k] for k in parents], set(pool)):
            pool[c["id"]] = dict(c, born=day)
            status[c["id"]] = {"low": 0, "retired": None}
            tried += 1
            run(c["id"], day)
    def curve(rets):
        ds = sorted(rets); e = [1.0]
        for d in ds:
            e.append(e[-1] * (1 + rets[d]))
        return ds, e[1:]
    sd, se = curve(sel_ret)
    bd, be = curve(blend_ret)
    n50 = {d: v for d, v in zip(M.dates, M.n50)}
    nd = [d for d in sd]
    ne = [n50[d] for d in nd]
    hold = (date.fromisoformat(days[-1]) - timedelta(days=HOLDOUT_DAYS)).isoformat()
    res = {}
    for name, (dd, ee) in (("selector", (sd, se)), ("blend", (bd, be)), ("nifty50", (nd, ne))):
        res[name] = {"whole": stats(ee, dd), "design": stats(ee, dd, b=hold), "holdout": stats(ee, dd, a=hold)}
    return {"pool": pool, "status": status, "runs": runs, "picks": picks_log, "live": live, "tried": tried, "result": res, "last_scores": last_scores,
            "holdout_from": hold, "selector_curve": [sd[::5], [round(x, 4) for x in se[::5]]], "blend_curve": [bd[::5], [round(x, 4) for x in be[::5]]]}


# ------------------------------------------------------------------ the AI paper scout

ARXIV = "http://export.arxiv.org/api/query?search_query=cat:q-fin.TR+OR+cat:q-fin.PM+OR+cat:q-fin.ST&sortBy=submittedDate&sortOrder=descending&max_results=40"
BOUNDS = {"n": (5, 400), "s": (3, 200), "l": (20, 400), "inn": (5, 300), "out": (3, 200), "lo": (5, 45), "hi": (40, 90), "k": (3, 60)}
SCOUT_SYSTEM = ("You screen finance research abstracts for SIMPLE trading rules on single stocks that use only daily prices. "
                "Answer in JSON: {\"items\": [{\"i\": <abstract number>, \"rule\": null or {\"family\": one of trend | mad | hi52 | cross | breakout | rsi, "
                "\"params\": {...}}, \"why\": \"<= 25 words\"}]}. Families and their params: trend {n: moving-average days}; mad {s: short days, l: long days} "
                "(hold stocks whose short average is furthest above the long one); hi52 {n: lookback sessions} (hold stocks closest to their n-session high); "
                "cross {s, l} (short average crossing above the long one); breakout {inn: entry high days, out: exit low days}; rsi {lo: oversold line, "
                "hi: exit line, k: max sessions}. Give a rule ONLY when the abstract itself tests such a rule; otherwise rule is null. Never invent settings "
                "the abstract does not suggest.")


def parse_arxiv(xml_text):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(xml_text).findall("a:entry", ns):
        out.append({"id": (e.findtext("a:id", "", ns) or "").strip(), "title": " ".join((e.findtext("a:title", "", ns) or "").split()),
                    "summary": " ".join((e.findtext("a:summary", "", ns) or "").split())[:1200], "date": (e.findtext("a:published", "", ns) or "")[:10]})
    return out


def to_candidate(rule, paper, today):
    """A scout proposal -> a candidate in the same grammar, or None when it does not fit (checked by code, not by the model)."""
    if not isinstance(rule, dict) or rule.get("family") not in GRID:
        return None
    fam, raw = rule["family"], rule.get("params") or {}
    keys = sorted(GRID[fam])
    p = {}
    for k in keys:
        v = raw.get(k, DEFAULTS[fam][k])
        try:
            v = int(round(float(v)))
        except (TypeError, ValueError):
            return None
        lo, hi = BOUNDS[k]
        if not lo <= v <= hi:
            return None
        p[k] = v
    if not valid(fam, p) or (fam == "rsi" and p["lo"] >= p["hi"]):
        return None
    return {"id": cid(fam, p), "fam": fam, "p": p, "filt": None, "born": today, "origin": f"AI scout: {paper['title'][:120]}", "paper": paper["id"]}


def scout(ctx, known_ids, today, llm=None, fetch=None):
    """Read the newest arXiv abstracts; -> (new candidates, notes). The model only proposes; code validates and the selector decides."""
    import urllib.request
    from .sentiment import _llm
    get = fetch or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "B-Lab research desk (educational)"}), timeout=40).read().decode("utf-8"))
    papers = parse_arxiv(get(ARXIV))
    if llm is None:
        _llm()                                                           # raises NoKey when no free model key is on this runner
        sys.path.insert(0, str(ROOT / "scripts"))
        import revenue_graph_builder as rb
        llm = rb.LLM(provider="auto", max_calls=len(papers) // 10 + 1)    # its own allowance: one call per 10 abstracts
        parse = rb.parse_json_text
    else:
        parse = json.loads
    new, notes = [], []
    for k in range(0, len(papers), 10):
        batch = papers[k:k + 10]
        user = "\n\n".join(f"{j + 1}. {p['title']}\n{p['summary']}" for j, p in enumerate(batch))
        ans = parse(llm.complete(SCOUT_SYSTEM, user)) or {}
        for it in ans.get("items") or []:
            try:
                paper = batch[int(it.get("i")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            c = to_candidate(it.get("rule"), paper, today) if it.get("rule") else None
            if c and c["id"] not in known_ids and c["id"] not in {x["id"] for x in new}:
                new.append(c)
                notes.append({"paper": paper["id"], "title": paper["title"], "candidate": c["id"], "why": str(it.get("why") or "")[:160]})
    return new, {"read": len(papers), "proposed": notes}
