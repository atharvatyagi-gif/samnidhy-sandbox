"""
ALADIN technical front + combiner + data/aladin/latest.json (the file the ALADIN tab reads, published as aladin.json).

  python scripts/aladin_model.py --full       walk-forward test 2013..now, final models, today's probabilities   (slow: weekly / by hand)
  python scripts/aladin_model.py --nightly    final models + today's probabilities, re-using the saved walk-forward record  (nightly)
  options: --limit N (use only N training stocks: quick check)   --horizons 5,10,20   --no-regime

Target     the stock's forward close-to-close return over 5 / 10 / 20 trading days is > 0 (raw direction, not excess over NIFTY).
Honesty    Walk-forward: each test year is predicted by models trained only on earlier data, with a purge gap of 10 / 15 / 25
           trading days between the last training day and the first test day. Every accuracy figure is from those unseen years and
           is compared with the BASE RATE (the share of up moves), not with 50%. Probabilities are calibrated (isotonic) on the pooled
           out-of-sample record. Nothing in a row at day t uses data after day t; the HMM is a forward filter fitted on the training
           window only.
Coverage   Every security with >= 250 daily bars gets a probability. Training uses NIFTY 500 plus main-board stocks whose 20-day
           average traded value is at least Rs 5 crore; the others are scored with the same models. SME and ETF are scored but not trained on.
Not done   LSTM (optional in the brief) was not tried. Order-book models, RL execution and Heston calibration have no free data: shown as
           "not measured" with the reason. The sweep weight stays a prior until a sweep validation exists.

Combiner   logit(p) = logit(p_tech) + wF F/100 + wS S/100 + wSweep S_sweep/100  (see combine_py; desk-aladin.js has the identical combine()).
"""

import argparse
import json
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aladin_filings as af_filings  # noqa: E402
import aladin_fund as af  # noqa: E402
import aladin_quant as aq  # noqa: E402
import predict_model as pm  # noqa: E402

TERM = ROOT / "data" / "terminal"
OUT_DIR = ROOT / "data" / "aladin"
CACHE = ROOT / "data" / "aladin_cache"
CFG = ROOT / "data" / "config" / "aladin_config.json"
HORIZONS = [5, 10, 20]
GAPS = {5: 10, 10: 15, 20: 25}
STEP = 5
MIN_TRAIN_YEARS = 4
FIRST_TEST_YEAR = 2013
SEEDS = [7, 21, 42]
MIN_BARS = 250
MIN_VALUE_CR = 5.0
REGIME_MIN_ROWS = 30000
NOT_MEASURED = [
    ["Satellite imagery", "No free source"], ["Card-spend data", "No free source"], ["Job postings", "Terms forbid scraping"], ["ESG scores", "No free source"],
    ["Order book (L2/L3)", "No free NSE history"], ["RL execution", "Optimises execution, not direction"], ["Heston calibration", "No free options history"],
    ["LSTM", "Optional in the brief; not tried in this build"], ["EPS surprise / revisions", "Yahoo has no estimates for NSE names"],
]

EXTRA_NAMES = {
    "pca_z": "residual return vs market factors", "pca_r2": "share explained by market factors", "coint_z": "spread vs cointegrated peer",
    "coint_hl": "peer spread half-life", "coint_p": "peer cointegration p-value", "hmm_p_highvol": "market turbulence probability",
    "jump_lam": "jump frequency", "jump_recent": "jump in last 20 days", "jump_bv": "jump share of variance",
}
NAMES = {**pm.NAMES, "ind": "industry", **EXTRA_NAMES, **{k + "_rk": v + " (rank)" for k, v in pm.NAMES.items()}}


def now_utc():
    return datetime.now(timezone.utc)


