"""The strategy library: every strategy ALADIN may choose from, per stock.
Not built yet (stated, not hidden): fundamental/quality tilts, event strategies, text and graph strategies, ML models (families 6-9 of the brief). They need
point-in-time fundamentals and events and their own ML protocol, and arrive in a later phase."""
from .base import Strategy, latch, make_ctx  # noqa: F401
from . import flow, relative, reversion, trend, volatility


def _naive_mom(ctx, p):
    c = ctx.px["c"]
    return ((c.shift(21) / c.shift(252) - 1) > 0).astype(float)


BASELINES = [Strategy("naive_momentum_12_1", "baseline", "naive", 0, {}, {"type": "fixed", "n": 10}, 252, ("c",), _naive_mom, baseline=True)]


def all_strategies(include_baselines=True, include_discovered=False, state_dir=None):
    S = trend.build() + reversion.build() + volatility.build() + relative.build() + flow.build()
    if include_discovered:                                       # rules promoted by the discovery search (specs on disk, rebuilt by the fixed interpreter in discover.py)
        from .. import discover
        S = S + discover.load_discovered(state_dir)
    return S + (BASELINES if include_baselines else [])


def by_id(include_discovered=True):
    return {s.id: s for s in all_strategies(include_discovered=include_discovered)}


def neighbours(s, S):
    """Same group, adjacent rank (the parameter-plateau test compares a setting with these)."""
    return [t for t in S if t.group == s.group and t.family == s.family and abs(t.rank - s.rank) == 1]
