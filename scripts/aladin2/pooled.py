"""
ALADIN 2.0 pooled-first selection (the design chosen at the Phase 2 gate).

Evidence is gathered per STRATEGY across the whole universe (hundreds of stocks, thousands of trades, trades in the same calendar month treated as one cluster), because a
single stock has too few trades to prove anything. A strategy is promoted when, on data before the block only:
  - n >= pooled_min_trades; one-sided month-cluster bootstrap p passes Benjamini-Hochberg across the strategies tested (q = fdr_q); the 2.5% lower bound of the mean is > 0
  - neighbouring parameter settings are also positive (plateau); >= stab_share of calendar years in the window are positive (>= stab_min_blocks years)
  - the last recent_d days are still positive (an edge that faded drops out)
Per-stock TILT: for each stock the strategy's own record is shrunk toward the pooled mean (empirical Bayes, weights from the stock's trade count). A stock whose shrunk
expectancy is <= 0 is VETOED for that strategy (it trades nothing there); a stock with little history simply inherits the pooled estimate.
Lifecycle: the strategy (not the stock) is the record. Candidate -> Probation when promoted; Probation -> Active after probation_days of paper-forward trading in which the
live month-cluster bootstrap p < 0.05 with >= pooled_min_live trades; Active/Probation -> Demoted when it stops passing, or live trades are significantly negative.
Same selection code in production and in the replay below. Replay = nested walk-forward over the same blocks as evaluate.walk_forward.
"""
import json
import math
import time

import numpy as np
import pandas as pd

from . import costs as C
from . import evaluate as E
from . import lifecycle as LC
from .strategies import registry as R

POOL = "*POOL*"
DEFAULTS = {"pooled_min_trades": 300, "pooled_min_live": 150, "pooled_boot": 3000, "veto_min_trades": 8}


def _cfgget(cfg, k):
    return cfg["eval"].get(k, DEFAULTS[k])


def collect(U, sid, win_start, train_end):
    xs, es, xx, sy = [], [], [], []
    for sym, sd in U.items():
        x, e, x_ = E.window(sd, sid, win_start, train_end)
        if len(x):
            xs.append(x); es.append(e); xx.append(x_); sy.append(np.full(len(x), sym, dtype=object))
    if not xs:
        return np.empty(0), np.empty(0, int), np.empty(0, int), np.empty(0, object)
    return np.concatenate(xs), np.concatenate(es), np.concatenate(xx), np.concatenate(sy)


def month_stats(x, e, months, n_boot, rng, bars=10.0):
    """-> mean, one-sided p (centred circular block bootstrap over calendar months), 2.5% lower bound. Block length = twice the average holding time."""
    mid = months[e]; u, inv = np.unique(mid, return_inverse=True)
    s = np.bincount(inv, weights=x); c = np.bincount(inv).astype(float)
    b = E._block_means(s, c, n_boot, E.block_len(bars), rng)
    m = float(x.mean()); p = (np.sum((b - m) >= m) + 1) / (n_boot + 1)
    return m, float(p), float(np.percentile(b, 2.5))


def pooled_select(U, strategies, cal, months, win_start, train_end, cfg, rng, debug=None):
    ev = cfg["eval"]; nmin = _cfgget(cfg, "pooled_min_trades"); sel = {s.id: s for s in strategies}; years = np.asarray(cal.year); data = {}; rows = []
    for sid in sel:
        x, e, xx, sy = collect(U, sid, win_start, train_end)
        if len(x) < nmin:
            continue
        m, p, lb = month_stats(x, e, months, _cfgget(cfg, "pooled_boot"), rng, float(np.mean(xx - e))); data[sid] = (x, e, xx, sy)
        rows.append({"sid": sid, "n": len(x), "m": m, "p": p, "lb": lb})
    if not rows:
        return {}, {"tested": 0, "bh_pass": 0, "promoted": 0}
    D = pd.DataFrame(rows); D["bh"] = E.bh_reject(D["p"].values, ev["fdr_q"]); out = {}
    if debug is not None:
        debug["D"] = D
    mean_of = D.set_index("sid")["m"].to_dict()
    for r in D[D["bh"] & (D["lb"] > 0)].itertuples():
        x, e, xx, sy = data[r.sid]
        nb = [mean_of[t.id] for t in R.neighbours(sel[r.sid], strategies) if t.id in mean_of]
        if nb and float(np.mean(nb)) <= 0:
            continue
        yr = years[e]; ok = [x[yr == y].mean() > 0 for y in np.unique(yr) if (yr == y).sum() >= 50]
        if len(ok) < ev["stab_min_blocks"] or np.mean(ok) < ev["stab_share"]:
            continue
        rm = xx >= train_end - ev["recent_d"]
        if rm.sum() >= 50 and x[rm].mean() <= 0:
            continue
        out[r.sid] = {"n": int(r.n), "mean_bps": round(r.m * 1e4, 1), "p": round(float(r.p), 5), "lb_bps": round(r.lb * 1e4, 1), "years_positive": f"{int(np.sum(ok))}/{len(ok)}"}
    return out, {"tested": int(len(D)), "bh_pass": int(D["bh"].sum()), "promoted": len(out)}