def load_cfg():
    base = {"weights": {"wF": 0.20, "wS": 0.12, "wSweep": 0.18}, "primary_horizon": 10}
    try:
        base.update(json.loads(CFG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return base


# ------------------------------------------------------------------ data

def load_prices(sym, min_bars=MIN_BARS):
    """Daily bars, split-adjusted: data/terminal/daily (5 years) spliced onto data/terminal/archive (2007-2021) as predict_model.load does."""
    p = TERM / "daily" / f"{pm.key(sym)}.json"
    if not p.exists():
        return None
    cur = json.loads(p.read_text(encoding="utf-8"))["d"]
    rows = cur
    a = TERM / "archive" / f"{pm.key(sym)}.json"
    if a.exists() and cur:
        old = json.loads(a.read_text(encoding="utf-8"))["d"]
        first = cur[0][0]
        ov = next((r for r in old if r[0] == first), None)
        k = cur[0][4] / ov[4] if ov and ov[4] else 1.0
        rows = [[r[0], r[1] * k, r[2] * k, r[3] * k, r[4] * k, r[5] / k] for r in old if r[0] < first] + cur
    df = pd.DataFrame(rows, columns=["date", "o", "h", "l", "c", "v"])
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pm.START].drop_duplicates("date").set_index("date").sort_index()
    df = df[(df["c"] > 0) & (df["h"] >= df["l"])]
    return df if len(df) >= min_bars else None


def universe(limit=None):
    """-> (all_stocks list, training symbols set). Training: main-board EQ non-ETF, NIFTY 500 or 20-day traded value >= Rs 5 cr."""
    stocks = json.loads((TERM / "universe.json").read_text(encoding="utf-8"))["stocks"]
    train = {s["s"] for s in stocks if s.get("board") == "Main" and s.get("series") == "EQ" and not s.get("etf")
             and (s.get("n500") or (s.get("avgv20") or 0) * (s.get("c") or 0) >= MIN_VALUE_CR * 1e7)}
    if limit:
        train = set(sorted(train, key=lambda x: -next(((s.get("avgv20") or 0) * (s.get("c") or 0) for s in stocks if s["s"] == x), 0))[:limit])
    return stocks, train


def sample_dates(cal, step=STEP, warmup=250):
    """Every `step`-th trading day counting back from the last day (so the last day is always included), after the warm-up year."""
    idx = np.arange(len(cal) - 1, warmup - 1, -step)
    return cal[np.sort(idx)]


def stock_frame(df, nlr, nc, keep_dates, tail=None):
    F, c = pm.features(df, nlr)
    for h in HORIZONS:
        F[f"fwd{h}"] = np.log(c.shift(-h) / c)
    F["rel20"] = F["r20"] - np.log(nc / nc.shift(20)).reindex(F.index)
    F["rel60"] = F["r60"] - np.log(nc / nc.shift(60)).reindex(F.index)
    F = F.join(aq.jump_features(np.log(c).diff()))
    F = F.iloc[250:] if tail is None else F.iloc[-1:]
    return F[F.index.isin(keep_dates)]


def build_dataset(limit=None, log=print):
    t0 = time.time()
    stocks, train = universe(limit)
    ind = {s["s"]: s.get("ind") or "none" for s in stocks}
    nifty = load_prices("^NSEI", 300)
    if nifty is None:
        raise SystemExit("NIFTY 50 history missing (data/terminal/daily/_5eNSEI.json): run scripts/terminal_hist.py first")
    nc = nifty["c"]
    nlr = np.log(nc).diff()
    cal = nc.index
    keep = sample_dates(cal)
    prices, tails, frames = {}, {}, []
    n500 = {x["s"] for x in stocks if x.get("n500")}
    for s in stocks:
        sym = s["s"]
        if sym.startswith("^") or sym.startswith("DUMMY"):
            continue
        in_train = sym in train
        df = load_prices(sym)
        if df is None or (df.index[-1] < cal[-1] - pd.Timedelta(days=10)):          # delisted / suspended: not scored
            continue
        F = stock_frame(df if in_train else df.iloc[-420:], nlr, nc, keep, tail=None if in_train else 1)
        if F.empty:
            continue
        F["sym"], F["ind"], F["tr"] = sym, ind[sym], in_train
        frames.append(F)
        tails[sym] = df["c"].iloc[-300:]
        if in_train and sym in n500:
            prices[sym] = df["c"]
    X = pd.concat(frames)
    X.index.name = "date"
    X = X.reset_index()
    log(f"features: {len(X):,} stock-days, {X['sym'].nunique()} stocks ({(X['tr']).sum():,} training rows) ({time.time() - t0:.0f}s)")
    # market-wide inputs from the training universe
    m = pd.DataFrame(index=cal)
    for n in (5, 20, 60):
        m[f"m_r{n}"] = np.log(nc / nc.shift(n))
    m["m_d200"] = nc / nc.rolling(200).mean() - 1
    m["m_vol20"] = nlr.rolling(20).std()
    T = X[X["tr"]]
    g = T.groupby("date")
    br = pd.DataFrame({"m_br200": g["d_sma200"].apply(lambda s: (s > 0).mean()), "m_br50": g["d_sma50"].apply(lambda s: (s > 0).mean()), "m_disp": g["r20"].std()})
    X = X.merge(m, left_on="date", right_index=True, how="left").merge(br, left_on="date", right_index=True, how="left")
    med = T.groupby(["date", "ind"])["r60"].median().rename("_med60")
    X = X.merge(med, left_on=["date", "ind"], right_index=True, how="left")
    X["sec_rel60"] = X["r60"] - X["_med60"]
    X = X.drop(columns=["_med60"])
    for col in pm.RANKED:
        X[col + "_rk"] = np.nan
        trm = X["tr"]
        X.loc[trm, col + "_rk"] = X[trm].groupby("date")[col].rank(pct=True)
    last = cal[-1]
    ref = X[(X["date"] == last) & X["tr"]]
    for col in pm.RANKED:                                    # non-training stocks (last day only): rank among the training stocks that day
        srt = np.sort(ref[col].dropna().values)
        rows = (~X["tr"]) & X[col].notna()
        if len(srt):
            X.loc[rows, col + "_rk"] = np.searchsorted(srt, X.loc[rows, col].values) / len(srt)
    X["ind"] = X["ind"].astype("category")
    X = X.replace([np.inf, -np.inf], np.nan)
    return X, cal, nc, nlr, prices, tails, ind, train


# ------------------------------------------------------------------ PCA / pairs features

def _refit_job(args):
    """One cointegration refit (runs in a worker process): pairs on the trailing window, then Kalman spreads forward to the next refit."""
    i, j, logpx_values, cols, dates, by_ind, turn, kal_warm = args
    lp = pd.DataFrame(logpx_values, index=dates, columns=cols)
    win = lp.iloc[i - 250:i + 1]
    win = win.loc[:, win.notna().all()]
    pairs = aq.engle_granger_pairs(win, by_ind, 40, 0.05, turn)
    out = []
    for s, pr in pairs.items():
        peer = pr["peer"]
        y, x = lp[s].values, lp[peer].values
        a, b, sp, st = aq.kalman_spread(y[i - kal_warm + 1:i + 1], x[i - kal_warm + 1:i + 1])
        hl = aq.half_life(sp)
        fwd_sp = np.array([])
        beta_last = b[-1]
        if j > i + 1:
            a2, b2, fwd_sp, _ = aq.kalman_spread(y[i + 1:j], x[i + 1:j], init=st)
            beta_last = b2[-1]
        allsp = np.r_[sp, fwd_sp]
        ser = pd.Series(allsp)
        z = ((ser - ser.rolling(60, min_periods=30).mean()) / ser.rolling(60, min_periods=30).std()).values
        zs = z[len(sp) - 1:]                                  # z at day i, i+1, ..., j-1
        for k, zz in enumerate(zs):
            out.append((dates[i + k], s, float(zz) if np.isfinite(zz) else np.nan, hl if hl is not None else np.nan, pr["p"], peer, float(beta_last)))
    return out


def pair_features(prices, ind, turnover, workers=None, refit_every=63, kal_warm=120, log=print):
    """coint_z / coint_hl / coint_p per (date, symbol). Partner and its Engle-Granger p refit every `refit_every` days (and on the last day);
    between refits the Kalman filter keeps updating. Quarterly rather than weekly refits keep the history affordable; the last day uses a fresh refit."""
    t0 = time.time()
    lp = np.log(pd.DataFrame(prices)).sort_index()
    dates = lp.index
    T = len(dates)
    cuts = list(range(250, T - 1, refit_every)) + [T - 1]
    jobs = []
    for n, i in enumerate(cuts):
        j = cuts[n + 1] if n + 1 < len(cuts) else T
        if i == T - 1 and n > 0:
            j = T
        jobs.append((i, j, lp.values, list(lp.columns), dates, ind, turnover, kal_warm))
    rows = []
    if workers and workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(_refit_job, jobs):
                rows += r
    else:
        for jb in jobs:
            rows += _refit_job(jb)
    df = pd.DataFrame(rows, columns=["date", "sym", "coint_z", "coint_hl", "coint_p", "peer", "beta"])
    df = df.sort_values(["date", "sym"]).drop_duplicates(["date", "sym"], keep="last")        # the live refit on the last day overrides the quarterly one
    log(f"pair features: {len(df):,} stock-days, {df['sym'].nunique()} stocks with a cointegrated peer ({time.time() - t0:.0f}s)")
    return df


def pca_frame(prices, log=print):
    t0 = time.time()
    lp = np.log(pd.DataFrame(prices)).sort_index()
    ret = lp.diff()
    resid, ks = aq.pca_residuals(ret)
    z, r2 = aq.pca_features(ret, resid)
    f = pd.concat({"pca_z": z.stack(dropna=False), "pca_r2": r2.stack(dropna=False)}, axis=1)
    f.index.names = ["date", "sym"]
    log(f"PCA residual features: {int(ks.median()) if len(ks) else 0} components (median), refit every 5 days ({time.time() - t0:.0f}s)")
    return f.reset_index(), (int(ks.iloc[-1]) if len(ks) else 0)


def market_obs(nc, nlr):
    r = nlr
    return pd.DataFrame({"r": r, "rv5": r.rolling(5).std()}).dropna()


def hmm_series(obs, cal, cut):
    """Forward-filtered P(high-vol) for every calendar day, parameters fitted on observations strictly before `cut`."""
    train = obs[obs.index < cut]
    h = aq.Gaussian2HMM().fit(train.values)
    p = pd.Series(h.filtered(obs.values), index=obs.index)
    return p.reindex(cal).ffill().fillna(0.0)


def attach_extras(X, pcaf, pairf):
    X = X.merge(pcaf, on=["date", "sym"], how="left")
    X = X.merge(pairf[["date", "sym", "coint_z", "coint_hl", "coint_p"]], on=["date", "sym"], how="left")
    X["ind"] = X["ind"].astype("category")
    return X


# ------------------------------------------------------------------ models

def clf_params():
    return dict(pm.P_CLF)


def fit_clfs(D, y, feats):
    return [lgb.LGBMClassifier(**clf_params(), random_state=s).fit(D[feats], y, categorical_feature=["ind"]) for s in SEEDS]


def predict(clfs, D, feats):
    return np.mean([c.predict_proba(D[feats])[:, 1] for c in clfs], axis=0)


def fit_horizon(train, h, feats, hmm_p, regime=True):
    """Pooled model, plus calm / stress models when each regime has enough rows. -> dict(pooled=[...], calm=[...]|None, stress=[...]|None)"""
    t = train[train[f"fwd{h}"].notna()]
    y = (t[f"fwd{h}"] > 0).astype(int)
    out = {"pooled": fit_clfs(t, y, feats), "calm": None, "stress": None, "n": len(t)}
    if regime:
        hi = t["hmm_p_highvol"].values >= 0.5
        if hi.sum() >= REGIME_MIN_ROWS and (~hi).sum() >= REGIME_MIN_ROWS:
            out["calm"] = fit_clfs(t[~hi], y[~hi], feats)
            out["stress"] = fit_clfs(t[hi], y[hi], feats)
    return out


def score_horizon(models, D, feats):
    p = predict(models["pooled"], D, feats)
    if models["calm"] is None:
        return p, np.full(len(D), np.nan)
    pi = D["hmm_p_highvol"].values
    return p, (1 - pi) * predict(models["calm"], D, feats) + pi * predict(models["stress"], D, feats)


def walk_forward(X, cal, obs, feats, horizons, regime=True, log=print):
    """Predict each test year with models trained on strictly earlier data (purge gap per horizon). -> {h: DataFrame(date, sym, y, p, p_reg)}"""
    T = X[X["tr"]]
    years = sorted(T["date"].dt.year.unique())
    first = max(FIRST_TEST_YEAR, years[0] + MIN_TRAIN_YEARS)
    oos = {h: [] for h in horizons}
    for yr in [y for y in years if y >= first]:
        t0 = time.time()
        test_all = T[T["date"].dt.year == yr]
        if test_all.empty:
            continue
        start_i = int(cal.searchsorted(test_all["date"].min()))
        hp = hmm_series(obs, cal, cal[max(0, start_i - max(GAPS.values()))])     # one HMM per test year, fitted before the longest purge gap: safe for every horizon
        for h in horizons:
            cut = cal[max(0, start_i - GAPS[h])]
            tr = T[T["date"] < cut].assign(hmm_p_highvol=lambda d: hp.reindex(d["date"]).values)
            te = test_all[test_all[f"fwd{h}"].notna()].assign(hmm_p_highvol=lambda d: hp.reindex(d["date"]).values)
            if len(tr) < 20000 or te.empty:
                continue
            models = fit_horizon(tr, h, feats, hp, regime)
            p, pr = score_horizon(models, te, feats)
            oos[h].append(pd.DataFrame({"date": te["date"].values, "sym": te["sym"].values, "y": (te[f"fwd{h}"] > 0).astype(int).values, "p": p, "p_reg": pr}))
            log(f"  {yr} h={h}: trained on {models['n']:,} rows up to {pd.Timestamp(cut).date()}  regime sets {'yes' if models['calm'] is not None else 'no'}  "
                f"AUC {roc_auc_score(oos[h][-1]['y'], p):.3f}")
        log(f"  test year {yr} done ({time.time() - t0:.0f}s)")
    return {h: pd.concat(v) for h, v in oos.items() if v}


# ------------------------------------------------------------------ evaluation

def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def evaluate(O, h):
    """Metrics from the pooled out-of-sample record. Chooses the regime blend only if its Brier score beats the pooled model's."""
    # Regime sets only exist for folds whose training window had enough calm AND stress rows, so p_reg is missing for the early years.
    # The two models are compared on exactly the rows where both exist; if the blend wins there it is used where available (pooled elsewhere).
    have = O["p_reg"].notna()
    has_reg = bool(have.any())
    b_pool = brier(O.loc[have, "p"], O.loc[have, "y"]) if has_reg else brier(O["p"], O["y"])
    b_reg = brier(O.loc[have, "p_reg"], O.loc[have, "y"]) if has_reg else None
    use_reg = bool(has_reg and b_reg < b_pool)
    raw = O["p_reg"].where(have, O["p"]) if use_reg else O["p"]
    y = O["y"].values
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98).fit(raw.values, y)
    p = iso.predict(raw.values)
    O = O.assign(pc=p)
    O = O.assign(rank=O.groupby("date")["pc"].rank(pct=True))
    O["dec"] = np.minimum(9, (O["rank"] * 10).astype(int)) + 1
    base = float(y.mean())
    def daily_ic(d):                                          # rank correlation of the day's probabilities with what happened (0/1)
        return np.corrcoef(d["pc"].rank(), d["y"])[0, 1] if d["y"].nunique() > 1 and d["pc"].nunique() > 1 else np.nan
    ic = O.groupby("date")[["pc", "y"]].apply(daily_ic).dropna()
    years = []
    for yr, d in O.groupby(O["date"].dt.year):
        top, bot = d[d["dec"] == 10], d[d["dec"] == 1]
        years.append({"year": int(yr), "auc": round(float(roc_auc_score(d["y"], d["pc"])), 3) if d["y"].nunique() > 1 else None, "n": int(len(d)),
                      "base": round(float(d["y"].mean()), 3), "acc": round(float(((d["pc"] > 0.5) == d["y"]).mean()), 3),
                      "top_hit": round(float(top["y"].mean()), 3) if len(top) else None, "bot_hit": round(float(bot["y"].mean()), 3) if len(bot) else None})
    cal = O.assign(bin=pd.qcut(O["pc"].rank(method="first"), 10, labels=False)).groupby("bin").agg(pred=("pc", "mean"), actual=("y", "mean"), n=("y", "size"))
    metrics = {"auc": round(float(roc_auc_score(y, O["pc"])), 3), "accuracy": round(float(((O["pc"] > 0.5) == y).mean()), 3), "base_rate": round(base, 3),
               "always_up_accuracy": round(max(base, 1 - base), 3), "brier": round(brier(O["pc"], y), 4), "brier_base": round(brier(np.full(len(y), base), y), 4),
               "n": int(len(O)), "from": str(O["date"].min().date()), "to": str(O["date"].max().date()),
               "top_decile_hit": round(float(O.loc[O["dec"] == 10, "y"].mean()), 3), "bottom_decile_hit": round(float(O.loc[O["dec"] == 1, "y"].mean()), 3),
               "ic_mean": round(float(ic.mean()), 4), "ic_t": round(float(ic.mean() / ic.std() * math.sqrt(len(ic) / h)), 2) if ic.std() else None,
               "regime": {"tested": has_reg, "rows_compared": int(have.sum()), "brier_pooled": round(b_pool, 4), "brier_regime": None if b_reg is None else round(b_reg, 4), "used": use_reg}}
    calib = [{"pred": round(float(r.pred), 3), "actual": round(float(r.actual), 3), "n": int(r.n)} for _, r in cal.iterrows()]
    iso_state = {"x": [round(float(v), 5) for v in iso.X_thresholds_], "y": [round(float(v), 5) for v in iso.y_thresholds_]}
    return {"metrics": metrics, "years": years, "calibration": calib}, iso_state, use_reg


