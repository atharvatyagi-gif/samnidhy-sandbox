"""Model E (scripts/aladin_e.py): the rules of aladin-audit/SPEC_ALADIN_E.md on synthetic prices, plus the calibration table."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import aladin_e as AE  # noqa: E402

CFG = json.loads((ROOT / "data" / "config" / "aladin_e.json").read_text(encoding="utf-8"))
CAL = json.loads((ROOT / "data" / "config" / "aladin_e_calibration.json").read_text(encoding="utf-8"))


def market(n_stocks=60, days=400, drift=None, seed=0, index_trend=0.0005):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=days)
    frames = {}
    for i in range(n_stocks):
        mu = (drift[i] if drift is not None else 0.0) + 0.0002
        c = 100 * np.exp(np.cumsum(rng.normal(mu, 0.01, days)))
        o = c * (1 + rng.normal(0, 0.002, days))
        frames[f"S{i:02d}"] = pd.DataFrame({"o": o, "c": c, "v": np.full(days, 2_000_000.0)}, index=dates)
    n5 = pd.Series(20000 * np.exp(np.cumsum(np.full(days, index_trend))), index=dates)
    return frames, n5


def cfg(**kw):
    c = dict(CFG)
    c.update({"min_adv_inr": 1e7, "pick_share": 0.1, **kw})
    return c


def test_ranks_use_only_data_up_to_the_signal_day():
    frames, n5 = market()
    asof = n5.index[300]
    T1 = AE.rank_table(frames, asof, cfg())
    for f in frames.values():
        f.loc[f.index > asof, "c"] *= 50                                         # a huge move AFTER the signal day must change nothing
    T2 = AE.rank_table(frames, asof, cfg())
    pd.testing.assert_series_equal(T1["r126"], T2["r126"])


def test_orders_fill_at_the_next_open_never_at_the_signal_close():
    frames, n5 = market(drift=[0.002 if i < 6 else 0 for i in range(60)])
    c = cfg()
    asof = n5.index[300]
    acct, out = AE.run(asof, frames, n5, c, CAL, None)
    assert acct["pending"] and acct["pending"]["created"] == str(asof.date()) and not acct["positions"]
    nxt = n5.index[301]
    acct, out = AE.run(nxt, frames, n5, c, CAL, acct)
    buys = [t for t in acct["trades"] if t["side"] == "enter"]
    assert buys and all(t["date"] == str(nxt.date()) for t in buys)
    t = buys[0]
    assert t["px"] == pytest.approx(round(float(frames[t["sym"]].loc[nxt, "o"]), 2))   # the open of the next session
    assert set(p for p in acct["positions"]) <= set(s for s in out["stocks"] if out["stocks"][s][3] == 1) | set(acct["positions"])


def test_running_twice_on_the_same_evening_changes_nothing():
    frames, n5 = market()
    c = cfg()
    acct, _ = AE.run(n5.index[300], frames, n5, c, CAL, None)
    acct, _ = AE.run(n5.index[301], frames, n5, c, CAL, acct)
    snap = json.dumps(acct, default=str)
    acct2, _ = AE.run(n5.index[301], frames, n5, c, CAL, json.loads(snap))
    assert json.dumps(acct2, default=str) == snap


def test_stale_prices_make_the_model_degraded_with_no_new_orders():
    frames, n5 = market()
    for k in frames:
        frames[k] = frames[k].iloc[:290]                                          # prices stop 10 sessions before the index
    acct, out = AE.run(n5.index[300], frames, n5, cfg(), CAL, None)
    assert out["status"] == "degraded" and out["degraded_reason"] and not acct["pending"] and out["stocks"] == {}


def test_index_below_its_200_day_average_halves_the_invested_share():
    frames, n5 = market(index_trend=-0.0008)
    acct, out = AE.run(n5.index[300], frames, n5, cfg(), CAL, None)
    assert out["risk"]["risk_on"] is False and out["risk"]["invested_share"] == CFG["invested_share_risk_off"]
    frames, n5 = market(index_trend=0.0008)
    acct, out = AE.run(n5.index[300], frames, n5, cfg(), CAL, None)
    assert out["risk"]["risk_on"] is True and out["risk"]["invested_share"] == CFG["invested_share"]


def test_kill_switch_stops_buying_after_the_drawdown_limit():
    frames, n5 = market()
    c = cfg()
    acct, _ = AE.run(n5.index[300], frames, n5, c, CAL, None)
    acct["peak"] = acct["capital"] / (1 - c["kill_drawdown"] - 0.01)            # the account now sits more than 25% below its peak
    acct, out = AE.run(n5.index[301], frames, n5, c, CAL, acct)
    assert out["status"] == "stopped" and out["risk"]["kill"] and out["risk"]["invested_share"] == c["invested_share_risk_off"]


def test_costs_include_stt_stamp_gst_slippage_and_the_dp_charge():
    c = cfg()
    v = 10000.0
    b, s = AE.buy_cost(v, 5e8, c), AE.sell_cost(v, 5e8, c)
    assert b == pytest.approx(v * (0.1 + 0.015) / 100 + v * (0.00297 + 0.0001) / 100 * 1.18 + v * 0.001, rel=1e-6)
    assert s == pytest.approx(v * 0.1 / 100 + v * (0.00297 + 0.0001) / 100 * 1.18 + v * 0.001 + 15.93, rel=1e-6)


def test_position_size_never_above_the_cap():
    assert 0 < AE.position_cap(CAL, CFG) <= CFG["max_position_share"]


def test_calibration_groups_are_ordered_and_cover_every_rank():
    b = CAL["buckets"]
    means = [x["mean_excess_pct"] for x in b]
    assert means == sorted(means, reverse=True)                                  # better rank group, better average result
    assert all(x["mean_excess_ci95_pct"][0] <= x["mean_excess_pct"] <= x["mean_excess_ci95_pct"][1] for x in b)
    for p in (0.0, 0.1, 0.5, 0.85, 0.93, 0.97, 1.0):
        assert AE.bucket(p, CAL) is not None
    assert AE.bucket(0.99, CAL)["label"].startswith("best 5%")


def test_page_file_has_no_price_target_and_states_its_version():
    frames, n5 = market()
    _, out = AE.run(n5.index[300], frames, n5, cfg(), CAL, None)
    text = json.dumps(out, default=str).lower()
    assert out["version"] == CFG["version"] and "target" not in text and out["as_of"] == str(n5.index[300].date())


def test_a_price_jump_beyond_any_price_band_is_treated_as_a_data_error():
    frames, n5 = market(n_stocks=40)
    asof = n5.index[300]
    f = frames["S00"]
    f.loc[f.index[250]:, "c"] *= 3                                               # an unadjusted 1:3 change in the window
    T = AE.rank_table(frames, asof, cfg())
    assert "S00" not in T.index and len(T) == 39


def test_closed_positions_are_judged_against_the_nifty500_over_the_same_days():
    frames, n5 = market(drift=[0.002 if i < 6 else 0 for i in range(60)])
    c = cfg(rebalance_every_sessions=5)
    acct = None
    for k in range(300, 320):
        acct, out = AE.run(n5.index[k], frames, n5, c, CAL, acct)
    sells = [t for t in acct["trades"] if t["side"] == "exit"]
    assert sells and all(t["index_return"] is not None for t in sells)
    h = out["health"]
    assert h["closed_positions"] == len(sells) and 0 <= h["last_20"]["hit_rate"] <= 1
    assert "nifty500" in out["market"] and "breadth" in out["market"]


def test_signals_are_the_paper_accounts_own_orders_and_holdings():
    """Buy/sell signals (owner, 2026-11-13) come from the paper account: the next open's orders, then what it holds, with the price it paid."""
    frames, n5 = market(drift=[0.002 if i < 6 else 0 for i in range(60)])
    c = cfg()
    acct, out = AE.run(n5.index[300], frames, n5, c, CAL, None)
    sg = out["signals"]
    pend = {o["sym"] for o in acct["pending"]["orders"] if o["side"] == "enter"}
    assert {b["sym"] for b in sg["buy"] if b["state"] == "next open"} == pend and not sg["sell"]
    for b in sg["buy"]:
        assert b["ref_price"] == pytest.approx(float(frames[b["sym"]]["c"][frames[b["sym"]].index <= n5.index[300]].iloc[-1]))
        assert b["range"]["low"] < b["ref_price"] * 1.0 < b["range"]["high"] and b["range"]["low"] <= b["range"]["typical"] <= b["range"]["high"]
    acct, out = AE.run(n5.index[301], frames, n5, c, CAL, acct)
    held = {b["sym"]: b for b in out["signals"]["buy"] if b["state"] == "held"}
    assert set(held) == set(acct["positions"])
    for s, b in held.items():
        assert b["ref_price"] == pytest.approx(round(acct["positions"][s]["entry_px"], 2)) and b["shares"] == acct["positions"][s]["shares"]


