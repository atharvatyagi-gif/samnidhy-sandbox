import json
import re

import numpy as np

from scripts.aladin2 import costs as C
from scripts.aladin2 import signals as SG

CFG = C.load_cfg()


def test_labels_come_from_one_dictionary_and_neutral_mode_has_no_banned_words():
    neutral = {**CFG, "signal_labels": "neutral"}; direc = {**CFG, "signal_labels": "directional"}
    assert SG.label(neutral, "bull") == "BULLISH SIGNAL" and SG.label(direc, "bull") == "BUY" and SG.label(neutral, "none") == "NO EDGE"
    text = json.dumps(CFG["labels"]["neutral"]) + SG.DIS + " ".join(SG.label(neutral, k) for k in ("bull", "bear", "none", "range", "level", "plan_level"))
    assert not re.search(r"buy|sell|target|recommendation|guaranteed", text, re.I)
    assert SG.DIS == CFG["disclaimer"]


def test_product_state_ladder():
    ev = {"strategies": [], "oos_trades": 0, "live_days": 0}
    assert SG.product_state(ev, CFG)[0] == "Learning"
    ev = {"strategies": ["Probation"], "oos_trades": 80, "live_days": 10, "ece": 0.03, "net_expectancy_bps": 12, "fdr_clean": True}
    s, why = SG.product_state(ev, CFG); assert s == "Provisional" and any("live days" in w for w in why) and any("Active" in w for w in why)
    ev.update(strategies=["Active"], live_days=70); assert SG.product_state(ev, CFG)[0] == "Validated"
    ev["ece"] = 0.08; assert SG.product_state(ev, CFG)[0] == "Provisional"
    ev.update(ece=0.03, suspended=True, suspended_reason="coverage broke"); assert SG.product_state(ev, CFG) == ("Suspended", ["coverage broke"])


def test_abstention_rules():
    assert SG.decide_signal("Learning", 1, 80, 40)[0] == "none" and SG.decide_signal("Provisional", 1, 80, 40)[0] == "none" and SG.decide_signal("Suspended", 1, 80, 40)[0] == "none"
    assert SG.decide_signal("Validated", 1, 30, 40)[0] == "none"                                       # edge inside the cost buffer
    assert SG.decide_signal("Validated", 1, 80, 40, event_imminent=True)[0] == "none"
    assert SG.decide_signal("Validated", 1, 80, 40)[0] == "bull" and SG.decide_signal("Validated", -1, 80, 40)[0] == "bear" and SG.decide_signal("Validated", 0, 80, 40)[0] == "none"


def test_stop_is_the_more_conservative_candidate_inside_the_atr_band():
    close, atr = 100.0, 2.0                                             # band: 95 (2.5 ATR) .. 97 (1.5 ATR)
    assert SG.choose_stop(close, atr, 96.5, 90.0, CFG) == 96.5          # strategy exit is the highest and inside the band
    assert SG.choose_stop(close, atr, None, None, CFG) == 96.0          # default 2.0 ATR
    assert SG.choose_stop(close, atr, 99.0, None, CFG) == 97.0          # too tight: clipped to 1.5 ATR
    assert SG.choose_stop(close, atr, 80.0, 70.0, CFG) == 96.0          # candidates below the vol stop lose to the vol stop
    assert SG.entry_zone(100.0, 2.0, CFG) == [99.5, 100.5]


def test_position_size_fixtures_each_limit_binds_in_turn():
    base = dict(capital=1_000_000, entry=100.0, stop=95.0, cfg=CFG)
    s = SG.position_size(adv_shares=1e9, mu=0.01, sd=0.05, **base)
    assert s["caps"]["risk per trade"] == 2000 and s["caps"]["max position size"] == 1000 and s["qty"] == 1000 and s["binding"] == "max position size"
    s = SG.position_size(adv_shares=10_000, mu=0.01, sd=0.05, **base); assert s["qty"] == 500 and s["binding"] == "liquidity"          # 5% of 10,000 shares
    s = SG.position_size(adv_shares=1e9, mu=0.0002, sd=0.05, **base); assert s["qty"] == 200 and s["binding"].startswith("fractional Kelly")   # 0.0002/0.0025 x 0.25 = 2% of capital
    assert SG.position_size(adv_shares=1e9, mu=-0.001, sd=0.05, **base)["qty"] == 0 and SG.position_size(adv_shares=1e9, mu=None, sd=0.05, **base)["qty"] == 0
    s = SG.position_size(adv_shares=1e9, mu=0.01, sd=0.05, risk_pct=0.2, **base); assert s["qty"] == 400 and s["binding"] == "risk per trade"
    b = SG.position_size(adv_shares=1e9, mu=0.01, sd=0.05, brake=True, **base); assert b["qty"] == 500 and "drawdown brake" in b["binding"]
    assert SG.position_size(adv_shares=1e9, mu=0.01, sd=0.05, entry=100, stop=100, capital=1e6, cfg=CFG)["qty"] == 0


