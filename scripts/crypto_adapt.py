"""
Self-evolving crypto rules: regime switching + a monthly champion/challenger, tested walk-forward BEFORE it may run the live account.

  python scripts/crypto_adapt.py --study        -> data/crypto/adapt_study.json   (walk-forward test, both coins)
  python scripts/crypto_adapt.py --table        -> data/crypto/adapt_table.json   (the table the live engine would use from now on)

Method, written down before any result was seen (owner's choice 2026-10-12: "both: regimes + challenger"):
  STATES   at each 4-hour close, from past bars only: trend = price above its 200-bar average AND that average higher than 30 bars ago ("up"),
           otherwise "down/sideways"; heat = ATR as a share of price above the 80th percentile of the previous 1,500 bars ("hot"), otherwise "calm".
           Four states: up-calm, up-hot, down-calm, down-hot.
  POOL     the rules already written down in crypto_flow.py / crypto_extra.py, all on 4-hour bars: momentum, breakout, momentum_trend, cvd_trend, union,
           ha_trend, ha_flow, flow_absorb, plus CASH. Nothing new is invented here.
  FIT      for a window of the last 3 years: run every rule over the window; credit each trade to the state at its entry bar; for each state pick the rule
           with the highest mean net return per trade (after costs) among rules with at least 8 trades in that state; if none is positive, CASH.
  SLEEVES  each coin keeps two sleeves (as live). Sleeve A starts from today's momentum rule, sleeve B from today's breakout rule. In the fit, sleeve B may
           not take the rule sleeve A took for the same state (so the two sleeves stay different).
  SWITCH   whichever rule the table names for the CURRENT state decides entries and exits; a position opened by one rule is closed by the rule now in
           charge (its exit signal) or, in a CASH state, at the next open. Stops: 3 ATR as now.
  CHALLENGE on the first day of every month: a challenger table is fitted on the 3 years ending 3 months ago; champion and challenger are both replayed
           on those last 3 months (unseen by the challenger); the challenger replaces the champion only if it made more there after costs. The first
           champion is exactly today's fixed rules (every state -> the sleeve's current rule), so nothing changes without evidence.
  TEST     walk-forward from 2021-01 (the first fit needs a year of history) to the last bar, at 0.12% and at 0.25% per fill, against the fixed rules.
           The adaptive version may run the live account only if it beats the fixed rules on 2024-2026 AND at double cost; otherwise the fixed rules stay
           and the table is only shown. Many choices are made inside (four states, eight rules, monthly), so even a pass is flattered; the live record decides.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypto_flow as CF  # noqa: E402
import crypto_extra as CX  # noqa: E402

OUT = CF.OUT
POOL = ["momentum", "breakout", "momentum_trend", "cvd_trend", "union", "ha_trend", "ha_flow", "flow_absorb"]
STATES = ["up_calm", "up_hot", "down_calm", "down_hot"]
START_RULE = {"A": "momentum", "B": "breakout"}
WINDOW_Y, VALID_M, MIN_N = 3, 3, 8
ASSETS = ["BTCUSDT", "ETHUSDT"]


def frame(symbol):
    f = CX.extra_features(CF.features(CF.resample(CF.load_bars(symbol=symbol), "4h")))
    return f[f.index >= "2020-01-15"]


def states(f):
    """State of every bar from bars up to and including it."""
    up = (f["c"] > f["sma200"]) & (f["sma200"] > f["sma200"].shift(30))
    atrp = f["atr"] / f["c"]; hot = atrp > atrp.rolling(1500, min_periods=300).quantile(0.8).shift(1)
    return pd.Series(np.where(up, "up", "down"), index=f.index) + "_" + pd.Series(np.where(hot.fillna(False), "hot", "calm"), index=f.index)


def rule_signals(f, rule):
    if rule in ("ha_trend", "ha_flow", "flow_absorb"):
        return CF.signals(f, rule)
    return CX.cand_signals(f, rule)


def all_signals(f):
    return {r: rule_signals(f, r) for r in POOL}


def full_trades(f, sig, cost=CF.COST):
    """Each rule run alone over the whole history once; a window's trades are then a filter (a trade's % return does not depend on the account size)."""
    return {r: CF.simulate(f, "flow_momentum", cost=cost, enter=e, exit_=x)["trades"] for r, (e, x) in sig.items()}


def fit(trades, st, lo, hi, taken=None):
    """table {state: rule or "cash"} from trades ENTERED in [lo, hi)."""
    taken, table = taken or {}, {}
    for s in STATES:
        best, score = "cash", 0.0
        for r, tr in trades.items():
            if taken.get(s) == r:
                continue
            x = [t["ret_pct"] for t in tr if lo <= pd.Timestamp(t["in"]) < hi and st.get(pd.Timestamp(t["in"])) == s]
            if len(x) >= MIN_N and np.mean(x) > score:
                best, score = r, float(np.mean(x))
        table[s] = best
    return table


def switched(f, sig, st, tables):
    """enter/exit arrays when the table in force at each bar (tables: list of (from timestamp, table)) names the rule for that bar's state."""
    n = len(f); en, ex = np.zeros(n, bool), np.zeros(n, bool); k = 0; idx = f.index; stv = st.values
    for i in range(n):
        while k + 1 < len(tables) and idx[i] >= tables[k + 1][0]:
            k += 1
        r = tables[k][1].get(stv[i], "cash")
        if r == "cash":
            ex[i] = True
        else:
            e, x = sig[r]; en[i], ex[i] = e[i], x[i]
    return en, ex


