"""
Bitcoin order-flow paper account, real time. A VIRTUAL account with a HARD budget of Rs 10,00,000 (converted to dollars once, at the start rate): no leverage, no top-ups, never more than the budget in Bitcoin.
Nothing here touches an exchange account or places an order.

  python scripts/crypto_live.py            one engine step (run every 15 minutes by .github/workflows/crypto-live.yml)

Strategies: the two order-flow strategies of scripts/crypto_flow.py that made money in BOTH the selection years (2020-2023) and the held-out years (2024-2026) and still did after doubling the costs, on BOTH Bitcoin
and Ethereum (the same two strategies, declared before Ethereum was looked at): flow_momentum and flow_breakout on 4-hour bars, four sleeves of 25% of the budget each. Heikin-Ashi on its own lost money after costs and is not traded.
The same signal and sizing code serves the backtest and this engine. ORDER-BOOK DEPTH is only RECORDED (hourly, data/crypto/depth.jsonl) and tested against what happened next; it never trades: there is no history to test it on.
Each run: read Binance's public market data (15-minute candles with taker buy volume, best bid and ask), build the 4-hour bars, and
  1. check each open position's stop against the 15-minute candles since entry (a stop fills at its price, or at the open if a candle opened through it) and against the live bid;
  2. once per closed 4-hour bar, act on the signal: buy at the live ask, sell at the live bid, each fill paying COST. A decision more than LATE_MIN minutes after the bar closed is skipped and logged (the backtest fills at the open);
  3. mark the account to market. Every fill and decision is appended to data/crypto/ledger.jsonl; the account is replayed from that file, so nothing can be edited afterwards.
"""
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypto_flow as CF  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "crypto"
LEDGER, LIVE, MARKS = OUT / "ledger.jsonl", OUT / "live.json", OUT / "marks.jsonl"
BASE = "https://data-api.binance.vision/api/v3"
BUDGET_INR = 1_000_000
ASSETS = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum"}
SLEEVES = {f"{a[:3].lower()}_{st}": {"asset": a, "strategy": st, "tf": "4h", "share": 0.25, "label": f"{ASSETS[a]} · {lab}"} for a in ASSETS for st, lab in (("flow_momentum", "order-flow momentum"), ("flow_breakout", "order-flow breakout"))}
SLEEVES["btc_flow_momentum"].update({"trail": True, "label": "Bitcoin · order-flow momentum + trailing stop"})          # rule change 2026-10-10 (before any trade): scripts/crypto_extra.py, momentum_trail_4h
DEPTH = OUT / "depth.jsonl"
LATE_MIN = 60
STALE_MIN = 45
N_BARS = 13000                                   # 15-minute bars fetched each run (about 135 days): enough for the 500-bar flow windows on 4-hour bars


def _get(url, params=None, tries=3):
    import requests
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=20, headers={"User-Agent": "samnidhy-crypto-paper"}); r.raise_for_status(); return r.json()
        except Exception as e:                                                  # noqa: BLE001
            last = e; time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"market-data request failed: {type(last).__name__}")


def fetch_bars(now=None, n=N_BARS, symbol="BTCUSDT"):
    """Complete 15-minute bars (o, h, l, c, v, n, tbv) newest last. The bar still forming is dropped."""
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000); rows, end = [], None
    while len(rows) < n:
        p = {"symbol": symbol, "interval": "15m", "limit": 1000}
        if end:
            p["endTime"] = end
        page = _get(f"{BASE}/klines", p)
        if not page:
            break
        rows = page + rows; end = page[0][0] - 1
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"]); df = df[df["ct"] < now_ms].drop_duplicates("t")
    df.index = pd.to_datetime(df["t"], unit="ms"); b = df[["o", "h", "l", "c", "v", "n", "tbv"]].astype(float); return b[~b.index.duplicated()].sort_index().tail(n)


def quote(symbol="BTCUSDT"):
    q = _get(f"{BASE}/ticker/bookTicker", {"symbol": symbol}); bid, ask = float(q["bidPrice"]), float(q["askPrice"]); return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}


def usd_inr():
    try:
        return float(_get("https://api.coinbase.com/v2/exchange-rates", {"currency": "USD"})["data"]["rates"]["INR"])
    except Exception:                                                           # noqa: BLE001
        return None


