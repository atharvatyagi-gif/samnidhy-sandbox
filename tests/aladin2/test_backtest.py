import numpy as np
import pandas as pd
import pytest

from scripts.aladin2 import backtest as B
from scripts.aladin2 import costs as C

CFG = C.load_cfg()
ZERO = {**CFG, "costs": {**CFG["costs"], "brokerage_bps": 0, "stt_delivery_bps": 0, "stt_intraday_bps": 0, "exchange_bps": 0, "sebi_bps": 0, "stamp_bps": 0, "stamp_intraday_bps": 0,
                         "slippage_bps_by_adv_decile": [0] * 10, "futures": {"brokerage_bps": 0, "stt_sell_bps": 0, "exchange_bps": 0, "stamp_buy_bps": 0}}}


def bars(opens, closes=None, highs=None, lows=None, vol=1e6):
    n = len(opens); closes = closes if closes is not None else opens
    idx = pd.bdate_range("2024-01-01", periods=n)
    o, c = np.array(opens, float), np.array(closes, float)
    h = np.array(highs, float) if highs is not None else np.maximum(o, c) * 1.001
    l = np.array(lows, float) if lows is not None else np.minimum(o, c) * 0.999
    df = pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "v": np.full(n, vol)}, index=idx)
    df["pc"] = df["c"].shift(); df["locked"] = (df["h"] == df["l"]) & (df["o"] == df["c"])
    return df


def sig(px, *days):
    s = pd.Series(0.0, index=px.index)
    for d in days:
        s.iloc[d] = 1.0
    return s


def test_entry_fills_at_next_open_never_at_the_signal_days_close():
    px = bars([100, 100, 120, 120, 120, 120], closes=[100, 110, 120, 120, 120, 120])
    r = B.run(px, sig(px, 1), {"type": "fixed", "n": 2}, "delivery", 5, ZERO)
    t = r["trades"].iloc[0]
    assert t["entry_px"] == 120 and t["entry_date"] == px.index[2]          # signal at close of day 1 (110) -> open of day 2 (120)
    assert t["signal_date"] == px.index[1]


def test_fixed_exit_arithmetic_and_costs_deducted():
    px = bars([100, 100, 100, 110, 110, 110, 110])
    r = B.run(px, sig(px, 0), {"type": "fixed", "n": 2}, "delivery", 5, ZERO)
    t = r["trades"].iloc[0]; assert t["entry_px"] == 100 and t["exit_px"] == 110 and t["bars"] == 2 and t["net"] == pytest.approx(0.10)
    r2 = B.run(px, sig(px, 0), {"type": "fixed", "n": 2}, "delivery", 5, CFG)
    assert r2["trades"].iloc[0]["net"] == pytest.approx(0.10 - C.round_trip_bps("long", "delivery", 5, CFG) / 1e4, abs=1e-9)


def test_daily_pnl_compounds_to_the_trade_return():
    rng = np.random.default_rng(1); o = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 40))); c = o * np.exp(rng.normal(0, 0.004, 40))
    px = bars(o, c)
    r = B.run(px, sig(px, 3), {"type": "fixed", "n": 15}, "delivery", 5, CFG)
    t = r["trades"].iloc[0]
    assert (1 + r["daily"]).prod() - 1 == pytest.approx(t["net"], abs=3e-4)       # equal up to second-order cost compounding
    assert r["exposure"].sum() == t["bars"] + 1


def test_circuit_locked_entry_day_is_not_filled():
    px = bars([100, 100, 105, 105, 105, 105], closes=[100, 100, 105, 105, 105, 105], highs=[100.1, 100.1, 105, 105.1, 105.1, 105.1], lows=[99.9, 99.9, 105, 104.9, 104.9, 104.9])
    px.iloc[2, px.columns.get_loc("o")] = 105; px["locked"] = (px["h"] == px["l"]) & (px["o"] == px["c"])
    assert px["locked"].iloc[2]                                                    # a 5% one-price day = upper circuit
    r = B.run(px, sig(px, 1), {"type": "fixed", "n": 2}, "delivery", 5, ZERO)
    assert r["trades"].empty


def test_zero_volume_and_oversized_order_are_not_filled():
    px = bars([100] * 6, vol=0.0)
    assert B.run(px, sig(px, 1), {"type": "fixed", "n": 2}, "delivery", 5, ZERO)["trades"].empty
    thin = bars([100] * 6, vol=1000)                                               # Rs 1 lakh order vs Rs 1 lakh of daily value: 100% participation
    assert B.run(thin, sig(thin, 1), {"type": "fixed", "n": 2}, "delivery", 5, ZERO)["trades"].empty


def test_negative_signal_is_never_a_delivery_short_but_is_a_futures_short():
    px = bars([100, 100, 100, 90, 90, 90, 90])
    s = pd.Series(0.0, index=px.index); s.iloc[0] = -1
    assert B.run(px, s, {"type": "fixed", "n": 2}, "delivery", 5, ZERO)["trades"].empty
    t = B.run(px, s, {"type": "fixed", "n": 2}, "futures", 5, ZERO)["trades"].iloc[0]
    assert t["side"] == "short" and t["net"] == pytest.approx(0.10)


def test_flip_exit_waits_for_the_next_open_after_the_signal_turns_off():
    px = bars([100, 100, 101, 102, 103, 104, 105, 106])
    s = pd.Series([1, 1, 1, 0, 0, 0, 0, 0.0], index=px.index)                       # signal turns off at the close of day 3 -> exit at the open of day 4
    t = B.run(px, s, {"type": "flip"}, "delivery", 5, ZERO)["trades"].iloc[0]
    assert t["entry_date"] == px.index[1] and t["exit_date"] == px.index[4] and t["exit_px"] == 103


def test_atr_stop_fills_at_the_stop_or_at_the_gap_open():
    px = bars([100, 100, 100, 100, 100], highs=[101] * 5, lows=[99, 99, 94, 99, 99])
    atr = pd.Series(2.0, index=px.index)
    t = B.run(px, sig(px, 0), {"type": "atr_trail", "mult": 2.5, "atr": atr, "max_n": 10}, "delivery", 5, ZERO)["trades"].iloc[0]
    assert t["reason"] == "stop" and t["exit_px"] == pytest.approx(95.0)           # stop = 100 - 2.5 x 2
    gap = bars([100, 100, 90, 90, 90], highs=[101, 101, 91, 91, 91], lows=[99, 99, 89, 89, 89])
    t2 = B.run(gap, sig(gap, 0), {"type": "atr_trail", "mult": 2.5, "atr": atr, "max_n": 10}, "delivery", 5, ZERO)["trades"].iloc[0]
    assert t2["exit_px"] == 90 and t2["reason"] == "stop"                          # gapped through the stop: fills at the open, worse than the stop


def test_one_position_at_a_time_and_buy_and_hold():
    px = bars(list(np.linspace(100, 130, 30)))
    r = B.run(px, pd.Series(1.0, index=px.index), {"type": "fixed", "n": 5}, "delivery", 5, ZERO)
    T = r["trades"]; assert (T["entry_date"].iloc[1:].values >= T["exit_date"].iloc[:-1].values).all()
    bh = B.buy_and_hold(px, "delivery", 5, ZERO)["trades"]; assert len(bh) == 1 and bh.iloc[0]["reason"] == "open_at_end"
