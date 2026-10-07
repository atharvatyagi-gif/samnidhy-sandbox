"""Family 2: mean reversion (long after a stretch down; fixed short holds)."""
import numpy as np

from .base import Strategy


def _rsi2(ctx, p):
    return (ctx.F["rsi2"] < p["below"]).astype(float)


def _bbz(ctx, p):
    return (ctx.F["bb_z"] < -p["z"]).astype(float)


def _reversal(ctx, p):
    F = ctx.F; z = F["r5"] / (F["vol20"] * np.sqrt(5))
    return ((z < -p["k"]) & (F["vz20"] > 0.5)).astype(float)                    # volume-confirmed sell-off


def _gapfill(ctx, p):
    return (ctx.F["gap"] < -p["gap"]).astype(float)


def build():
    out = []
    for i, t in enumerate([5, 10, 15]):
        out.append(Strategy(f"rsi2_below_{t}", "reversion", "rsi2", i, {"below": t}, {"type": "fixed", "n": 5}, 20, ("rsi2",), _rsi2))
    for i, z in enumerate([1.5, 2.0, 2.5]):
        out.append(Strategy(f"bb_z_below_{z}", "reversion", "bb_z", i, {"z": z}, {"type": "fixed", "n": 10}, 20, ("bb_z",), _bbz))
    for i, k in enumerate([1.0, 1.5, 2.0]):
        out.append(Strategy(f"reversal5_vol_{k}", "reversion", "reversal5", i, {"k": k}, {"type": "fixed", "n": 10}, 25, ("r5", "vol20", "vz20"), _reversal))
    for i, g in enumerate([0.01, 0.02, 0.03]):
        out.append(Strategy(f"gapfill_{int(g * 100)}pct", "reversion", "gapfill", i, {"gap": g}, {"type": "fixed", "n": 5}, 2, ("gap",), _gapfill))
    return out