# ------------------------------------------------------------------ the ledger and the account replayed from it
def read_ledger(path=None):
    p = Path(path or LEDGER); return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def append(rec, path=None):
    p = Path(path or LEDGER); p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def replay(lines):
    """Per-sleeve account from the ledger alone: {name: {cash, qty, entry, stop, since, trades, decided}}; the start line fixes the budget."""
    start = next((r for r in lines if r["t"] == "start"), None)
    if not start:
        return None, {}
    S = {k: {"cash": start["budget_usd"] * v["share"], "qty": 0.0, "entry": None, "stop": None, "since": None, "ecost": 0.0, "trades": [], "decided": set(), "stops": []} for k, v in start["sleeves"].items()}
    for r in lines:
        if r["t"] == "decision":
            S[r["sleeve"]]["decided"].add(r["bar"])
        elif r["t"] == "stop":
            a = S[r["sleeve"]]
            if a["qty"] > 0 and r["stop"] > a["stop"]:
                a["stop"] = r["stop"]; a["stops"].append((r["effective"], r["stop"]))
        elif r["t"] == "fill":
            a = S[r["sleeve"]]
            if r["side"] == "buy":
                a["cash"] -= r["qty"] * r["price"] + r["cost"]; a["qty"] += r["qty"]; a["entry"], a["stop"], a["since"], a["ecost"] = r["price"], r["stop"], r["ts"], r["cost"]; a["stops"] = [(r["ts"], r["stop"])]
            else:
                a["cash"] += r["qty"] * r["price"] - r["cost"]; gross = r["qty"] * (r["price"] - a["entry"]); costs = a["ecost"] + r["cost"]
                a["trades"].append({"sleeve": r["sleeve"], "in_ts": a["since"], "out_ts": r["ts"], "in": round(a["entry"], 2), "out": round(r["price"], 2), "qty": round(r["qty"], 6), "gross": round(gross, 2), "costs": round(costs, 2),
                                    "net": round(gross - costs, 2), "ret_pct": round((gross - costs) / (r["qty"] * a["entry"]) * 100, 3), "why": r["why"]})
                a["qty"] = 0.0; a["entry"] = a["stop"] = a["since"] = None; a["ecost"] = 0.0; a["stops"] = []
    return start, S


def _naive(ts):
    t = pd.Timestamp(ts); return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t


def stop_hit(bars15, since, stops, bid):
    """(price, timestamp) where an open position's stop was hit, else None. stops: a number, or the history [(effective time, level), ...] of a trailing stop. Each 15-minute candle that started after the entry is tested
    against the stop in force at that time: the first with a low at or under it fills at the stop, or at its open if it opened through it; otherwise the live bid at or under the current stop fills at the bid."""
    t0 = _naive(since).floor("15min"); hist = [(since, float(stops))] if isinstance(stops, (int, float)) else list(stops)
    for k, (eff, level) in enumerate(hist):
        lo = max(t0, _naive(eff)) if k else t0; hi = _naive(hist[k + 1][0]) if k + 1 < len(hist) else None
        sub = bars15[(bars15.index > lo) if k == 0 else (bars15.index >= lo)]
        if hi is not None:
            sub = sub[sub.index < hi]
        hit = sub[sub["l"] <= level]
        if len(hit):
            r = hit.iloc[0]; return min(float(r["o"]), level), str(hit.index[0])
    cur = hist[-1][1]
    return (bid, None) if bid <= cur else None


def depth_sample(symbol, mid):
    """Order-book imbalance now: (bid size - ask size) / (bid size + ask size) within 0.02% and 0.05% of the mid price, from the top 5,000 levels each side, plus the spread in basis points."""
    d = _get(f"{BASE}/depth", {"symbol": symbol, "limit": 5000}); bids = [(float(p), float(q)) for p, q in d["bids"]]; asks = [(float(p), float(q)) for p, q in d["asks"]]

    def imb(w):
        b = sum(q for p, q in bids if p >= mid * (1 - w)); a = sum(q for p, q in asks if p <= mid * (1 + w)); return round((b - a) / (b + a), 4) if b + a > 0 else None
    return {"imb_near": imb(0.0002), "imb_wide": imb(0.0005), "spread_bps": round((asks[0][0] - bids[0][0]) / mid * 1e4, 3)}


