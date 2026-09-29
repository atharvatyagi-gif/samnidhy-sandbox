"""
B-LAB outlook model: probability that each NIFTY 500 stock beats the NIFTY 50 over the next 20 trading days.

Data     Daily candles, split-adjusted: data/terminal/daily (last 5 years) + data/terminal/archive (older years,
         from the repository's "history" branch). NIFTY 50 from the same files. Nothing else, nothing estimated.
Inputs   ~60 per stock per day, all computed from information available at that day's close:
         returns 1d..1y, 12-1 momentum, distance from 20/50/200-day averages and their slopes, RSI 2/14,
         stochastic, CCI-style z, ADX / directional movement, MACD, Bollinger %B and width, ATR%, volatility
         20/60 and their ratio, 52-week high/low distance, 60-day drawdown, volume surprise and trend, turnover,
         skew, up-day share, gaps, beta / correlation / idiosyncratic volatility vs NIFTY, returns relative to
         NIFTY and to the stock's sector; market-wide breadth (share above 50/200-day averages), NIFTY trend,
         momentum and volatility, cross-sectional dispersion; and each stock's rank among all stocks that day.
Target   1 if the stock's 20-trading-day return beats NIFTY 50's over the same days, else 0.
Model    Ensemble of gradient-boosted trees (LightGBM): 3 classifiers with different seeds + 1 regressor on the
         excess return. Their scores are rank-averaged each day.
Honesty  Walk-forward: for every test year the models are trained only on earlier data, with a 25-trading-day
         gap so no answer can leak in. Every accuracy number shown is from those unseen years. Probabilities are
         calibrated (isotonic) on that out-of-sample record; "expected excess return" is what that score decile
         actually did out of sample. Every day's predictions are saved and scored after 20 trading days.

  python scripts/predict_model.py      -> data/predict/latest.json  (+ data/predict/history/<date>.json)
"""

import json
import sys
import time
import warnings
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
TERM = ROOT / "data" / "terminal"
OUT = ROOT / "data" / "predict"
H = 20                 # horizon, trading days
GAP = 25               # purge between training labels and the test period
START = "2008-01-01"   # oldest data used
STEP = 5               # train on every 5th day (labels overlap 20 days, so neighbours add little new information)
MIN_TRAIN_YEARS = 4
SEEDS = [7, 21, 42]

NAMES = {  # readable names for the "drivers" shown in the terminal
    "r1": "1-day return", "r5": "1-week return", "r10": "2-week return", "r20": "1-month return", "r60": "3-month return", "r120": "6-month return",
    "r250": "1-year return", "mom12_1": "12-1 momentum", "d_sma20": "distance from 20-day avg", "d_sma50": "distance from 50-day avg",
    "d_sma200": "distance from 200-day avg", "sma50_slope": "50-day avg slope", "sma200_slope": "200-day avg slope", "rsi2": "RSI(2)", "rsi14": "RSI(14)",
    "stoch14": "stochastic %K", "cci_z": "CCI-style z", "adx": "ADX trend strength", "di_diff": "+DI minus -DI", "macd_h": "MACD histogram",
    "bb_pct": "Bollinger %B", "bb_w": "Bollinger width", "atr_pct": "ATR %", "vol20": "1-month volatility", "vol60": "3-month volatility",
    "vol_ratio": "volatility trend", "hi52": "distance from 52-week high", "lo52": "distance from 52-week low", "dd60": "3-month drawdown",
    "vz20": "volume vs 20-day avg", "vtrend": "volume trend", "turn": "traded value", "skew60": "return skew", "up20": "share of up days",
    "gap20": "average gap", "range20": "average daily range", "beta": "beta to NIFTY", "corr60": "correlation with NIFTY", "idio60": "stock-specific volatility",
    "rel20": "1-month return vs NIFTY", "rel60": "3-month return vs NIFTY", "sec_rel60": "3-month return vs its sector",
    "m_r5": "NIFTY 1-week return", "m_r20": "NIFTY 1-month return", "m_r60": "NIFTY 3-month return", "m_d200": "NIFTY vs its 200-day avg",
    "m_vol20": "NIFTY volatility", "m_br200": "market breadth (200-day)", "m_br50": "market breadth (50-day)", "m_disp": "market dispersion",
}
RANKED = ["r5", "r20", "r60", "r120", "mom12_1", "vol20", "hi52", "turn", "vz20", "rsi14", "d_sma200", "beta", "idio60", "rel20", "rel60", "atr_pct", "dd60"]


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def load(sym):
    p = TERM / "daily" / f"{key(sym)}.json"
    if not p.exists():
        return None
    cur = json.loads(p.read_text(encoding="utf-8"))["d"]
    a = TERM / "archive" / f"{key(sym)}.json"
    rows = cur
    if a.exists() and cur:
        old = json.loads(a.read_text(encoding="utf-8"))["d"]
        first = cur[0][0]
        ov = next((r for r in old if r[0] == first), None)
        k = cur[0][4] / ov[4] if ov and ov[4] else 1.0          # rescale if a split happened since the archive was made
        rows = [[r[0], r[1] * k, r[2] * k, r[3] * k, r[4] * k, r[5] / k] for r in old if r[0] < first] + cur
    df = pd.DataFrame(rows, columns=["date", "o", "h", "l", "c", "v"])
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= START].drop_duplicates("date").set_index("date").sort_index()
    return df if len(df) > 300 else None