def test_capital_at_risk_is_one_number_everywhere():
    s = SG.position_size(capital=1_000_000, entry=100.0, stop=95.0, adv_shares=1e9, mu=0.01, sd=0.05, cfg=CFG, risk_pct=0.5)
    assert s["capital_at_risk"] == SG.capital_at_risk(100.0, 95.0, s["qty"]) == 5000.0 == s["qty"] * 5.0


def test_portfolio_layer_open_cap_sector_cap_correlation_and_drawdown_brake():
    cand = lambda s, sec, q=1000: {"sym": s, "sector": sec, "entry": 100.0, "stop": 95.0, "qty": q}
    cfg = {**CFG, "risk": {**CFG["risk"], "max_open_signals": 2}}
    acc, rej, _ = SG.portfolio_apply([cand("A", "Banks"), cand("B", "IT"), cand("C", "Auto")], [], 1_000_000, cfg)
    assert [a["sym"] for a in acc] == ["A", "B"] and "open signals" in rej[0]["reason"]
    acc, rej, _ = SG.portfolio_apply([cand("A", "Banks", 2000), cand("B", "Banks", 2000)], [], 1_000_000, CFG)       # sector cap: 30% of 1,000,000 = 3,000 shares at 100
    assert acc[0]["qty"] == 2000 and acc[1]["qty"] == 1000 and "sector" in acc[1]["note"]
    acc, _, _ = SG.portfolio_apply([cand("A", "Banks"), cand("B", "IT")], [], 1_000_000, CFG, corr=lambda a, b: 0.9)
    assert acc[0]["qty"] == 1000 and acc[1]["qty"] == 500 and "correlated" in acc[1]["note"]
    acc, _, sm = SG.portfolio_apply([cand("A", "Banks")], [], 1_000_000, CFG, paper_drawdown_pct=12.0)
    assert acc[0]["qty"] == 500 and sm["drawdown_brake_on"] and sm["worst_case_loss_if_every_stop_hits"] == 500 * 5.0
    held = [{"sym": f"P{i}", "sector": "x", "entry": 100.0, "stop": 95.0, "qty": 1} for i in range(20)]
    acc, rej, _ = SG.portfolio_apply([cand("Z", "Auto")], held, 1_000_000, CFG); assert not acc and "open signals" in rej[0]["reason"]


def test_plan_evaluation_on_deterministic_paths():
    H = 10; up = np.tile(np.linspace(0.0, 0.10, H), (50, 1)); r = SG.evaluate_plan(up, 100.0, 100.0, 95.0, [105.0, 120.0])
    assert r["p_stop"] == 0 and r["levels"][0]["p_touch"] == 1.0 and r["levels"][1]["p_touch"] == 0.0 and r["expected_R"] > 1.0
    down = np.tile(np.linspace(0.0, -0.20, H), (50, 1)); r = SG.evaluate_plan(down, 100.0, 100.0, 95.0, [105.0])
    assert r["p_stop"] == 1.0 and r["expected_R"] < -1.0                                              # exit at the breach close, below the stop: worse than -1 R (gap risk is real)
    flat = np.tile(np.r_[np.zeros(4), np.full(6, -0.0513)], (10, 1)); r2 = SG.evaluate_plan(flat, 100.0, 100.0, 95.0, [105.0])        # closes at 100 then 95.0 (just through the stop 95.0x)
    assert r2["p_stop"] == 1.0 and abs(r2["expected_R"] - (100 * np.exp(-0.0513) - 100) / 5) < 1e-9


def test_paper_book_costs_equity_and_drawdown():
    b = SG.PaperBook(1_000_000, CFG); b.open("A", 100, 1000.0, 950.0, "2026-10-01"); cost_in = float(C.leg_cost("buy", 100_000, "delivery", 5, CFG)["total"])
    assert abs(b.cash - (1_000_000 - 100_000 - cost_in)) < 1e-6
    e1 = b.mark("2026-10-02", {"A": 1100.0}); e2 = b.mark("2026-10-03", {"A": 900.0}); assert e1 > e2 and abs(b.drawdown_pct() - (1 - e2 / e1) * 100) < 1e-9
    pnl = b.close("A", 900.0, "2026-10-04"); assert pnl < -10000 and not b.pos and b.closed[0]["net_pnl"] == pnl
