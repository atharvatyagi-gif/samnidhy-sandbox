"""
ALADIN 2.0 evaluation machine (section 6 of the brief): nested walk-forward, FDR control, empirical-Bayes shrinkage, stability tests, the policy replay.

THE SAME CODE RUNS IN PRODUCTION AND IN RESEARCH: `select()` is what chooses the strategies for the next block; `walk_forward()` simply calls it block after block on
history, trades the chosen set through the unseen block, and records what happened. The concatenated unseen blocks are the honest performance of ALADIN as a POLICY
(selection included), not of any one strategy.

Per block k (test_d trading days):
  train window   trades that ENTERED within the last select_lookback_d days before the block and EXITED before block start - purge_d - embargo_d
  statistic      excess = net trade return - bars held x the stock's mean daily return in the window  (what the trade earned beyond simply owning the stock for those days)
  eligibility    n >= min_trades_oos; one-sided bootstrap p-value of mean excess > 0 passes Benjamini-Hochberg at fdr_q over ALL (stock x strategy) pairs of the block;
                 bootstrap lower bound > 0; empirical-Bayes shrunk expectancy > 0 (sector prior, else universe); beats the naive 12-1 momentum rule on the same stock;
                 parameter plateau (neighbouring settings not negative); >= stab_share of yearly blocks positive.
  lifecycle      lifecycle.step() moves each record; the next block trades every Probation/Active strategy (paper); live CUSUM can cut a strategy inside the block.
Bootstrap: stationary block bootstrap of the trade sequence, centred for the p-value. It is run only where a quick t-test p is below boot_prelim_p; all other pairs keep
the (larger) t-test p, which cannot pass BH anyway; this changes speed, not the decisions.
"""
from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd

from . import backtest as B
from . import costs as C
from . import lifecycle as LC
from .strategies import base as SB, registry as R

NAIVE = "naive_momentum_12_1"


# ------------------------------------------------------------------ statistics

def stationary_bootstrap(x, n_boot, mean_block, rng):
    """Resampled means of x with stationary block bootstrap (Politis-Romano). Returns an array of n_boot means."""
    x = np.asarray(x, float); n = len(x)
    if n < 2:
        return np.full(n_boot, x.mean() if n else np.nan)
    start = rng.integers(0, n, size=(n_boot, 1)); newb = rng.random((n_boot, n - 1)) < 1.0 / mean_block
    jump = rng.integers(0, n, size=(n_boot, n - 1))
    idx = np.empty((n_boot, n), dtype=np.int64); idx[:, 0:1] = start
    for j in range(1, n):
        idx[:, j] = np.where(newb[:, j - 1], jump[:, j - 1], (idx[:, j - 1] + 1) % n)
    return x[idx].mean(axis=1)


def boot_test(x, n_boot, mean_block, rng):
    """-> (one-sided p for mean > 0, 2.5% lower bound of the mean). p from the centred bootstrap, with the +1 correction."""
    m = float(np.mean(x)); b = stationary_bootstrap(x, n_boot, mean_block, rng)
    p = (np.sum((b - m) >= m) + 1) / (n_boot + 1)
    return float(p), float(np.percentile(b, 2.5))


def t_pvalue(m, s, n):
    """One-sided p for mean > 0 from a t statistic (normal tail; n >= 30 is required elsewhere)."""
    if n < 2 or not s or s <= 0:
        return 1.0
    return 0.5 * math.erfc((m / (s / math.sqrt(n))) / math.sqrt(2))


def bh_reject(p, q):
    """Benjamini-Hochberg: boolean mask of rejected hypotheses at false-discovery rate q."""
    p = np.asarray(p, float); m = len(p)
    if m == 0:
        return np.zeros(0, bool)
    o = np.argsort(p); thr = q * (np.arange(1, m + 1) / m); ok = p[o] <= thr
    k = np.max(np.where(ok)[0]) + 1 if ok.any() else 0
    out = np.zeros(m, bool); out[o[:k]] = True
    return out


