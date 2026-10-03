"""
Quantitative building blocks for the ALADIN technical front (scripts/aladin_model.py). Pure numpy/pandas functions,
each testable on its own (tests/test_aladin_quant.py). Nothing here looks ahead: every value at day t uses data up to
and including day t only, and the HMM is a forward (filtering) recursion, never a smoother.

  Gaussian2HMM            2-state Gaussian hidden Markov model, EM fit + forward-filtered state probabilities. (hmmlearn does not
                          install on every Python, and it would give smoothed probabilities by default, so this is a small
                          self-contained version that can only filter.)
  kalman_spread           random-walk [alpha, beta] Kalman filter for y_t = alpha_t + beta_t x_t + e_t
  half_life               AR(1) mean-reversion half-life of a series
  pca_residuals           rolling PCA (refit every `refit_every` days on the trailing window) -> residual returns, R^2
  engle_granger_pairs     best same-industry partner per stock by return correlation, tested with Engle-Granger
  jump_params, bipower_jump_share   Merton-style jump statistics from robust sigma
"""

import math

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ HMM

class Gaussian2HMM:
    """Two-state Gaussian HMM on d-dimensional observations (full covariances). State 1 is always the 'high-volatility' state:
    the one whose first-coordinate variance is larger (so labels are stable across refits)."""

    def __init__(self, n_iter=30, tol=1e-4, seed=0):
        self.n_iter, self.tol, self.seed = n_iter, tol, seed
        self.fitted = False

    # -- helpers
    @staticmethod
    def _logpdf(X, mu, cov):
        d = X.shape[1]
        cov = cov + np.eye(d) * 1e-6
        inv = np.linalg.inv(cov)
        _, logdet = np.linalg.slogdet(cov)
        diff = X - mu
        return -0.5 * (np.einsum("ij,jk,ik->i", diff, inv, diff) + logdet + d * math.log(2 * math.pi))

    def _emission(self, X):
        return np.column_stack([self._logpdf(X, self.mu[k], self.cov[k]) for k in range(2)])

    def fit(self, X):
        X = np.asarray(X, float)
        n, d = X.shape
        self.m, self.s = X.mean(0), X.std(0) + 1e-12            # standardise with the TRAINING window's moments only
        Z = (X - self.m) / self.s
        vol = np.abs(Z[:, 0])
        hi = vol > np.quantile(vol, 0.7)                         # initial split: calm vs stormy days
        self.mu = np.array([Z[~hi].mean(0), Z[hi].mean(0)])
        self.cov = np.array([np.cov(Z[~hi].T) + np.eye(d) * 1e-3, np.cov(Z[hi].T) + np.eye(d) * 1e-3])
        self.A = np.array([[0.95, 0.05], [0.10, 0.90]])
        self.pi = np.array([0.8, 0.2])
        prev = -np.inf
        for _ in range(self.n_iter):
            logB = self._emission(Z)
            B = np.exp(logB - logB.max(1, keepdims=True))
            c = np.zeros(n)
            alpha = np.zeros((n, 2))
            a = self.pi * B[0]
            c[0] = a.sum(); alpha[0] = a / c[0]
            for t in range(1, n):
                a = (alpha[t - 1] @ self.A) * B[t]
                c[t] = a.sum(); alpha[t] = a / c[t]
            beta = np.ones((n, 2))
            xi = np.zeros((2, 2))
            A = self.A
            for t in range(n - 2, -1, -1):
                nb = B[t + 1] * beta[t + 1]
                x = alpha[t][:, None] * A * nb[None, :]
                xi += x / x.sum()
                beta[t] = (A @ nb) / c[t + 1]
            gamma = alpha * beta
            gamma /= gamma.sum(1, keepdims=True)
            self.A = xi / xi.sum(1, keepdims=True)
            self.pi = gamma[0]
            for k in range(2):
                w = gamma[:, k]
                sw = w.sum() + 1e-12
                self.mu[k] = (w[:, None] * Z).sum(0) / sw
                diff = Z - self.mu[k]
                self.cov[k] = (w[:, None, None] * np.einsum("ij,ik->ijk", diff, diff)).sum(0) / sw + np.eye(d) * 1e-4
            ll = float((np.log(c) + logB.max(1)).sum())
            if abs(ll - prev) < self.tol * abs(ll):
                break
            prev = ll
        if self.cov[0][0, 0] > self.cov[1][0, 0]:                # make state 1 the high-variance state
            self.mu, self.cov = self.mu[::-1].copy(), self.cov[::-1].copy()
            self.A = self.A[::-1, ::-1].copy()
            self.pi = self.pi[::-1].copy()
        self.fitted = True
        return self

    def filtered(self, X):
        """P(high-vol state at t | observations up to t) for every row. Forward recursion only: row t never sees row t+1."""
        Z = (np.asarray(X, float) - self.m) / self.s
        logB = self._emission(Z)
        B = np.exp(logB - logB.max(1, keepdims=True))
        n = len(Z)
        out = np.zeros(n)
        a = self.pi * B[0]
        a /= a.sum(); out[0] = a[1]
        for t in range(1, n):
            a = (a @ self.A) * B[t]
            a /= a.sum() or 1.0
            out[t] = a[1]
        return out


