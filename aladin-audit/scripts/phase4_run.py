"""
ALADIN audit, phase 4: head-to-head test of the options on one setup (scripts/phase4_engine.py).

  python aladin-audit/scripts/phase4_run.py --main <main working copy> --panel <panel.pkl>
  -> aladin-audit/phase4/results.json, aladin-audit/TRIALS.md, charts

Fixed before any result was seen (2026-11-10):
  * Filter levels: tight = best 2% of the universe, medium = best 5%, loose = best 10% (your goal: test looser filters).
  * Selection period 2010-01-01 .. 2026-05-07. Hold-out 2026-05-08 .. 2026-11-06 is used once, at the end, for the finalists.
  * Walk-forward: for each year Y from 2013, each option's setting is the one with the best Sharpe ratio on 2010 .. Y-1 only.
  * Purged cross-validation: 5 time blocks; settings chosen on the other blocks minus 21 trading days on each side (purge + embargo).
  * Ranking of options: Sharpe of the walk-forward series in excess of random picks with the same rules; steadiness across years breaks ties.
  * Your risk limit: worst fall no deeper than -25%.
"""
import argparse
import itertools
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

import phase4_engine as E

AUDIT = Path(__file__).resolve().parent.parent
OUT = AUDIT / "phase4"
SEL_END = "2026-05-07"
LEVELS = {"tight 2%": 0.02, "medium 5%": 0.05, "loose 10%": 0.10}


# ------------------------------------------------------------------ signals

def rank_pct(x):
    return pd.Series(x).rank(pct=True).values


def momentum(L, skip, sector=None):
    def f(c, t, ids):
        s = c.ret(t, L, skip)[ids]
        if sector is None:
            return s
        g = sector[ids]
        out = np.full(len(ids), np.nan)
        df = pd.DataFrame({"s": s, "g": g})
        r = df.groupby("g")["s"].rank(pct=True)
        n = df.groupby("g")["s"].transform("count")
        out = np.where(n >= 3, r, df["s"].rank(pct=True))
        return np.where(np.isfinite(s), out, np.nan)
    return f


def lowvol(c, t, ids):
    return -c.vol252[t][ids]


def reversal(L):
    return lambda c, t, ids: -c.ret(t, L, 0)[ids]


def blend(w_calm, w_stress):
    def f(c, t, ids):
        calm = bool(c.mkt_up[t]) and np.isfinite(c.vix_pct[t]) and c.vix_pct[t] < 0.7
        w = w_calm if calm else w_stress
        m, v, r = c.ret(t, 252, 21)[ids], -c.vol252[t][ids], -c.ret(t, 21, 0)[ids]
        ok = np.isfinite(m) & np.isfinite(v) & np.isfinite(r)
        sc = w[0] * rank_pct(m) + w[1] * rank_pct(v) + w[2] * rank_pct(r)
        return np.where(ok, sc, np.nan)
    return f


def record_scores(main, h, col):
    O = pd.read_pickle(main / "data" / "aladin_cache" / f"oos_{h}.pkl")
    raw = O[col].where(O[col].notna(), O["p"]) if col != "p" else O["p"]
    O = O.assign(s=raw.values)
    by = {d: g.set_index("sym")["s"] for d, g in O.groupby("date")}
    dates = np.array(sorted(by))

    def f(c, t, ids):
        d = c.dates[t]
        k = dates.searchsorted(d, side="right") - 1
        if k < 0 or (d - dates[k]).days > 8:
            return np.full(len(ids), np.nan)
        s = by[dates[k]]
        return s.reindex(c.syms[ids]).values.astype(float)
    return f, pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])


# ------------------------------------------------------------------ overlays (option E)

def ov_trend(full_off=0.0):
    return lambda c, t, hist: 1.0 if c.mkt_up[t] else full_off


def ov_voltarget(target=0.15):
    def f(c, t, hist):
        h = np.asarray(hist[-63:])
        if len(h) < 40 or h.std() == 0:
            return 1.0
        return float(min(1.0, target / (h.std() * math.sqrt(252))))
    return f


def ov_vix(cut=0.8):
    return lambda c, t, hist: 0.5 if np.isfinite(c.vix_pct[t]) and c.vix_pct[t] > cut else 1.0


def ov_ddbrake(limit=0.12):
    """Halve the money invested while the account is more than `limit` below its own peak (your -25% limit in mind)."""
    def f(c, t, hist):
        if len(hist) < 2:
            return 1.0
        e = np.cumprod(1 + np.asarray(hist[-500:]))
        return 0.5 if e[-1] / e.max() - 1 < -limit else 1.0
    return f


def ov_trend_vol(target=0.15):
    a, b = ov_trend(0.0), ov_voltarget(target)
    return lambda c, t, hist: a(c, t, hist) * b(c, t, hist)


