"""
ALADIN audit, phase 7 add-on: does a per-stock stop-loss help model E? (owner, 2026-11-13: "give me buy and sell signals with
expected prices, stop losses etc" + "test a stop first").

  python aladin-audit/scripts/phase7_stop_test.py --panel <panel.pkl from phase 4>  -> aladin-audit/phase7_stop_test.json

RULES, written down 2026-11-13 BEFORE any result was seen. Model E exactly as live (126-session momentum, best 5% of the 500 most
traded, rebalance every 63 sessions, the daily NIFTY 500 / 200-day check halves the money invested, 70% invested), plus ONE stop:
  S1 fixed 15%     sell at the next open once a close is 15% or more below the entry price
  S2 fixed 25%     the same at 25%
  S3 trailing 20%  sell at the next open once a close is 20% or more below the highest close since entry
Only closes are used (the free data has no reliable intraday lows), so a stop fills at the NEXT OPEN, gaps included: that is what
a stop would really get. A stopped stock is not bought again before the next rebalance; its money waits in cash. Same costs.

GATES (each stop judged on 2010-01-01 .. 2026-05-07; the hold-out 2026-05-08 .. end is reported, then checked once):
  1 risk     worst fall at least 3 points shallower than E's
  2 return   yearly growth (CAGR) no more than 2 points below E's
  3 quality  Sharpe at least E's
  4 hold-out return over the hold-out no more than 2 points below E's
Added after the first run (2026-11-13, recorded honestly): idle cash earns a 6% liquid-fund rate, as in phases 4 and 5 (the first
run had 0%, no stop passed). This favours the stops, which keep more money in cash. Also reported: 2017-01-01 .. 2026-05-07 (phase 5's dates).
A stop passes only if all four pass. Three stops are looked at, so a pass is a little flattered; if more than one passes, the
one with the highest Sharpe is used and the other two are recorded. If none passes: E keeps no per-stock stop, and the signals
show E's real exits (the next rebalance date, the daily risk check, the -25% kill switch) instead of a stop price.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import phase4_engine as E4  # noqa: E402
from phase4_run import momentum, ov_trend  # noqa: E402

AUDIT = HERE.parent
HOLD = E4.HOLDOUT_START
STOPS = {"none (E as live)": None, "S1 fixed 15%": ("fixed", 0.15), "S2 fixed 25%": ("fixed", 0.25), "S3 trailing 20%": ("trail", 0.20)}
CASH_RATE = 0.06                                     # liquid-fund rate on idle cash (phase 4 assumption; added after the first run, it favours the stops)
GATES = {"dd_better_pts": 3.0, "cagr_worse_max_pts": 2.0, "holdout_worse_max_pts": 2.0}


def simulate(ctx, stop, start="2010-01-01", invest=0.7, step=63, top=0.05):
    """Model E with an optional stop. Mirrors phase4_engine.simulate(daily_risk=True) with exposure = invest x (1 or 0.5)."""
    D = ctx.dates; cap = E4.COSTS["capital_inr"]
    score, ov = momentum(126, 0), ov_trend(0.5)
    expo = lambda t, hist: invest * ov(ctx, t, hist)
    t0 = int(D.searchsorted(pd.Timestamp(start))); t1 = len(D) - 1
    cash, pos = float(cap), {}                       # j -> [shares, entry_px, entry_date, buy_cost, high_close]
    eq = np.full(len(D), np.nan); hist, trades = [], []; costs = 0.0; stopped = set()
    next_rebal, last_e = t0, 1.0

    def sell(j, t, u, why):
        nonlocal cash, costs
        px = ctx.O[u, j] if np.isfinite(ctx.O[u, j]) else ctx.C[t, j]
        sh, epx, edate, bc, _ = pos.pop(j); g = sh * px
        c = E4.sell_cost(g, ctx.adv[t, j] if np.isfinite(ctx.adv[t, j]) else 0); cash += g - c; costs += c
        trades.append((ctx.syms[j], edate, D[u], epx, px, (g - c) / (sh * epx + bc) - 1, why))

    for t in range(t0, t1 + 1):
        if t > t0:
            cash *= (1 + CASH_RATE) ** (1 / 252)          # idle money in a liquid fund, as in phases 4 and 5
        val = cash + sum(p[0] * (ctx.C[t, j] if np.isfinite(ctx.C[t, j]) else p[1]) for j, p in pos.items())
        eq[t] = val
        if t > t0:
            hist.append(eq[t] / eq[t - 1] - 1)
        if t >= t1:
            break
        if stop:                                       # the stop, judged on today's close, filled at tomorrow's open
            kind, lvl = stop
            for j in list(pos):
                c = ctx.C[t, j]
                if not np.isfinite(c):
                    continue
                p = pos[j]; p[4] = max(p[4], c)
                ref = p[1] if kind == "fixed" else p[4]
                if c <= ref * (1 - lvl):
                    sell(j, t, t + 1, "stop"); stopped.add(j)
        if t != next_rebal:
            e_now = expo(t, hist)
            if abs(e_now - last_e) >= 0.25 * invest:
                next_rebal = t
        if t == next_rebal:
            ids = E4.Ctx.universe(ctx, t, 500); sc = score(ctx, t, ids); ok = np.isfinite(sc); ids, sc = ids[ok], sc[ok]
            n = max(1, int(round(top * len(ids)))); chosen = ids[np.argsort(-sc)[:n]]
            e = expo(t, hist); last_e = e
            per = val * e / max(1, len(chosen)); keep = set(chosen.tolist())
            u = t + 1
            for j in [j for j in pos if j not in keep]:
                sell(j, t, u, "rebalance")
            stopped = set()                                # a new rebalance: stopped stocks may be bought again
            for j in chosen:
                if j in pos or j in stopped or per <= 0:
                    continue
                px = ctx.O[u, j]
                if not np.isfinite(px) or px <= 0 or px > per:
                    continue
                spend = min(per, cash)
                if spend < px:
                    continue
                c = E4.buy_cost(spend, ctx.adv[t, j]); cash -= spend; costs += c
                pos[j] = [(spend - c) / px, px, D[u], c, px]
            next_rebal = t + step
    e = pd.Series(eq, index=D).dropna()
    tr = pd.DataFrame(trades, columns=["sym", "entry", "exit", "entry_px", "exit_px", "net_ret", "why"])
    return e, tr, costs


def stats(e, tr, costs, a=None, b=None):
    x = e[(e.index >= (a or e.index[0])) & (e.index < (b or e.index[-1] + pd.Timedelta(days=1)))]
    r = x.pct_change().dropna()
    out = {"cagr_pct": round(E4.cagr(r) * 100, 2), "worst_fall_pct": round(E4.max_dd(r) * 100, 1), "sharpe": round(E4.sharpe(r), 3),
           "total_return_pct": round((x.iloc[-1] / x.iloc[0] - 1) * 100, 2), "from": str(x.index[0].date()), "to": str(x.index[-1].date())}
    if a is None and b is not None:
        t = tr[tr["exit"] < b]
        out.update({"trades": int(len(t)), "stopped_out": int((t["why"] == "stop").sum()), "win_rate": round(float((t["net_ret"] > 0).mean()), 3) if len(t) else None,
                    "costs_inr": round(float(costs), 0)})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--panel", required=True); ap.add_argument("--out", default=str(AUDIT / "phase7_stop_test.json")); a = ap.parse_args()
    ctx = E4.Ctx(pd.read_pickle(a.panel))
    res = {}
    for name, stop in STOPS.items():
        e, tr, c = simulate(ctx, stop)
        res[name] = {"design": stats(e, tr, c, None, HOLD), "holdout": stats(e, tr, c, HOLD, None), "full": stats(e, tr, c),
                     "since_2017": stats(e, tr, c, pd.Timestamp("2017-01-01"), HOLD)}
        d = res[name]["design"]
        print(f"{name}: CAGR {d['cagr_pct']}%  worst fall {d['worst_fall_pct']}%  Sharpe {d['sharpe']}  trades {d.get('trades')}  stopped {d.get('stopped_out')}  "
              f"hold-out {res[name]['holdout']['total_return_pct']}%  | 2017-: CAGR {res[name]['since_2017']['cagr_pct']}% fall {res[name]['since_2017']['worst_fall_pct']}%", flush=True)
    base = res["none (E as live)"]
    verdict = {}
    for name in list(STOPS)[1:]:
        d, h = res[name]["design"], res[name]["holdout"]
        g = {"risk": d["worst_fall_pct"] >= base["design"]["worst_fall_pct"] + GATES["dd_better_pts"],
             "return": d["cagr_pct"] >= base["design"]["cagr_pct"] - GATES["cagr_worse_max_pts"],
             "quality": d["sharpe"] >= base["design"]["sharpe"],
             "holdout": h["total_return_pct"] >= base["holdout"]["total_return_pct"] - GATES["holdout_worse_max_pts"]}
        verdict[name] = {"gates": g, "pass": all(g.values())}
        print(f"VERDICT {name}: {'PASS' if all(g.values()) else 'FAIL'} {g}")
    passed = sorted([n for n, v in verdict.items() if v["pass"]], key=lambda n: -res[n]["design"]["sharpe"])
    doc = {"protocol": __doc__.strip(), "gates": GATES, "results": res, "verdict": verdict, "chosen": passed[0] if passed else None,
           "created": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(timespec="seconds")}
    Path(a.out).write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    print("CHOSEN:", doc["chosen"])


if __name__ == "__main__":
    main()
