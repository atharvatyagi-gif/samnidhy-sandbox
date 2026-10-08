"""Phase 7 stress tests: gap shocks, circuit-limit and suspension stretches, bad data, a crash year. The engine must stay arithmetically consistent and must fail safe (stand aside, suspend), never crash or invent."""
import json

import numpy as np
import pandas as pd
import pytest

from scripts.aladin2 import backtest as B
from scripts.aladin2 import costs as C
from scripts.aladin2 import data_lake as L
from scripts.aladin2 import forecast as FC
from scripts.aladin2 import kill as K
from scripts.aladin2 import signals as SG
from scripts.aladin2 import synthetic as S
from scripts.aladin2.strategies import base, registry as R

CFG = C.load_cfg()
ZERO = json.loads(json.dumps(CFG)); ZERO["costs"].update({k: 0 for k in ("brokerage_bps", "stt_delivery_bps", "stt_intraday_bps", "exchange_bps", "sebi_bps", "stamp_bps", "stamp_intraday_bps")}); ZERO["costs"]["slippage_bps_by_adv_decile"] = [0] * 10


def bars(o, c=None, h=None, l=None, v=1e6):
    n = len(o); idx = pd.bdate_range("2024-01-01", periods=n); o = np.array(o, float); c = o if c is None else np.array(c, float)
    df = pd.DataFrame({"o": o, "h": np.maximum(o, c) * 1.001 if h is None else h, "l": np.minimum(o, c) * 0.999 if l is None else l, "c": c, "v": np.full(n, v) if np.isscalar(v) else v}, index=idx)
    df["pc"] = df["c"].shift(); df["locked"] = (df["h"] == df["l"]) & (df["o"] == df["c"]); return df


def sig(px, *days):
    s = pd.Series(0.0, index=px.index)
    for d in days:
        s.iloc[d] = 1.0
    return s


def test_overnight_crash_gaps_through_the_stop_and_the_loss_is_accounted_exactly():
    o = [100] * 6 + [75] * 6                                                      # a 25% overnight gap on day 6 (2008 style)
    px = bars(o, h=[100.1] * 6 + [75.1] * 6, l=[99.9] * 6 + [74.9] * 6)
    r = B.run(px, sig(px, 0), {"type": "atr_trail", "mult": 2.5, "atr": pd.Series(2.0, index=px.index), "max_n": 20}, "delivery", 5, ZERO)
    t = r["trades"].iloc[0]
    assert t["reason"] == "stop" and t["exit_px"] == 75 and t["gross"] == pytest.approx(-0.25)                  # filled at the gap open, not at the stop 95
    assert abs(t["net"]) > 0.05 * 2.5 / 5 * 100 / 100 and (1 + r["daily"]).prod() - 1 == pytest.approx(t["net"], abs=1e-9)


def test_crash_then_paper_drawdown_brake_halves_new_sizes():
    b = SG.PaperBook(1_000_000, CFG); b.open("A", 5000, 100.0, 95.0, "2026-01-01"); b.mark("2026-01-02", {"A": 100.0}); b.mark("2026-01-03", {"A": 75.0})
    assert b.drawdown_pct() > CFG["risk"]["drawdown_brake_pct"]
    acc, _, sm = SG.portfolio_apply([{"sym": "B", "sector": "IT", "entry": 100.0, "stop": 95.0, "qty": 1000}], list(b.pos.values()) and [{"sym": "A", "sector": "Banks", "entry": 100.0, "stop": 95.0, "qty": 5000}], 1_000_000, CFG, paper_drawdown_pct=b.drawdown_pct())
    assert sm["drawdown_brake_on"] and acc[0]["qty"] == 500