def apply_iso(state, p):
    return np.interp(p, state["x"], state["y"])


# ------------------------------------------------------------------ combiner (twin of combine() in desk-aladin.js)

def logit(p):
    return math.log(p / (1 - p))


def combine_py(p_tech, F=None, S=None, S_sweep=None, w=None, agreement_scores=None):
    """The ALADIN combiner. Missing fronts contribute 0. p is clipped to [0.02, 0.98].
    confidence: Low if |p-0.5| < 0.03, Medium if < 0.07, else High.
    agreement: of the AVAILABLE fronts (F, T, S) how many lean the same way as p (a front leans up above +10, down below -10): 'k/n'."""
    w = w or {"wF": 0.20, "wS": 0.12, "wSweep": 0.18}
    T = max(-100.0, min(100.0, 200 * (p_tech - 0.5)))
    z = logit(min(0.999999, max(1e-6, p_tech))) + w["wF"] * (F or 0) / 100 + w["wS"] * (S or 0) / 100 + w["wSweep"] * (S_sweep or 0) / 100
    p = min(0.98, max(0.02, 1 / (1 + math.exp(-z))))
    fronts = [x for x in (F, T, S) if x is not None]
    lean_up = p > 0.5
    EPS = 1e-9                                                    # 200*(0.55-0.5) is 10.000000000000009 in floating point: "above +10" must mean above 10 by more than rounding noise
    k = sum(1 for x in fronts if (x > 10 + EPS and lean_up) or (x < -10 - EPS and not lean_up))
    d = abs(p - 0.5)
    return {"p": round(p, 4), "q": round(1 - p, 4), "T": round(T, 1), "conf": "Low" if d < 0.03 else "Medium" if d < 0.07 else "High", "agree": f"{k}/{len(fronts)}", "agree_k": k, "agree_n": len(fronts)}


