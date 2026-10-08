import json
import random

import numpy as np
import pandas as pd

from scripts.aladin2 import costs as C
from scripts.aladin2 import data_lake as L
from scripts.aladin2 import discover as DS
from scripts.aladin2 import evaluate as E
from scripts.aladin2 import synthetic as S
from scripts.aladin2.strategies import base

CFG = C.load_cfg()


def test_grammar_validity_and_hash_stability():
    s = DS.SEEDS[0]; assert DS.valid(s) and DS.complexity(s) == 2
    assert DS.spec_hash(s) == DS.spec_hash(json.loads(json.dumps(s, sort_keys=True))) == DS.spec_hash({"hold": s["hold"], "regime": s["regime"], "conds": s["conds"]})
    bad = [{"conds": [{"p": "__import__('os')", "op": "<", "t": 1}], "regime": None, "hold": 0}, {"conds": [], "regime": None, "hold": 0},
           {"conds": [{"p": "rsi2", "op": "<", "t": 7}], "regime": None, "hold": 0}, {"conds": [{"p": "z5", "op": "<", "t": 1}] * 2, "regime": None, "hold": 0},
           {"conds": [{"p": p, "op": "<", "t": DS.GRID[p][0]} for p in ("z5", "z20", "z60", "rsi2")], "regime": None, "hold": 0}, {"conds": [{"p": "z5", "op": "<", "t": 1}], "regime": "weird", "hold": 0}]
    assert not any(DS.valid(b) for b in bad)                                  # unknown primitives, off-grid thresholds, > 3 conditions, unknown regimes: all refused; no string is ever executed


def test_operators_only_produce_valid_distinct_untested_specs():
    rng = random.Random(1); tested = {DS.spec_hash(DS.SEEDS[0]): {}}
    out = DS.propose(60, None, rng, tested); hs = [DS.spec_hash(s) for s in out]
    assert len(out) == 60 and len(set(hs)) == 60 and DS.spec_hash(DS.SEEDS[0]) not in hs and all(DS.valid(s) and DS.complexity(s) <= 4 for s in out)
    child = DS.crossover(DS.SEEDS[0], DS.SEEDS[1], rng); assert DS.valid(child) or len(child["conds"]) <= 3


def test_candidate_signal_has_no_lookahead_and_is_binary():
    px = L.clean_prices(S.make("noise", n=900, seed=4)[["o", "h", "l", "c", "v"]]); D = px.index[600]
    for spec in DS.SEEDS:
        st = DS.to_strategy(spec); a = st.signal(base.make_ctx(px, L.price_features(px)))
        assert set(a.unique()) <= {0.0, 1.0}
        bad = px.copy(); bad.loc[bad.index > D, ["o", "h", "l", "c"]] *= 1.5; b = st.signal(base.make_ctx(bad, L.price_features(bad)))
        pd.testing.assert_series_equal(a.loc[:D], b.loc[:D])


def test_regime_filter_uses_only_the_given_stress_series():
    px = L.clean_prices(S.make("noise", n=600, seed=5)[["o", "h", "l", "c", "v"]]); F = L.price_features(px)
    spec = {"conds": [{"p": "z5", "op": "<", "t": 1}], "regime": "calm", "hold": 1}; st = DS.to_strategy(spec)
    free = st.signal(base.make_ctx(px, F)); ctx = base.make_ctx(px, F); ctx.stress = pd.Series(1.0, index=px.index)
    assert free.sum() > 0 and st.signal(ctx).sum() == 0                          # permanent stress: a calm-only rule never fires


def test_bar_scales_with_the_number_of_rules_ever_tested():
    r = [{"p": 0.0004, "mean_bps": 50, "holdout_mean_bps": 30, "holdout_p": 0.05}]
    assert DS.verdicts([dict(r[0])], 10, CFG)[0]["passed"] is True                    # bar = 0.1 / 11 = 0.009
    assert DS.verdicts([dict(r[0])], 500, CFG)[0]["passed"] is False                  # bar = 0.1 / 501 = 0.0002: the same evidence no longer clears it
    x = dict(r[0], holdout_mean_bps=-5); assert DS.verdicts([x], 10, CFG)[0]["passed"] is False and "holdout" in x["why"]


def test_noise_universe_promotes_nothing_through_the_whole_pipeline():
    n = 3000; cal = pd.bdate_range("2012-01-02", periods=n); cfg = json.loads(json.dumps(CFG)); cfg["eval"]["select_lookback_d"] = 2500
    rng = random.Random(2); specs = DS.propose(10, None, rng, {}); strats = [DS.to_strategy(s) for s in specs]; U = {}
    for i in range(40):
        d = S.make("noise", n=n, seed=500 + i); px = L.clean_prices(d[["o", "h", "l", "c", "v"]]); U[f"N{i}"] = E.build_stock(f"N{i}", "x", px, L.price_features(px), strats, cal, 5, cfg)
    E.attach_benchmark(U, cal); res = DS.verdicts(DS.evaluate_batch(specs, U, cal, cfg, n - 1), 0, cfg)
    assert len(res) == 10 and not any(r["passed"] for r in res)


def test_same_rule_in_a_different_condition_order_is_one_rule_and_survivorship_stress_blocks_thin_edges():
    a = {"conds": [{"p": "rsi2", "op": "<", "t": 10}, {"p": "d_sma200", "op": ">", "t": 0}], "regime": None, "hold": 1}
    b = {"conds": list(reversed(a["conds"])), "regime": None, "hold": 1}
    assert DS.spec_hash(a) == DS.spec_hash(b) and DS.canon(a) == DS.canon(b)
    thin = {"p": 0.0001, "mean_bps": 60, "stress_mean_bps": 60 - DS.STRESS_BPS, "holdout_mean_bps": 40, "holdout_p": 0.05}
    r = DS.verdicts([thin], 5, CFG)[0]; assert r["passed"] is False and "survivorship" in r["why"]
    ok = {**thin, "mean_bps": 160, "stress_mean_bps": 60}; assert DS.verdicts([ok], 5, CFG)[0]["passed"] is True