def wilder(x, n):
    return x.ewm(alpha=1 / n, adjust=False).mean()


def features(df, nlr):
    c, h, l, o = df["c"], df["h"], df["l"], df["o"]
    v = df["v"].replace(0, np.nan)
    lr = np.log(c).diff()
    F = pd.DataFrame(index=df.index)
    for n in [1, 5, 10, 20, 60, 120, 250]:
        F[f"r{n}"] = np.log(c / c.shift(n))
    F["mom12_1"] = F["r250"] - F["r20"]
    for n in [20, 50, 200]:
        F[f"d_sma{n}"] = c / c.rolling(n).mean() - 1
    F["sma50_slope"] = c.rolling(50).mean().pct_change(10)
    F["sma200_slope"] = c.rolling(200).mean().pct_change(20)
    d = c.diff()
    for n in [2, 14]:
        up, dn = wilder(d.clip(lower=0), n), wilder((-d).clip(lower=0), n)
        F[f"rsi{n}"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    ll, hh = l.rolling(14).min(), h.rolling(14).max()
    F["stoch14"] = (c - ll) / (hh - ll).replace(0, np.nan)
    tp = (h + l + c) / 3
    F["cci_z"] = (tp - tp.rolling(20).mean()) / tp.rolling(20).std()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = wilder(tr, 14)
    F["atr_pct"] = atr / c
    upm, dnm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((upm > dnm) & (upm > 0), upm, 0.0), index=df.index)
    mdm = pd.Series(np.where((dnm > upm) & (dnm > 0), dnm, 0.0), index=df.index)
    pdi, mdi = 100 * wilder(pdm, 14) / atr, 100 * wilder(mdm, 14) / atr
    F["adx"] = wilder(100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan), 14)
    F["di_diff"] = pdi - mdi
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    F["macd_h"] = (macd - macd.ewm(span=9, adjust=False).mean()) / c
    m, sd = c.rolling(20).mean(), c.rolling(20).std()
    F["bb_pct"] = (c - (m - 2 * sd)) / (4 * sd).replace(0, np.nan)
    F["bb_w"] = 4 * sd / m
    F["vol20"], F["vol60"] = lr.rolling(20).std(), lr.rolling(60).std()
    F["vol_ratio"] = F["vol20"] / F["vol60"]
    F["hi52"] = c / h.rolling(252).max() - 1
    F["lo52"] = c / l.rolling(252).min() - 1
    F["dd60"] = c / c.rolling(60).max() - 1
    F["vz20"] = np.log(v / v.rolling(20).mean())
    F["vtrend"] = np.log(v.rolling(5).mean() / v.rolling(60).mean())
    F["turn"] = np.log((c * v).rolling(20).mean())
    F["skew60"] = lr.rolling(60).skew()
    F["up20"] = (lr > 0).astype(float).rolling(20).mean()
    F["gap20"] = np.log(o / c.shift()).abs().rolling(20).mean()
    F["range20"] = ((h - l) / c).rolling(20).mean()
    n = nlr.reindex(df.index)
    cov = lr.rolling(250, min_periods=120).cov(n)
    beta = cov / n.rolling(250, min_periods=120).var()
    F["beta"] = beta
    F["corr60"] = lr.rolling(60).corr(n)
    F["idio60"] = (lr - beta * n).rolling(60).std()
    return F, c