def eb_shrink(m, n, s2):
    """Empirical-Bayes shrinkage of per-unit means toward their weighted mean. m, n, s2 arrays (mean, count, per-trade variance).
    -> (shrunk means, weights on the unit's own mean, prior mean, tau2). tau2 is the cross-unit variance in excess of sampling noise (method of moments), floored."""
    m, n, s2 = (np.asarray(a, float) for a in (m, n, s2)); se2 = s2 / np.maximum(n, 1)
    w0 = 1.0 / (se2 + 1e-12); mu0 = float(np.sum(w0 * m) / np.sum(w0)) if len(m) else 0.0
    tau2 = max(float(np.var(m, ddof=1) - np.mean(se2)), 1e-9) if len(m) > 2 else 1e-9
    w = tau2 / (tau2 + se2)
    return mu0 + w * (m - mu0), w, mu0, tau2


# ------------------------------------------------------------------ per-stock data

@dataclass
class StockData:
    sym: str
    sector: str
    dr: np.ndarray                       # daily simple returns aligned to the master calendar (NaN where the stock has no bar)
    trades: dict = field(default_factory=dict)   # sid -> dict(e, x, net, bars) integer calendar positions and floats, sorted by entry


def build_stock(sym, sector, px, F, strategies, cal, decile, cfg, nifty=None, deliv=None, min_entry=None):
    """Backtest every strategy for one stock (long-only delivery), keep compact arrays aligned to the master calendar."""
    ctx = SB.make_ctx(px, F, nifty, deliv)
    P = px.join(F.drop(columns=[c for c in F.columns if c in px.columns]))
    pos = cal.searchsorted(px.index.values)
    dr = np.full(len(cal), np.nan); r = (px["c"] / px["c"].shift() - 1).where(~px["suspect_action"]).values
    ok = (pos < len(cal)) & (cal[np.minimum(pos, len(cal) - 1)] == px.index.values)
    dr[pos[ok]] = r[ok]
    sd = StockData(sym, sector, dr)
    for s in strategies:
        sig = s.signal(ctx); rule = dict(s.rule)
        if rule["type"] == "atr_trail":
            rule["atr"] = F["atr14"]
        T = B.run(P, sig, rule, "delivery", decile, cfg)["trades"]
        if T.empty:
            continue
        if min_entry is not None:
            T = T[T["entry_date"] >= min_entry]
        if T.empty:
            continue
        e = cal.searchsorted(T["entry_date"].values); x = cal.searchsorted(T["exit_date"].values)
        sd.trades[s.id] = {"e": e.astype(np.int64), "x": x.astype(np.int64), "net": T["net"].values.astype(float), "bars": T["bars"].values.astype(float)}
    return sd


def _mu(dr, a, b):
    v = dr[max(a, 0):b]; v = v[np.isfinite(v)]
    return float(v.mean()) if len(v) > 20 else 0.0


def window(sd, sid, win_start, train_end):
    """Excess returns of the pair's trades inside [win_start, train_end] (entered after win_start, exited by train_end). -> (excess array, entry positions, exit positions)."""
    t = sd.trades.get(sid)
    if t is None:
        return np.empty(0), np.empty(0, int), np.empty(0, int)
    m = (t["e"] >= win_start) & (t["x"] <= train_end)
    if not m.any():
        return np.empty(0), np.empty(0, int), np.empty(0, int)
    mu = _mu(sd.dr, win_start, train_end + 1)
    return t["net"][m] - t["bars"][m] * mu, t["e"][m], t["x"][m]


# ------------------------------------------------------------------ selection (the production step)