def depth_stats(rows):
    """Does the hourly order-book imbalance say anything about the NEXT hour or the next four hours? Spearman rank correlation per asset, from the recorded samples only. No trade uses it."""
    out = {}
    for sym in ASSETS:
        r = pd.DataFrame([x for x in rows if x["sym"] == sym])
        if len(r) < 3:
            out[sym] = {"n": len(r)}; continue
        r["t"] = pd.to_datetime(r["ts"], utc=True).dt.tz_localize(None); r = r.sort_values("t").reset_index(drop=True)

        def corr(k, lo, hi):
            gap = (r["t"].shift(-k) - r["t"]).dt.total_seconds() / 3600; ret = r["mid"].shift(-k) / r["mid"] - 1; ok = gap.between(lo, hi) & r["imb_near"].notna() & ret.notna()
            n = int(ok.sum()); return {"n": n, "rho": round(float(r.loc[ok, "imb_near"].corr(ret[ok], method="spearman")), 3) if n >= 30 else None, "needs_abs_rho_above": round(2 / n ** 0.5, 3) if n >= 30 else None}
        out[sym] = {"n": len(r), "next_1h": corr(1, 0.8, 1.2), "next_4h": corr(4, 3.5, 4.5), "latest": {k: (None if pd.isna(r.iloc[-1][k]) else float(r.iloc[-1][k])) for k in ("imb_near", "imb_wide", "spread_bps")}}
    return out


def hourly_due(now, path):
    p = Path(path)
    if not p.exists():
        return True
    rows = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return not rows or (now - datetime.fromisoformat(json.loads(rows[-1])["ts"])).total_seconds() >= 3300