def test_circuit_locked_days_delay_the_exit_to_the_next_fillable_open_and_never_fill_inside_the_lock():
    o = [100, 100, 100, 100, 90, 90, 90, 92, 93, 94]
    px = bars(o, c=[100, 100, 100, 100, 90, 90, 90, 92, 93, 94], h=[100.1, 100.1, 100.1, 100.1, 90, 90, 90, 92.1, 93.1, 94.1], l=[99.9, 99.9, 99.9, 99.9, 90, 90, 90, 91.9, 92.9, 93.9])
    px["pc"] = px["c"].shift(); px["locked"] = (px["h"] == px["l"]) & (px["o"] == px["c"]); assert px["locked"].iloc[4:7].all()               # lower circuit: three one-price days
    t = B.run(px, sig(px, 0), {"type": "fixed", "n": 4}, "delivery", 5, ZERO)["trades"].iloc[0]
    assert t["exit_date"] == px.index[7] and t["exit_px"] == 92 and t["bars"] == 6                                       # due on day 5, locked until day 7: the exit waits, and fills at that open


def test_suspension_with_no_volume_blocks_both_entry_and_exit():
    v = np.r_[np.full(3, 1e6), np.zeros(5), np.full(6, 1e6)]
    px = bars([100] * 14, v=v)
    assert B.run(px, sig(px, 3), {"type": "fixed", "n": 3}, "delivery", 5, ZERO)["trades"].empty                         # the entry day (day 4) is in the zero-volume stretch
    t = B.run(px, sig(px, 0), {"type": "fixed", "n": 3}, "delivery", 5, ZERO)["trades"].iloc[0]
    assert t["entry_date"] == px.index[1] and t["exit_date"] == px.index[8]                                                # exit due on day 4 waits for volume to return on day 8


def test_bad_data_never_crashes_features_or_strategies_and_signals_stay_binary():
    px = S.make("noise", n=700, seed=9)[["o", "h", "l", "c", "v"]].copy()
    px.iloc[300, :4] = np.nan; px.iloc[301:306, 4] = 0.0; px.iloc[400, :4] = px.iloc[400, :4] * 6                              # missing bar, no-volume stretch, a wild print
    p = L.clean_prices(px.dropna()); F = L.price_features(p); ctx = base.make_ctx(p, F, None, None)
    for s in R.all_strategies():
        out = s.signal(ctx); assert set(out.unique()) <= {0.0, 1.0} and not out.isna().any()


def test_flat_and_zero_range_bars_give_finite_volatility_inputs():
    px = pd.DataFrame({"o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1e6}, index=pd.bdate_range("2024-01-01", periods=300))
    g = FC.gk_var(px); assert (g == FC.FLOOR).all() and np.isfinite(FC.har_terms(g).dropna().values).all()


def test_a_crash_year_that_breaks_range_coverage_suspends_the_engine_and_hides_signals():
    live = {"n": 5000, "ece": 0.02, "coverage": {"50": 0.46, "80": 0.7049, "95": 0.90}, "n_cov": 5000}                          # the 2020 numbers of the historical simulation at 20 days
    s, why = K.check(live, CFG); assert s and any("80%" in w for w in why)
    out, banners = K.apply({"A": {"sector": "IT"}}, {}, {}, live, CFG)
    assert out["A"][0] == "Suspended" and banners[0]["scope"] == "engine"
    ev = {"strategies": ["Active"], "oos_trades": 90, "live_days": 80, "ece": 0.03, "net_expectancy_bps": 20, "fdr_clean": True, "suspended": True, "suspended_reason": out["A"][1][0]}
    assert SG.decide_signal(SG.product_state(ev, CFG)[0], 1, 80, 40)[0] == "none"


def test_extreme_volatility_regime_keeps_the_forecast_machinery_finite():
    d = S.make("noise", n=1500, seed=3, vol_ann=1.6); px = L.clean_prices(d[["o", "h", "l", "c", "v"]]); gk = FC.gk_var(px); T = FC.har_terms(gk)
    assert np.isfinite(T.dropna().values).all()
    res = FC.standardise(np.random.default_rng(0).standard_t(3, 5000)); p = FC.simulate_paths(0.08, 0.05, 20, 500, res, np.random.default_rng(1))
    assert np.isfinite(p).all() and p.shape == (500, 20)
