import collections

import numpy as np
import pandas as pd
import pytest

from scripts.aladin2 import data_lake as L
from scripts.aladin2 import synthetic as S
from scripts.aladin2.strategies import base, registry as R

STRATS = R.all_strategies()


def ctx_for(px, nifty, deliv):
    px = L.clean_prices(px[["o", "h", "l", "c", "v"]]); F = L.price_features(px)
    return base.make_ctx(px, F, nifty.reindex(px.index), deliv.reindex(px.index))


def data(seed=2, n=900):
    px = S.make("momentum", n=n, seed=seed, strength=15)
    nifty = S.make("noise", n=n, seed=seed + 100)["c"]
    deliv = pd.Series(40 + 10 * np.random.default_rng(seed).standard_normal(n), index=px.index)
    return px, nifty, deliv


def test_registry_is_well_formed():
    assert len({s.id for s in STRATS}) == len(STRATS) and len({s.hash for s in STRATS}) == len(STRATS)
    assert max(collections.Counter((s.family, s.group) for s in STRATS).values()) <= 12          # coarse grid, <= 12 settings per family line
    assert {s.family for s in STRATS} >= {"trend", "reversion", "volatility", "relative", "flow", "baseline"}


@pytest.mark.parametrize("s", STRATS, ids=lambda s: s.id)
def test_strategy_has_no_lookahead_and_is_binary(s):
    px, nifty, deliv = data(); D = px.index[600]
    a = s.signal(ctx_for(px, nifty, deliv))
    assert set(a.unique()) <= {0.0, 1.0} and not a.isna().any()
    bad = px.copy(); bad.loc[bad.index > D, ["o", "h", "l", "c"]] *= 1.5
    nb = nifty.copy(); nb.loc[nb.index > D] *= 1.5; db = deliv.copy(); db.loc[db.index > D] *= 3
    b = s.signal(ctx_for(bad, nb, db))
    pd.testing.assert_series_equal(a.loc[:D], b.loc[:D])
    pd.testing.assert_series_equal(a.loc[:D], s.signal(ctx_for(px.loc[:D], nifty.loc[:D], deliv.loc[:D])).loc[:D])      # truncating the data gives the same past signals


def test_strategies_that_need_missing_inputs_say_nothing():
    px, _, _ = data(); c = ctx_for(px, px["c"] * np.nan, pd.Series(dtype=float)); c.nifty = None; c.deliv = None
    for s in STRATS:
        if s.family in ("relative", "flow"):
            assert s.signal(c).sum() == 0
