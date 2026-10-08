"""
ALADIN 2.0 meta-learner (section 7.3 and 7.5): how the ACTIVE strategies of a stock are combined, and how probabilities are kept honest.

  Hedge         exponentially weighted weights over the active strategies, updated from realised COST-ADJUSTED outcomes (loss = -excess return, scaled), one Hedge per market regime,
                with a floor and a cap so no strategy can vanish or dominate.
  thompson      weights from Thompson sampling of each strategy's posterior mean net expectancy (Normal, from its trades): how often it is the best arm.
  regime        P(high-volatility state) from the 2-state Gaussian HMM already in scripts/aladin_quant.py, FILTERED probabilities only (never smoothed, so no look-ahead).
  combine       score in [0, 1] = weighted share of active strategies that are on.
  Calibrator    isotonic calibration of probabilities on a rolling window of RESOLVED live forecasts; with fewer than `min_n` points it falls back to the pooled calibrator; ECE is tracked and a
                breach demotes the stock (kill.py).
The learner changes only weights and calibration, never code.
"""
import math

import numpy as np
from sklearn.isotonic import IsotonicRegression


class Hedge:
    def __init__(self, arms, eta=0.5, floor=0.05, cap=0.6):
        self.arms = list(arms); self.eta, self.floor, self.cap = eta, floor, cap; self.logw = {a: 0.0 for a in self.arms}

    def weights(self):
        """Softmax of the log weights projected onto {floor <= w <= cap, sum = 1}: w_i = clip(lambda * softmax_i, floor, cap) with lambda found by bisection (the sum is monotone in lambda)."""
        lw = np.array([self.logw[a] for a in self.arms]); w = np.exp(lw - lw.max()); w /= w.sum()
        lo, hi = 1e-300, 1e300
        for _ in range(400):
            mid = math.sqrt(lo * hi); tot = np.clip(mid * w, self.floor, self.cap).sum()
            lo, hi = (mid, hi) if tot < 1.0 else (lo, mid)
        out = np.clip(math.sqrt(lo * hi) * w, self.floor, self.cap)
        return dict(zip(self.arms, out / out.sum()))

    def update(self, losses, scale=0.05):
        """losses: {arm: loss}, e.g. -(net excess return) of the arm's trade; scaled so a 5% loss is one unit."""
        for a, l in losses.items():
            if a in self.logw:
                self.logw[a] -= self.eta * float(np.clip(l / scale, -3, 3))


class RegimeHedge:
    """One Hedge per regime ('calm', 'stress'); the combined weights blend the two by the filtered probability of stress."""
    def __init__(self, arms, **kw):
        self.h = {"calm": Hedge(arms, **kw), "stress": Hedge(arms, **kw)}

    def update(self, losses, p_stress):
        self.h["stress" if p_stress >= 0.5 else "calm"].update(losses)

    def weights(self, p_stress):
        a, b = self.h["calm"].weights(), self.h["stress"].weights()
        return {k: (1 - p_stress) * a[k] + p_stress * b[k] for k in a}


def thompson_weights(means, ses, rng, n=4000):
    """Share of draws in which each arm has the highest sampled mean net expectancy."""
    arms = list(means); M = np.column_stack([rng.normal(means[a], max(ses[a], 1e-9), n) for a in arms]); win = np.bincount(M.argmax(1), minlength=len(arms)) / n
    return dict(zip(arms, win))


def stress_probability(nifty_close, train_n=500):
    """Filtered P(high-volatility regime) for every day of an index close series, from the existing 2-state HMM (observations: daily log return and 20-day volatility).
    The HMM is fitted on the FIRST train_n observations only and then run forward, so for rows after train_n a probability never changes when later data arrives (rows inside the
    training window are in-sample); in production the fit is refreshed periodically on data before the day being scored."""
    import numpy as _np
    import pandas as _pd
    from scripts.aladin_quant import Gaussian2HMM
    c = _pd.Series(nifty_close).astype(float); lr = _np.log(c / c.shift()); X = _pd.concat([lr, lr.rolling(20).std()], axis=1).dropna()
    train = X.iloc[:train_n]; h = Gaussian2HMM().fit(train.values)
    return _pd.Series(h.filtered(X.values), index=X.index)


def combine(signals, weights):
    """signals {strategy: 0/1}, weights {strategy: w}. -> score in [0, 1]."""
    tot = sum(weights.get(s, 0.0) for s in signals) or 1.0
    return float(sum(weights.get(s, 0.0) * v for s, v in signals.items()) / tot)


class Calibrator:
    def __init__(self, min_n=300):
        self.min_n, self.iso, self.n = min_n, None, 0

    def fit(self, p, y):
        self.n = len(p)
        if self.n >= 20:
            self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98).fit(np.asarray(p, float), np.asarray(y, float))
        return self

    def usable(self):
        return self.iso is not None and self.n >= self.min_n

    def predict(self, p, fallback=None):
        """Own calibration when it has >= min_n resolved forecasts, else the fallback calibrator (pooled), else the input unchanged."""
        if self.usable():
            return self.iso.predict(np.asarray(p, float))
        if fallback is not None and fallback.usable():
            return fallback.iso.predict(np.asarray(p, float))
        return np.asarray(p, float)
