"""NEXUS impact score (override 17): units, sign and scale, the dependence-basis rule, the beta window, as-of integrity (no look-ahead), validation rules, the x block."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import graph_impact as gi  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CFG = {"min_conf": 0.5, "dr_cap_pct": 15, "impact_scale": 25, "impact_window_d": 5, "shock_min_pct": 3.0}


def E(i, s, d, w, wb, conf=0.9, kind="disclosed", rel="supplies"):
    return {"id": i, "s": s, "d": d, "w": w, "wb": wb, "conf": conf, "kind": kind, "rel": rel}


def item(cp="B", w=0.5, conf=1.0, rel="supplies"):
    return {"cp": cp, "rel": rel, "w": w, "conf": conf, "edge": "e-" + cp}


# ---------------------------------------------------------------- which edges count
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


# ---------------------------------------------------------------- the formula: units, sign, scale (override 17)
def test_worked_example_dR_minus_6_share_024_conf_09():
    ip, I, rows = gi.impact_from({"B": -6.0}, [item("B", 0.24, 0.9)], scale=25)
    assert ip == pytest.approx(-1.296, abs=1e-9)                      # -6.0 * 0.24 * 0.9
    assert I == pytest.approx(32.4, abs=1e-9)                         # clip(-25 * -1.296)
    assert rows == [["B", "supplies", 0.24, -6.0, 0.9]]               # [counterparty, relation, share, dR_pct, conf]
    F = 10
    assert max(-100, min(100, F - I)) == pytest.approx(-22.4)         # F_adj


def test_python_combiner_returns_the_fixture_numbers_for_that_example():
    import aladin_model as am
    ip, I, _ = gi.impact_from({"B": -6.0}, [item("B", 0.24, 0.9)])
    r = am.combine_py(0.5, F=10, I=I)
    fx = json.loads((ROOT / "tests" / "fixtures" / "combiner_cases.json").read_text(encoding="utf-8"))["cases"]
    case = next(c for c in fx if c["name"].startswith("worked example"))
    assert case["in"]["I"] == I == 32.4 and case["in"]["F"] == 10
    assert r["p"] == case["out"]["p"] == case["hand"]["p"] == pytest.approx(0.4888, abs=1e-4)         # desk-aladin.js is held to the same fixture by tests/js/combiner.test.mjs


def test_sign_scale_and_clip():
    assert gi.impact_from({"B": -4.0}, [item(w=1.0)], 25)[1] == 100.0                  # a linked estimate of -4 pts maps to I = +100 (adverse)
    assert gi.impact_from({"B": -2.0}, [item(w=1.0)], 25)[1] == 50.0
    assert gi.impact_from({"B": +4.0}, [item(w=1.0)], 25)[1] == -100.0                 # favourable: negative I
    assert gi.impact_from({"B": 0.0}, [item(w=1.0)], 25)[1] == 0.0
    assert gi.impact_from({"B": -15.0}, [item(w=1.0)], 25)[1] == 100.0                 # clipped, never beyond +/-100
    two = [item("B", 1.0), item("C", 1.0)]
    assert gi.impact_from({"B": -10, "C": -10}, two)[1] == 100.0
    assert gi.impact_from({}, [item()]) == (None, None, [])                            # nothing measurable -> not measured, never 0
    assert gi.impact_from({"B": float("nan")}, [item()]) == (None, None, [])


def test_the_scale_is_a_prior_taken_from_config_not_tuned():
    assert gi.SCALE == 25 and gi.DR_CAP == 15 and gi.MIN_EDGE_DAYS == 200
    cfg = json.loads((ROOT / "data" / "config" / "aladin_config.json").read_text(encoding="utf-8"))["nexus"]
    assert cfg["impact_scale"] == 25 and cfg["dr_cap_pct"] == 15 and cfg["impact_window_d"] == 5 and "z_cap" not in cfg


# ---------------------------------------------------------------- dR: window, beta, cap
def make_prices(n=420, seed=3, syms="ABC"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    m = rng.normal(0, 0.008, n)
    cols = {}
    for s in syms:
        cols[s] = 100 * np.cumprod(1 + 0.9 * m + rng.normal(0, 0.01, n))
    nifty = pd.Series(100 * np.cumprod(1 + m), idx)
    return pd.DataFrame(cols, idx), nifty


def test_dR_is_the_window_sum_of_residuals_with_beta_from_the_250_days_before_the_window():
    closes, nifty = make_prices(400)
    rets, m = closes.pct_change(), nifty.pct_change()
    dr = gi.window_dr(rets, m, 5, cap=1000)
    k = 380
    d = rets.index[k]
    est = slice(k - 5 - 249, k - 5 + 1)                               # the 250 days ENDING 5 days before d: none of the window's 5 days are in it
    beta = np.cov(rets["A"].iloc[est], m.iloc[est])[0, 1] / np.var(m.iloc[est], ddof=1)
    want = (rets["A"].iloc[k - 4:k + 1].sum() - beta * m.iloc[k - 4:k + 1].sum()) * 100
    assert dr.at[d, "A"] == pytest.approx(want, abs=1e-9)


def test_dR_is_capped_at_15_points():
    closes, nifty = make_prices()
    closes.iloc[-1, closes.columns.get_loc("B")] *= 0.60               # -40% in a day
    dr = gi.window_dr(closes.pct_change(), nifty.pct_change(), 5, cap=15)
    assert dr["B"].iloc[-1] == -15.0 and dr.max().max() <= 15 and dr.min().min() >= -15


def test_no_look_ahead_rewriting_prices_after_D_leaves_everything_up_to_D_unchanged():
    closes, nifty = make_prices(500)
    D = closes.index[330]
    for shift_market in (False, True):
        c2, n2 = closes.copy(), nifty.copy()
        c2.loc[c2.index > D] *= 1.5                                    # every price after D is 50% higher
        if shift_market:
            n2.loc[n2.index > D] *= 1.5
        a = gi.window_dr(closes.pct_change(), nifty.pct_change(), 5)
        b = gi.window_dr(c2.pct_change(), n2.pct_change(), 5)
        pd.testing.assert_frame_equal(a.loc[:D], b.loc[:D])           # dR for every date <= D is identical
        g = {"edges": [E("e1", "A", "B", 0.4, "revenue"), E("e2", "C", "A", 0.2, "purchases")]}
        ex = gi.exposures(g, {"A", "B", "C"})
        pd.testing.assert_frame_equal(gi.impact_pct_panel(a, ex).loc[:D], gi.impact_pct_panel(b, ex).loc[:D])      # so is impact_pct, hence I


def test_scores_use_only_data_up_to_the_as_of_day():
    closes, nifty = make_prices()
    g = {"nodes": [], "edges": [E("e1", "A", "B", 0.4, "revenue")]}
    base, _ = gi.build(g, closes, nifty, CFG)
    cut = closes.index[300]
    c2, n2 = closes.copy(), nifty.copy()
    c2.loc[c2.index > cut] *= 1.5
    n2.loc[n2.index > cut] *= 1.5
    early, _ = gi.build(g, closes.loc[:cut], nifty.loc[:cut], CFG)
    changed, _ = gi.build(g, c2.loc[:cut], n2.loc[:cut], CFG)
    assert early["stocks"] == changed["stocks"] and early["as_of"] == changed["as_of"] == cut.strftime("%Y-%m-%d")
    assert base["as_of"] == closes.index[-1].strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the stored block (the x block in aladin.json comes from this)
def test_a_counterparty_crash_gives_a_stored_block_and_a_shock():
    closes, nifty = make_prices()
    closes.iloc[-1, closes.columns.get_loc("B")] *= 0.80               # B falls 20% on the last day
    g = {"nodes": [], "edges": [E("e1", "A", "B", 0.4, "revenue")]}
    imp, shocks = gi.build(g, closes, nifty, CFG)
    x = imp["stocks"]["A"]
    assert set(x) == {"i", "ip", "n", "top"} and x["n"] == 1
    assert x["ip"] < 0 and x["i"] > 0 and x["i"] == pytest.approx(min(100, -25 * x["ip"]), abs=0.1)
    cp, rel, share, dr, conf = x["top"][0]
    assert (cp, rel, share, conf) == ("B", "supplies", 0.4, 0.9) and dr < -3
    s = shocks["shocks"][0]
    assert s["cp"] == "B" and s["dr"] <= -3 and s["cp_ret"] < -0.15 and "z" not in s
    assert imp["scale"] == 25 and imp["window_d"] == 5 and imp["dr_cap_pct"] == 15


def test_the_model_writes_the_estimate_into_the_x_block():
    src = (ROOT / "scripts" / "aladin_model.py").read_text(encoding="utf-8")
    assert 'e["x"] = {"i": xi["i"], "ip": xi.get("ip"), "n": xi["n"], "top": xi["top"], "asof"' in src


def test_empty_graph_gives_no_scores():
    closes, nifty = make_prices()
    imp, shocks = gi.build({"nodes": [], "edges": []}, closes, nifty, CFG)
    assert imp["stocks"] == {} and shocks["shocks"] == [] and imp["validation"]["validated"] is False


# ---------------------------------------------------------------- validation
def test_too_little_data_says_cannot_validate_instead_of_giving_a_result():
    closes, nifty = make_prices(420)                                   # one edge, ~110 usable days: well under 200 edge-days
    g = {"nodes": [], "edges": [E("e1", "A", "B", 0.4, "revenue")]}
    v = gi.build(g, closes, nifty, CFG)[0]["validation"]
    assert v["edge_days"] < 200 and v["validated"] is False and "windows" not in v
    assert v["note"].startswith("Impact term: cannot validate: insufficient data")


def test_a_random_signal_with_plenty_of_data_is_unvalidated_and_reports_its_inputs():
    closes, nifty = make_prices(900, seed=2, syms="ABCDEFGH")
    g = {"edges": [E(f"e{i}", a, b, 0.3, "revenue") for i, (a, b) in enumerate(zip("ABCDEFGH", "BCDEFGHA"))]}
    v = gi.build(g, closes, nifty, CFG)[0]["validation"]
    assert v["edge_days"] >= 200 and v["n_dates"] > 30 and v["focal_stocks"] == 8 and v["validated"] is False
    assert abs(v["ic_mean"]) < 0.3 and v["note"] == "Impact term: prior, unvalidated"
    assert set(v["windows"]) == {"1", "3", "5"}                        # windows 1, 3 and 5 are reported for information


def test_newey_west_t_needs_enough_observations():
    assert gi.newey_west_t([0.1] * 5)[0] is None
    t, n = gi.newey_west_t(np.random.default_rng(1).normal(0.2, 0.1, 200))
    assert n == 200 and t > 2


def test_validation_can_pass_when_a_real_lead_lag_exists_and_the_scale_is_not_touched():
    rng = np.random.default_rng(5)
    n, syms = 1500, "ABCDEFGH"
    idx = pd.bdate_range("2019-01-01", periods=n)
    m = rng.normal(0, 0.008, n)
    noise = {s: rng.normal(0, 0.01, n) for s in syms}
    cols = {}
    for s, cp in zip(syms, "BCDEFGHA"):                                # each stock follows its counterparty's own news from the day before
        lagged = np.r_[0, noise[cp][:-1]]
        cols[s] = 100 * np.cumprod(1 + 0.9 * m + noise[s] + 1.5 * lagged)
    closes = pd.DataFrame(cols, idx)
    nifty = pd.Series(100 * np.cumprod(1 + m), idx)
    g = {"edges": [E(f"e{i}", a, b, 0.3, "revenue") for i, (a, b) in enumerate(zip(syms, "BCDEFGHA"))]}
    imp = gi.build(g, closes, nifty, CFG)[0]
    v = imp["validation"]
    assert v["validated"] is True and v["t"] >= 2 and v["ic_mean"] > 0 and v["note"] == "Impact term: validated"
    assert imp["scale"] == 25                                          # passing the test did not change k


def test_a_stock_bar_on_a_day_the_index_did_not_trade_does_not_blank_the_latest_windows():
    closes, nifty = make_prices()
    hol = closes.index[-3]
    n2 = nifty.drop(hol)                                               # the index has no bar that day (a holiday), the stock does (flat print)
    g = {"nodes": [], "edges": [E("e1", "A", "B", 0.4, "revenue")]}
    imp, _ = gi.build(g, closes, n2, CFG)
    assert imp["as_of"] == closes.index[-1].strftime("%Y-%m-%d") and "A" in imp["stocks"]


def test_synthetic_fixture_graph_exposures_shocks_and_impact():
    """tests/fixtures/synthetic_graph.json is invented (labelled so, never published): it lets the logic be proven without real filings."""
    g = json.loads((ROOT / "tests" / "fixtures" / "synthetic_graph.json").read_text(encoding="utf-8"))
    assert g["_note"].startswith("SYNTHETIC")
    ex = gi.exposures(g, {"SUPA", "CUSB", "CUSC", "CUSD"}, 0.5)
    assert {(f, i["cp"], i["w"]) for f, its in ex.items() for i in its} == {("SUPA", "CUSB", 0.30), ("CUSB", "SUPA", 0.20)}        # s3 has an unlisted end
    closes, nifty = make_prices(420, seed=11, syms=["SUPA", "CUSB", "CUSC", "CUSD"])
    closes.iloc[-1, closes.columns.get_loc("CUSB")] *= 0.85                                                                           # the customer drops 15% on the last day
    imp, shocks = gi.build(g, closes, nifty, CFG)
    x = imp["stocks"]["SUPA"]
    assert x["ip"] < 0 and x["i"] > 0 and x["top"][0][0] == "CUSB"
    assert x["i"] == pytest.approx(min(100, -25 * x["ip"]), abs=0.1)
    assert [s["edge"] for s in shocks["shocks"]][0] == "s1" and shocks["shocks"][0]["focal"] == "SUPA"
    assert "CUSC" not in imp["stocks"] and "CUSD" not in imp["stocks"]                                                                   # no disclosed dependency: not measured, never 0