def test_sell_signals_appear_with_the_rebalance_exits_and_no_stop_price():
    frames, n5 = market(drift=[0.002 if i < 6 else 0 for i in range(60)])
    c = cfg(rebalance_every_sessions=5)
    acct = None
    for k in range(300, 312):
        frames2 = frames
        if k >= 305:                                                       # the early leaders fall back: they leave the best group
            frames2 = {s: (f.assign(c=f["c"] * np.where(f.index >= n5.index[305], 0.6, 1.0), o=f["o"] * np.where(f.index >= n5.index[305], 0.6, 1.0)) if s < "S03" else f) for s, f in frames.items()}
        acct, out = AE.run(n5.index[k], frames2, n5, c, CAL, acct)
        sg = out["signals"]
        exits = [o for o in ((acct.get("pending") or {}).get("orders") or []) if o["side"] == "exit"] if (acct.get("pending") or {}).get("created") == str(n5.index[k].date()) else []
        assert {s["sym"] for s in sg["sell"]} == {o["sym"] for o in exits}
        assert all(s["why"] for s in sg["sell"])
    assert any(t["side"] == "exit" for t in acct["trades"]) and out["signals"]["sold_recently"]
    txt = json.dumps(out["signals"]).lower()
    assert "stop_price" not in txt and "target" not in txt and out["signals"]["stop_loss"].startswith("none")


