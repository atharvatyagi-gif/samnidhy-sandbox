"""Head-to-head: the self-evolving strategy desk against model E on survivorship-free data (docs/blab/HEAD_TO_HEAD.md, rules
and gates written 2026-11-17 before any result).

  python scripts/blab/head_to_head.py --bhav ../SAMNIDHY_bhav
  -> data/blab/head_to_head.json and docs/blab/HEAD_TO_HEAD_RESULT.md

Both run in the same simulator (scripts/blab/evolve.py) with the same costs, the same next-open fills, the same treatment of
locked circuits and of holdings that stop trading, and the same market risk control applied to their daily returns:
70% invested, 35% while the index is below its 200-day average (decided at the previous close; idle cash earns nothing;
a change of invested share pays 0.25% on the money moved). No kill switch for either (it is an emergency stop, not the model).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blab import evolve as V  # noqa: E402
from blab.core import DATA, ROOT  # noqa: E402

E_RULE = {"id": "model_e", "fam": "mom", "p": {"n": 126}}
E_OPTS = {"slots": 25, "rebal": 63, "top_n": 500, "min_value": 5e7}      # aladin_e.json: best 5% of the 500 most traded, every 63 sessions
GATE_RISK, GATE_HOLDOUT_PTS = -25.0, 2.0
SHARE_ON, SHARE_OFF, RESIZE_COST = 0.70, 0.35, 0.0025


def index_series():
    from blab.technical import joined, _rows, TERM
    n50 = joined("_5eNSEI.json", _rows(TERM / "idx" / "out" / "d" / "Nifty_2050.json"))
    n500 = {r[0]: r[4] for r in _rows(TERM / "idx" / "out" / "d" / "Nifty_20500.json") if r[4]}
    return n50, n500


def risk_share(dates, n50, n500):
    """Invested share for each day, decided at the PREVIOUS close: the NIFTY 500 against its 200-day average where it has
    200 days of history, otherwise the NIFTY 50 (docs/blab/HEAD_TO_HEAD.md section 3)."""
    import numpy as np
    def above(series):
        ds = sorted(series); v = np.array([series[d] for d in ds], float)
        ma = np.convolve(v, np.ones(200) / 200, mode="full")[: len(v)]
        ma[:199] = np.nan
        return {d: (v[i] > ma[i]) if np.isfinite(ma[i]) else None for i, d in enumerate(ds)}
    a500, a50 = above(n500), above(n50)
    out, prev = {}, None
    for d in dates:
        out[d] = SHARE_ON if prev is None else prev
        x = a500.get(d)
        x = a50.get(d) if x is None else x
        prev = SHARE_OFF if x is False else SHARE_ON
    return out


def overlay(rets, share):
    """Daily strategy returns (fully invested) -> returns of the account with the risk control."""
    out, last = {}, None
    for d in sorted(rets):
        s = share.get(d, SHARE_ON)
        r = s * rets[d] - (abs(s - last) * RESIZE_COST if last is not None and s != last else 0.0)
        out[d], last = r, s
    return out


def curve(rets):
    ds = sorted(rets); e = [1.0]
    for d in ds:
        e.append(e[-1] * (1 + rets[d]))
    return ds, e[1:]


def summary(rets, hold):
    ds, e = curve(rets)
    return {"whole": V.stats(e, ds), "design": V.stats(e, ds, b=hold), "holdout": V.stats(e, ds, a=hold)}


def model_e(M, cfg, vanish):
    r = V.simulate(M, E_RULE, cfg, vanish=vanish, **E_OPTS)
    import numpy as np
    e = np.array(r["eq"], float)
    return dict(zip(r["dates"][1:], (e[1:] / e[:-1] - 1).tolist())), r


def desk(M, cfg, vanish):
    R = V.replay(M, cfg, vanish=vanish, log=lambda *a: None)
    sel, bl = R["result"]["selector"]["whole"] or {}, R["result"]["blend"]["whole"] or {}
    mode = "selector" if (sel.get("sharpe") or -9) > (bl.get("sharpe") or -9) else "blend"
    return (R["sel_ret"] if mode == "selector" else R["blend_ret"]), mode, R


def gates(desk_s, e_s, desk_stress, e_stress):
    g1 = (desk_s["whole"] or {}).get("worst_fall_pct", -100) >= GATE_RISK
    g2 = ((desk_s["design"] or {}).get("sharpe") or -9) > ((e_s["design"] or {}).get("sharpe") or -9)
    g3 = ((desk_s["holdout"] or {}).get("cagr_pct") or -99) >= ((e_s["holdout"] or {}).get("cagr_pct") or -99) - GATE_HOLDOUT_PTS
    g4 = ((desk_stress["whole"] or {}).get("sharpe") or -9) > ((e_stress["whole"] or {}).get("sharpe") or -9)
    return {"1 risk (worst fall no deeper than -25%)": bool(g1), "2 quality (higher Sharpe than model E, design years)": bool(g2),
            "3 hold-out (yearly return within 2 points of model E)": bool(g3), "4 stress (Sharpe above model E with vanished holdings at zero)": bool(g4)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--bhav", required=True); ap.add_argument("--skip-bias", action="store_true"); a = ap.parse_args()
    from blab.unbiased import BhavMarket
    cfg = json.loads((DATA / "config" / "aladin_e.json").read_text(encoding="utf-8"))
    n50, n500 = index_series()
    M = BhavMarket(a.bhav, index_series=n50)
    share = risk_share(M.dates, n50, n500)
    print(f"bias-free market: {len(M.syms):,} companies (delisted included), {M.dates[0]} to {M.dates[-1]}; tradable on the last day: {int(M.elig[-1].sum())}", flush=True)
    out = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": {"companies": len(M.syms), "from": M.dates[0], "to": M.dates[-1]}, "cases": {}}
    hold = (date.fromisoformat(M.dates[-1]) - __import__("datetime").timedelta(days=V.HOLDOUT_DAYS)).isoformat()
    out["holdout_from"] = hold
    for case in ("base", "stress"):
        er, erun = model_e(M, cfg, case)
        dr, mode, R = desk(M, cfg, case)
        e_s, d_s = summary(overlay(er, share), hold), summary(overlay(dr, share), hold)
        n_ret = {d: M.n50[i] / M.n50[i - 1] - 1 for i, d in enumerate(M.dates) if i}
        out["cases"][case] = {"model_e": e_s, "desk": d_s, "desk_mode": mode, "desk_tried": R["tried"], "desk_live": R["live"],
                              "desk_unlevered": summary(dr, hold), "model_e_unlevered": summary(er, hold), "nifty50": summary({d: v for d, v in n_ret.items() if d >= V.START}, hold),
                              "model_e_trades": len(erun["trades"]), "model_e_vanished": sum(1 for t in erun["trades"] if len(t) > 7)}
        print(case, "model E", e_s["whole"], "| desk", mode, d_s["whole"], flush=True)
    c = out["cases"]
    out["gates"] = gates(c["base"]["desk"], c["base"]["model_e"], c["stress"]["desk"], c["stress"]["model_e"])
    out["verdict"] = "replace model E with the desk" if all(out["gates"].values()) else "keep model E; the desk stays a research page"
    if not a.skip_bias:                                                  # the bias the old cache carried (same rules, companies listed today only)
        Mc = V.Market()
        er0, _ = model_e(Mc, cfg, None); dr0, mode0, _ = desk(Mc, cfg, None)
        sh0 = risk_share(Mc.dates, n50, n500)
        out["old_cache"] = {"model_e": summary(overlay(er0, sh0), hold), "desk": summary(overlay(dr0, sh0), hold), "desk_mode": mode0}
    (DATA / "blab" / "head_to_head.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("GATES", out["gates"], "->", out["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