# ------------------------------------------------------------------ selection

def yearly_choice(runs, first=2013):
    """runs: {name: daily Series}. Walk-forward: for each year Y choose the run with the best Sharpe on data before Y. -> stitched Series, choices."""
    years = sorted({d.year for r in runs.values() for d in r.index if d.year >= first})
    parts, choice = [], {}
    for y in years:
        best, bs = None, -1e9
        for k, r in runs.items():
            past = r[r.index.year < y]
            if len(past) < 400:
                continue
            s = E.sharpe(past)
            if s > bs:
                best, bs = k, s
        if best is None:
            continue
        choice[y] = best
        parts.append(runs[best][runs[best].index.year == y])
    return (pd.concat(parts) if parts else pd.Series(dtype=float)), choice


def purged_cv(runs, k=5, gap=21):
    idx = sorted(set().union(*[set(r.index) for r in runs.values()]))
    idx = pd.DatetimeIndex(idx)
    idx = idx[(idx >= "2011-01-01") & (idx <= SEL_END)]
    blocks = np.array_split(np.arange(len(idx)), k)
    out = []
    for b in blocks:
        lo, hi = b[0], b[-1]
        test = idx[lo:hi + 1]
        excl = idx[max(0, lo - gap):min(len(idx), hi + gap + 1)]
        best, bs = None, -1e9
        for name, r in runs.items():
            tr = r[~r.index.isin(excl)]
            s = E.sharpe(tr)
            if s > bs:
                best, bs = name, s
        rt = runs[best][runs[best].index.isin(test)]
        out.append({"block": f"{test[0].date()}..{test[-1].date()}", "chosen": best, "sharpe_on_block": round(E.sharpe(rt), 2)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True)
    ap.add_argument("--panel", required=True)
    a = ap.parse_args()
    main = Path(a.main)
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    P = pd.read_pickle(a.panel)
    ctx = E.Ctx(P)
    prof = json.loads((main / "data" / "nexus_predict" / "profiles.json").read_text(encoding="utf-8"))["cos"]
    sector = np.array([(prof.get(s) or {}).get("ind") or "none" for s in ctx.syms])

    # ---------- the trial grid (every run is logged)
    grid = {}
    for lvl, pct in LEVELS.items():
        for L, skip, step, sn in itertools.product([126, 189, 252], [0, 21], [21, 63], [False, True]):
            grid[("A momentum", lvl, f"L{L} skip{skip} step{step}{' sector' if sn else ''}")] = (momentum(L, skip, sector if sn else None), step, pct, None)
        for L, skip, step in itertools.product([126, 252], [0, 21], [21, 63]):
            for oname, ov in {"trend": ov_trend(0.0), "trend half": ov_trend(0.5), "vol 15%": ov_voltarget(0.15), "trend+vol": ov_trend_vol(0.15), "vix": ov_vix(0.8), "dd brake 12%": ov_ddbrake(0.12)}.items():
                grid[("E momentum + risk", lvl, f"L{L} skip{skip} step{step} {oname}")] = (momentum(L, skip), step, pct, ov)
                grid[("x first try: risk checked on rebalance days only", lvl, f"L{L} skip{skip} step{step} {oname}")] = (momentum(L, skip), step, pct, ov)
        for wc, ws in itertools.product([(0.6, 0.2, 0.2), (0.8, 0.2, 0.0), (0.4, 0.4, 0.2)], [(0.2, 0.8, 0.0), (0.4, 0.6, 0.0), (0.2, 0.6, 0.2)]):
            grid[("D regime blend", lvl, f"calm{wc} stress{ws}")] = (blend(wc, ws), 21, pct, None)
        for step in [21, 63]:
            grid[("G low volatility", lvl, f"step{step}")] = (lowvol, step, pct, None)
        grid[("G reversal", lvl, "1 week, weekly")] = (reversal(5), 5, pct, None)
        grid[("G reversal", lvl, "1 month, monthly")] = (reversal(21), 21, pct, None)
    rec = {}
    for h, col, step in ((20, "p", 20), (10, "p_reg", 10), (5, "p", 5)):
        f, d0, d1 = record_scores(main, h, col)
        rec[h] = (d0, d1)
        for lvl, pct in LEVELS.items():
            grid[("C machine learning (ALADIN 1 model)", lvl, f"{h}-day model, hold {step}")] = (f, step, pct, None)
    f5, d0, d1 = record_scores(main, 5, "p")
    grid[("Current ALADIN (weekly BUY rule)", "top 1% (as live)", "5-day model, hold 5")] = (f5, 5, 0.01, None)

    runs, log = {}, []
    for key, (fn, step, pct, ov) in grid.items():
        start = "2015-01-02" if key[0].startswith(("C ", "Current")) else "2010-01-01"
        r = E.simulate(ctx, fn, step, ("pct", pct), start=start, end=SEL_END, exposure_fn=ov, record=False, daily_risk=key[0].startswith("E"))["daily"]
        runs[key] = r
        log.append({"option": key[0], "filter": key[1], "setting": key[2], "from": str(r.index[0].date()), "cagr_pct": round(E.cagr(r) * 100, 1), "sharpe": round(E.sharpe(r), 2), "max_dd_pct": round(E.max_dd(r) * 100, 1)})
    print(f"{len(runs)} trial runs in {time.time() - t0:.0f} s")
    sr_daily = np.array([r.mean() / r.std() for r in runs.values() if r.std() > 0])
    n_trials, sr_var = len(runs), float(np.var(sr_daily))

    # ---------- baselines
    base = {}
    for lvl, pct in LEVELS.items():
        rs = [E.simulate(ctx, None, 21, ("pct", pct), start="2010-01-01", end=SEL_END, seed=s, record=False)["daily"] for s in range(10)]
        base[("random, monthly", lvl)] = pd.concat(rs, axis=1).mean(axis=1)
        rs = [E.simulate(ctx, None, 21, ("pct", pct), start="2015-01-02", end=SEL_END, seed=s, record=False)["daily"] for s in range(10)]
        base[("random, monthly, from 2015", lvl)] = pd.concat(rs, axis=1).mean(axis=1)
    base[("equal weight, whole universe", "all")] = E.simulate(ctx, lambda c, t, ids: np.zeros(len(ids)), 21, ("pct", 1.0), start="2010-01-01", end=SEL_END, record=False)["daily"]
    n5 = pd.Series(ctx.n500, index=ctx.dates)
    base[("NIFTY 500 index (price only)", "all")] = n5.pct_change().loc["2010-01-04":SEL_END]

    # ---------- walk-forward per option and filter level
    results = {}
    for opt in sorted({k[0] for k in runs}):
        for lvl in sorted({k[1] for k in runs if k[0] == opt}):
            sub = {k[2]: r for k, r in runs.items() if k[0] == opt and k[1] == lvl}
            wf, choice = yearly_choice(sub, first=2017 if opt.startswith(("C ", "Current")) else 2013)
            if not len(wf):
                continue
            rkey = ("random, monthly, from 2015", lvl) if opt.startswith(("C ", "Current")) else ("random, monthly", lvl)
            rnd = base.get(rkey, base[("random, monthly", "medium 5%")]).reindex(wf.index).fillna(0)
            ex = wf - rnd
            years = wf.groupby(wf.index.year).apply(lambda x: np.prod(1 + x) - 1)
            ryears = rnd.groupby(rnd.index.year).apply(lambda x: np.prod(1 + x) - 1)
            results[f"{opt} | {lvl}"] = {
                "option": opt, "filter": lvl, "from": str(wf.index[0].date()), "to": str(wf.index[-1].date()),
                "cagr_pct": round(E.cagr(wf) * 100, 1), "sharpe": round(E.sharpe(wf), 2), "max_dd_pct": round(E.max_dd(wf) * 100, 1), "max_dd_inr_on_1L": round(E.max_dd(wf) * 1e5),
                "random_same_rules_cagr_pct": round(E.cagr(rnd) * 100, 1), "excess_cagr_vs_random_pct": round((E.cagr(wf) - E.cagr(rnd)) * 100, 1),
                "excess_sharpe": round(E.sharpe(ex), 2), "years_beating_random": f"{int((years - ryears.reindex(years.index)).gt(0).sum())}/{len(years)}",
                "deflated_sharpe": round(E.deflated_sharpe(wf.values, n_trials, sr_var), 3), "within_risk_limit": bool(E.max_dd(wf) >= -0.25),
                "regimes": E.regime_split(wf, ctx), "pre_2020_cagr": round(E.cagr(wf[wf.index < "2020-01-01"]) * 100, 1) if (wf.index < "2020-01-01").any() else None,
                "post_2020_cagr": round(E.cagr(wf[wf.index >= "2020-01-01"]) * 100, 1), "choices": {int(k): v for k, v in choice.items()},
                "by_year": {int(k): round(float(v) * 100, 1) for k, v in years.items()}, "purged_cv": purged_cv(sub) if len(sub) > 1 else None}
    ranked = sorted(results.values(), key=lambda r: (-r["excess_sharpe"], -int(r["years_beating_random"].split("/")[0])))

    # ---------- detail, robustness and hold-out for the two best options (best filter level each)
    finalists, seen = [], set()
    for r in ranked:
        if r["option"] in seen or r["option"].startswith("Current"):
            continue
        seen.add(r["option"]); finalists.append(r)
        if len(finalists) == 2:
            break
    detail = {}
    for f in finalists:
        last_choice = f["choices"][max(f["choices"])]
        key = (f["option"], f["filter"], last_choice)
        fn, step, pct, ov = grid[key]
        start = "2015-01-02" if f["option"].startswith(("C ", "Current")) else "2010-01-01"
        res = E.simulate(ctx, fn, step, ("pct", pct), start=start, end=SEL_END, exposure_fn=ov, daily_risk=f["option"].startswith("E"))
        d = {"setting": last_choice, "full_report": E.report(res, ctx)}
        rob = {}
        for name, (stp, pc) in {"step -20%": (max(1, round(step * 0.8)), pct), "step +20%": (round(step * 1.2), pct), "pick -20%": (step, pct * 0.8), "pick +20%": (step, pct * 1.2)}.items():
            rr = E.simulate(ctx, fn, stp, ("pct", pc), start=start, end=SEL_END, exposure_fn=ov, record=False, daily_risk=f["option"].startswith("E"))["daily"]
            rob[name] = {"cagr_pct": round(E.cagr(rr) * 100, 1), "sharpe": round(E.sharpe(rr), 2), "max_dd_pct": round(E.max_dd(rr) * 100, 1)}
        for name, top in {"largest 100 stocks only": 100, "largest 250": 250}.items():
            rr = E.simulate(ctx, fn, step, ("pct", pct), start=start, end=SEL_END, exposure_fn=ov, universe_top=top, record=False, daily_risk=f["option"].startswith("E"))["daily"]
            rob[name] = {"cagr_pct": round(E.cagr(rr) * 100, 1), "sharpe": round(E.sharpe(rr), 2), "max_dd_pct": round(E.max_dd(rr) * 100, 1)}
        d["robustness"] = rob
        if not f["option"].startswith(("C ", "Current")):
            ho = E.simulate(ctx, fn, step, ("pct", pct), start="2026-05-08", exposure_fn=ov, daily_risk=f["option"].startswith("E"))
            hr = E.simulate(ctx, None, step, ("pct", pct), start="2026-05-08", seed=1, record=False)["daily"]
            d["holdout"] = {"from": "2026-05-08", "to": str(ho["daily"].index[-1].date()), "return_pct": round((np.prod(1 + ho["daily"]) - 1) * 100, 1),
                            "max_dd_pct": round(E.max_dd(ho["daily"]) * 100, 1), "trades": int(len(ho["trades"])), "random_return_pct": round((np.prod(1 + hr) - 1) * 100, 1),
                            "nifty500_return_pct": round(float(n5.loc["2026-05-08":].iloc[-1] / n5.loc[:"2026-05-07"].iloc[-1] - 1) * 100, 1)}
        else:
            d["holdout"] = "not possible: the ALADIN 1 unseen-year record ends in September 2026"
        detail[f["option"]] = d

    bl = {f"{k[0]} | {k[1]}": {"cagr_pct": round(E.cagr(r) * 100, 1), "sharpe": round(E.sharpe(r), 2), "max_dd_pct": round(E.max_dd(r) * 100, 1), "from": str(r.index[0].date())} for k, r in base.items()}
    out = {"n_trials": n_trials, "sharpe_variance_daily": sr_var, "ranked": ranked, "finalists": detail, "baselines": bl, "record_dates": {str(k): [str(v[0].date()), str(v[1].date())] for k, v in rec.items()},
           "runtime_s": round(time.time() - t0)}
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    lines = ["# Trial log (phase 4)", "", f"Every setting run on the selection period (to {SEL_END}), after costs, ₹1,00,000 start. {n_trials} trials in total;",
             "the deflated Sharpe ratio in the report discounts for this number of tries.", "",
             "| # | Option | Filter | Setting | From | CAGR % | Sharpe | Worst fall % |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {i + 1} | {x['option']} | {x['filter']} | {x['setting']} | {x['from']} | {x['cagr_pct']} | {x['sharpe']} | {x['max_dd_pct']} |" for i, x in enumerate(log)]
    (AUDIT / "TRIALS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for r in ranked:
        print(f"{r['option'][:36]:36s} {r['filter']:16s} CAGR {r['cagr_pct']:6.1f} vsRandom {r['excess_cagr_vs_random_pct']:5.1f} exSharpe {r['excess_sharpe']:5.2f} DSR {r['deflated_sharpe']:.2f} DD {r['max_dd_pct']:6.1f} beat {r['years_beating_random']}")
    print(json.dumps(detail, indent=1, default=str)[:6000])
    print(json.dumps(bl, indent=1))


if __name__ == "__main__":
    main()
