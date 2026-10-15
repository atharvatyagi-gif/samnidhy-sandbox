"""Black Box tests: no look-ahead (and a deliberately leaky strategy is caught), scenario sanity, costs, metrics on hand-computed cases,
reproducibility, benchmarks, the module wiring and the analysis layer.   pytest -q blackbox/tests"""
import copy

import numpy as np
import pandas as pd
import pytest

from blackbox.analysis import gaps as GA
from blackbox.analysis import recommendations as RE
from blackbox.data import synthetic as SY
from blackbox.engine import costs as CO
from blackbox.engine import metrics as ME
from blackbox.engine import modules as MO
from blackbox.engine import simulator as SIM
from blackbox.scenarios import library as LIB
from blackbox.strategies import REGISTRY
from blackbox.strategies import benchmarks as B
from blackbox.strategies._common import Book, finish, hold_value

CFG = SIM.load_config()


def panel(sid="S09_steady_bull", seed=3):
    return SY.generate(CFG, LIB.by_id(CFG, sid), seed)


def perturbed(p, t0, seed=99):
    """A copy whose every input AFTER day t0 is replaced (prices, volumes, BTC and the other assets, the stand-in scores)."""
    q = copy.deepcopy(p); q.__dict__.pop("_cache", None); rng = np.random.default_rng(seed)
    f = np.exp(rng.normal(0, 0.05, q.c[t0 + 1:].shape))
    for k in ("o", "h", "l", "c"):
        getattr(q, k)[t0 + 1:] *= f
    q.v[t0 + 1:] *= 3.0
    for x in q.extras.values():
        g = np.exp(rng.normal(0, 0.05, len(x["c"]) - t0 - 1))
        for k in ("o", "h", "l", "c"):
            x[k][t0 + 1:] *= g
    for d in (q.zfwd, q.noise):
        for hz in d:
            d[hz][t0 + 1:] = rng.normal(0, 1, d[hz][t0 + 1:].shape)
    return q


def lookahead_violations(fn, params, p, t0):
    """Runs a strategy on the panel and on a copy changed after t0; anything up to t0 that differs is a look-ahead violation."""
    a = fn(p, params, CO.for_panel(CFG, p), p.eval_start); q = perturbed(p, t0); b = fn(q, params, CO.for_panel(CFG, q), q.eval_start)
    k = t0 - p.eval_start + 1; bad = []
    if not np.allclose(a.equity[: k + 1], b.equity[: k + 1], rtol=1e-12, atol=1e-9):
        bad.append("equity up to t0 changed")
    ea = [(t["entry_t"], round(t["capital"], 6)) for t in a.trades if t["entry_t"] <= t0]
    eb = [(t["entry_t"], round(t["capital"], 6)) for t in b.trades if t["entry_t"] <= t0]
    if sorted(ea) != sorted(eb):
        bad.append("entries up to t0 changed")
    return bad


@pytest.mark.parametrize("name", list(REGISTRY))
def test_no_strategy_uses_data_after_the_decision_day(name):
    p = panel(); t0 = p.eval_start + 120
    assert lookahead_violations(REGISTRY[name][0], CFG["strategies"][name]["defaults"], p, t0) == []


def test_a_deliberately_leaky_strategy_is_caught():
    def leaky(p, params, cm, start):                                            # buys today if TOMORROW's close is higher: future data
        bk = Book(1e6, cm); eq = [bk.cash]; g = [0.0]; ex = [0.0]
        for t in range(start, p.T - 1):
            for i in list(bk.pos):
                bk.close(i, p.o[t, i], t, "x")
            up = np.where(p.c[t + 1] > p.c[t])[0][:3]
            for i in up:
                bk.open(int(i), 1, 100, p.o[t, i], t, int(i))
            eq.append(bk.value({i: hold_value(p.c[t], i, q["ref"]) for i, q in bk.pos.items()})); g.append(bk.costs); ex.append(0)
        return finish(bk, eq, g, ex)
    p = panel(); assert lookahead_violations(leaky, {}, p, p.eval_start + 100)


