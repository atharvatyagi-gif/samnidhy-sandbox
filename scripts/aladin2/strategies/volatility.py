"""Family 3: volatility and range (compression then expansion; channel breaks)."""
from .base import Strategy


def _squeeze(ctx, p):
    F = ctx.F; w = F["bb_w"]
    tight = w <= w.rolling(120, min_periods=100).quantile(p["pct"])
    return (tight.shift(1, fill_value=False) & (F["bb_z"] > 2)).astype(float)


def _atr_break(ctx, p):
    c, F = ctx.px["c"], ctx.F
    return (c > c.rolling(20).mean() + p["k"] * F["atr14"]).astype(float)


def _nr7(ctx, p):
    return ((ctx.F["nr7"].shift(1) == 1) & (ctx.px["c"] > ctx.px["h"].shift())).astype(float)


def build():
    out = []
    for i, q in enumerate([0.10, 0.20]):
        out.append(Strategy(f"bb_squeeze_break_{int(q * 100)}", "volatility", "squeeze", i, {"pct": q}, {"type": "fixed", "n": 10}, 120, ("bb_w", "bb_z"), _squeeze))
    for i, k in enumerate([1.5, 2.0, 3.0]):
        out.append(Strategy(f"atr_channel_{k}", "volatility", "atr_break", i, {"k": k}, {"type": "atr_trail", "mult": 3.0, "max_n": 60}, 20, ("atr14",), _atr_break))
    out.append(Strategy("nr7_break", "volatility", "nr7", 0, {}, {"type": "fixed", "n": 5}, 10, ("nr7",), _nr7))
    return out
