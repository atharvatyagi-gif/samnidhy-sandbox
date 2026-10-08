"""
ALADIN 2.0 forecast engine (section 8): "by this date the price is likely between a and b".

Pipeline per horizon H in {1, 5, 10, 20, 60} trading days (pooled across stocks, retrained every calendar year, never on data after the fold boundary):
  1. Volatility. HAR regression (pooled, OLS) of log(mean Garman-Klass daily variance over the next H days) on log of today's 1-, 5-, 22- and 66-day mean variance and the market's 22-day variance.
     -> sigma_H, the forecast standard deviation of the H-day log return (Jensen-corrected).
  2. Shape. z = r_H / sigma_H. LightGBM QUANTILE regression of z on a few causal features (7 quantile levels from `forecast.quantiles`). Crossing quantiles are sorted.
  3. Honesty. Split-conformal (CQR) correction per band (50 / 80 / 95%): the correction is learned on the most recent `conformal_window_d` days BEFORE the test year (resolved targets only,
     purged by the longest horizon), never on the training data. Bands are therefore guaranteed to cover about their nominal share on exchangeable data, and the realised coverage out of sample is reported.
  4. P(up). Read from the corrected quantile curve (piecewise linear CDF) at z = 0, then calibrated by isotonic regression fitted on the same untouched calibration window.
  5. Paths. Filtered historical simulation: a GARCH(1,1)-type variance recursion (fixed persistence 0.98) started at the HAR forecast and mean-reverting to the long-horizon forecast, driven by
     bootstrapped STANDARDISED residuals. Gives the fan, P(touch a level before a date) and expected excursions. Validated against realised touches in run_phase3.py.
Nothing here predicts direction with confidence: the centre is the (usually near-zero) conditional median; the product is the RANGE and its honest coverage.
"""
import numpy as np
import pandas as pd

H_LIST = [1, 5, 10, 20, 60]
Q_LEVELS = [0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975]
BANDS = {"50": (2, 4), "80": (1, 5), "95": (0, 6)}                      # indices into Q_LEVELS of the (lower, upper) quantile of each central band
NOMINAL = {"50": 0.50, "80": 0.80, "95": 0.95}
FEATS = ["lv_ratio", "r5z", "r20z", "r60z", "hi52", "d_sma50", "d_sma200", "rsi14", "vz20", "bb_z", "mkt_lrv22", "vix"]
FLOOR = 1e-8


# ------------------------------------------------------------------ volatility inputs (causal)

def gk_var(px):
    """Garman-Klass daily variance of the log price (open-high-low-close). Row t uses bar t only."""
    o, h, l, c = px["o"], px["h"], px["l"], px["c"]
    v = 0.5 * np.log(h / l) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
    return v.clip(lower=FLOOR)


def har_terms(gk):
    """Log of the 1-, 5-, 22- and 66-day mean daily variance, using bars up to and including t."""
    return pd.DataFrame({"lrv1": np.log(gk), "lrv5": np.log(gk.rolling(5, min_periods=4).mean()), "lrv22": np.log(gk.rolling(22, min_periods=18).mean()), "lrv66": np.log(gk.rolling(66, min_periods=50).mean())}, index=gk.index)


def forward_logvar(gk, H):
    """log of the mean daily variance over bars t+1 .. t+H (the HAR target). NaN near the end of the sample."""
    return np.log(gk[::-1].rolling(H, min_periods=H).mean()[::-1].shift(-1))


def forward_return(c, H, bad=None):
    """log(c[t+H] / c[t]); NaN when a flagged corporate-action bar lies inside (t, t+H]."""
    r = np.log(c.shift(-H) / c)
    if bad is not None:
        b = bad.astype(float)
        inside = b[::-1].rolling(H, min_periods=1).sum()[::-1].shift(-1)
        r = r.where(~(inside > 0))
    return r


# ------------------------------------------------------------------ HAR volatility model

class HAR:
    """Pooled OLS. Fit on rows (X: columns lrv1, lrv5, lrv22, lrv66, mkt_lrv22), target = forward log variance. predict() returns the daily sigma (Jensen corrected)."""
    COLS = ["lrv1", "lrv5", "lrv22", "lrv66", "mkt_lrv22"]

    def fit(self, D, y):
        X = np.c_[np.ones(len(D)), D[self.COLS].values]; ok = np.isfinite(X).all(1) & np.isfinite(y)
        self.beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None); res = y[ok] - X[ok] @ self.beta; self.s2 = float(res.var())
        return self

    def log_var(self, D):
        return np.c_[np.ones(len(D)), D[self.COLS].values] @ self.beta

    def sigma(self, D):
        return np.sqrt(np.exp(self.log_var(D) + self.s2 / 2))


# ------------------------------------------------------------------ quantile model + conformal

