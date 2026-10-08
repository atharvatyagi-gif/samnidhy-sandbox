"""Family 4: relative strength vs the NIFTY 50 (needs the index series; absent -> no signal, i.e. not measured)."""
from .base import Strategy


def _rs(ctx, p):
    if ctx.nifty is None:
        return ctx.px["c"] * 0.0
    c = ctx.px["c"]; n = ctx.nifty.reindex(ctx.px.index).ffill(); L = p["lookback"]
    rel = (c / c.shift(L) - 1) - (n / n.shift(L) - 1)
    return (rel > p["margin"]).astype(float)


def build():
    return [Strategy(f"rel_strength_60_{int(m * 100)}", "relative", "rs60", i, {"lookback": 60, "margin": m}, {"type": "flip", "max_n": 250}, 60, ("c", "nifty"), _rs)
            for i, m in enumerate([0.0, 0.05, 0.10])]
