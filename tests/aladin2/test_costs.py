from decimal import Decimal as D

import pytest

from scripts.aladin2 import costs as C

CFG = C.load_cfg()


def test_worked_trade_reproduces_every_line_to_the_paisa():
    # 500 x Rs 800 bought, sold at Rs 830, delivery, liquidity decile 3 (slippage 6 bps per leg)
    t = C.cost_trade("long", "delivery", D(400000), D(415000), 3, CFG)
    e, x = t["entry"], t["exit"]
    assert e == {"brokerage": D("120.00"), "stt": D("400.00"), "exchange": D("14.00"), "sebi": D("4.00"), "gst": D("24.84"), "stamp": D("60.00"), "slippage": D("240.00"), "total": D("862.84")}
    assert x == {"brokerage": D("124.50"), "stt": D("415.00"), "exchange": D("14.53"), "sebi": D("4.15"), "gst": D("25.77"), "stamp": D("0.00"), "slippage": D("249.00"), "total": D("832.95")}
    assert t["total"] == D("1695.79")


def test_delivery_stt_on_both_legs_stamp_on_buy_only():
    b, s = C.leg_cost("buy", 100000, "delivery", 0, CFG), C.leg_cost("sell", 100000, "delivery", 0, CFG)
    assert b["stt"] == s["stt"] == D("100.00")
    assert b["stamp"] == D("15.00") and s["stamp"] == D("0.00")


def test_intraday_stt_on_sell_only_and_cheaper_than_delivery():
    b, s = C.leg_cost("buy", 100000, "intraday", 0, CFG), C.leg_cost("sell", 100000, "intraday", 0, CFG)
    assert b["stt"] == D("0.00") and s["stt"] == D("25.00")
    assert C.round_trip_bps("long", "intraday", 0, CFG) < C.round_trip_bps("long", "delivery", 0, CFG)


def test_gst_is_on_fees_only_not_on_stt_or_stamp():
    p = C.leg_cost("buy", 100000, "delivery", 0, CFG)
    assert p["gst"] == (D("0.18") * (p["brokerage"] + p["exchange"] + p["sebi"])).quantize(D("0.01"))


def test_cash_delivery_cannot_be_shorted():
    with pytest.raises(ValueError):
        C.cost_trade("short", "delivery", 100000, 100000, 0, CFG)
    assert C.cost_trade("short", "futures", 100000, 100000, 0, CFG)["total"] > 0           # futures short is allowed
    assert C.cost_trade("short", "intraday", 100000, 100000, 0, CFG)["total"] > 0


def test_futures_stt_on_sell_leg_only():
    assert C.leg_cost("buy", 100000, "futures", 0, CFG)["stt"] == D("0.00")
    assert C.leg_cost("sell", 100000, "futures", 0, CFG)["stt"] == D("20.00")


def test_slippage_rises_with_illiquidity_and_decile_helper():
    assert C.round_trip_bps("long", "delivery", 9, CFG) > C.round_trip_bps("long", "delivery", 0, CFG)
    universe = list(range(1, 101))
    assert C.adv_decile(100, universe) == 0 and C.adv_decile(1, universe) == 9
