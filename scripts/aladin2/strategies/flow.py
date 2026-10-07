"""Family 5: participation and flow (NSE delivery %; available from 2020, absent before -> no signal)."""
from .base import Strategy


def _deliv_surge(ctx, p):
    d = ctx.deliv
    if d is None or len(d) == 0:
        return ctx.px["c"] * 0.0
    d = d.reindex(ctx.px.index).ffill(limit=3).shift(1)                        # published after the close: usable from the next row
    surge = d.rolling(5).mean() > (1 + p["k"]) * d.rolling(20).mean()
    return (surge & (ctx.px["c"] > ctx.px["c"].shift())).astype(float)


def build():
    return [Strategy(f"delivery_surge_{int(k * 100)}", "flow", "deliv", i, {"k": k}, {"type": "fixed", "n": 10}, 30, ("delivery",), _deliv_surge) for i, k in enumerate([0.2, 0.4])]