def live_step(now=None, bars=None, q=None, fx=None, ledger=None, out=None, depth=None, marks=None, depth_file=None):
    """bars, q: dicts keyed by symbol (fetched when not given); depth: optional {symbol: sample} for tests."""
    now = now or datetime.now(timezone.utc); led = Path(ledger or LEDGER); ts = now.isoformat(timespec="seconds")
    bars = bars or {a: fetch_bars(now, symbol=a) for a in ASSETS}; q = q or {a: quote(a) for a in ASSETS}; fx = fx if fx is not None else usd_inr(); lines = read_ledger(led)
    if not lines:
        if fx is None:
            raise RuntimeError("the start rate (USD/INR) is not available: not starting the account")
        append({"t": "start", "ts": ts, "budget_inr": BUDGET_INR, "fx0": fx, "budget_usd": round(BUDGET_INR / fx, 2), "price0": {a: q[a]["mid"] for a in ASSETS},
                "sleeves": {k: {"share": v["share"], "tf": v["tf"], "asset": v["asset"], "strategy": v["strategy"]} for k, v in SLEEVES.items()},
                "note": "forward clock starts: only decisions from here on count. Hard budget: no leverage, no top-ups."}, led); lines = read_ledger(led)
    if lines and not any(r["t"] == "rule_change" for r in lines) and not any(r["t"] == "fill" for r in lines):
        append({"t": "rule_change", "ts": ts, "sleeve": "btc_flow_momentum", "to": "order-flow momentum + trailing stop (stop ratchets up to 3 ATR under each closed 4-hour bar)", "why": "round two of the search (scripts/crypto_extra.py): beat the plain version on 2020-23 Sharpe (0.86 vs 0.51), on 2024-26 (0.92 vs 0.79) and at double costs; written before the sleeve had traded"}, led); lines = read_ledger(led)
    start, S = replay(lines); feats = {}; fresh_start = not any(r["t"] == "decision" for r in lines)
    for name, cfg in SLEEVES.items():
        a = S[name]; sym, strat = cfg["asset"], cfg["strategy"]; qq = q[sym]; f = CF.features(CF.resample(bars[sym], cfg["tf"])); feats[name] = f; bar = str(f.index[-1]); close_t = f.index[-1] + pd.Timedelta(cfg["tf"])
        late = (now.replace(tzinfo=None) - close_t.to_pydatetime()).total_seconds() / 60
        if a["qty"] > 0:                                                                     # 1. stops first
            h = stop_hit(bars[sym], a["since"], a["stops"], qq["bid"])
            if h:
                price, when = h; fee = a["qty"] * price * CF.COST
                append({"t": "fill", "ts": when or ts, "engine_ts": ts, "sleeve": name, "side": "sell", "why": "stop", "price": round(price, 2), "qty": round(a["qty"], 8), "cost": round(fee, 2), "bid": qq["bid"], "ask": qq["ask"]}, led)
                lines = read_ledger(led); _, S = replay(lines); a = S[name]
        if bar not in a["decided"]:                                                          # 2. one decision per closed 4-hour bar
            en, ex = CF.signals(f, strat); act, why, row = "hold", None, f.iloc[-1]
            if late > LATE_MIN:
                act, why = "skipped", (f"the account started {late:.0f} min after this bar closed: it only acts on bars it saw close" if fresh_start else f"decision {late:.0f} min after the bar closed (limit {LATE_MIN}): the engine was not running")
            elif a["qty"] > 0 and ex[-1]:
                price = qq["bid"]; fee = a["qty"] * price * CF.COST; act = "sell"
                append({"t": "fill", "ts": ts, "sleeve": name, "side": "sell", "why": "signal", "price": round(price, 2), "qty": round(a["qty"], 8), "cost": round(fee, 2), "bid": qq["bid"], "ask": qq["ask"], "bar": bar}, led)
            elif a["qty"] == 0 and en[-1] and not math.isnan(row["atr"]):
                price = qq["ask"]; stop = float(row["c"] - CF.STOP_ATR[strat] * row["atr"]); val = CF.size_value(a["cash"], price, stop)
                if val > 1:
                    qty = val / price; fee = val * CF.COST; act = "buy"
                    append({"t": "fill", "ts": ts, "sleeve": name, "side": "buy", "price": round(price, 2), "qty": round(qty, 8), "cost": round(fee, 2), "stop": round(stop, 2), "bid": qq["bid"], "ask": qq["ask"], "bar": bar}, led)
                else:
                    act, why = "skipped", "no size (the stop is above the price or the sleeve has no cash)"
            ind = {k: (None if pd.isna(row[k]) else round(float(row[k]), 3)) for k in ("flow24", "delta_z", "vol_z", "c", "hi24", "sma50", "atr")}
            append({"t": "decision", "ts": ts, "sleeve": name, "bar": bar, "action": act, "signal_enter": bool(en[-1]), "signal_exit": bool(ex[-1]), "why": why, "minutes_after_close": round(late, 1), "indicators": ind}, led)
            lines = read_ledger(led); _, S = replay(lines)
    for name, cfg in SLEEVES.items():                                                        # 2b. a trailing stop only ever moves up, once per closed bar
        a = S[name]
        if cfg.get("trail") and a["qty"] > 0:
            f = feats[name]; row = f.iloc[-1]; eff = f.index[-1] + pd.Timedelta(cfg["tf"]); new = round(float(row["c"] - CF.STOP_ATR[cfg["strategy"]] * row["atr"]), 2)
            if not math.isnan(new) and new > a["stop"] and eff > _naive(a["since"]) and eff <= _naive(ts):
                append({"t": "stop", "ts": ts, "sleeve": name, "effective": str(eff), "bar": str(f.index[-1]), "stop": new, "was": a["stop"]}, led)
    lines = read_ledger(led); _, S = replay(lines)
    # 3. mark to market, each sleeve at its own coin's bid
    sl, tot = {}, 0.0
    for name, a in S.items():
        cfg = SLEEVES[name]; mark = q[cfg["asset"]]["bid"]; f = feats[name]; row = f.iloc[-1]; eq = a["cash"] + a["qty"] * mark; tot += eq
        sl[name] = {"label": cfg["label"], "asset": cfg["asset"], "strategy": cfg["strategy"], "timeframe": cfg["tf"], "share": cfg["share"], "trail": bool(cfg.get("trail")), "cash": round(a["cash"], 2), "qty": round(a["qty"], 8), "equity": round(eq, 2), "entry": a["entry"], "stop": a["stop"], "since": a["since"],
                    "unrealised": round(a["qty"] * (mark - a["entry"]) - a["ecost"], 2) if a["qty"] > 0 else None, "trades": len(a["trades"]), "wins": sum(1 for t in a["trades"] if t["net"] > 0), "net": round(sum(t["net"] for t in a["trades"]), 2),
                    "now": {k: (None if pd.isna(row[k]) else round(float(row[k]), 3)) for k in ("flow24", "delta_z", "vol_z", "c", "hi24", "sma50")}, "last_bar": str(f.index[-1])}
    assert all(a["cash"] > -1e-6 for a in S.values()) and tot < start["budget_usd"] * 3, "budget invariant broken"
    bh = sum(start["budget_usd"] * v["share"] / (start["price0"][v["asset"]] * (1 + CF.COST)) * q[v["asset"]]["bid"] * (1 - CF.COST) for v in SLEEVES.values())
    invested = sum(a["qty"] * q[SLEEVES[k]["asset"]]["bid"] for k, a in S.items())
    trades = sorted((t for a in S.values() for t in a["trades"]), key=lambda t: t["out_ts"])[-100:]; decisions = [r for r in lines if r["t"] == "decision"][-60:]
    mfile = Path(marks or MARKS); dfile = Path(depth_file or DEPTH); due = hourly_due(now, mfile); curve = _marks(ts, tot, {a: q[a]["mid"] for a in ASSETS}, now, path=mfile, due=due)
    if due:                                                                                  # the order-book recorder: one sample per coin per hour
        for a in ASSETS:
            try:
                append({"ts": ts, "sym": a, "mid": q[a]["mid"], **((depth or {}).get(a) or depth_sample(a, q[a]["mid"]))}, dfile)
            except Exception as e:                                                           # noqa: BLE001  a failed sample is skipped, never fatal
                print("depth sample failed:", a, type(e).__name__)
    drows = [json.loads(x) for x in dfile.read_text(encoding="utf-8").splitlines() if x.strip()] if dfile.exists() else []
    doc = {"kind": "LIVE PAPER ACCOUNT (Bitcoin and Ethereum, order flow)", "label": "LIVE PAPER ACCOUNT: simulated money on Binance's real BTCUSDT and ETHUSDT prices. Hard budget Rs 10,00,000, no leverage, no exchange account, no real order.",
           "engine_ts": ts, "started": start["ts"], "budget_inr": BUDGET_INR, "budget_usd": start["budget_usd"], "fx0": start["fx0"], "fx_now": fx, "assets": {a: {"name": ASSETS[a], **q[a]} for a in ASSETS}, "equity_usd": round(tot, 2),
           "pnl_usd": round(tot - start["budget_usd"], 2), "return_pct": round((tot / start["budget_usd"] - 1) * 100, 3), "equity_inr_at_start_rate": round(tot * start["fx0"], 0), "equity_inr_now": round(tot * fx, 0) if fx else None,
           "invested_pct": round(invested / tot * 100, 1) if tot else 0.0, "buy_hold_usd": round(bh, 2), "sleeves": sl, "trades": trades, "decisions": decisions, "curve": curve, "stale_after_min": STALE_MIN,
           "depth_experiment": {"label": "EXPERIMENT, NOT TRADED: does the hourly order-book imbalance (resting buy size minus resting sell size within 0.02% of the price) say anything about the next hour or the next four hours? Nothing trades on it until it proves itself on live samples.",
                                "stats": depth_stats(drows)},
           "study": {"BTCUSDT": "t/c/study.json", "ETHUSDT": "t/c/study_eth.json", "extra": "t/c/study_extra.json"}}
    p = Path(out or LIVE); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False, default=lambda v: None), encoding="utf-8"); return doc


def _marks(ts, equity, prices, now, path=None, due=None):
    """Hourly equity points (kept in data/crypto/marks.jsonl); returns the last 1,000 for the page."""
    p = Path(path or MARKS); rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    if due is None:
        due = not rows or (now - datetime.fromisoformat(rows[-1]["ts"])).total_seconds() >= 3300
    if due:
        rows.append({"ts": ts, "equity": round(equity, 2), "px": {k: round(v, 2) for k, v in prices.items()}}); p.parent.mkdir(parents=True, exist_ok=True); p.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n", encoding="utf-8")
    return [[r["ts"], r["equity"]] for r in rows[-1000:]]


def main():
    d = live_step(); print(f"equity ${d['equity_usd']:,.2f} ({d['return_pct']:+.3f}%) of ${d['budget_usd']:,.2f} | invested {d['invested_pct']}% | " + " ".join(f"{k}: {v['trades']}t {'IN' if v['qty'] else 'flat'}" for k, v in d["sleeves"].items()))


if __name__ == "__main__":
    main()