def select(U, strategies, cal, win_start, train_end, cfg, rng, years=None, debug=None):
    """Evaluate every (stock, selectable strategy) on the window and return a dict pair -> evidence for pairs that are ELIGIBLE, plus counters.
    U: {sym: StockData}. strategies: selectable ones only (baselines excluded). `years`: calendar-year number per calendar position (for stability blocks)."""
    ev = cfg["eval"]; nmin = ev["min_trades_oos"]; sel = {s.id: s for s in strategies}
    rows = []
    for sym, sd in U.items():
        for sid in sel:
            x, e, xx = window(sd, sid, win_start, train_end)
            n = len(x)
            if n < nmin:
                continue
            m, s = float(x.mean()), float(x.std(ddof=1))
            rows.append({"sym": sym, "sid": sid, "n": n, "m": m, "s": s, "p": t_pvalue(m, s, n), "lb": np.nan, "sector": sd.sector})
    if not rows:
        return {}, {"pairs": 0, "fdr_pass": 0, "eligible": 0}
    D = pd.DataFrame(rows)
    for i in np.where(D["p"].values < ev["boot_prelim_p"])[0]:
        r = D.iloc[i]; x, _, _ = window(U[r["sym"]], r["sid"], win_start, train_end)
        p, lb = boot_test(x, min(ev["n_boot"], 1000), ev["boot_block"], rng)
        D.iat[i, D.columns.get_loc("p")] = max(p, 1.0 / (ev["n_boot"] + 1)) if D.iat[i, D.columns.get_loc("m")] > 0 else 1.0
        D.iat[i, D.columns.get_loc("lb")] = lb
    D["fdr"] = bh_reject(D["p"].values, ev["fdr_q"])
    # empirical-Bayes shrinkage per strategy: sector prior when the sector has >= 8 stocks with enough trades, else the whole universe
    D["shrunk"] = np.nan; D["w"] = np.nan
    for sid, g in D.groupby("sid"):
        sh, w, _, _ = eb_shrink(g["m"].values, g["n"].values, g["s"].values ** 2)
        D.loc[g.index, "shrunk"] = sh; D.loc[g.index, "w"] = w
        for sec, gs in g.groupby("sector"):
            if len(gs) >= 8:
                sh2, w2, _, _ = eb_shrink(gs["m"].values, gs["n"].values, gs["s"].values ** 2)
                D.loc[gs.index, "shrunk"] = sh2; D.loc[gs.index, "w"] = w2
    if debug is not None:
        debug["D"] = D
    out = {}; naive = {sym: window(sd, NAIVE, win_start, train_end)[0] for sym, sd in U.items()}
    for r in D[D["fdr"] & (D["lb"] > 0) & (D["shrunk"] > 0)].itertuples():
        sd = U[r.sym]; x, e, xx = window(sd, r.sid, win_start, train_end)
        nv = naive[r.sym]
        if len(nv) >= 10 and r.m <= float(nv.mean()):
            continue                                                                    # does not beat the naive momentum rule on this stock
        nb = [t for t in R.neighbours(sel[r.sid], strategies)]
        nm = [window(sd, t.id, win_start, train_end)[0] for t in nb]; nm = [float(a.mean()) for a in nm if len(a) >= ev["plateau_min_trades"]]
        if nm and float(np.mean(nm)) <= 0:
            continue                                                                    # isolated spike: neighbouring settings do not agree
        rec_m = xx >= train_end - ev["recent_d"]
        if rec_m.sum() >= ev["recent_min_trades"] and x[rec_m].mean() <= 0:
            continue                                                                    # the edge has faded: the recent window no longer agrees with the long one
        yr = years[e]; ok = []
        for y in np.unique(yr):
            a = x[yr == y]
            if len(a) >= 3:
                ok.append(a.mean() > 0)
        if len(ok) < ev["stab_min_blocks"] or np.mean(ok) < ev["stab_share"]:
            continue
        out[(r.sym, r.sid)] = {"n": int(r.n), "mean_bps": round(r.m * 1e4, 1), "shrunk_bps": round(r.shrunk * 1e4, 1), "w_own": round(float(r.w), 3), "p": round(float(r.p), 5),
                               "lb_bps": round(r.lb * 1e4, 1), "sd": float(r.s), "score": float(r.shrunk / r.s * math.sqrt(r.n)), "yr_pos": f"{int(np.sum(ok))}/{len(ok)}"}
    return out, {"pairs": int(len(D)), "fdr_pass": int(D["fdr"].sum()), "eligible": len(out)}


# ------------------------------------------------------------------ nested walk-forward policy replay

def folds(cal, cfg):
    ev = cfg["eval"]; first = int(cal.searchsorted(pd.Timestamp(ev["first_test"]))); out = []; i = first
    while i + 1 < len(cal):
        out.append((i, min(i + ev["test_d"], len(cal)) - 1)); i += ev["test_d"]
    return out


