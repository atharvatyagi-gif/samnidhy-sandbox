import numpy as np
import pandas as pd

from scripts.aladin2 import costs as C
from scripts.aladin2 import kill as K
from scripts.aladin2 import meta as M
from scripts.aladin2 import signals as SG

CFG = C.load_cfg()


def test_kill_limits():
    ok = {"ece": 0.03, "n": 500, "coverage": {"50": 0.5, "80": 0.8, "95": 0.95}, "n_cov": 500}
    assert K.check(ok, CFG) == (False, [])
    s, why = K.check({**ok, "ece": 0.09}, CFG); assert s and "calibration" in why[0]
    assert K.check({**ok, "ece": 0.09, "n": 100}, CFG)[0] is False                                   # too few resolved forecasts to judge
    s, why = K.check({**ok, "coverage": {"50": 0.5, "80": 0.70, "95": 0.95}}, CFG); assert s and "80%" in why[0]
    assert K.check({"cusum_alarm": True}, CFG)[0]


def test_forced_calibration_break_suspends_the_stock_and_hides_its_signal():
    stocks = {"A": {"sector": "IT"}, "B": {"sector": "IT"}}
    ev = {"strategies": ["Active"], "oos_trades": 80, "live_days": 70, "ece": 0.03, "net_expectancy_bps": 12, "fdr_clean": True}
    assert SG.product_state(ev, CFG)[0] == "Validated" and SG.decide_signal("Validated", 1, 80, 40)[0] == "bull"
    out, banners = K.apply(stocks, {"A": {"ece": 0.12, "n": 400}}, {}, {}, CFG)
    assert out["A"][0] == "Suspended" and "B" not in out and not banners
    ev.update(suspended=True, suspended_reason=out["A"][1][0]); state, why = SG.product_state(ev, CFG)
    assert state == "Suspended" and SG.decide_signal(state, 1, 80, 40)[0] == "none"                    # signal hidden automatically


def test_sector_and_engine_suspension():
    stocks = {f"S{i}": {"sector": "Banks"} for i in range(6)}; stocks["X"] = {"sector": "IT"}
    out, b = K.apply(stocks, {f"S{i}": {"ece": 0.2, "n": 999} for i in range(3)}, {}, {}, CFG)
    assert all(out[f"S{i}"][0] == "Suspended" for i in range(6)) and "X" not in out and b[0]["scope"] == "sector Banks"          # half of a sector failing suspends all of it
    out, b = K.apply(stocks, {}, {}, {"ece": 0.2, "n": 999}, CFG); assert len(out) == 7 and b[0]["scope"] == "engine"


def test_hedge_weights_follow_realised_outcomes_within_floor_and_cap():
    h = M.Hedge(["a", "b", "c"], floor=0.05, cap=0.6)
    for _ in range(200):
        h.update({"a": -0.03, "b": 0.03, "c": 0.0})                      # a earns, b loses
    w = h.weights(); assert abs(sum(w.values()) - 1) < 1e-9 and w["a"] == max(w.values()) and w["a"] <= 0.6 + 1e-9 and w["b"] >= 0.05 - 1e-9
    r = M.RegimeHedge(["a", "b"]); r.update({"a": -0.05, "b": 0.05}, 0.9)
    assert r.weights(0.0)["a"] == r.weights(0.0)["b"] and r.weights(1.0)["a"] > r.weights(1.0)["b"]


def test_thompson_and_combine():
    w = M.thompson_weights({"a": 0.02, "b": 0.0}, {"a": 0.005, "b": 0.005}, np.random.default_rng(0)); assert w["a"] > 0.99 and abs(sum(w.values()) - 1) < 1e-9
    assert M.combine({"a": 1, "b": 0}, {"a": 0.75, "b": 0.25}) == 0.75


def test_calibrator_falls_back_to_the_pooled_one_with_few_points():
    rng = np.random.default_rng(1); p = rng.uniform(0.2, 0.8, 2000); y = (rng.random(2000) < p).astype(int)
    pooled = M.Calibrator(300).fit(p, y); own = M.Calibrator(300).fit(p[:50], y[:50])
    assert pooled.usable() and not own.usable()
    x = np.array([0.3, 0.7]); assert np.allclose(own.predict(x, fallback=pooled), pooled.predict(x)) and np.allclose(own.predict(x), x)


def test_filtered_stress_probability_rises_in_a_volatile_stretch_and_never_peeks():
    rng = np.random.default_rng(2); r = np.r_[rng.normal(0, 0.006, 700), rng.normal(0, 0.03, 100), rng.normal(0, 0.006, 300)]
    c = pd.Series(100 * np.exp(np.cumsum(r)), index=pd.bdate_range("2015-01-01", periods=len(r)))
    p = M.stress_probability(c); assert p.iloc[720:800].mean() > 0.6 > p.iloc[100:600].mean()
    p2 = M.stress_probability(c.iloc[:760]); assert np.allclose(p.iloc[520:700].values, p2.iloc[520:700].values, atol=1e-9)               # later data does not change earlier probabilities
