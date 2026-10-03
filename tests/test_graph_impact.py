"""NEXUS impact score: sign, caps, the dependence-basis rule, as-of integrity (no look-ahead), validation plumbing."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import graph_impact as gi  # noqa: E402

CFG = {"min_conf": 0.5, "z_cap": 3.0, "impact_window_d": 5}


def E(i, s, d, w, wb, conf=0.9, kind="disclosed", rel="supplies"):
    return {"id": i, "s": s, "d": d, "w": w, "wb": wb, "conf": conf, "kind": kind, "rel": rel}


def test_only_shares_that_measure_the_focals_own_dependence_count():
    g = {"edges": [E("e1", "AAA", "BBB", 0.30, "revenue"),     # AAA sells to BBB, 30% of AAA's revenue -> AAA depends on BBB
                   E("e2", "AAA", "BBB", 0.10, "purchases"),   # 10% of BBB's purchases -> BBB depends on AAA
                   E("e3", "CCC", "AAA", 0.20, "purchases"),   # 20% of AAA's purchases come from CCC -> AAA depends on CCC
                   E("e4", "DDD", "AAA", 0.50, "revenue", kind="sector_io"),
                   E("e5", "EEE", "AAA", 0.40, "purchases", conf=0.3)]}
    ex = gi.exposures(g, {"AAA", "BBB", "CCC", "DDD", "EEE"}, 0.5)
    assert {(i["cp"], i["w"]) for i in ex["AAA"]} == {("BBB", 0.30), ("CCC", 0.20)}
    assert {(i["cp"], i["w"]) for i in ex["BBB"]} == {("AAA", 0.10)}
    assert "DDD" not in ex and "EEE" not in ex


def test_shares_over_one_are_scaled_down():
    g = {"edges": [E("e1", "AAA", "BBB", 0.8, "revenue"), E("e2", "AAA", "CCC", 0.8, "revenue")]}
    ex = gi.exposures(g, {"AAA", "BBB", "CCC"})
    assert sum(i["w"] for i in ex["AAA"]) == pytest.approx(1.0, abs=1e-3)


def test_sign_a_counterparty_falling_is_adverse_and_the_score_is_clipped():
    items = [{"cp": "B", "rel": "supplies", "w": 0.5, "conf": 1.0, "edge": "e1"}]
    i, rows = gi.impact_from({"B": -3.0}, items)
    assert i == pytest.approx(100 * 0.5 * np.tanh(1.5), abs=0.1) and i > 0 and rows[0][3] == -3.0
    assert gi.impact_from({"B": +3.0}, items)[0] < 0
    assert gi.impact_from({"B": 0.0}, items)[0] == 0.0
    big = [{"cp": "B", "rel": "supplies", "w": 1.0, "conf": 1.0, "edge": "e"}, {"cp": "C", "rel": "supplies", "w": 1.0, "conf": 1.0, "edge": "f"}]
    assert gi.impact_from({"B": -3, "C": -3}, big)[0] == 100
    assert gi.impact_from({}, items) == (None, [])                       # nothing measurable -> not measured, never 0


def make_prices(n=420, seed=3, syms="ABC"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    m = rng.normal(0, 0.008, n)
    cols = {}
    for s in syms:
        cols[s] = 100 * np.cumprod(1 + 0.9 * m + rng.normal(0, 0.01, n))
    nifty = pd.Series(100 * np.cumprod(1 + m), idx)
    return pd.DataFrame(cols, idx), nifty


def test_scores_use_only_data_up_to_the_as_of_day():
    closes, nifty = make_prices()
    g = {"nodes": [], "edges": [E("e1", "A", "B", 0.4, "revenue")]}
    base, _ = gi.build(g, closes, nifty, CFG)
    cut = closes.index[300]
    c2, n2 = closes.copy(), nifty.copy()
    c2.loc[c2.index > cut] *= 1.5                                         # the future is rewritten
    n2.loc[n2.index > cut] *= 1.5
    early, _ = gi.build(g, closes.loc[:cut], nifty.loc[:cut], CFG)
    changed, _ = gi.build(g, c2.loc[:cut], n2.loc[:cut], CFG)
    assert early["stocks"] == changed["stocks"] and early["as_of"] == changed["as_of"] == cut.strftime("%Y-%m-%d")
    assert base["as_of"] == closes.index[-1].strftime("%Y-%m-%d")


def test_residual_z_reacts_to_a_counterparty_crash_and_shocks_are_listed():
    closes, nifty = make_prices()
    closes.iloc[-1, closes.columns.get_loc("B")] *= 0.80                  # B falls 20% on the last day
    g = {"nodes": [], "edges": [E("e1", "A", "B", 0.4, "revenue")]}
    imp, shocks = gi.build(g, closes, nifty, CFG)
    assert imp["stocks"]["A"]["i"] > 10 and imp["stocks"]["A"]["top"][0][0] == "B"
    assert shocks["shocks"][0]["cp"] == "B" and shocks["shocks"][0]["z"] <= -1.5 and shocks["shocks"][0]["cp_ret"] < -0.15
    assert imp["validation"]["note"].startswith("Impact term: ")


def test_empty_graph_gives_no_scores():
    closes, nifty = make_prices()
    imp, shocks = gi.build({"nodes": [], "edges": []}, closes, nifty, CFG)
    assert imp["stocks"] == {} and shocks["shocks"] == [] and imp["validation"]["validated"] is False


def test_validation_labels_a_random_signal_unvalidated_and_reports_its_inputs():
    closes, nifty = make_prices(900, seed=2, syms="ABCDEFGH")
    g = {"edges": [E(f"e{i}", a, b, 0.3, "revenue") for i, (a, b) in enumerate(zip("ABCDEFGH", "BCDEFGHA"))]}
    imp, _ = gi.build(g, closes, nifty, CFG)
    v = imp["validation"]
    assert v["n_dates"] > 30 and v["focal_stocks"] == 8 and v["validated"] is False
    assert abs(v["ic_mean"]) < 0.3


def test_newey_west_t_needs_enough_observations():
    assert gi.newey_west_t([0.1] * 5)[0] is None
    t, n = gi.newey_west_t(np.random.default_rng(1).normal(0.2, 0.1, 200))
    assert n == 200 and t > 2


def test_validation_can_pass_when_a_real_lead_lag_exists():
    rng = np.random.default_rng(5)
    n, syms = 900, "ABCDEFGH"
    idx = pd.bdate_range("2022-01-03", periods=n)
    m = rng.normal(0, 0.008, n)
    noise = {s: rng.normal(0, 0.01, n) for s in syms}
    cols = {}
    for s, cp in zip(syms, "BCDEFGHA"):                                   # each stock follows its counterparty's own news from the day before
        lagged = np.r_[0, noise[cp][:-1]]
        cols[s] = 100 * np.cumprod(1 + 0.9 * m + noise[s] + 0.8 * lagged)
    closes = pd.DataFrame(cols, idx)
    nifty = pd.Series(100 * np.cumprod(1 + m), idx)
    g = {"edges": [E(f"e{i}", a, b, 0.3, "revenue") for i, (a, b) in enumerate(zip(syms, "BCDEFGHA"))]}
    v = gi.build(g, closes, nifty, CFG)[0]["validation"]
    assert v["validated"] is True and v["ic_mean"] > 0 and v["note"] == "Impact term: validated"