def build():
    uni = pd.read_csv(ROOT / "data" / "universe" / "nifty500.csv")
    syms = dict(zip(uni["Symbol"], uni["Industry"]))
    nifty = load("^NSEI")
    if nifty is None:
        raise SystemExit("NIFTY 50 history missing (data/terminal/daily/_5eNSEI.json): run scripts/terminal_hist.py first")
    nc = nifty["c"]
    nlr = np.log(nc).diff()
    frames, closes = [], {}
    t0 = time.time()
    for sym, ind in syms.items():
        df = load(sym)
        if df is None:
            continue
        F, c = features(df, nlr)
        nfw = np.log(nc.shift(-H) / nc).reindex(F.index)
        F["fwd"] = np.log(c.shift(-H) / c) - nfw                  # excess log return over the next H days
        F["rel20"] = F["r20"] - np.log(nc / nc.shift(20)).reindex(F.index)
        F["rel60"] = F["r60"] - np.log(nc / nc.shift(60)).reindex(F.index)
        F["sym"], F["ind"] = sym, ind
        F = F.iloc[250:]                                         # a year of warm-up for the long features
        frames.append(F)
        closes[sym] = c
    X = pd.concat(frames)
    X.index.name = "date"
    X = X.reset_index()
    # market-wide inputs (same for every stock on a day)
    m = pd.DataFrame(index=nifty.index)
    m["m_r5"], m["m_r20"], m["m_r60"] = [np.log(nc / nc.shift(n)) for n in (5, 20, 60)]
    m["m_d200"] = nc / nc.rolling(200).mean() - 1
    m["m_vol20"] = nlr.rolling(20).std()
    g = X.groupby("date")
    br = pd.DataFrame({"m_br200": g["d_sma200"].apply(lambda s: (s > 0).mean()), "m_br50": g["d_sma50"].apply(lambda s: (s > 0).mean()),
                       "m_disp": g["r20"].std()})
    X = X.merge(m, left_on="date", right_index=True, how="left").merge(br, left_on="date", right_index=True, how="left")
    X["sec_rel60"] = X["r60"] - X.groupby(["date", "ind"])["r60"].transform("median")
    for col in RANKED:
        X[col + "_rk"] = X.groupby("date")[col].rank(pct=True)
    X["ind"] = X["ind"].astype("category")
    X = X.replace([np.inf, -np.inf], np.nan)
    print(f"features: {len(X):,} stock-days, {X['sym'].nunique()} stocks, {X['date'].min().date()} .. {X['date'].max().date()} ({time.time() - t0:.0f}s)")
    return X


FEATS = None
P_CLF = dict(objective="binary", learning_rate=0.03, num_leaves=31, min_child_samples=400, feature_fraction=0.7, bagging_fraction=0.7, bagging_freq=1,
             lambda_l2=10.0, max_bin=63, verbose=-1, n_estimators=350)