def walk_forward(U, strategies, cal, cfg, seed=0, log=print, max_folds=None, retire_zero_after=None):
    """Replay. Returns dict(rows=DataFrame of traded paper trades, folds=DataFrame, events=list, records=dict)."""
    ev = cfg["eval"]; lc = cfg["lifecycle"]; rng = np.random.default_rng(seed); years = np.asarray(cal.year)
    selectable = [s for s in strategies if not s.baseline]
    records = {}; pending = {}; alarms = {}; rows = []; fold_rows = []; events = []; elig_by_fold = []
    sector_of = {sym: sd.sector for sym, sd in U.items()}
    FL = folds(cal, cfg)
    if max_folds:
        FL = FL[:max_folds]
    for k, (a, b) in enumerate(FL):
        train_end = a - ev["purge_d"] - ev["embargo_d"]; win_start = max(train_end - ev["select_lookback_d"], 0)
        D = cal[a]; elig, cnt = select(U, selectable, cal, win_start, train_end, cfg, rng, years); elig_by_fold.append(list(elig))
        # --- lifecycle at the block boundary
        for pair, rec in records.items():
            keep = []
            for xi, exv in pending.get(pair, []):
                if xi < a:
                    rec.live_returns.append(exv)
                else:
                    keep.append((xi, exv))
            pending[pair] = keep; rec.live_n = len(rec.live_returns)
        for pair in set(records) | set(elig):
            sym, sid = pair
            rec = records.setdefault(pair, LC.Record(sym, sid, since=str(D.date())))
            fresh = True
            if rec.state == "Retired":
                post = window(U[sym], sid, int(cal.searchsorted(pd.Timestamp(rec.retired_on))), train_end)[0]
                fresh = len(post) >= ev["min_trades_oos"] and post.mean() > 0
            ds = (D - pd.Timestamp(rec.since)).days if rec.since else 0
            for e_ in LC.step(rec, D, pair in elig, fresh, alarms.pop(pair, None), cfg, ds, elig.get(pair, {}).get("score", 0.0), elig.get(pair)):
                events.append(e_)
        by_sym = {}
        for (sym, sid), r in records.items():
            by_sym.setdefault(sym, []).append(r)
        for sym, rs in by_sym.items():
            if sum(r.state == "Active" for r in rs) > lc["max_active_per_stock"]:
                events += LC.enforce_cap(rs, {r.sid: elig.get((sym, r.sid), {}).get("score", 0.0) for r in rs}, D, cfg)
        # --- trade the block
        n_tr = 0; n_act = 0
        for pair, rec in records.items():
            if rec.state not in LC.TRADING:
                continue
            sym, sid = pair; sd = U[sym]; t = sd.trades.get(sid)
            if t is None:
                continue
            m = (t["e"] >= a) & (t["e"] <= b)
            if not m.any():
                continue
            ev_ = elig.get(pair) or {}
            ex = np.where(m)[0]; mu_t = _mu(sd.dr, a, b + 1)
            order = ex[np.argsort(t["x"][ex])]; cut_after = None; kept = []
            tr_mean = ev_.get("shrunk_bps", 0.0) / 1e4; tr_sd = ev_.get("sd") or float(np.std(t["net"][:200])) or 0.02
            S = 0.0
            for i in order:
                if cut_after is not None and t["e"][i] > cut_after:
                    continue
                excess = t["net"][i] - t["bars"][i] * mu_t
                kept.append(i)
                S = max(0.0, S + (tr_mean - excess) / tr_sd - lc["cusum_k"])
                if S > lc["retire_cusum_h"] and cut_after is None:
                    cut_after = t["x"][i]; alarms[pair] = {"cusum": round(S, 2), "h": lc["retire_cusum_h"], "at": str(cal[min(t["x"][i], len(cal) - 1)].date())}
            for i in kept:
                excess = t["net"][i] - t["bars"][i] * mu_t
                rows.append((sym, sid, k, rec.state, int(t["e"][i]), int(t["x"][i]), float(t["net"][i]), float(t["bars"][i]), float(excess), sd.sector))
                pending.setdefault(pair, []).append((int(t["x"][i]), float(excess)))
                n_tr += 1; n_act += rec.state == "Active"
        st = pd.Series([r.state for r in records.values()]).value_counts().to_dict()
        fold_rows.append({"fold": k, "start": str(D.date()), **cnt, "paper_trades": n_tr, "active_trades": n_act, **{f"n_{s}": int(st.get(s, 0)) for s in LC.STATES}})
        if log and k % 10 == 0:
            log(f"  fold {k + 1}/{len(FL)} {D.date()} pairs {cnt['pairs']:,} FDR {cnt['fdr_pass']} eligible {cnt['eligible']} states {st}")
    R_ = pd.DataFrame(rows, columns=["sym", "sid", "fold", "state", "e", "x", "net", "bars", "excess", "sector"])
    R_["entry_date"] = cal[R_["e"].values] if len(R_) else pd.DatetimeIndex([])
    return {"rows": R_, "folds": pd.DataFrame(fold_rows), "events": events, "records": records, "eligible_by_fold": elig_by_fold}


