"""
ALADIN 2.0 drift detection (section 7.2): is the world a strategy was selected in still the world it trades in?

  psi            Population Stability Index of a feature between a reference window and a recent window (bins from the reference quantiles). Rule of thumb: < 0.1 stable, 0.1-0.25 moving, > 0.25 shifted.
  ks             two-sample Kolmogorov-Smirnov statistic and p-value.
  vol_break      recent realised volatility vs the reference (a ratio above `vol_ratio` or below its inverse is a regime break).
  strategy_drift  checks every feature a strategy uses (pooled over a sample of stocks) and the volatility regime; returns an alarm dict for lifecycle.step() or None.
Alarms are only RAISED here; the lifecycle decides (an alarm demotes an Active or Probation strategy at the next block boundary) and the journal records the evidence.
"""
import numpy as np
from scipy import stats


def psi(ref, cur, bins=10):
    ref, cur = np.asarray(ref, float), np.asarray(cur, float); ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 100 or len(cur) < 50:
        return None
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return None
    edges[0], edges[-1] = -np.inf, np.inf
    a = np.histogram(ref, edges)[0] / len(ref); b = np.histogram(cur, edges)[0] / len(cur); a, b = np.clip(a, 1e-4, None), np.clip(b, 1e-4, None)
    return float(np.sum((b - a) * np.log(b / a)))


def ks(ref, cur):
    ref, cur = np.asarray(ref, float), np.asarray(cur, float); ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 100 or len(cur) < 50:
        return None
    r = stats.ks_2samp(ref, cur); return float(r.statistic), float(r.pvalue)


def vol_break(ref_returns, cur_returns, ratio=2.0):
    a, b = np.nanstd(ref_returns), np.nanstd(cur_returns)
    if not a or not np.isfinite(a) or not np.isfinite(b):
        return None
    r = float(b / a); return {"ratio": round(r, 2), "break": bool(r > ratio or r < 1 / ratio)}


def strategy_drift(features_used, ref, cur, psi_alarm=0.25, ks_p=1e-6, ref_ret=None, cur_ret=None, vol_ratio=2.0):
    """ref / cur: dicts feature -> 1-D arrays (pooled over stocks) for the reference and the recent window. -> alarm dict or None."""
    hits = {}
    for f in features_used:
        if f in ref and f in cur:
            p = psi(ref[f], cur[f]); k = ks(ref[f], cur[f])
            if p is not None and p > psi_alarm and k is not None and k[1] < ks_p:
                hits[f] = {"psi": round(p, 3), "ks": round(k[0], 3)}
    vb = vol_break(ref_ret, cur_ret, vol_ratio) if ref_ret is not None and cur_ret is not None else None
    if hits or (vb and vb["break"]):
        return {"reason": "feature drift" if hits else "volatility regime break", "features": hits, "vol": vb}
    return None