P_RANK = dict(objective="lambdarank", learning_rate=0.03, num_leaves=31, min_child_samples=400, feature_fraction=0.7, bagging_fraction=0.7, bagging_freq=1,
              lambda_l2=10.0, max_bin=63, verbose=-1, n_estimators=300, lambdarank_truncation_level=100, label_gain=[0, 1, 2, 3, 4])
P_REG = dict(objective="huber", alpha=0.08, learning_rate=0.03, num_leaves=31, min_child_samples=400, feature_fraction=0.7, bagging_fraction=0.7, bagging_freq=1,
             lambda_l2=10.0, max_bin=63, verbose=-1, n_estimators=350)


def fit(train):
    t = train[train["date"].dt.dayofweek.isin([0, 1, 2, 3, 4])]
    t = t[t["date"].rank(method="dense").astype(int) % STEP == 0]     # every STEP-th trading day
    t = t.dropna(subset=["fwd"])
    X, y, r = t[FEATS], (t["fwd"] > 0).astype(int), t["fwd"].clip(-0.4, 0.4)
    clfs = [lgb.LGBMClassifier(**P_CLF, random_state=s).fit(X, y, categorical_feature=["ind"]) for s in SEEDS]
    reg = lgb.LGBMRegressor(**P_REG, random_state=1).fit(X, r, categorical_feature=["ind"])
    # ranker: learns to ORDER each day's stocks by excess return (quintile labels, LambdaRank)
    t = t.sort_values("date")
    rel = t.groupby("date")["fwd"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False)).astype(int)
    rk = lgb.LGBMRanker(**P_RANK, random_state=3).fit(t[FEATS], rel, group=t.groupby("date", sort=True).size().values, categorical_feature=["ind"])
    return clfs, reg, len(t), rk


def score(models, D):
    clfs, reg = models[0], models[1]
    p = np.mean([c.predict_proba(D[FEATS])[:, 1] for c in clfs], axis=0)
    q = reg.predict(D[FEATS])
    k = models[3].predict(D[FEATS])
    s = pd.DataFrame({"date": D["date"].values, "p": p, "q": q, "k": k})
    # rank-average classifier, regressor and ranker within each day -> one score in 0..1
    g = s.groupby("date")
    return ((g["p"].rank(pct=True) + g["q"].rank(pct=True) + g["k"].rank(pct=True)) / 3).values, p


def walk_forward(X):
    dates = np.sort(X["date"].unique())
    years = sorted(pd.DatetimeIndex(dates).year.unique())
    first = years[0] + MIN_TRAIN_YEARS
    oos = []
    for yr in [y for y in years if y >= first]:
        test = X[(X["date"].dt.year == yr) & X["fwd"].notna()]
        if test.empty:
            continue
        start = pd.Timestamp(test["date"].min())
        cut = dates[max(0, np.searchsorted(dates, np.datetime64(start)) - GAP)]
        train = X[X["date"] < cut]
        t0 = time.time()
        models = fit(train)
        sc, p = score(models, test)
        part = test[["date", "sym", "fwd"]].copy()
        part["score"], part["p_raw"] = sc, p
        oos.append(part)
        print(f"  test {yr}: trained on {models[2]:,} rows up to {pd.Timestamp(cut).date()}, "
              f"AUC {roc_auc_score(part['fwd'] > 0, part['score']):.3f} ({time.time() - t0:.0f}s)")
    return pd.concat(oos)


