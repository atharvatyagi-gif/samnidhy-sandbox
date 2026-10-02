"""Paper trader accounting, on fixtures with exact numbers worked out by hand."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import paper_trader as pt  # noqa: E402

CFG = {"threshold": 0.60, "hold_days": 10, "cost_roundtrip": 0.005, "max_open": 10, "notional": 100000, "entry_wait_days": 7}
DATES = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-05", periods=40)]


def bars(opens, closes=None, dates=DATES):
    n = len(opens)
    return {"dates": list(dates[:n]), "o": np.array(opens, float), "c": np.array(closes if closes is not None else opens, float)}


def aladin(stocks, as_of):
    return {"as_of": as_of, "stocks": {s: {"comb": {"10": c}} for s, c in stocks.items()}}


def pf0():
    return pt.empty_portfolio(CFG)


# ---------------------------------------------------------------- signals
def test_signal_rule_is_strict_and_not_loosened():
    a = aladin({"OK": [0.65, "High", "3/3"], "EDGE": [0.60, "High", "3/3"], "MED": [0.65, "Medium", "3/3"], "TWO": [0.70, "High", "2/3"], "LOW": [0.55, "Low", "3/3"], "ETF": [0.9, "High", "3/3"], "SME": [0.9, "High", "3/3"]}, "2026-01-30")
    uni = [{"s": s, "board": "Main", "series": "EQ", "n500": True} for s in ("OK", "EDGE", "MED", "TWO", "LOW")] + [{"s": "ETF", "board": "Main", "series": "EQ", "etf": True, "n500": True},
                                                                                                                       {"s": "SME", "board": "SME", "series": "SM", "n500": True}]
    sigs = pt.new_signals(a, CFG, pt.eligible_symbols(uni))
    assert [s["sym"] for s in sigs] == ["OK"]                                    # 0.60 exactly is not above 0.60; Medium, 2/3, Low, ETF and SME are all out


def test_eligibility_rule():
    uni = [{"s": "N5", "board": "Main", "series": "EQ", "n500": True}, {"s": "LIQ", "board": "Main", "series": "EQ", "avgv20": 1e6, "c": 100},
           {"s": "THIN", "board": "Main", "series": "EQ", "avgv20": 1000, "c": 10}]
    assert pt.eligible_symbols(uni) == {"N5", "LIQ"}


def test_signals_are_ordered_by_probability():
    a = aladin({"A": [0.62, "High", "3/3"], "B": [0.80, "High", "3/3"], "C": [0.70, "High", "3/3"]}, "2026-01-30")
    assert [s["sym"] for s in pt.new_signals(a, CFG)] == ["B", "C", "A"]


# ---------------------------------------------------------------- entry and exit
def test_entry_is_the_next_sessions_open_never_the_signal_close():
    pf = pf0()
    sig_i = 4
    o = [100 + i for i in range(20)]                                             # opens 100, 101, ...
    c = [150 + i for i in range(20)]                                             # closes far from the opens so a wrong price is obvious
    b = bars(o, c)
    pt.add_signals(pf, [{"sym": "X", "signal_date": DATES[sig_i], "p_up": 0.7, "conf": "High", "agree": "3/3"}], CFG)
    pt.open_positions(pf, {"X": b}, CFG)
    pos = pf["open"][0]
    assert pos["entry_date"] == DATES[sig_i + 1] and pos["entry_px"] == o[sig_i + 1] == 105.0 and pos["entry_px"] != c[sig_i]


def test_signal_waits_until_the_entry_bar_exists_then_skips_after_a_week():
    pf = pf0()
    b = bars([100] * 5)                                                          # data ends on the signal day
    pt.add_signals(pf, [{"sym": "X", "signal_date": DATES[4], "p_up": 0.7, "conf": "High", "agree": "3/3"}], CFG)
    pt.open_positions(pf, {"X": b}, CFG, today=pd.Timestamp(DATES[4]).date())
    assert len(pf["pending"]) == 1 and not pf["open"] and not pf["skipped"]
    pt.open_positions(pf, {"X": b}, CFG, today=pd.Timestamp(DATES[4]).date() + pd.Timedelta(days=10))
    assert not pf["pending"] and "no entry bar" in pf["skipped"][0]["reason"]      # logged, not silently dropped


def test_exit_is_the_close_of_the_tenth_trading_day_after_entry_with_costs_and_excess():
    pf = pf0()
    o = [100.0] * 30
    c = [100.0] * 30
    sig_i = 4
    entry_i = sig_i + 1
    o[entry_i] = 100.0
    c[entry_i + 10] = 110.0                                                      # the 10th trading day after entry
    c[entry_i + 9], c[entry_i + 11] = 90.0, 200.0                                # neighbours that would give the wrong answer
    stock = bars(o, c)
    no, nc = [200.0] * 30, [200.0] * 30
    nc[entry_i + 10] = 210.0
    nifty = bars(no, nc)
    pt.add_signals(pf, [{"sym": "X", "signal_date": DATES[sig_i], "p_up": 0.7, "conf": "High", "agree": "3/3"}], CFG)
    pt.open_positions(pf, {"X": stock}, CFG)
    pt.close_due(pf, {"X": stock}, nifty, CFG)
    assert not pf["open"] and len(pf["closed"]) == 1
    t = pf["closed"][0]
    assert t["exit_date"] == DATES[entry_i + 10] and t["exit_px"] == 110.0
    assert t["gross_ret"] == pytest.approx(0.10) and t["net_ret"] == pytest.approx(0.095)      # 10% gross minus 0.5% round trip
    assert t["nifty_ret"] == pytest.approx(0.05) and t["excess"] == pytest.approx(0.045)       # NIFTY: open at entry 200 -> close at exit 210
    assert t["pnl"] == pytest.approx(9500.0)                                                    # 0.095 x Rs 1,00,000


def test_position_stays_open_until_its_tenth_day_bar_exists():
    pf = pf0()
    stock = bars([100.0] * 12)                                                   # entry on index 5, needs index 15
    pt.add_signals(pf, [{"sym": "X", "signal_date": DATES[4], "p_up": 0.7, "conf": "High", "agree": "3/3"}], CFG)
    pt.open_positions(pf, {"X": stock}, CFG)
    pt.close_due(pf, {"X": stock}, None, CFG)
    assert len(pf["open"]) == 1 and not pf["closed"]
    assert pf["open"][0]["due_estimated"] is True


def test_losing_trade_net_return_and_missing_nifty():
    pf = pf0()
    o, c = [100.0] * 30, [100.0] * 30
    c[15] = 95.0
    stock = bars(o, c)
    pt.add_signals(pf, [{"sym": "X", "signal_date": DATES[4], "p_up": 0.7, "conf": "High", "agree": "3/3"}], CFG)
    pt.open_positions(pf, {"X": stock}, CFG)
    pt.close_due(pf, {"X": stock}, None, CFG)
    t = pf["closed"][0]
    assert t["net_ret"] == pytest.approx(-0.055) and t["nifty_ret"] is None and t["excess"] is None


# ---------------------------------------------------------------- portfolio rules
def test_cap_of_ten_open_highest_probability_first_and_the_rest_logged():
    pf = pf0()
    sigs = [{"sym": f"S{i}", "signal_date": DATES[4], "p_up": 0.61 + i / 1000, "conf": "High", "agree": "3/3"} for i in range(13)]
    pt.add_signals(pf, sigs, CFG)
    pt.open_positions(pf, {f"S{i}": bars([100.0] * 20) for i in range(13)}, CFG)
    assert len(pf["open"]) == 10 and {p["sym"] for p in pf["open"]} == {f"S{i}" for i in range(3, 13)}      # the three weakest are the ones left out
    assert len(pf["skipped"]) == 3 and all("portfolio full" in s["reason"] for s in pf["skipped"])


def test_one_position_per_symbol_and_signals_are_not_taken_twice():
    pf = pf0()
    s = {"sym": "X", "signal_date": DATES[4], "p_up": 0.7, "conf": "High", "agree": "3/3"}
    pt.add_signals(pf, [s, s], CFG)
    assert len(pf["pending"]) == 1
    pt.open_positions(pf, {"X": bars([100.0] * 20)}, CFG)
    pt.add_signals(pf, [s], CFG)                                                 # same signal again on a re-run
    pt.add_signals(pf, [{**s, "signal_date": DATES[5]}], CFG)                    # a newer signal for a symbol that is already open
    assert len(pf["open"]) == 1 and not pf["pending"]


def test_run_is_idempotent_and_updates_stats(tmp_path):
    uni = [{"s": "X", "board": "Main", "series": "EQ", "n500": True}]
    a = aladin({"X": [0.7, "High", "3/3"]}, DATES[4])
    o, c = [100.0] * 30, [100.0] * 30
    c[15] = 110.0
    avail = {"n": 12}                                                            # how many sessions of data exist so far
    loader = lambda sym, root=None: {"X": bars(o[:avail["n"]], c[:avail["n"]]), "^NSEI": bars([200.0] * avail["n"], [200.0] * avail["n"])}.get(sym)
    pf = pt.run(a, uni, None, loader, tmp_path, CFG, today=pd.Timestamp(DATES[5]).date())
    assert pf["stats"]["open"] == 1 and pf["meta"]["signals_today"] == 1
    again = pt.run(a, uni, json.loads(json.dumps(pf)), loader, tmp_path, CFG, today=pd.Timestamp(DATES[5]).date())
    assert again["stats"]["open"] == 1 and len(again["open"]) == 1
    avail["n"] = 30                                                              # later the 10th trading day arrives
    later = pt.run(aladin({}, DATES[20]), uni, json.loads(json.dumps(again)), loader, tmp_path, CFG, today=pd.Timestamp(DATES[20]).date())
    s = later["stats"]
    assert s["closed"] == 1 and s["open"] == 0 and s["net_win_rate"] == 1.0 and s["mean_net_ret"] == pytest.approx(0.095) and s["mean_excess"] == pytest.approx(0.095)
    assert later["equity_curve"] == [[DATES[15], 9500.0]] and later["meta"]["caption"].startswith("Simulated. Not real trades.")


# ---------------------------------------------------------------- decile spread
def test_decile_spread_uses_all_matured_predictions_not_only_trades(tmp_path):
    n = 200
    syms = [f"S{i}" for i in range(n)]
    d0 = DATES[2]
    snap = {s: [None, None, None, i / n, None, None] for i, s in enumerate(syms)}          # p10 rises with the index
    (tmp_path / f"{d0}.json").write_text(json.dumps({"hmm": 0.0, "s": snap}))
    bs = {}
    for i, s in enumerate(syms):
        c = [100.0] * 40
        c[12] = 100.0 * (1 + (i - 100) / 1000)                                           # the 10-day return also rises with the index: top decile ~ +8.5%, bottom ~ -9.5%
        bs[s] = bars([100.0] * 40, c)
    r = pt.decile_spread(tmp_path, bs, 10)
    top = np.mean([(i - 100) / 1000 for i in range(180, 200)])
    bot = np.mean([(i - 100) / 1000 for i in range(0, 20)])
    assert r["matured_days"] == 1 and r["top_ret"] == pytest.approx(top, abs=1e-4) and r["bottom_ret"] == pytest.approx(bot, abs=1e-4)
    assert r["spread"] == pytest.approx(top - bot, abs=1e-4) and r["top_hit"] == 1.0 and r["bottom_hit"] == pytest.approx(0.05, abs=0.06)


def test_decile_spread_ignores_unmatured_days_and_says_so(tmp_path):
    syms = [f"S{i}" for i in range(80)]
    (tmp_path / f"{DATES[30]}.json").write_text(json.dumps({"s": {s: [None, None, None, 0.5, None, None] for s in syms}}))
    r = pt.decile_spread(tmp_path, {s: bars([100.0] * 36) for s in syms}, 10)         # the snapshot's 10th day is beyond the data
    assert r["matured_days"] == 0 and "none have yet" in r["note"]
    assert pt.decile_spread(tmp_path / "nothing", {}, 10)["matured_days"] == 0
