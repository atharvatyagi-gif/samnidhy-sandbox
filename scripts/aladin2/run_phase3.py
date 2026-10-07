"""
ALADIN 2.0 Phase 3 run: out-of-sample coverage and calibration of the forecast engine (forecast.py).

  python -m scripts.aladin2.run_phase3 --workers 14        -> data/aladin2/phase3_report.json
Universe: every liquid main-board stock, restricted day by day to the top 500 by trailing traded value known the day before (point-in-time; survivors to today only).
Rows: every 5th trading day per stock (targets overlap, so more rows add little). Test years 2012..2026, each forecast by models trained and calibrated on strictly earlier data.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import time

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from . import costs as C
from . import data_lake as L
from . import forecast as FC
from . import run_phase2 as P

STRIDE = 5
FIRST_ROW = "2006-01-01"
PURGE_CAL_D = 100                  # calendar days: longest horizon (60 trading days) plus slack
CAL_WINDOW_D = 730                 # calendar days of the conformal calibration window (about conformal_window_d = 500 trading days)


def _panel(args):
    sym, cal_vals = args
    cal = pd.DatetimeIndex(cal_vals)
    px = L.load_prices(sym)
    if px is None or len(px) < 750:
        return None
    px = L.clean_prices(px); F = L.price_features(px); gk = FC.gk_var(px); T = FC.har_terms(gk)
    nifty = L.load_index(); vix = L.load_macro("india_vix")
    pos = cal.searchsorted(px.index.values); ok = (pos < len(cal)) & (cal[np.minimum(pos, len(cal) - 1)] == px.index.values)
    mr = np.log(nifty / nifty.shift()); mkt = np.log((mr ** 2).rolling(22, min_periods=18).mean().clip(lower=FC.FLOOR)).reindex(px.index).ffill()
    D = pd.DataFrame(index=px.index); D["pos"] = np.where(ok, pos, -1)
    for c in ("lrv1", "lrv5", "lrv22", "lrv66"):
        D[c] = T[c]
    D["mkt_lrv22"] = mkt
    sd20 = F["vol20"].clip(lower=1e-4)
    D["r5z"] = F["r5"] / (sd20 * np.sqrt(5)); D["r20z"] = F["r20"] / (sd20 * np.sqrt(20)); D["r60z"] = F["r60"] / (sd20 * np.sqrt(60))
    for c in ("hi52", "d_sma50", "d_sma200", "rsi14", "vz20", "bb_z"):
        D[c] = F[c]
    D["vix"] = np.log(vix.reindex(px.index).ffill()) if vix is not None else np.nan
    adv = (px["c"] * px["v"]).rolling(250, min_periods=120).mean() / 1e7; D["adv_prev"] = adv.shift(1)
    bad = px["suspect_action"]
    for H in FC.H_LIST:
        D[f"y{H}"] = FC.forward_logvar(gk, H); D[f"r{H}"] = FC.forward_return(px["c"], H, bad)
    c = px["c"]; fwd = pd.concat([np.log(c.shift(-k) / c) for k in range(1, 21)], axis=1)
    D["max20"] = fwd.max(axis=1, skipna=False); D["min20"] = fwd.min(axis=1, skipna=False)
    D["post_break"] = px["post_break"]; D["sym"] = sym
    D = D[(D["pos"] >= 0) & (D["pos"] % STRIDE == 0) & (D.index >= pd.Timestamp(FIRST_ROW)) & ~D["post_break"]].reset_index().rename(columns={"d": "date", "index": "date"})
    # standardised residual pool (EWMA 0.94) for the path simulator: a subsample of this stock's history
    lr = np.log(px["c"] / px["c"].shift()).where(~px["suspect_action"]); ew = (lr ** 2).ewm(alpha=0.06, adjust=False).mean().shift(1); e = (lr / np.sqrt(ew.clip(lower=1e-8))).replace([np.inf, -np.inf], np.nan).dropna().clip(-8, 8)
    return D.astype({c: "float32" for c in D.columns if D[c].dtype == "float64"}), e.values[::7].astype("float32")


def build_panel(workers):
    cfg = C.load_cfg(); nifty = L.load_index(); cal = nifty.index[nifty.index >= pd.Timestamp(cfg["eval"]["data_start"]) - pd.Timedelta(days=400)]
    syms = [r[0] for r in P.universe_pit(cfg)]
    with ProcessPoolExecutor(workers) as ex:
        out = [o for o in ex.map(_panel, [(s, cal.values) for s in syms], chunksize=4) if o is not None]
    D = pd.concat([o[0] for o in out], ignore_index=True); resid = np.concatenate([o[1] for o in out])
    D["rank"] = D.groupby("date")["adv_prev"].rank(ascending=False, method="first"); D = D[D["rank"] <= 500].drop(columns=["rank"])
    return D.reset_index(drop=True), resid, cfg


def run_fold(D, year, H, cfg, seed=0):
    ys = pd.Timestamp(f"{year}-01-01"); ye = pd.Timestamp(f"{year + 1}-01-01"); cal_end = ys - pd.Timedelta(days=PURGE_CAL_D); cal_start = cal_end - pd.Timedelta(days=CAL_WINDOW_D)
    tr = D[D["date"] < cal_start - pd.Timedelta(days=PURGE_CAL_D)]; ca = D[(D["date"] > cal_start) & (D["date"] <= cal_end)]; te = D[(D["date"] >= ys) & (D["date"] < ye)]
    need = [f"y{H}", f"r{H}"] + FEATS_ALL
    tr, ca, te = (x.dropna(subset=["lrv1", "lrv5", "lrv22", "lrv66", "mkt_lrv22"] + [f"r{H}"]) for x in (tr, ca, te))
    if len(tr) < 5000 or len(ca) < 1000 or len(te) < 100:
        return None
    har = FC.HAR().fit(tr.dropna(subset=[f"y{H}"]), tr.dropna(subset=[f"y{H}"])[f"y{H}"].values)
    out = {}
    def prep(d):
        sig = har.sigma(d) * np.sqrt(H); z = (d[f"r{H}"].values / sig).clip(-8, 8)
        X = d[["r5z", "r20z", "r60z", "hi52", "d_sma50", "d_sma200", "rsi14", "vz20", "bb_z", "mkt_lrv22", "vix"]].copy(); X.insert(0, "lv_ratio", har.log_var(d) - d["lrv66"].values)
        return sig, z, X.astype(float)
    (s_tr, z_tr, X_tr), (s_ca, z_ca, X_ca), (s_te, z_te, X_te) = prep(tr), prep(ca), prep(te)
    if len(tr) > 250_000:
        i = np.random.default_rng(seed).choice(len(tr), 250_000, replace=False); X_fit, z_fit = X_tr.iloc[i], z_tr[i]
    else:
        X_fit, z_fit = X_tr, z_tr
    models = FC.fit_quantiles(X_fit, z_fit, seed=seed)
    Qca, Qte = FC.predict_quantiles(models, X_ca), FC.predict_quantiles(models, X_te)
    corr = {b: FC.conformal_adjust(Qca[:, list(BANDS_IDX[b])], z_ca, FC.NOMINAL[b]) for b in FC.BANDS}
    Aca, Ate = FC.adjusted_quantiles(Qca, corr), FC.adjusted_quantiles(Qte, corr)
    p_ca, p_te = FC.p_up_from_quantiles(Aca), FC.p_up_from_quantiles(Ate); y_ca = (ca[f"r{H}"].values > 0).astype(int)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98).fit(p_ca, y_ca); p_cal = iso.predict(p_te)
    base = np.quantile(z_tr, FC.Q_LEVELS)
    res = {"year": year, "H": H, "n_train": len(tr), "n_cal": len(ca), "n_test": len(te), "corr": {k: round(v, 4) for k, v in corr.items()}, "z": z_te, "Q": Qte, "A": Ate, "p_raw": p_te, "p_cal": p_cal, "base_q": base,
           "y": (te[f"r{H}"].values > 0).astype(int), "sigma": s_te, "idx": te.index.values}
    if H in (1, 60):
        res["sigma_daily"] = har.sigma(te)
    return res


BANDS_IDX = FC.BANDS
FEATS_ALL = ["r5z", "r20z", "r60z", "hi52", "d_sma50", "d_sma200", "rsi14", "vz20", "bb_z", "mkt_lrv22"]


def summarise(R_by_h, D):
    out = {}
    for H, rs in R_by_h.items():
        z = np.concatenate([r["z"] for r in rs]); A = np.vstack([r["A"] for r in rs]); Q = np.vstack([r["Q"] for r in rs]); y = np.concatenate([r["y"] for r in rs])
        pr = np.concatenate([r["p_raw"] for r in rs]); pc = np.concatenate([r["p_cal"] for r in rs]); yr = np.concatenate([[r["year"]] * len(r["z"]) for r in rs]); sig = np.concatenate([r["sigma"] for r in rs])
        h = {"rows": int(len(z)), "coverage": {}, "coverage_before_conformal": {}, "coverage_by_year_worst_gap": {}, "mean_width_in_sigma": {}}
        for b, (lo, hi) in FC.BANDS.items():
            inside = (z > A[:, lo]) & (z < A[:, hi]); h["coverage"][b] = round(float(inside.mean()), 4)
            h["coverage_before_conformal"][b] = round(float(((z > Q[:, lo]) & (z < Q[:, hi])).mean()), 4)
            gaps = [abs(float(inside[yr == y_].mean()) - FC.NOMINAL[b]) for y_ in np.unique(yr) if (yr == y_).sum() >= 200]
            h["coverage_by_year_worst_gap"][b] = round(max(gaps), 4) if gaps else None
            h["mean_width_in_sigma"][b] = round(float((A[:, hi] - A[:, lo]).mean()), 3)
            h.setdefault("coverage_normal_har_baseline", {})[b] = round(float((np.abs(z) < {"50": 0.6745, "80": 1.2816, "95": 1.96}[b]).mean()), 4)
        base = np.mean([r["base_q"] for r in rs], axis=0)
        h["pinball_model_vs_unconditional"] = {str(q): [round(FC.pinball(z, A[:, i], q), 5), round(FC.pinball(z, np.full(len(z), base[i]), q), 5)] for i, q in enumerate(FC.Q_LEVELS)}
        e_raw, _ = FC.ece(pr, y); e_cal, tab = FC.ece(pc, y)
        h["p_up"] = {"base_rate": round(float(y.mean()), 4), "ece_before_isotonic": round(e_raw, 4), "ece_after_isotonic": round(e_cal, 4), "auc": round(float(roc_auc_score(y, pc)), 4) if len(np.unique(y)) > 1 else None,
                     "brier": round(float(np.mean((pc - y) ** 2)), 5), "brier_base_rate": round(float(np.mean((y.mean() - y) ** 2)), 5), "reliability": tab,
                     "range_of_p": [round(float(np.percentile(pc, 1)), 3), round(float(np.percentile(pc, 99)), 3)]}
        ter = np.digitize(sig / np.sqrt(H), np.quantile(sig / np.sqrt(H), [1 / 3, 2 / 3]))
        h["coverage_80_by_volatility_third"] = {k: round(float(((z > A[:, 1]) & (z < A[:, 5]))[ter == i].mean()), 4) for i, k in enumerate(["calm", "middle", "turbulent"])}
        h["coverage_80_by_year"] = {int(y_): round(float(((z > A[:, 1]) & (z < A[:, 5]))[yr == y_].mean()), 4) for y_ in np.unique(yr)}
        out[str(H)] = h
    return out


def barrier_check(D, R_by_h, resid, n_rows=4000, n_paths=800, seed=0):
    """Validate the path simulator on 20-day horizons: predicted P(touch +1 sigma_20 / -1 sigma_20 at a close) against realised touches, and the 80% band from paths."""
    rng = np.random.default_rng(seed); rs1 = {r["year"]: r for r in R_by_h[1]}; rs60 = {r["year"]: r for r in R_by_h[60]}; rs20 = {r["year"]: r for r in R_by_h[20]}
    res = FC.standardise(resid[np.isfinite(resid)]); rows = []
    for yr, r20 in rs20.items():
        if yr not in rs1 or yr not in rs60:
            continue
        idx20, idx1, idx60 = r20["idx"], rs1[yr]["idx"], rs60[yr]["idx"]
        s1 = dict(zip(idx1, rs1[yr]["sigma_daily"])); s60 = dict(zip(idx60, rs60[yr]["sigma_daily"]))
        for j, ix in enumerate(idx20):
            if ix in s1 and ix in s60:
                rows.append((ix, s1[ix], s60[ix], r20["sigma"][j], r20["A"][j]))
    pick = rng.choice(len(rows), min(n_rows, len(rows)), replace=False); recs = []
    for i in pick:
        ix, s1_, s60_, sig20, Arow = rows[i]; d = D.loc[ix]; mx, mn, r20 = d["max20"], d["min20"], d["r20"]
        if not np.isfinite(mx) or not np.isfinite(mn) or not np.isfinite(r20):
            continue
        raw = FC.simulate_paths(s1_, s60_, 20, n_paths, res, rng); paths = FC.fit_to_band(raw, Arow[1] * sig20, Arow[5] * sig20)
        recs.append((FC.touch_prob(paths, sig20), float(mx >= sig20), FC.touch_prob(paths, -sig20), float(mn <= -sig20),
                     float((np.quantile(paths[:, -1], 0.1) < r20) & (r20 < np.quantile(paths[:, -1], 0.9))),
                     FC.touch_prob(raw, sig20), FC.touch_prob(raw, -sig20), float((np.quantile(raw[:, -1], 0.1) < r20) & (r20 < np.quantile(raw[:, -1], 0.9)))))
    R_ = np.array(recs); out = {"rows": int(len(R_))}
    for name, pi, yi in (("touch_up_1sigma", 0, 1), ("touch_down_1sigma", 2, 3)):
        e, tab = FC.ece(R_[:, pi], R_[:, yi]); out[name] = {"mean_predicted": round(float(R_[:, pi].mean()), 4), "realised": round(float(R_[:, yi].mean()), 4), "ece": round(e, 4), "reliability": tab}
    out["paths_80pct_band_coverage_20d"] = round(float(R_[:, 4].mean()), 4)
    out["uncalibrated_simulator"] = {"touch_up_mean_predicted": round(float(R_[:, 5].mean()), 4), "touch_down_mean_predicted": round(float(R_[:, 6].mean()), 4), "paths_80pct_band_coverage_20d": round(float(R_[:, 7].mean()), 4),
                                    "ece_up": round(FC.ece(R_[:, 5], R_[:, 1])[0], 4), "ece_down": round(FC.ece(R_[:, 6], R_[:, 3])[0], 4)}
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=14); ap.add_argument("--out", default="data/aladin2/phase3_report.json"); ap.add_argument("--first_year", type=int, default=2012); ap.add_argument("--last_year", type=int, default=2026)
    a = ap.parse_args(); t0 = time.time(); D, resid, cfg = build_panel(a.workers)
    print(f"panel {len(D):,} rows, {D['sym'].nunique()} stocks, {D['date'].min().date()}..{D['date'].max().date()} ({time.time() - t0:.0f}s)", flush=True)
    R_by_h = {H: [] for H in FC.H_LIST}; corr_log = []
    for year in range(a.first_year, a.last_year + 1):
        for H in FC.H_LIST:
            r = run_fold(D, year, H, cfg)
            if r is not None:
                R_by_h[H].append(r); corr_log.append({"year": year, "H": H, **{f"corr_{k}": v for k, v in r["corr"].items()}, "n_train": r["n_train"], "n_cal": r["n_cal"], "n_test": r["n_test"]})
        print(f"  {year} done ({time.time() - t0:.0f}s)", flush=True)
    rep = {"universe": "point-in-time top 500 by trailing traded value (survivors to today only)", "rows": f"every {STRIDE}th trading day", "test_years": [a.first_year, a.last_year], "coverage_tol": cfg["forecast"]["coverage_tol"], "ece_max": cfg["calibration"]["ece_max"]}
    rep["horizons"] = summarise(R_by_h, D); rep["barrier_check_20d"] = barrier_check(D, R_by_h, resid); rep["corrections"] = corr_log[::5]; rep["runtime_s"] = round(time.time() - t0)
    json.dump(rep, open(a.out, "w"), indent=1, default=str); print(json.dumps({"coverage": {h: v["coverage"] for h, v in rep["horizons"].items()}, "ece": {h: v["p_up"]["ece_after_isotonic"] for h, v in rep["horizons"].items()}}, indent=1))


if __name__ == "__main__":
    main()