def decile_of(values):
    """1..10 by rank of each value among the others (10 = highest)."""
    s = pd.Series(values)
    rank = s.rank(method="first")                                  # 1 = lowest
    return np.minimum(9, np.floor(10 * (rank - 1) / max(1, len(s) - 1)).astype(int)).add(1).tolist()


# ------------------------------------------------------------------ stacker (used only once >= 120 trading days of predictions have matured)

def fit_stacker(rows, min_days=120, test_frac=0.3):
    """rows: DataFrame with columns date, y, logit_t, F, S, hmm. Walk-forward logistic stacker on [logit_t, F, S, F*hmm, S*hmm]; it replaces the prior
    weights only if its out-of-sample Brier score is better than the prior combiner's on the same held-out days. Returns a dict (mode 'prior'|'fitted')."""
    from sklearn.linear_model import LogisticRegression
    days = sorted(rows["date"].unique())
    if len(days) < min_days:
        return {"mode": "prior", "reason": f"only {len(days)} matured trading days of predictions; {min_days} needed", "fit": None}
    cut_day = days[int(len(days) * (1 - test_frac))]
    tr, te = rows[rows["date"] < cut_day], rows[rows["date"] >= cut_day]
    def X(d):
        return np.column_stack([d["logit_t"], d["F"].fillna(0) / 100, d["S"].fillna(0) / 100, d["F"].fillna(0) / 100 * d["hmm"], d["S"].fillna(0) / 100 * d["hmm"]])
    m = LogisticRegression(C=1.0, max_iter=500).fit(X(tr), tr["y"])
    p_fit = m.predict_proba(X(te))[:, 1]
    p_prior = 1 / (1 + np.exp(-(te["logit_t"] + 0.20 * te["F"].fillna(0) / 100 + 0.12 * te["S"].fillna(0) / 100)))
    bf, bp = brier(p_fit, te["y"]), brier(p_prior, te["y"])
    better = bf < bp
    return {"mode": "fitted" if better else "prior", "reason": None if better else "the fitted stacker did not beat the prior weights out of sample",
            "fit": {"coef": [round(float(c), 4) for c in m.coef_[0]], "intercept": round(float(m.intercept_[0]), 4), "brier_fitted": round(bf, 4), "brier_prior": round(bp, 4), "n_test": int(len(te))}}