def test_prices_older_than_the_account_never_change_it():
    frames, n5 = market(drift=[0.002 if i < 6 else 0 for i in range(60)])
    c = cfg()
    acct, _ = AE.run(n5.index[300], frames, n5, c, CAL, None)
    acct, _ = AE.run(n5.index[302], frames, n5, c, CAL, acct)
    snap = json.dumps(acct, default=str)
    acct2, out = AE.run(n5.index[299], frames, n5, c, CAL, json.loads(snap))
    assert json.dumps(acct2, default=str) == snap
    assert {b["sym"] for b in out["signals"]["buy"] if b["state"] == "held"} == set(acct["positions"])


def test_orders_that_cannot_fill_are_logged_for_the_weekly_report():
    frames, n5 = market(drift=[0.002 if i < 6 else 0 for i in range(60)])
    c = cfg()
    asof, nxt = n5.index[300], n5.index[301]
    acct, _ = AE.run(asof, frames, n5, c, CAL, None)
    first = acct["pending"]["orders"][0]["sym"]
    frames[first].loc[nxt, "o"] = float("nan")                                   # no opening price that day
    acct, _ = AE.run(nxt, frames, n5, c, CAL, acct)
    assert acct["not_filled"] == [{"date": str(nxt.date()), "sym": first, "side": "enter", "why": "no opening price that day"}]
    assert first not in acct["positions"]