# ------------------------------------------------------------------ Kalman spread

def kalman_spread(y, x, delta=1e-4, init=None):
    """Random-walk regression y_t = alpha_t + beta_t x_t + e_t. State [alpha, beta] ~ random walk with Q = delta/(1-delta) I,
    observation variance fixed at the OLS residual variance of the first `min(60, n)` points (or `init['R']`).
    Returns (alpha_t, beta_t, spread_t) with spread_t = y_t - alpha_t - beta_t x_t using the PRIOR state (one-step-ahead), so it is
    what a trader could have computed before seeing y_t. `init` = {'theta': [a, b], 'P': 2x2, 'R': float} continues an earlier run."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    n = len(y)
    if init is None:
        k = min(60, n)
        X0 = np.column_stack([np.ones(k), x[:k]])
        th, *_ = np.linalg.lstsq(X0, y[:k], rcond=None)
        res = y[:k] - X0 @ th
        R = float(res.var()) + 1e-10
        theta, P = th.copy(), np.eye(2) * 1e-2
    else:
        theta, P, R = np.array(init["theta"], float), np.array(init["P"], float), float(init["R"])
    Q = delta / (1 - delta) * np.eye(2)
    a_t, b_t, s_t = np.zeros(n), np.zeros(n), np.zeros(n)
    for t in range(n):
        P = P + Q
        h = np.array([1.0, x[t]])
        e = y[t] - h @ theta                                     # innovation = spread before seeing y_t
        S = h @ P @ h + R
        K = P @ h / S
        a_t[t], b_t[t], s_t[t] = theta[0], theta[1], e
        theta = theta + K * e
        P = P - np.outer(K, h) @ P
    state = {"theta": theta.tolist(), "P": P.tolist(), "R": R}
    return a_t, b_t, s_t, state


def half_life(s):
    """Mean-reversion half-life in days from an AR(1) fit s_t = a + phi s_{t-1}; None if not mean-reverting."""
    s = np.asarray(s, float)
    s = s[np.isfinite(s)]
    if len(s) < 20:
        return None
    x, y = s[:-1], s[1:]
    vx = ((x - x.mean()) ** 2).sum()
    if vx == 0:
        return None
    phi = ((x - x.mean()) * (y - y.mean())).sum() / vx
    if not (0 < phi < 1):
        return None
    return round(-math.log(2) / math.log(phi), 2)


# ------------------------------------------------------------------ PCA residuals

def pca_residuals(ret, var_share=0.55, kmax=15, window=250, refit_every=5, min_obs=240, liquid=None):
    """ret: DataFrame (date x symbol) of daily log returns. Every `refit_every` days the principal components are re-estimated on the
    trailing `window` days (only stocks with >= min_obs observations in it, and, if `liquid` is given, only stocks that are liquid ON THAT DAY:
    `liquid` is a boolean DataFrame aligned with `ret`, so the stock list never depends on how a stock traded later); the days until the next
    refit are projected on those components. Returns (residual returns DataFrame, k per refit Series). Residual_t = r_t - V V' r_t, using only
    components fitted on data up to a date <= t, so there is no look-ahead."""
    cols = list(ret.columns)
    pos = {c: k for k, c in enumerate(cols)}
    R = ret.fillna(0.0).values
    N = ret.shape[1]
    outv = np.full(ret.shape, np.nan)
    ks = {}
    V, idx = None, None
    counts = ret.notna().rolling(window, min_periods=1).sum().values if len(ret) > window else None
    liq = None if liquid is None else liquid.reindex(index=ret.index, columns=cols).fillna(False).values
    for i in range(window, len(ret)):
        if V is None or (i - window) % refit_every == 0:
            ok = counts[i] >= min_obs
            if liq is not None:
                ok = ok & liq[i]
            idx = np.where(ok)[0]
            if len(idx) < 30:
                V = None
                continue
            W = R[i - window + 1:i + 1][:, idx]
            W = W - W.mean(0)
            u, s, vt = np.linalg.svd(W, full_matrices=False)
            share = np.cumsum(s ** 2) / (s ** 2).sum()
            k = int(min(kmax, np.searchsorted(share, var_share) + 1))
            V = vt[:k].T                                          # members x k
            ks[ret.index[i]] = k
        if V is None:
            continue
        r = R[i, idx]
        outv[i, idx] = r - V @ (V.T @ r)
    return pd.DataFrame(outv, index=ret.index, columns=cols), pd.Series(ks, dtype=float)


def pca_features(ret, resid):
    """pca_z: 20-day cumulative residual return z-scored against the stock's own trailing 250-day history of that statistic.
    pca_r2: share of the stock's 60-day return variance explained by the common components (1 - var(resid)/var(ret))."""
    cum20 = resid.rolling(20, min_periods=15).sum()
    z = (cum20 - cum20.rolling(250, min_periods=120).mean()) / cum20.rolling(250, min_periods=120).std()
    r2 = 1 - resid.rolling(60, min_periods=40).var() / ret.rolling(60, min_periods=40).var()
    return z, r2.clip(0, 1)