def test_the_crash_produces_its_specified_drawdown_and_dead_flat_is_flat():
    dd, rf, vf = [], [], []
    for s in range(12):
        p = panel("S01_systemic_crash", s); ix = p.index[p.eval_start - 1:]; dd.append((ix / np.maximum.accumulate(ix) - 1).min())
        q = panel("S10_dead_flat", s); jx = q.index[q.eval_start - 1:]; r = np.diff(np.log(jx)); rf.append(r.sum()); vf.append(r.std() * np.sqrt(252))
    assert -0.58 <= np.median(dd) <= -0.33                                         # configured -35% to -50% (plus normal noise)
    assert abs(np.median(rf)) < 0.03 and np.median(vf) < 0.08


def test_scenario_shocks_hit_what_they_name():
    p = panel("S03_war", 1); e = p.eval_start
    assert p.extras["oil"]["c"][e + 100] / p.extras["oil"]["c"][e + 89] - 1 > 0.2 and p.news.max() > 0.9
    q = panel("S11_black_swan_stock", 1); d = q.drawn["black_swan"]; i, t = d["stock"], d["day"]
    assert q.o[t, i] / q.c[t - 1, i] < 0.5                                         # the -60% overnight gap


def test_costs_pay_the_spread_both_ways_rise_in_a_crisis_and_fail_part_of_the_fill():
    p = panel("S01_systemic_crash", 0); cm = CO.for_panel(CFG, p); calm, crisis = p.eval_start + 10, p.eval_start + 70
    assert cm.fill(100, 1, calm, 0) > 100 > cm.fill(100, -1, calm, 0)
    assert cm.slip_bps(crisis, 0) > 2 * cm.slip_bps(calm, 0) and cm.filled_share(crisis) < 1.0 == cm.filled_share(calm)
    assert cm.fee(1e6) == pytest.approx(1e6 * CFG["costs"]["delivery_fee_bps"] / 1e4)
    assert CO.for_panel(CFG, p, cost_mult=2.0).fee(1e6) == pytest.approx(2 * cm.fee(1e6))


def test_metrics_on_hand_computed_cases():
    s = ME.returns_stats(np.array([100.0, 110.0, 99.0, 108.9]))
    cash = ME.returns_stats(100 * (1 + ME.RF_ANN / 252) ** np.arange(253.0)); assert abs(cash["sharpe"]) < 1e-6 and cash["total_ret"] > 0.06   # cash earns no Sharpe
    assert s["total_ret"] == pytest.approx(0.089) and s["max_dd"] == pytest.approx(-0.1) and s["worst_day"] == pytest.approx(-0.1)
    t = ME.trade_stats([{"pnl": 10, "pnl_pct": 0.1, "days": 2}, {"pnl": -5, "pnl_pct": -0.05, "days": 4}, {"pnl": -5, "pnl_pct": -0.05, "days": 3}], 252)
    assert t["win_rate"] == pytest.approx(1 / 3) and t["profit_factor"] == pytest.approx(1.0) and t["payoff"] == pytest.approx(2.0)
    assert t["max_losing_streak"] == 2 and t["avg_hold"] == pytest.approx(3.0) and t["expectancy_pct"] == pytest.approx(0.0)
    lo, hi = ME.bootstrap_ci(np.arange(100.0)); assert lo < 49.5 < hi


def test_the_same_seed_gives_identical_results_and_another_seed_does_not():
    a, b, c = panel(seed=5), panel(seed=5), panel(seed=6)
    assert np.array_equal(a.c, b.c) and not np.array_equal(a.c, c.c)
    r1 = SIM._main_job(CFG, "S08_sideways_chop", 4, False, False)["rows"]; r2 = SIM._main_job(CFG, "S08_sideways_chop", 4, False, False)["rows"]
    assert [round(x["total_ret"], 12) for x in r1] == [round(x["total_ret"], 12) for x in r2]