def replay(f, sig, st, tables, lo, hi, cost=CF.COST):
    e, x = switched(f, sig, st, tables); r = CF.simulate(f, "flow_momentum", cost=cost, enter=e, exit_=x)
    eq = r["equity"]; seg = eq[(eq.index >= lo) & (eq.index < hi)].dropna()
    return float(seg.iloc[-1] / seg.iloc[0] - 1) if len(seg) > 1 else 0.0, r


def evolve(f, sig, st, trades, sleeve, first, months, taken_by=None):
    """Walk the months: returns the list of (from, table) actually in force, and a log of every challenge."""
    champion = {s: START_RULE[sleeve] for s in STATES}; tables, log = [(f.index[0], champion)], []
    for m in months:
        vlo = m - pd.DateOffset(months=VALID_M); flo = vlo - pd.DateOffset(years=WINDOW_Y)
        taken = {s: t[s] for s in STATES} if (t := (taken_by(m) if taken_by else None)) else None
        chal = fit(trades, st, max(flo, f.index[0]), vlo, taken)
        if chal == champion:
            continue
        c_ret, _ = replay(f, sig, st, [(f.index[0], chal)], vlo, m)
        h_ret, _ = replay(f, sig, st, [(f.index[0], champion)], vlo, m)
        won = c_ret > h_ret
        log.append({"month": str(m.date()), "challenger": chal, "champion": champion, "challenger_3m_pct": round(c_ret * 100, 2), "champion_3m_pct": round(h_ret * 100, 2), "replaced": won})
        if won:
            champion = chal; tables.append((m, champion))
    return tables, log


def table_at(tables, m):
    t = tables[0][1]
    for ts, tb in tables:
        if ts <= m:
            t = tb
    return t


def study_asset(symbol):
    f = frame(symbol); st = states(f); sig = all_signals(f); trades = full_trades(f, sig)
    months = list(pd.date_range("2021-01-01", f.index[-1], freq="MS"))
    tabA, logA = evolve(f, sig, st, trades, "A", None, months)
    tabB, logB = evolve(f, sig, st, trades, "B", None, months, taken_by=lambda m: table_at(tabA, m))
    out = {"states_share": st.value_counts(normalize=True).round(3).to_dict(), "sleeves": {}}
    for sl, tabs, log in (("A", tabA, logA), ("B", tabB, logB)):
        res = {}
        for cost, tag in ((CF.COST, "cost_0.12pct"), (0.0025, "cost_0.25pct")):
            _, ad = replay(f, sig, st, tabs, f.index[0], f.index[-1] + pd.Timedelta("4h"), cost)
            fx = CF.simulate(f, "flow_momentum", cost=cost, enter=sig[START_RULE[sl]][0], exit_=sig[START_RULE[sl]][1])
            res[tag] = {"adaptive": {"2021-2023": CF.period_stats(ad["equity"], ad["trades"], "2021-01-01", CF.SELECT_END), "2024-2026": CF.period_stats(ad["equity"], ad["trades"], "2024-01-01", None)},
                        "fixed": {"2021-2023": CF.period_stats(fx["equity"], fx["trades"], "2021-01-01", CF.SELECT_END), "2024-2026": CF.period_stats(fx["equity"], fx["trades"], "2024-01-01", None)}}
        out["sleeves"][sl] = {"start_rule": START_RULE[sl], "results": res, "challenges": log, "replacements": sum(1 for x in log if x["replaced"]), "table_now": tabs[-1][1], "table_since": str(tabs[-1][0].date())}
    return out, f, st, sig, trades


def passes(a):
    """The pre-declared gate: adaptive beats fixed on 2024-2026 at normal AND double cost, for the sleeve."""
    ok = True
    for tag in ("cost_0.12pct", "cost_0.25pct"):
        r = a["results"][tag]; ad, fx = r["adaptive"]["2024-2026"].get("return_pct"), r["fixed"]["2024-2026"].get("return_pct")
        ok = ok and ad is not None and fx is not None and ad > fx
    return ok


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--study", action="store_true"); ap.add_argument("--table", action="store_true"); a = ap.parse_args()
    if a.study:
        doc = {"protocol": __doc__.strip(), "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "assets": {}}
        for sym in ASSETS:
            res, *_ = study_asset(sym)
            for sl in res["sleeves"].values():
                sl["passes_gate"] = passes(sl)
            doc["assets"][sym] = res
            for k, sl in res["sleeves"].items():
                for tag, r in sl["results"].items():
                    P = lambda d: f"n={d.get('trades', 0):3d} ret {d.get('return_pct')!s:>7}% dd {d.get('max_drawdown_pct')!s:>6}% sh {d.get('sharpe')!s:>5}"
                    print(f"{sym} sleeve {k} ({sl['start_rule']}) {tag}: 21-23 ADAPT {P(r['adaptive']['2021-2023'])} | FIXED {P(r['fixed']['2021-2023'])}")
                    print(f"{' ' * len(sym)}                {tag}: 24-26 ADAPT {P(r['adaptive']['2024-2026'])} | FIXED {P(r['fixed']['2024-2026'])}")
                print(f"   replacements {sl['replacements']} of {len(sl['challenges'])} challenges; table now {sl['table_now']} (since {sl['table_since']}); PASSES GATE: {sl['passes_gate']}")
            print("   time in each state:", res["states_share"])
        (OUT / "adapt_study.json").write_text(json.dumps(doc, separators=(",", ":"), default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