# ------------------------------------------------------------------ pairs

def engle_granger(y, x):
    """Engle-Granger cointegration p-value of two log-price series (statsmodels, 1 lag). None if it cannot be computed."""
    try:
        from statsmodels.tsa.stattools import coint
        p = coint(y, x, trend="c", maxlag=1, autolag=None)[1]
        return float(p) if np.isfinite(p) else None
    except Exception:
        return None


def engle_granger_pairs(logpx, by_ind, top_n=40, p=0.05, turnover=None):
    """For each industry take the `top_n` stocks by `turnover` (default: all, in column order), pick each stock's partner as the
    industry peer with the highest correlation of daily log-price changes, and keep the pair only if Engle-Granger p < `p`.
    Returns {sym: {"peer": sym, "p": p_value}} for stocks that have a cointegrated partner."""
    out = {}
    d = logpx.diff()
    groups = {}
    for s in logpx.columns:
        groups.setdefault(by_ind.get(s), []).append(s)
    for ind, syms in groups.items():
        if ind is None or len(syms) < 2:
            continue
        if turnover is not None:
            syms = sorted(syms, key=lambda s: -(turnover.get(s) or 0))[:top_n]
        syms = [s for s in syms if logpx[s].notna().all()]
        if len(syms) < 2:
            continue
        C = np.corrcoef(d[syms].values[1:].T)
        np.fill_diagonal(C, -2)
        for i, s in enumerate(syms):
            j = int(np.argmax(C[i]))
            pv = engle_granger(logpx[s].values, logpx[syms[j]].values)
            if pv is not None and pv < p:
                out[s] = {"peer": syms[j], "p": round(pv, 4)}
    return out


# ------------------------------------------------------------------ jumps

def robust_sigma(r):
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    return 1.4826 * float(np.median(np.abs(r - np.median(r)))) if len(r) else float("nan")


def jump_params(r, k=4.0, window=250):
    """Merton jump statistics from the last `window` daily log returns: jump if |r| > k * robust sigma.
    -> {lam: jumps per year, mj: mean jump, sj: jump std, last: trading days since the last jump (None if none in the window)}."""
    r = np.asarray(r, float)[-window:]
    r = r[np.isfinite(r)]
    if len(r) < 60:
        return None
    sig = robust_sigma(r)
    j = np.abs(r) > k * sig
    jr = r[j]
    last = None if not j.any() else int(len(r) - 1 - np.where(j)[0][-1])
    return {"lam": round(float(j.sum() / len(r) * 252), 2), "mj": round(float(jr.mean()), 4) if len(jr) else 0.0,
            "sj": round(float(jr.std()), 4) if len(jr) > 1 else 0.0, "last": last}


def bipower_jump_share(r, window=60):
    """max(0, RV - BV) / RV over the last `window` returns, with BV = (pi/2) sum |r_t||r_{t-1}|. 0 = no jump component."""
    r = np.asarray(r, float)[-window:]
    r = r[np.isfinite(r)]
    if len(r) < 20:
        return None
    rv = float((r ** 2).sum())
    bv = float(math.pi / 2 * (np.abs(r[1:]) * np.abs(r[:-1])).sum())
    return round(max(0.0, rv - bv) / rv, 4) if rv > 0 else None


def jump_features(lr, k=4.0, window=250):
    """Daily rolling versions for model training: jump_lam (jumps/yr over `window`), jump_recent (a jump in the last 20 days, 0/1),
    jump_bv (bipower jump share over 60 days). `lr` is a Series of daily log returns."""
    x = lr.values
    n = len(x)
    lam = np.full(n, np.nan)
    recent = np.full(n, np.nan)
    if n > window:
        from numpy.lib.stride_tricks import sliding_window_view
        W = sliding_window_view(x[1:], window)                    # row i = returns i+1 .. i+window
        med = np.nanmedian(W, axis=1)
        mad = np.nanmedian(np.abs(W - med[:, None]), axis=1)
        thr = 4.0 * 1.4826 * mad if k == 4.0 else k * 1.4826 * mad
        jumps = np.abs(W) > thr[:, None]
        cnt = jumps.sum(1)
        idx = np.arange(window, n)                                # row i ends at return index i+window
        lam[idx] = cnt / window * 252
        last20 = jumps[:, -20:].any(1)
        recent[idx] = last20.astype(float)
    ar = np.abs(x)
    bp = np.abs(np.r_[np.nan, x[1:]]) * np.abs(np.r_[np.nan, np.nan, x[1:-1]]) if n > 2 else np.full(n, np.nan)
    rv60 = pd.Series(x ** 2).rolling(60, min_periods=40).sum().values
    bv60 = (math.pi / 2) * pd.Series(bp).rolling(60, min_periods=40).sum().values
    share = np.clip((rv60 - bv60) / np.where(rv60 > 0, rv60, np.nan), 0, 1)
    return pd.DataFrame({"jump_lam": lam, "jump_recent": recent, "jump_bv": share}, index=lr.index)
