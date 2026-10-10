"""
Round two of the Bitcoin strategy search: are there better strategies than the two now traded (order-flow momentum and order-flow breakout on 4-hour bars)?

  python scripts/crypto_extra.py [--symbol BTCUSDT]      -> data/crypto/study_extra[_eth].json

The candidates below were written down BEFORE any result was seen. The held-out years 2024-2026 were already looked at once for the two strategies now traded, so they are not untouched any more; to limit the damage:
  1. A candidate is eligible only if, on 2020-2023, it made at least 30 trades and was profitable in BOTH halves (2020-21 and 2022-23).
  2. Eligible candidates are ranked by Sharpe on 2020-2023 ONLY. The ranking never looks at 2024-2026.
  3. A traded strategy is replaced only if a candidate beats it on 2020-2023 Sharpe AND is positive on 2024-2026 AND is positive at double costs AND its 2024-2026 Sharpe is not lower. Otherwise nothing changes.
  Trying many candidates flatters the winner; the live record is what finally decides.
Candidates (timeframe in brackets; all long-only, risk 2% to a 3-ATR stop, cost 0.12% a fill):
  momentum / breakout on 8h and 12h bars            the same two rules on slower bars: fewer trades, less fee drag
  momentum_trend [4h, 8h]                           momentum entry only while price is above its 200-bar average; leave when buying fades or price falls under its 50-bar average
  cvd_trend [4h, 8h]                                Heikin-Ashi green twice AND cumulative delta at a 48-bar high; leave when cumulative delta falls under its 24-bar low or the bar turns red
  union [4h, 8h]                                    enter on a momentum OR a breakout signal; leave only when both want out
  momentum_trail / breakout_trail [4h]              the baseline rules, plus a trailing stop that ratchets up to 3 ATR under each close
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypto_flow as CF  # noqa: E402

OUT = CF.OUT


def extra_features(f):
    f = f.copy(); f["sma200"] = f["c"].rolling(200).mean(); f["cvd"] = f["delta"].cumsum()
    f["cvd_hi48"] = f["cvd"].shift(1).rolling(48).max(); f["cvd_lo24"] = f["cvd"].shift(1).rolling(24).min(); return f


def cand_signals(f, name):
    mom_e, mom_x = CF.signals(f, "flow_momentum"); brk_e, brk_x = CF.signals(f, "flow_breakout")
    if name in ("momentum", "momentum_trail"):
        return mom_e, mom_x
    if name in ("breakout", "breakout_trail"):
        return brk_e, brk_x
    if name == "momentum_trend":
        e = mom_e & (f["c"] > f["sma200"]).fillna(False).values; x = mom_x | (f["c"] < f["sma50"]).fillna(False).values; return e, x
    if name == "cvd_trend":
        ok = f[["atr", "cvd_hi48", "cvd_lo24"]].notna().all(axis=1)
        e = (f["ha_green"] & f["ha_nowick"] & f["ha_green"].shift(1, fill_value=False) & f["ha_nowick"].shift(1, fill_value=False) & (f["cvd"] >= f["cvd_hi48"]) & ok).fillna(False).values
        x = ((f["cvd"] < f["cvd_lo24"]) | ~f["ha_green"]).fillna(False).values; return e, x
    if name == "union":
        return mom_e | brk_e, mom_x & brk_x
    raise KeyError(name)


CANDIDATES = [("momentum", "4h"), ("breakout", "4h"), ("momentum", "8h"), ("breakout", "8h"), ("momentum", "12h"), ("breakout", "12h"), ("momentum_trend", "4h"), ("momentum_trend", "8h"), ("cvd_trend", "4h"), ("cvd_trend", "8h"),
              ("union", "4h"), ("union", "8h"), ("momentum_trail", "4h"), ("breakout_trail", "4h")]
BASELINE = {("momentum", "4h"), ("breakout", "4h")}


def run(f, name, cost=CF.COST):
    e, x = cand_signals(f, name); return CF.simulate(f, "flow_momentum", cost=cost, enter=e, exit_=x, trail=name.endswith("_trail"))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbol", default="BTCUSDT"); a = ap.parse_args(); bars = CF.load_bars(symbol=a.symbol); res = {}; cache = {}
    for name, tf in CANDIDATES:
        if tf not in cache:
            cache[tf] = extra_features(CF.features(CF.resample(bars, tf))); cache[tf] = cache[tf][cache[tf].index >= "2020-01-15"]
        f = cache[tf]; r = run(f, name); r2 = run(f, name, cost=0.0025); tr = r["trades"]
        res[f"{name}_{tf}"] = {"strategy": name, "timeframe": tf, "baseline": (name, tf) in BASELINE, "selection": CF.period_stats(r["equity"], tr, None, CF.SELECT_END),
                               "half_2020_21": CF.period_stats(r["equity"], tr, None, "2021-12-31 23:59"), "half_2022_23": CF.period_stats(r["equity"], tr, "2022-01-01", CF.SELECT_END),
                               "held_out": CF.period_stats(r["equity"], tr, "2024-01-01", None), "held_out_cost_0.25pct": CF.period_stats(r2["equity"], r2["trades"], "2024-01-01", None),
                               "held_out_trade_ci95_pct": CF.boot_mean([t for t in tr if pd.Timestamp(t["out"]) >= pd.Timestamp("2024-01-01")])}
    elig = {k: v for k, v in res.items() if v["selection"].get("trades", 0) >= 30 and (v["half_2020_21"].get("return_pct") or -1) > 0 and (v["half_2022_23"].get("return_pct") or -1) > 0}
    rank = sorted(elig, key=lambda k: -(elig[k]["selection"].get("sharpe") or -9))
    base = {k: v for k, v in res.items() if v["baseline"]}; best_base = max(base, key=lambda k: base[k]["selection"].get("sharpe") or -9)
    replace = []
    for k in rank:
        v = res[k]
        if v["baseline"]:
            continue
        for b, bv in base.items():
            ok = (v["selection"]["sharpe"] > bv["selection"]["sharpe"] and (v["held_out"].get("return_pct") or -1) > 0 and (v["held_out_cost_0.25pct"].get("return_pct") or -1) > 0 and (v["held_out"].get("sharpe") or -9) >= (bv["held_out"].get("sharpe") or -9))
            if ok:
                replace.append({"candidate": k, "beats": b})
    out = {"protocol": __doc__.strip(), "symbol": a.symbol, "variants": res, "eligible_ranked_on_selection": rank, "replacement_rule_passed": replace}
    (OUT / ("study_extra.json" if a.symbol == "BTCUSDT" else f"study_extra_{a.symbol[:-4].lower()}.json")).write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    P = lambda d: f"n={d.get('trades', 0):3d} ret {d.get('return_pct')!s:>7}% dd {d.get('max_drawdown_pct')!s:>6}% sh {d.get('sharpe')!s:>5} avg {d.get('avg_net_pct')!s:>6}%"
    for k, v in res.items():
        print(f"{k:24s}{'*' if v['baseline'] else ' '} SEL {P(v['selection'])} | h1 {v['half_2020_21'].get('return_pct')!s:>6} h2 {v['half_2022_23'].get('return_pct')!s:>6} || HELD {P(v['held_out'])} | x2cost {v['held_out_cost_0.25pct'].get('return_pct')}%")
    print("eligible, ranked on selection:", rank); print("replacement rule passed:", replace)


if __name__ == "__main__":
    main()