def evaluate(O):
    y = (O["fwd"] > 0).astype(int)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98).fit(O["score"], y)
    O = O.assign(p=iso.predict(O["score"]), dec=np.minimum(9, (O["score"] * 10).astype(int)) + 1)
    by_dec = O.groupby("dec").agg(n=("fwd", "size"), hit=("fwd", lambda s: float((s > 0).mean())), excess=("fwd", lambda s: float(np.expm1(s).mean())))
    ic = O.groupby("date").apply(lambda d: d["score"].corr(d["fwd"], method="spearman")).dropna()
    years = []
    for yr, d in O.groupby(O["date"].dt.year):
        top, bot = d[d["dec"] == 10], d[d["dec"] == 1]
        years.append({"year": int(yr), "auc": round(float(roc_auc_score(d["fwd"] > 0, d["score"])), 3), "n": int(len(d)),
                      "top_hit": round(float((top["fwd"] > 0).mean()), 3), "top_excess": round(float(np.expm1(top["fwd"]).mean()), 4),
                      "bottom_excess": round(float(np.expm1(bot["fwd"]).mean()), 4)})
    cal = O.assign(bin=pd.qcut(O["score"], 10, labels=False, duplicates="drop")).groupby("bin").agg(pred=("p", "mean"), actual=("fwd", lambda s: float((s > 0).mean())), n=("p", "size"))
    metrics = {
        "auc": round(float(roc_auc_score(y, O["score"])), 3), "accuracy": round(float(((O["p"] > 0.5) == y).mean()), 3),
        "base_rate": round(float(y.mean()), 3), "n": int(len(O)), "from": str(O["date"].min().date()), "to": str(O["date"].max().date()),
        "ic_mean": round(float(ic.mean()), 4), "ic_t": round(float(ic.mean() / ic.std() * np.sqrt(len(ic) / H)), 2) if ic.std() else None,
        "top_decile_hit": round(float(by_dec.loc[10, "hit"]), 3), "bottom_decile_hit": round(float(by_dec.loc[1, "hit"]), 3),
        "top_decile_excess": round(float(by_dec.loc[10, "excess"]), 4), "bottom_decile_excess": round(float(by_dec.loc[1, "excess"]), 4),
        "confident_accuracy": round(float(((O["p"] > 0.5) == y)[(O["p"] - 0.5).abs() >= 0.1].mean()), 3) if ((O["p"] - 0.5).abs() >= 0.1).any() else None,
        "confident_share": round(float(((O["p"] - 0.5).abs() >= 0.1).mean()), 3),
    }
    deciles = [{"dec": int(k), "n": int(r.n), "hit": round(r.hit, 3), "excess": round(r.excess, 4)} for k, r in by_dec.iterrows()]
    calib = [{"pred": round(float(r.pred), 3), "actual": round(float(r.actual), 3), "n": int(r.n)} for _, r in cal.iterrows()]
    return iso, metrics, years, deciles, calib


def track_record(X):
    """Score saved daily predictions whose 20 trading days have passed."""
    hist = sorted((OUT / "history").glob("*.json"))
    fwd = X.dropna(subset=["fwd"]).set_index(["date", "sym"])["fwd"]
    rows = []
    for f in hist:
        d = pd.Timestamp(f.stem)
        saved = json.loads(f.read_text(encoding="utf-8"))
        for sym, (p, dec) in saved.items():
            v = fwd.get((d, sym))
            if v is not None and not np.isnan(v):
                rows.append((d, sym, p, dec, v))
    if not rows:
        return {"matured_days": 0, "note": "Predictions are scored 20 trading days after they are made; the first ones mature about a month after launch."}
    R = pd.DataFrame(rows, columns=["date", "sym", "p", "dec", "fwd"])
    y = R["fwd"] > 0
    return {"matured_days": int(R["date"].nunique()), "n": int(len(R)), "accuracy": round(float(((R["p"] > 0.5) == y).mean()), 3),
            "auc": round(float(roc_auc_score(y, R["p"])), 3) if y.nunique() > 1 else None,
            "top_decile_hit": round(float(y[R["dec"] == 10].mean()), 3) if (R["dec"] == 10).any() else None,
            "top_decile_excess": round(float(np.expm1(R.loc[R["dec"] == 10, "fwd"]).mean()), 4) if (R["dec"] == 10).any() else None}