def fit_quantiles(X, z, params=None, seed=0):
    """One LightGBM quantile regressor per level. Returns a list of boosters."""
    import lightgbm as lgb
    P = {"objective": "quantile", "n_estimators": 150, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 300, "colsample_bytree": 0.8, "subsample": 0.8, "subsample_freq": 1,
         "verbose": -1, "n_jobs": 14, "random_state": seed}; P.update(params or {})
    return [lgb.LGBMRegressor(alpha=q, **P).fit(X, z) for q in Q_LEVELS]


def predict_quantiles(models, X):
    """-> (n, 7) quantiles of z, rows sorted so that quantiles never cross."""
    return np.sort(np.column_stack([m.predict(X) for m in models]), axis=1)


def conformal_adjust(Qcal, zcal, alpha_level):
    """CQR: the correction (in z units) that makes the central band [Q lo, Q hi] cover `alpha_level` of the calibration targets. Qcal is the (n, 2) lower/upper matrix."""
    s = np.maximum(Qcal[:, 0] - zcal, zcal - Qcal[:, 1]); n = len(s)
    k = min(n, int(np.ceil((n + 1) * alpha_level)))
    return float(np.sort(s)[k - 1])


def adjusted_quantiles(Q, corr):
    """Apply per-band corrections to the sorted (n, 7) quantile matrix: the lower end of band b moves down by corr[b], the upper end up by corr[b]; the median is kept. Re-sorted."""
    A = Q.copy()
    for b, (lo, hi) in BANDS.items():
        A[:, lo] = Q[:, lo] - corr[b]; A[:, hi] = Q[:, hi] + corr[b]
    return np.sort(A, axis=1)


def p_up_from_quantiles(A):
    """P(z > 0) from the adjusted quantile curve: piecewise-linear CDF between the 7 levels; beyond the outer quantiles the tail mass is spread by a straight line to 0 / 1 over one band width."""
    levels = np.array(Q_LEVELS); out = np.empty(len(A))
    for i, q in enumerate(A):
        if q[0] >= 0:
            out[i] = 0.99
        elif q[-1] <= 0:
            out[i] = 0.01
        else:
            out[i] = 1.0 - float(np.interp(0.0, q, levels, left=0.0, right=1.0))
    return np.clip(out, 0.01, 0.99)


# ------------------------------------------------------------------ calibration metrics

def ece(p, y, bins=10):
    """Expected calibration error with equal-count bins (and the reliability table)."""
    p, y = np.asarray(p, float), np.asarray(y, float); o = np.argsort(p); chunks = np.array_split(o, bins); tab = []
    e = 0.0
    for c in chunks:
        if len(c):
            e += len(c) / len(p) * abs(p[c].mean() - y[c].mean()); tab.append({"pred": round(float(p[c].mean()), 4), "actual": round(float(y[c].mean()), 4), "n": int(len(c))})
    return float(e), tab


def pinball(z, q, level):
    d = z - q
    return float(np.mean(np.maximum(level * d, (level - 1) * d)))


# ------------------------------------------------------------------ path simulation (filtered historical simulation)

def simulate_paths(sigma1, sigma_lr, H, n_paths, resid, rng, alpha=0.06, beta=0.92):
    """Daily log-return paths. Variance follows h' = w + alpha*e^2 + beta*h, with w chosen so the long-run variance is sigma_lr^2 (persistence alpha+beta = 0.98), started at sigma1^2.
    resid: 1-D array of STANDARDISED residuals (zero mean, unit variance) bootstrapped for the shocks. Returns an (n_paths, H) array of cumulative log returns from today's close."""
    w = (1 - alpha - beta) * sigma_lr ** 2; h = np.full(n_paths, sigma1 ** 2); out = np.empty((n_paths, H)); cum = np.zeros(n_paths)
    for k in range(H):
        eps = rng.choice(resid, size=n_paths); r = np.sqrt(h) * eps; cum = cum + r; out[:, k] = cum; h = w + alpha * r * r + beta * h
    return out


def standardise(resid):
    r = np.asarray(resid, float); r = np.clip(r[np.isfinite(r)], -8, 8)         # a stretch of zero returns makes the filtered volatility tiny and the ratio explode: winsorise
    return (r - r.mean()) / r.std()


def fit_to_band(paths, lo, hi, q=(0.1, 0.9)):
    """Rescale the simulated cumulative returns so that the simulated central 80% band at the END of the horizon has the same width as the conformal-calibrated band [lo, hi]
    (the simulator's own dispersion is not calibrated against outcomes; the conformal band is). The shape of the paths (clustering, fat tails, order of moves) is kept."""
    a, b = np.quantile(paths[:, -1], q); w = b - a
    return paths * ((hi - lo) / w) if w > 0 else paths


def touch_prob(paths, level):
    """P(the path touches `level` (a log-return, positive = up, negative = down) at any close during the horizon)."""
    return float((paths.max(1) >= level).mean()) if level >= 0 else float((paths.min(1) <= level).mean())


def fan(paths, qs=(0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)):
    """Quantiles of the cumulative log return at every day of the horizon -> (len(qs), H)."""
    return np.quantile(paths, qs, axis=0)