# ------------------------------------------------------------------ baselines on the same blocks and aggregation

def baseline_rows(U, cal, cfg, sid, which="all"):
    """Trades of one strategy over every OOS block for every stock in U, excess vs the ex-post block drift (the benchmark), for comparison with the policy."""
    FL = folds(cal, cfg); out = []
    starts = np.array([a for a, _ in FL]); ends = np.array([b for _, b in FL])
    for sym, sd in U.items():
        t = sd.trades.get(sid)
        if t is None:
            continue
        k = np.searchsorted(starts, t["e"], side="right") - 1
        ok = (k >= 0) & (t["e"] <= ends[np.clip(k, 0, None)])
        for i in np.where(ok)[0]:
            a, b = FL[k[i]]; mu = _mu(sd.dr, a, b + 1)
            out.append((sym, sid, int(k[i]), "baseline", int(t["e"][i]), int(t["x"][i]), float(t["net"][i]), float(t["bars"][i]), float(t["net"][i] - t["bars"][i] * mu), sd.sector))
    R_ = pd.DataFrame(out, columns=["sym", "sid", "fold", "state", "e", "x", "net", "bars", "excess", "sector"])
    R_["entry_date"] = cal[R_["e"].values] if len(R_) else pd.DatetimeIndex([])
    return R_


def month_bootstrap(rows, col, n_boot=2000, seed=0):
    """Mean of `col` per trade with a 95% interval from resampling CALENDAR MONTHS (trades in the same month share the market, so they are not independent)."""
    if len(rows) == 0:
        return None
    g = rows.groupby(rows["entry_date"].dt.to_period("M"))[col].agg(["sum", "count"]); rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n_boot, len(g))); s = g["sum"].values[idx].sum(1); c = g["count"].values[idx].sum(1); b = s / c
    return {"n_trades": int(len(rows)), "n_months": int(len(g)), "mean_bps": round(float(rows[col].mean() * 1e4), 2), "ci95_bps": [round(float(np.percentile(b, 2.5) * 1e4), 2), round(float(np.percentile(b, 97.5) * 1e4), 2)]}


def month_p(rows, col="excess", n_boot=4000, seed=0):
    """One-sided p-value that the mean of `col` is > 0, resampling calendar months (centred bootstrap). Used for POOLED (strategy-level, not stock-level) evidence."""
    g = rows.groupby(rows["entry_date"].dt.to_period("M"))[col].agg(["sum", "count"]); rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n_boot, len(g))); b = g["sum"].values[idx].sum(1) / g["count"].values[idx].sum(1)
    m = rows[col].mean(); return float((np.sum((b - m) >= m) + 1) / (n_boot + 1))


def describe(rows, label):
    if len(rows) == 0:
        return {"label": label, "n_trades": 0}
    d = {"label": label, "excess_vs_stock_drift": month_bootstrap(rows, "excess"), "net_per_trade": month_bootstrap(rows, "net"),
         "win_rate": round(float((rows["net"] > 0).mean()), 4), "avg_bars": round(float(rows["bars"].mean()), 1), "net_per_day_in_market_bps": round(float(rows["net"].sum() / rows["bars"].sum() * 1e4), 2),
         "stocks": int(rows["sym"].nunique())}
    x = rows["net"].values
    if len(x) > 10 and x.std() > 0:
        d["psr_net_per_trade"] = round(LC.psr_of(x), 3)
    return d