def test_random_entry_is_about_zero_before_costs_and_negative_after_in_a_flat_market():
    g, n = [], []
    for s in range(15):
        p = panel("S10_dead_flat", s); cm = CO.for_panel(CFG, p)
        r = B.random_entry(p, cm, p.eval_start, 200, 5, 50_000, 1e6, np.random.default_rng(s))
        g.append(r.gross_equity[-1] / 1e6 - 1); n.append(r.equity[-1] / 1e6 - 1)
    assert abs(np.mean(g)) < 0.01 and np.mean(n) < np.mean(g) - 0.005


def test_buy_and_hold_shows_the_large_drawdown_of_the_crash():
    dd = [ME.run_stats(B.buy_hold(p, CO.for_panel(CFG, p), p.eval_start))["max_dd"] for p in (panel("S01_systemic_crash", s) for s in range(8))]
    assert np.median(dd) < -0.30


def test_the_terminal_risk_indicators_are_wired_and_timed():
    p = panel("S03_war", 2); g = MO.geo_lead_lag(p, CFG["news"], np.random.default_rng(0)); f = MO.flow_lead_lag(p, np.random.default_rng(0))
    assert g["geo_wired"] and f["flow_wired"] and g["geo_max"] >= 65 and 0 <= g["geo_false_alarm_rate"] <= 1
    assert MO.event_day(p) == 88 or MO.event_day(p) == 90


def test_gap_analysis_and_recommendations_follow_the_evidence():
    rows = []
    for sc in ("A", "B", "C"):
        rows += [{"strategy": "aladin_v3", "param": "default", "value": "null", "scenario": sc, "sharpe": 0.1, "seed": 0},
                 {"strategy": "aladin_v3", "param": "hold_days", "value": "10", "scenario": sc, "sharpe": 0.6, "seed": 0}]
    G = GA.analyse(pd.DataFrame(rows), CFG)
    r = G.iloc[0]; assert r["best_value"] == "10" and r["verdict"] == "ROBUST" and r["wins"] == 3
    same = GA.analyse(pd.DataFrame([dict(x, sharpe=0.1) for x in rows]), CFG).iloc[0]; assert same["verdict"] == "TERMINAL VALUE OK"
    S = pd.DataFrame([{"strategy": "x", "scenario": s, "severity": 1, "p_beat_random": 0.2, "sharpe": -0.5, "max_dd": -0.5, "final_p5": 0.4, "p_ruin": 0.0,
                       "gross_ret": -0.01, "cost_drag": 0.03, "cost_share_of_gross": np.nan, "turnover": 5.0, "largest_loss": -1.0, "total_ret": -0.1}
                      for s in ("S01_systemic_crash", "S08_sideways_chop", "S10_dead_flat", "S09_steady_bull")])
    R = RE.build(S, G, None, {"gaps": []}, CFG)
    assert set(R["group"]) >= {"a", "b", "c", "e"} and R.iloc[0]["priority"] == "Critical"


def test_real_csvs_become_a_baseline_scenario(tmp_path, monkeypatch):
    from blackbox.data import loader as LD
    rng = np.random.default_rng(0); dates = pd.bdate_range("2023-01-02", periods=520)
    for k in range(55):
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(dates))))
        pd.DataFrame({"date": dates, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6}).to_csv(tmp_path / f"S{k}.csv", index=False)
    monkeypatch.setattr(LD, "REAL", tmp_path)
    assert LD.available()
    p = LD.load(CFG, 0); assert p.N == 55 and p.T == CFG["market"]["warmup_days"] + CFG["market"]["eval_days"] and "REAL" in p.label
    r = REGISTRY["aladin_v3"][0](p, CFG["strategies"]["aladin_v3"]["defaults"], CO.for_panel(CFG, p), p.eval_start); assert len(r.equity) == CFG["market"]["eval_days"] + 1