# ------------------------------------------------------------------ live scoring and the output file

def drivers(clf, D, feats, k=5):
    contrib = clf.predict(D[feats], pred_contrib=True)
    out = []
    market = np.array([f.startswith("m_") or f == "hmm_p_highvol" for f in feats])        # market-wide inputs are identical for every stock that day: not a reason specific to this stock
    for row in contrib:
        v = np.where(market, 0.0, row[:-1])
        top = np.argsort(-np.abs(v))[:k]
        out.append([[NAMES.get(feats[i], feats[i]), round(float(v[i]), 3)] for i in top])
    return out


def live_scores(X, feats, models, iso, hp_final, nc, ind, extras):
    last = X["date"].max()
    L = X[X["date"] == last].assign(hmm_p_highvol=float(hp_final.iloc[-1]))
    L = L.assign(ind=pd.Categorical(L["ind"].astype(str), categories=X["ind"].cat.categories))
    per = {}
    for h in HORIZONS:
        if h not in models:
            continue
        p, pr = score_horizon(models[h], L, feats)
        raw = np.where(np.isnan(pr), p, pr) if models[h]["calm"] is not None and iso[h].get("use_reg") else p
        per[h] = np.clip(apply_iso(iso[h]["state"], raw), 0.02, 0.98)
    prim = 10 if 10 in models else HORIZONS[0]
    drv = drivers(models[prim]["pooled"][0], L, feats)
    return L, per, drv