def vetoes(U, sid, pooled_mean, win_start, train_end, cfg):
    """Stocks excluded for this strategy: those whose own record, shrunk toward the pooled mean, is <= 0. Returns the set of symbols."""
    syms, m, n, s2 = [], [], [], []
    for sym, sd in U.items():
        x, _, _ = E.window(sd, sid, win_start, train_end)
        if len(x) >= _cfgget(cfg, "veto_min_trades"):
            syms.append(sym); m.append(x.mean()); n.append(len(x)); s2.append(x.var(ddof=1))
    if len(syms) < 10:
        return set()
    m, n, s2 = map(np.asarray, (m, n, s2)); se2 = s2 / n; tau2 = max(float(np.var(m, ddof=1) - np.mean(se2)), 1e-9)
    w = tau2 / (tau2 + se2); sh = pooled_mean + w * (m - pooled_mean)
    return {sym for sym, v in zip(syms, sh) if v <= 0}


def walk_forward(U, strategies, cal, cfg, seed=0, log=print, max_folds=None, tilt=True):
    ev = cfg["eval"]; rng = np.random.default_rng(seed); months = np.asarray(cal.year * 12 + cal.month)
    selectable = [s for s in strategies if not s.baseline]; FL = E.folds(cal, cfg)[: max_folds or None]
    recs = {}; rows = []; fold_rows = []; events = []; live = {}                           # live: sid -> list of (entry_pos, excess) of paper-traded trades
    lc_cfg = json.loads(json.dumps(cfg)); lc_cfg["lifecycle"]["min_live_trades"] = _cfgget(cfg, "pooled_min_live")
    for k, (a, b) in enumerate(FL):
        train_end = a - ev["purge_d"] - ev["embargo_d"]; win_start = max(train_end - ev["select_lookback_d"], 0); D = cal[a]
        elig, cnt = pooled_select(U, selectable, cal, months, win_start, train_end, cfg, rng)
        for sid in set(recs) | set(elig):
            rec = recs.setdefault(sid, LC.Record(POOL, sid, since=str(D.date())))
            lv = [(e_, x_) for e_, x_ in live.get(sid, []) if e_ < train_end]                  # trades that are fully known by the boundary
            alarm, ltest = None, None
            if lv and rec.state in ("Probation", "Active", "Demoted"):
                x_ = np.array([v for _, v in lv]); e_ = np.array([e for e, _ in lv])
                if len(x_) >= _cfgget(cfg, "pooled_min_live"):
                    m_, p_, lb_ = month_stats(x_, e_, months, 1500, rng, 10.0)
                    ltest = (p_ < 0.05 and m_ > 0, {"live_trades": len(x_), "live_mean_bps": round(m_ * 1e4, 1), "live_p": round(p_, 4)})
                    if m_ < 0 and (1 - p_) < 0.05:
                        alarm = {"live_trades": len(x_), "live_mean_bps": round(m_ * 1e4, 1), "reason": "live trades significantly negative"}
            ds = (D - pd.Timestamp(rec.since)).days if rec.since else 0
            events += LC.step(rec, D, sid in elig, True, alarm, lc_cfg, ds, 0.0, elig.get(sid), live_test=ltest)
        n_tr = 0; n_veto = 0
        for sid, rec in recs.items():
            if rec.state not in LC.TRADING:
                continue
            veto = vetoes(U, sid, elig[sid]["mean_bps"] / 1e4 if sid in elig else 0.0, win_start, train_end, cfg) if (tilt and sid in elig) else set()
            n_veto += len(veto)
            for sym, sd in U.items():
                if sym in veto:
                    continue
                t = sd.trades.get(sid)
                if t is None:
                    continue
                m = (t["e"] >= a) & (t["e"] <= b)
                if not m.any():
                    continue
                for i in np.where(m)[0]:
                    ex = float(t["net"][i] - t["bm"][i])
                    rows.append((sym, sid, k, rec.state, int(t["e"][i]), int(t["x"][i]), float(t["net"][i]), float(t["bars"][i]), ex, sd.sector))
                    live.setdefault(sid, []).append((int(t["x"][i]), ex)); n_tr += 1
        st = pd.Series([r.state for r in recs.values()]).value_counts().to_dict()
        fold_rows.append({"fold": k, "start": str(D.date()), **cnt, "paper_trades": n_tr, "vetoed_stock_slots": n_veto, **{f"n_{s}": int(st.get(s, 0)) for s in LC.STATES}})
        if log and k % 10 == 0:
            log(f"  block {k + 1}/{len(FL)} {D.date()} tested {cnt['tested']} BH {cnt['bh_pass']} promoted {cnt['promoted']} states {st}")
    R_ = pd.DataFrame(rows, columns=["sym", "sid", "fold", "state", "e", "x", "net", "bars", "excess", "sector"])
    R_["entry_date"] = cal[R_["e"].values] if len(R_) else pd.DatetimeIndex([])
    return {"rows": R_, "folds": pd.DataFrame(fold_rows), "events": events, "records": recs}