def main():
    global FEATS
    t0 = time.time()
    X = build()
    FEATS = [c for c in X.columns if c not in ("date", "sym", "fwd")]
    print(f"{len(FEATS)} inputs; walk-forward test:")
    O = walk_forward(X)
    iso, metrics, years, deciles, calib = evaluate(O)
    print(f"out-of-sample: AUC {metrics['auc']}, accuracy {metrics['accuracy']} (base rate {metrics['base_rate']}), "
          f"top decile beats NIFTY {metrics['top_decile_hit']:.1%} vs bottom {metrics['bottom_decile_hit']:.1%}")
    # final models: everything whose 20-day answer is known, then today's prediction
    dates = np.sort(X["date"].unique())
    last = pd.Timestamp(dates[-1])
    cut = dates[-(GAP + 1)]
    models = fit(X[X["date"] < cut])
    today = X[X["date"] == last].copy()
    sc, _ = score(models, today)
    today["score"], today["p"] = sc, iso.predict(sc)
    today["dec"] = np.minimum(9, (today["score"] * 10).astype(int)) + 1
    dec_excess = {d["dec"]: d["excess"] for d in deciles}
    contrib = np.mean([c.predict_proba(today[FEATS], pred_contrib=True) for c in models[0]], axis=0)[:, :-1]
    imp = pd.Series(np.mean([c.booster_.feature_importance("gain") for c in models[0]], axis=0), index=FEATS).sort_values(ascending=False)
    base = lambda f: "market" if f.startswith("m_") else f[:-3] if f.endswith("_rk") else f
    NAMES["market"] = "market conditions (breadth, NIFTY trend and volatility)"
    out = {}
    for i, (_, r) in enumerate(today.iterrows()):
        # the day's market conditions are the same for every stock, so they can't explain why one stock ranks above another
        cs = pd.Series(contrib[i], index=FEATS).groupby(lambda f: base(f)).sum().drop("market", errors="ignore").sort_values()
        NAMES["ind"] = f"its sector ({r['ind']})"
        drv = [[NAMES.get(f, f), round(float(v), 3)] for f, v in list(cs[::-1].items())[:3] if v > 0] + [[NAMES.get(f, f), round(float(v), 3)] for f, v in list(cs.items())[:2] if v < 0]
        out[r["sym"]] = {"p": round(float(r["p"]), 3), "s": round(float(r["score"]), 4), "dec": int(r["dec"]), "er": dec_excess.get(int(r["dec"])), "drivers": drv}
    (OUT / "history").mkdir(parents=True, exist_ok=True)
    (OUT / "history" / f"{last.date()}.json").write_text(json.dumps({s: [v["p"], v["dec"]] for s, v in out.items()}, separators=(",", ":")), encoding="utf-8")
    res = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(timespec="seconds"), "as_of": str(last.date()), "horizon_days": H,
        "question": "Will the stock beat the NIFTY 50 over the next 20 trading days?",
        "model": {"type": "LightGBM ensemble (3 classifiers + 1 excess-return regressor + 1 LambdaRank ranker), rank-averaged, isotonic-calibrated",
                  "inputs": len(FEATS), "stocks": int(today["sym"].nunique()), "train_rows_final": models[2], "train_to": str(pd.Timestamp(cut).date()),
                  "top_inputs": [[("sector" if f == "ind" else NAMES.get(f, f)), round(float(v / imp.sum()), 3)] for f, v in imp.groupby(lambda f: base(f)).sum().sort_values(ascending=False).head(12).items()]},
        "oos": {"metrics": metrics, "years": years, "deciles": deciles, "calibration": calib},
        "live": track_record(X),
        "stocks": out,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(res, allow_nan=False, default=lambda o: None), encoding="utf-8")
    top = sorted(out.items(), key=lambda kv: -kv[1]["p"])[:5]
    print("as of", last.date(), "· top 5:", ", ".join(f"{s} {v['p']:.0%}" for s, v in top), f"· done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
