"""
Bitcoin order-flow paper account, real time. A VIRTUAL account with a HARD budget of Rs 10,00,000 (converted to dollars once, at the start rate): no leverage, no top-ups, never more than the budget in Bitcoin.
Nothing here touches an exchange account or places an order.

  python scripts/crypto_live.py            one engine step (run every 15 minutes by .github/workflows/crypto-live.yml)

Strategies: the two order-flow strategies of scripts/crypto_flow.py that made money in BOTH the selection years (2020-2023) and the held-out years (2024-2026) and still did after doubling the costs:
flow_momentum and flow_breakout on 4-hour bars, each trading half of the budget. Heikin-Ashi on its own lost money after costs and is not traded. The same signal and sizing code serves the backtest and this engine.
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
SLEEVES = {"flow_momentum": {"tf": "4h", "share": 0.5, "label": "Order-flow momentum"}, "flow_breakout": {"tf": "4h", "share": 0.5, "label": "Order-flow breakout"}}
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


def fetch_bars(now=None, n=N_BARS):
    """Complete 15-minute bars (o, h, l, c, v, n, tbv) newest last. The bar still forming is dropped."""
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000); rows, end = [], None
    while len(rows) < n:
        p = {"symbol": "BTCUSDT", "interval": "15m", "limit": 1000}
        if end:
            p["endTime"] = end
        page = _get(f"{BASE}/klines", p)
        if not page:
            break
        rows = page + rows; end = page[0][0] - 1
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"]); df = df[df["ct"] < now_ms].drop_duplicates("t")
    df.index = pd.to_datetime(df["t"], unit="ms"); b = df[["o", "h", "l", "c", "v", "n", "tbv"]].astype(float); return b[~b.index.duplicated()].sort_index().tail(n)


def quote():
    q = _get(f"{BASE}/ticker/bookTicker", {"symbol": "BTCUSDT"}); bid, ask = float(q["bidPrice"]), float(q["askPrice"]); return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}


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
    S = {k: {"cash": start["budget_usd"] * v["share"], "qty": 0.0, "entry": None, "stop": None, "since": None, "ecost": 0.0, "trades": [], "decided": set()} for k, v in start["sleeves"].items()}
    for r in lines:
        if r["t"] == "decision":
            S[r["sleeve"]]["decided"].add(r["bar"])
        elif r["t"] == "fill":
            a = S[r["sleeve"]]
            if r["side"] == "buy":
                a["cash"] -= r["qty"] * r["price"] + r["cost"]; a["qty"] += r["qty"]; a["entry"], a["stop"], a["since"], a["ecost"] = r["price"], r["stop"], r["ts"], r["cost"]
            else:
                a["cash"] += r["qty"] * r["price"] - r["cost"]; gross = r["qty"] * (r["price"] - a["entry"]); costs = a["ecost"] + r["cost"]
                a["trades"].append({"sleeve": r["sleeve"], "in_ts": a["since"], "out_ts": r["ts"], "in": round(a["entry"], 2), "out": round(r["price"], 2), "qty": round(r["qty"], 6), "gross": round(gross, 2), "costs": round(costs, 2),
                                    "net": round(gross - costs, 2), "ret_pct": round((gross - costs) / (r["qty"] * a["entry"]) * 100, 3), "why": r["why"]})
                a["qty"] = 0.0; a["entry"] = a["stop"] = a["since"] = None; a["ecost"] = 0.0
    return start, S


def stop_hit(bars15, since, stop, bid):
    """(price, timestamp) where an open position's stop was hit, else None. 15-minute candles that started after the entry: the first with a low at or under the stop fills at the stop, or at its open if it opened through it;
    otherwise the live bid at or under the stop fills at the bid."""
    t0 = pd.Timestamp(since).tz_convert("UTC").tz_localize(None) if pd.Timestamp(since).tzinfo else pd.Timestamp(since)
    sub = bars15[bars15.index > t0.floor("15min")]
    hit = sub[sub["l"] <= stop]
    if len(hit):
        r = hit.iloc[0]; return min(float(r["o"]), stop), str(hit.index[0])
    return (bid, None) if bid <= stop else None


def live_step(now=None, bars=None, q=None, fx=None, ledger=None, out=None):
    now = now or datetime.now(timezone.utc); led = Path(ledger or LEDGER); bars = fetch_bars(now) if bars is None else bars; q = q or quote(); fx = fx if fx is not None else usd_inr(); ts = now.isoformat(timespec="seconds")
    lines = read_ledger(led)
    if not lines:
        if fx is None:
            raise RuntimeError("the start rate (USD/INR) is not available: not starting the account")
        append({"t": "start", "ts": ts, "budget_inr": BUDGET_INR, "fx0": fx, "budget_usd": round(BUDGET_INR / fx, 2), "price0": q["mid"], "sleeves": {k: {"share": v["share"], "tf": v["tf"]} for k, v in SLEEVES.items()},
                "note": "forward clock starts: only decisions from here on count. Hard budget: no leverage, no top-ups."}, led); lines = read_ledger(led)
    start, S = replay(lines); feats, status = {}, {}
    for name, cfg in SLEEVES.items():
        a = S[name]; f = CF.features(CF.resample(bars, cfg["tf"])); feats[name] = f; bar = str(f.index[-1]); close_t = f.index[-1] + pd.Timedelta(cfg["tf"]); late = (now.replace(tzinfo=None) - close_t.to_pydatetime()).total_seconds() / 60
        if a["qty"] > 0:                                                                     # 1. stops first
            h = stop_hit(bars, a["since"], a["stop"], q["bid"])
            if h:
                price, when = h; fee = a["qty"] * price * CF.COST; append({"t": "fill", "ts": when or ts, "engine_ts": ts, "sleeve": name, "side": "sell", "why": "stop", "price": round(price, 2), "qty": round(a["qty"], 8), "cost": round(fee, 2), "bid": q["bid"], "ask": q["ask"]}, led)
                lines = read_ledger(led); _, S = replay(lines); a = S[name]
        if bar not in a["decided"]:                                                          # 2. one decision per closed 4-hour bar
            en, ex = CF.signals(f, name); act, why, row = "hold", None, f.iloc[-1]
            if late > LATE_MIN:
                act, why = "skipped", (f"the account started {late:.0f} min after this bar closed: it only acts on bars it saw close" if not a["decided"] and not a["trades"] and a["qty"] == 0 and len([1 for r in lines if r["t"] == "decision"]) == 0
                                       else f"decision {late:.0f} min after the bar closed (limit {LATE_MIN}): the engine was not running")
            elif a["qty"] > 0 and ex[-1]:
                price = q["bid"]; fee = a["qty"] * price * CF.COST; act = "sell"; append({"t": "fill", "ts": ts, "sleeve": name, "side": "sell", "why": "signal", "price": round(price, 2), "qty": round(a["qty"], 8), "cost": round(fee, 2), "bid": q["bid"], "ask": q["ask"], "bar": bar}, led)
            elif a["qty"] == 0 and en[-1] and not math.isnan(row["atr"]):
                price = q["ask"]; stop = float(row["c"] - CF.STOP_ATR[name] * row["atr"]); val = CF.size_value(a["cash"], price, stop)
                if val > 1:
                    qty = val / price; fee = val * CF.COST; act = "buy"; append({"t": "fill", "ts": ts, "sleeve": name, "side": "buy", "price": round(price, 2), "qty": round(qty, 8), "cost": round(fee, 2), "stop": round(stop, 2), "bid": q["bid"], "ask": q["ask"], "bar": bar}, led)
                else:
                    act, why = "skipped", "no size (the stop is above the price or the sleeve has no cash)"
            ind = {k: (None if pd.isna(row[k]) else round(float(row[k]), 3)) for k in ("flow24", "delta_z", "vol_z", "c", "hi24", "sma50", "atr")}
            append({"t": "decision", "ts": ts, "sleeve": name, "bar": bar, "action": act, "signal_enter": bool(en[-1]), "signal_exit": bool(ex[-1]), "why": why, "minutes_after_close": round(late, 1), "indicators": ind}, led)
            lines = read_ledger(led); _, S = replay(lines)
    # 3. mark to market
    mark = q["bid"]; sl, tot = {}, 0.0
    for name, a in S.items():
        f = feats[name]; row = f.iloc[-1]; eq = a["cash"] + a["qty"] * mark; tot += eq
        sl[name] = {"label": SLEEVES[name]["label"], "timeframe": SLEEVES[name]["tf"], "share": SLEEVES[name]["share"], "cash": round(a["cash"], 2), "btc": round(a["qty"], 8), "equity": round(eq, 2), "entry": a["entry"], "stop": a["stop"], "since": a["since"],
                    "unrealised": round(a["qty"] * (mark - a["entry"]) - a["ecost"], 2) if a["qty"] > 0 else None, "trades": len(a["trades"]), "wins": sum(1 for t in a["trades"] if t["net"] > 0), "net": round(sum(t["net"] for t in a["trades"]), 2),
                    "now": {k: (None if pd.isna(row[k]) else round(float(row[k]), 3)) for k in ("flow24", "delta_z", "vol_z", "c", "hi24", "sma50")}, "last_bar": str(f.index[-1])}
    assert tot <= start["budget_usd"] * 3 and all(a["cash"] > -1e-6 for a in S.values()), "budget invariant broken"
    bh = start["budget_usd"] / (start["price0"] * (1 + CF.COST)) * mark * (1 - CF.COST)
    trades = sorted((t for a in S.values() for t in a["trades"]), key=lambda t: t["out_ts"])[-100:]; decisions = [r for r in lines if r["t"] == "decision"][-60:]
    marks = _marks(ts, tot, mark, now)
    doc = {"kind": "LIVE PAPER ACCOUNT (Bitcoin, order flow)", "label": "LIVE PAPER ACCOUNT: simulated money on Binance's real BTCUSDT prices. Hard budget Rs 10,00,000, no leverage, no exchange account, no real order.",
           "engine_ts": ts, "started": start["ts"], "budget_inr": BUDGET_INR, "budget_usd": start["budget_usd"], "fx0": start["fx0"], "fx_now": fx, "price": q["mid"], "bid": q["bid"], "ask": q["ask"], "equity_usd": round(tot, 2),
           "pnl_usd": round(tot - start["budget_usd"], 2), "return_pct": round((tot / start["budget_usd"] - 1) * 100, 3), "equity_inr_at_start_rate": round(tot * start["fx0"], 0), "equity_inr_now": round(tot * fx, 0) if fx else None,
           "invested_pct": round(sum(a["qty"] for a in S.values()) * mark / tot * 100, 1) if tot else 0.0, "buy_hold_usd": round(bh, 2), "sleeves": sl, "trades": trades, "decisions": decisions, "curve": marks, "stale_after_min": STALE_MIN,
           "study": "data/crypto/study.json"}
    p = Path(out or LIVE); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False), encoding="utf-8"); return doc


def _marks(ts, equity, price, now, path=None):
    """Hourly equity points (kept in data/crypto/marks.jsonl); returns the last 1,000 for the page."""
    p = Path(path or MARKS); rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    if not rows or (now - datetime.fromisoformat(rows[-1]["ts"])).total_seconds() >= 3300:
        rows.append({"ts": ts, "equity": round(equity, 2), "price": round(price, 2)}); p.parent.mkdir(parents=True, exist_ok=True); p.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n", encoding="utf-8")
    return [[r["ts"], r["equity"], r["price"]] for r in rows[-1000:]]


def main():
    d = live_step(); print(f"BTC ${d['price']:,.2f} | equity ${d['equity_usd']:,.2f} ({d['return_pct']:+.3f}%) of ${d['budget_usd']:,.2f} | invested {d['invested_pct']}% | " + " ".join(f"{k}: {v['trades']} trades, {'IN' if v['btc'] else 'flat'}" for k, v in d["sleeves"].items()))


if __name__ == "__main__":
    main()
