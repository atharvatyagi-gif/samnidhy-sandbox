"""Bitcoin all-weather TREND (the shadow account's rule family), on the synthetic BTC series.

Mirrors scripts/crypto_quant.py: rule_score() "TREND" line 104 (mean of the multi-horizon momentum z-scores, each clipped to +-2, the 1-bar horizon left
out), positions() line 151 (target = clip(tanh(s) x 0.40 / realised vol, -1, +1)), ROUNDS[2] line 221 (decide once a day, score smoothed over the last
3 daily scores, no-trade band 0.25), simulate() line 156 (decided at a close, traded at the next open, 0.12% of the traded value a fill).
DEVIATIONS: the terminal uses 4-hour bars (horizons 6..360 bars = 1..60 days, sigma over 180 bars = 30 days, realised vol over 42 bars = 7 days);
the synthetic market is daily, so the same horizons are used in days, and a synthetic year has 252 days (vol annualised with sqrt(252)).
Funding on shorts is not modelled (no synthetic funding rate).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..engine.metrics import Result

SOURCE = "scripts/crypto_quant.py (rule_score TREND, positions, ROUNDS[2], simulate)"
H = [3, 7, 14, 30, 60]


def score(c: np.ndarray, sigma_days: int) -> np.ndarray:
    """TREND score at each close (uses closes <= t only)."""
    lr = np.diff(np.log(c), prepend=np.nan); sig = pd.Series(lr).rolling(sigma_days, min_periods=sigma_days).std().values
    with np.errstate(all="ignore"):
        parts = [np.clip(np.log(c / pd.Series(c).shift(h).values) / (sig * math.sqrt(h)), -2, 2) for h in H]
        return np.nanmean(np.vstack(parts), axis=0)


def targets(c: np.ndarray, p: dict) -> np.ndarray:
    with np.errstate(all="ignore"):
        s = pd.Series(score(c, int(p["sigma_days"]))).rolling(int(p["smooth"]), min_periods=1).mean().values
        rv = pd.Series(np.diff(np.log(c), prepend=np.nan)).rolling(int(p["rv_days"]), min_periods=int(p["rv_days"])).std().values * math.sqrt(252)
        tgt = np.clip(np.tanh(s) * p["vol_target"] / rv, -1, 1)
    return np.clip(tgt, 0, 1) if p.get("long_only") else tgt


def run(panel, p: dict, cm, start: int) -> Result:
    x = panel.extras["btc"]; o, c = x["o"], x["c"]; T = len(c); tgt = targets(c, p)
    eq, gross, expo, trades = [1.0], [1.0], [0.0], []; pos = 0.0; traded = 0.0; cur = None
    fee = p["fee_bps"] / 1e4 * cm.cost_mult
    for t in range(start, T):
        e, g = eq[-1], gross[-1]
        r_night = o[t] / c[t - 1] - 1; e *= 1 + pos * r_night; g *= 1 + pos * r_night         # the old position carries the overnight move
        want = tgt[t - 1] if np.isfinite(tgt[t - 1]) else pos                                    # decided at yesterday's close
        if abs(want - pos) >= p["band"] or (want == 0 and pos != 0 and abs(pos) < p["band"]):
            d = abs(want - pos); cost = d * (fee + cm.slip_bps(t, None, "crypto") / 1e4); e *= 1 - cost; traded += d * e
            if cur is not None and (want == 0 or np.sign(want) != np.sign(cur["pos"])):
                r = (o[t] / cur["px"] - 1) * np.sign(cur["pos"])
                trades.append({"side": "long" if cur["pos"] > 0 else "short", "entry_t": cur["t"], "exit_t": t, "days": t - cur["t"], "pnl": r * abs(cur["pos"]),
                               "pnl_pct": r, "cost": cost, "capital": abs(cur["pos"]), "reason": "signal"}); cur = None
            if want != 0 and cur is None:
                cur = {"t": t, "px": o[t], "pos": want}
            pos = want
        r_day = c[t] / o[t] - 1; e *= 1 + pos * r_day; g *= 1 + pos * r_day
        eq.append(e); gross.append(g); expo.append(abs(pos))
    return Result(equity=np.array(eq), gross_equity=np.array(gross), trades=trades, exposure=np.array(expo), traded_value=traded)