def build_stock_entries(L, per, drv, fund, sentiment, cfg, hmm_last, jumps, pairs_live, alt=None):
    alt = alt or {}
    w = cfg["weights"]
    prim = cfg.get("primary_horizon", 10)
    syms = L["sym"].tolist()
    entries, decs = {}, {}
    for h in per:
        decs[h] = dict(zip(syms, decile_of(per[h])))
    sent = (sentiment or {}).get("stocks", {})
    for i, sym in enumerate(syms):
        pt = {str(h): round(float(per[h][i]), 3) for h in per}
        T = round(max(-100.0, min(100.0, 200 * (float(per[prim][i]) - 0.5))), 1)
        fd = fund.get(sym)
        al = alt.get(sym) or {}
        Fsc, cov_f = (None, 0.0)
        if fd:
            Fsc, cov_f = af.f_score(fd.get("v"), fd.get("q"), fd.get("m"), al.get("nlp_z"), (fd.get("dist") or {}).get("band"))
        S = (sent.get(sym) or {}).get("sc")
        row = L.iloc[i]
        t = {"sc": T, "p": pt, "drv": drv[i]}
        for k, src in (("pca_z", "pca_z"),):
            v = row.get(src)
            if v == v and v is not None:
                t[k] = round(float(v), 2)
        if row.get("coint_z") == row.get("coint_z") and sym in pairs_live:
            pl = pairs_live[sym]
            t["coint"] = {"peer": pl["peer"], "z": round(float(row["coint_z"]), 2), "hl": None if pl["hl"] != pl["hl"] else round(float(pl["hl"]), 1), "beta": round(float(pl["beta"]), 2)}
        t["hmm"] = round(float(hmm_last), 3)
        if sym in jumps:
            t["jump"] = jumps[sym]
        e = {"cov": {"f": cov_f if fd else None, "t": 1, "s": 1 if S is not None else None}, "t": t,
             "dec": {str(h): decs[h][sym] for h in per}}
        if fd:
            e["f"] = {"sc": Fsc, "v": fd.get("v"), "q": fd.get("q"), "m": fd.get("m"), "dist": fd.get("dist"), "fin": fd.get("fin")}
            if al.get("nlp"):
                e["f"]["nlp"] = al["nlp"]
            if al.get("alt"):
                e["f"]["alt"] = al["alt"]
            if row.get("tr"):
                e["f"]["raw"] = fd.get("raw")
        comb = {str(h): combine_py(float(per[h][i]), Fsc, S, None, w) for h in per}
        e["comb"] = {k: [v["p"], v["conf"], v["agree"]] for k, v in comb.items()}
        entries[sym] = e
    return entries


