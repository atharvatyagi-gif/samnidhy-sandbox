"""Family 1: trend and momentum (long when the trend is up; flat otherwise)."""
from .base import Strategy, latch


def _ma_cross(ctx, p):
    c = ctx.px["c"]
    return (c.rolling(p["fast"]).mean() > c.rolling(p["slow"]).mean()).astype(float)


def _donchian(ctx, p):
    c, h, l = ctx.px["c"], ctx.px["h"], ctx.px["l"]; n = p["n"]
    return latch(c > h.shift().rolling(n).max(), c < l.shift().rolling(max(5, n // 2)).min())


def _tsmom(ctx, p):
    c = ctx.px["c"]
    return ((c.shift(21) / c.shift(p["lookback"]) - 1) > 0).astype(float)


def _hi52(ctx, p):
    c = ctx.px["c"]
    return (c >= (1 - p["within"]) * c.rolling(250, min_periods=200).max()).astype(float)


def build():
    out = []; flip = {"type": "flip", "max_n": 250}
    for i, (f, s) in enumerate([(10, 50), (20, 100), (50, 200)]):
        out.append(Strategy(f"ma_cross_{f}_{s}", "trend", "ma_cross", i, {"fast": f, "slow": s}, flip, s, ("c",), _ma_cross))
    for i, n in enumerate([20, 55, 100]):
        out.append(Strategy(f"donchian_{n}", "trend", "donchian", i, {"n": n}, flip, n, ("h", "l", "c"), _donchian))
    for i, lb in enumerate([60, 120, 250]):
        out.append(Strategy(f"tsmom_{lb}_skip21", "trend", "tsmom", i, {"lookback": lb}, flip, lb, ("c",), _tsmom))
    for i, w in enumerate([0.05, 0.10]):
        out.append(Strategy(f"hi52_within_{int(w * 100)}", "trend", "hi52", i, {"within": w}, flip, 250, ("c",), _hi52))
    return out
