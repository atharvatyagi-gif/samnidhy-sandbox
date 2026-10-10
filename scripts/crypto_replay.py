"""
Replay the LIVE engine (scripts/crypto_live.py live_step) over a past stretch of real data, one closed 4-hour bar at a time, exactly as it would have run, and compare what it did with the backtest.

  python scripts/crypto_replay.py --from 2024-03-01 --to 2024-04-30

It proves the machinery end to end: signals -> orders at the ask and bid -> stops -> ledger -> replayed account -> P&L. The replay's prices are real Binance candles (the next 15-minute bar's open is the price at which the engine runs,
with a 1 basis point spread), so it is the closest a past period can get to a live run. It writes only to a temporary folder. It is a check of the engine, not evidence about the strategies.
"""
import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypto_flow as CF  # noqa: E402
import crypto_live as CL  # noqa: E402


def replay(start, end, keep=9000):
    bars = {a: CF.load_bars(symbol=a) for a in CL.ASSETS}; tmp = Path(tempfile.mkdtemp(prefix="crypto_replay_")); led, out = tmp / "ledger.jsonl", tmp / "live.json"
    CL.MARKS, CL.DEPTH = tmp / "marks.jsonl", tmp / "depth.jsonl"; flat = {a: {"imb_near": 0.0, "imb_wide": 0.0, "spread_bps": 0.1} for a in CL.ASSETS}
    closes = pd.date_range(pd.Timestamp(start).ceil("4h"), pd.Timestamp(end), freq="4h"); doc = None
    for t in closes:
        b = {a: v[v.index < t].tail(keep) for a, v in bars.items()}                              # complete 15-minute bars up to the 4-hour close t
        nxt = {a: v[v.index >= t].head(1) for a, v in bars.items()}
        if any(len(x) == 0 for x in nxt.values()):
            break
        mid = {a: float(x["o"].iloc[0]) for a, x in nxt.items()}; q = {a: {"bid": m * (1 - 0.00005), "ask": m * (1 + 0.00005), "mid": m} for a, m in mid.items()}
        now = (t + pd.Timedelta(minutes=2)).to_pydatetime().replace(tzinfo=timezone.utc)
        doc = CL.live_step(now, b, q, 96.0, led, out, depth=flat)
    return doc, CL.read_ledger(led), tmp


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--from", dest="a", default="2024-03-01"); ap.add_argument("--to", dest="b", default="2024-04-30"); x = ap.parse_args()
    doc, lines, tmp = replay(x.a, x.b); fills = [r for r in lines if r["t"] == "fill"]; stops = [r for r in lines if r["t"] == "stop"]
    print(f"replayed {x.a} to {x.b}: {sum(1 for r in lines if r['t'] == 'decision')} decisions, {len(fills)} fills, {len(stops)} stop raises, files in {tmp}")
    print(f"account: budget ${doc['budget_usd']:,.2f} -> ${doc['equity_usd']:,.2f}  P&L {doc['pnl_usd']:+,.2f} ({doc['return_pct']:+.2f}%)  invested {doc['invested_pct']}%  buy&hold ${doc['buy_hold_usd']:,.2f}")
    for k, v in doc["sleeves"].items():
        print(f"  {k:20s} trades {v['trades']:2d} wins {v['wins']:2d} net ${v['net']:+9.2f} open {'yes, ' + str(v['qty']) if v['qty'] else 'no'}  sleeve value ${v['equity']:,.2f}")
    print("closed trades:")
    for t in doc["trades"]:
        print(f"  {t['sleeve']:20s} {t['in_ts'][5:16]} -> {t['out_ts'][5:16]}  {t['in']:>9,.2f} -> {t['out']:>9,.2f}  net ${t['net']:+8.2f} ({t['ret_pct']:+.2f}%)  {t['why']}")
    # the backtest on the same bars and window, for comparison: same signals, fills at the next bar's open
    print("backtest of the same sleeves over the same window (own account each, risk 2% to a 3-ATR stop):")
    for name, cfg in CL.SLEEVES.items():
        f = CF.features(CF.resample(CF.load_bars(symbol=cfg["asset"]), cfg["tf"])); f = f[f.index >= "2020-01-15"]; r = CF.simulate(f, cfg["strategy"], trail=bool(cfg.get("trail")))
        tr = [t for t in r["trades"] if x.a <= t["in"][:10] <= x.b]
        print(f"  {name:20s} {len(tr)} trades entered in the window: " + ", ".join(f"{t['in'][5:16]} {t['ret_pct']:+.2f}%" for t in tr[:8]))


if __name__ == "__main__":
    main()