def jump_table(prices_by_sym, syms):
    out = {}
    for s in syms:
        r = prices_by_sym.get(s)
        if r is None:
            continue
        jp = aq.jump_params(np.log(r).diff().values)
        if jp:
            jp["bv"] = aq.bipower_jump_share(np.log(r).diff().values)
            out[s] = jp
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--nightly", action="store_true")
    ap.add_argument("--reeval", action="store_true", help="re-do the evaluation and final models from the saved walk-forward record")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--horizons", default="5,10,20")
    ap.add_argument("--no-regime", action="store_true")
    ap.add_argument("--workers", type=int, default=0)
    a = ap.parse_args(argv)
    if not (a.full or a.nightly or a.reeval):
        ap.error("choose --full, --nightly or --reeval")
    horizons = [int(h) for h in a.horizons.split(",")]
    t0 = time.time()
    cfg = load_cfg()
    X, cal, nc, nlr, prices, tails, ind, train = build_dataset(a.limit)
    turn = {s["s"]: (s.get("avgv20") or 0) * (s.get("c") or 0) for s in json.loads((TERM / "universe.json").read_text(encoding="utf-8"))["stocks"]}
    pcaf, pca_k = pca_frame(prices)
    pairf = pair_features(prices, ind, turn, workers=a.workers)
    X = attach_extras(X, pcaf, pairf)
    X["hmm_p_highvol"] = np.nan
    base_feats = [c for c in X.columns if c not in ("date", "sym", "tr") and not c.startswith("fwd")]
    feats = base_feats
    obs = market_obs(nc, nlr)
    state_path = OUT_DIR / "model_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    oos_out, iso, regime_use = {}, {}, {}
    if a.full or a.reeval:
        if a.reeval:
            O = {h: pd.read_pickle(CACHE / f"oos_{h}.pkl") for h in horizons if (CACHE / f"oos_{h}.pkl").exists()}
        else:
            O = walk_forward(X, cal, obs, feats, horizons, not a.no_regime)
            CACHE.mkdir(parents=True, exist_ok=True)
            for h, d in O.items():
                d.to_pickle(CACHE / f"oos_{h}.pkl")                       # kept so the evaluation can be redone without the 25-minute walk-forward (--reeval)
        for h in horizons:
            if h in O:
                ev, st, use = evaluate(O[h], h)
                oos_out[str(h)], iso[h], regime_use[h] = ev, {"state": st, "use_reg": use}, use
                print(f"h={h}: AUC {ev['metrics']['auc']} acc {ev['metrics']['accuracy']} (base {ev['metrics']['base_rate']}) brier {ev['metrics']['brier']} regime used: {use}")
        state = {"saved_utc": now_utc().isoformat(timespec="seconds"), "oos": oos_out, "iso": {str(h): iso[h] for h in iso}}
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    else:
        if not state.get("iso"):
            raise SystemExit("data/aladin/model_state.json is missing: run --full once first")
        oos_out = state["oos"]
        iso = {int(h): v for h, v in state["iso"].items()}
        regime_use = {h: v["use_reg"] for h, v in iso.items()}
    # final models on everything labelled, HMM fitted on all market data
    hp_final = hmm_series(obs, cal, cal[-1] + pd.Timedelta(days=1))
    T = X[X["tr"]].assign(hmm_p_highvol=lambda d: hp_final.reindex(d["date"]).values)
    models = {}
    for h in horizons:
        if h in iso:
            models[h] = fit_horizon(T, h, feats, hp_final, regime_use.get(h, False))
            print(f"final model h={h}: {models[h]['n']:,} rows, regime sets {'yes' if models[h]['calm'] is not None else 'no'} ({time.time() - t0:.0f}s)")
    L, per, drv = live_scores(X, feats, models, iso, hp_final, nc, ind, None)
    fund = json.loads((CACHE / "fund_scores.json").read_text(encoding="utf-8")).get("stocks", {}) if (CACHE / "fund_scores.json").exists() else {}
    sentiment = json.loads((OUT_DIR / "sentiment.json").read_text(encoding="utf-8")) if (OUT_DIR / "sentiment.json").exists() else None
    pairs_live = {r.sym: {"peer": r.peer, "hl": r.coint_hl, "beta": r.beta} for r in pairf[pairf["date"] == cal[-1]].itertuples()}
    jumps = jump_table(tails, L["sym"].tolist())
    alt = af_filings.load_alt()
    entries = build_stock_entries(L, per, drv, fund, sentiment, cfg, float(hp_final.iloc[-1]), jumps, pairs_live, alt)
    doc = {"generated_utc": now_utc().isoformat(timespec="seconds"), "as_of": str(cal[-1].date()), "horizons": horizons, "primary": cfg.get("primary_horizon", 10),
           "weights": {"mode": "prior", **cfg["weights"], "fit": None, "sweep_validated": False},
           "model": {"type": "LightGBM x3 seeds per horizon, isotonic-calibrated; regime blend where it beat the pooled model out of sample", "features": len(feats),
                     "regime_blend": bool(any(regime_use.values())), "lstm": {"used": False, "tested": False, "auc_gain": None}, "pca_k": pca_k, "pairs": int(pairf[pairf["date"] == cal[-1]]["sym"].nunique()),
                     "names": {f: NAMES[f] for f in feats if f in NAMES}, "trained_stocks": len(train), "scored_stocks": len(entries)},
           "oos": oos_out, "live": {str(h): {"scored": int(len(per[h])), "mean_p": round(float(np.mean(per[h])), 3)} for h in per}, "sweep_eval": None,
           "not_measured": NOT_MEASURED, "stocks": entries}
    txt = json.dumps(doc, separators=(",", ":"), allow_nan=False, default=lambda o: None)
    size = len(txt.encode())
    if size > 2_900_000:                                               # keep aladin.json under 3 MB: drop the heavy per-stock detail outside the training universe
        for sym, e in entries.items():
            if sym not in train:
                e["t"].pop("drv", None)
                (e.get("f") or {}).pop("raw", None)
        txt = json.dumps(doc, separators=(",", ":"), allow_nan=False, default=lambda o: None)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "latest.json").write_text(txt, encoding="utf-8")
    hist_dir = OUT_DIR / "history"
    hist_dir.mkdir(exist_ok=True)
    snap = {s: [e.get("f", {}).get("sc"), (sentiment or {}).get("stocks", {}).get(s, {}).get("sc"), e["t"]["sc"], e["t"]["p"].get("10"), e["t"]["p"].get("5"), e["t"]["p"].get("20")] for s, e in entries.items()}
    (hist_dir / f"{cal[-1].date()}.json").write_text(json.dumps({"hmm": round(float(hp_final.iloc[-1]), 3), "s": snap}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote data/aladin/latest.json ({len(txt) / 1e6:.2f} MB), {len(entries)} stocks, as of {cal[-1].date()} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