def main():
    import argparse, gzip
    from . import robustness as RB
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--cache", default="../U_pit.pkl"); ap.add_argument("--universe", default="pit"); ap.add_argument("--top", type=int, default=500)
    ap.add_argument("--out", default="data/aladin2/phase2b_report.json"); ap.add_argument("--events", default="data/aladin2/phase2b_events.jsonl.gz"); a = ap.parse_args()
    t0 = time.time(); U, cal, cfg = RB.load_universe(a.workers, a.cache, a.universe, a.top); strategies = R.all_strategies(); selectable = [s for s in strategies if not s.baseline]
    print(f"universe {len(U)} stocks", flush=True)
    res = walk_forward(U, strategies, cal, cfg, seed=1); res_nt = walk_forward(U, strategies, cal, cfg, seed=1, log=None, tilt=False)
    first = pd.Timestamp(cfg["eval"]["first_test"]); A = res["rows"]; A = A[A["entry_date"] >= first]; Bn = A[A["state"] == "Active"]; At = res_nt["rows"]
    naive = E.baseline_rows(U, cal, cfg, "naive_momentum_12_1"); pool = pd.concat([E.baseline_rows(U, cal, cfg, s.id) for s in selectable], ignore_index=True)
    key = set(zip(A["sym"], A["fold"])); same = lambda df: df[[(s, f) in key for s, f in zip(df["sym"], df["fold"])]]
    out = {"design": "pooled-first selection with per-stock veto (pooled.py)", "universe": {"stocks_built": len(U), "kind": a.universe, "top_by_trailing_traded_value": a.top if a.universe == "pit" else None},
           "policy_pooled_with_veto_Probation_and_Active": E.describe(A, "pooled-first policy, Probation+Active (paper)"),
           "policy_pooled_with_veto_Active_only": E.describe(Bn, "pooled-first policy, Active only"),
           "policy_pooled_no_veto": E.describe(At, "pooled-first policy, no stock veto"),
           "baseline_naive_momentum_all_stocks": E.describe(naive, "naive 12-1 momentum"), "baseline_all_strategies_no_selection": E.describe(pool, "all 34 strategies, no selection"),
           "pooled_by_strategy_oos": None,
           "by_year_policy": {int(y): E.describe(g, str(y)).get("excess_vs_stock_drift") for y, g in A.groupby(A["entry_date"].dt.year)},
           "by_strategy_policy": {sid: E.describe(g, sid).get("excess_vs_stock_drift") for sid, g in A.groupby("sid")},
           "promotions_per_block": res["folds"][["fold", "start", "tested", "bh_pass", "promoted", "paper_trades", "vetoed_stock_slots", "n_Probation", "n_Active", "n_Demoted", "n_Retired"]].iloc[::4].to_dict("records"),
           "transitions": pd.Series([f"{e['from']}->{e['to']}" for e in res["events"]]).value_counts().to_dict(), "runtime_s": round(time.time() - t0)}
    P_ = []
    for sid, g in pool.groupby("sid"):
        mb = E.month_bootstrap(g, "excess"); P_.append({"strategy": sid, "family": R.by_id()[sid].family, "trades": mb["n_trades"], "avg_bars": round(float(g["bars"].mean()), 1), "excess_bps": mb["mean_bps"],
                                                       "excess_per_day_bps": round(float(g["excess"].sum() / g["bars"].sum() * 1e4), 2), "ci95_bps": mb["ci95_bps"], "p": E.month_p(g)})
    rej = E.bh_reject(np.array([r["p"] for r in P_]), cfg["eval"]["fdr_q"])
    for r, k in zip(P_, rej):
        r["bh_pass"] = bool(k)
    out["pooled_by_strategy_oos"] = sorted(P_, key=lambda r: r["p"])
    from pathlib import Path
    st = Path("data/aladin2/state"); st.mkdir(parents=True, exist_ok=True)
    json.dump({"as_of": str(cal[-1].date()), "universe": a.universe, "strategies": {sid: {"state": r.state, "since": r.since, "retired_on": r.retired_on, "last_events": r.history[-3:]} for sid, r in res["records"].items()}},
              open(st / "strategies.json", "w"), indent=1, default=str)
    json.dump(out, open(a.out, "w"), indent=1, default=str)
    with gzip.open(a.events, "wt") as f:
        for e in res["events"]:
            f.write(json.dumps(e, default=str) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("promotions_per_block", "by_year_policy", "by_strategy_policy")}, indent=1, default=str))


if __name__ == "__main__":
    main()
