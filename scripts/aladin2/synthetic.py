"""
ALADIN 2.0 synthetic price generators with KNOWN truth, used to prove the learner is honest (tests/aladin2, section 6.7 of the brief).

  noise       pure random walk with realistic volatility: no strategy has a true edge, so any promotion is a false discovery
  momentum    a slow latent drift (OU, half-life ~23 days) is added to returns: trend-following has a real edge, scaled by `strength` (std of the daily drift, bps)
  reversion   a mean-reverting price component (OU, half-life ~6 days) on top of a random walk: short-term reversal has a real edge
  regime      momentum drift that exists only on days of a persistent high-volatility regime
  vanishing   momentum drift for the first `frac` of the sample and nothing afterwards
Every generator returns a DataFrame of daily o,h,l,c,v on business days a `regime` column (0 calm / 1 stressed) and `.attrs["truth"]` describing what was planted.
Returns are split into an overnight gap (about a third of the move) and an intraday part so that next-open fills are not unrealistically kind.
"""
import numpy as np
import pandas as pd


def _ou(n, phi, sd_uncond, rng):
    x = np.zeros(n); sd_e = sd_uncond * np.sqrt(1 - phi ** 2)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + sd_e * rng.standard_normal()
    return x


def _vol_path(n, rng, vol_ann=0.30):
    """Stochastic daily volatility: log-vol follows a slow OU, with two persistent regimes (calm / stressed). -> (sigma_d, regime 0/1)"""
    reg = np.zeros(n, dtype=int)
    for t in range(1, n):
        reg[t] = (1 - reg[t - 1]) if rng.random() < (0.02 if reg[t - 1] == 0 else 0.05) else reg[t - 1]
    lv = _ou(n, 0.97, 0.15, rng)
    sig = vol_ann / np.sqrt(250) * np.exp(lv) * np.where(reg == 1, 1.8, 0.8)
    return sig, reg


def _ohlcv(lr, sigma, rng, start="2012-01-02"):
    n = len(lr); idx = pd.bdate_range(start, periods=n)
    c = 100 * np.exp(np.cumsum(lr)); pc = np.r_[100.0, c[:-1]]
    gap = lr * 0.33 + 0.25 * sigma * rng.standard_normal(n)                    # overnight part (includes its own noise, so intraday absorbs the difference)
    o = pc * np.exp(gap)
    hi = np.maximum(o, c) * np.exp(np.abs(rng.standard_normal(n)) * 0.45 * sigma)
    lo = np.minimum(o, c) * np.exp(-np.abs(rng.standard_normal(n)) * 0.45 * sigma)
    v = np.exp(np.log(2e6) + 0.35 * rng.standard_normal(n) + 4 * (sigma / sigma.mean() - 1) * 0.3)
    return pd.DataFrame({"o": o, "h": hi, "l": lo, "c": c, "v": v}, index=idx)


def make(kind="noise", n=2500, seed=0, strength=6.0, frac=0.5, vol_ann=0.30):
    """strength: std of the planted daily drift in basis points (momentum/regime/vanishing) or of the mean-reverting log-price component in percent*10 (reversion)."""
    rng = np.random.default_rng(seed)
    sigma, reg = _vol_path(n, rng, vol_ann)
    eps = sigma * rng.standard_normal(n)
    drift = np.zeros(n); truth = {"kind": kind, "strength": strength, "seed": seed}
    if kind in ("momentum", "regime", "vanishing"):
        mu = _ou(n, 0.97, strength * 1e-4, rng)                                   # the drift that is "in the market" on day t; r_t = mu_{t-1} + eps_t
        mu = np.r_[0.0, mu[:-1]]
        if kind == "regime":
            mu = mu * (reg == 1)
        if kind == "vanishing":
            mu[int(n * frac):] = 0.0; truth["vanishes_at_index"] = int(n * frac)
        drift = mu; truth["family"] = "trend"
    lr = drift + eps
    if kind == "reversion":
        x = _ou(n, 0.85, strength * 1e-3, rng)                                     # mean-reverting log-price wiggle, returns pick up its first difference
        lr = eps + np.r_[0.0, np.diff(x)]; truth["family"] = "reversion"
    if kind == "noise":
        truth["family"] = None
    df = _ohlcv(lr, sigma, rng)
    df["regime"] = reg; df.attrs["truth"] = truth
    return df
