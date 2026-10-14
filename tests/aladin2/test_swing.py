import numpy as np
import pandas as pd
import pytest

from scripts.aladin2 import costs as C
from scripts.aladin2 import swing as S

CFG = C.load_cfg()
CAL = pd.bdate_range("2021-01-04", periods=60)


def arrays(rows, trig_long=(), trig_short=(), atr=2.0):
    """rows: {i: (o, h, l, c)}; other days flat at 100. Triggers are set by hand (prep() is tested separately)."""
    d = {i: (100.0, 100.5, 99.5, 100.0) for i in range(len(CAL))}; d.update(rows)
    o, h, l, c = (np.array([d[i][k] for i in range(len(CAL))]) for k in range(4))
    lt = np.zeros(len(CAL), bool); st = np.zeros(len(CAL), bool); lt[list(trig_long)] = True; st[list(trig_short)] = True
    return {"idx": {x: i for i, x in enumerate(CAL)}, "dates": CAL, "o": o, "h": h, "l": l, "c": c, "atr": np.full(len(CAL), atr), "adv_cr": np.full(len(CAL), 500.0),
            "adv_sh": np.full(len(CAL), 5e7), "long": lt, "short": st}


LISTS = {CAL[4]: {"long": ["AAA"], "short": ["ZZZ"]}, CAL[9]: {"long": ["AAA"], "short": ["ZZZ"]}}


def run(prices, short=True):
    return S.simulate(LISTS, prices, CAL, CFG, allow_short=short)


def test_a_trigger_enters_at_the_next_open_and_the_profit_taking_level_closes_it():
    r = run({"AAA": arrays({6: (100.0, 107.0, 99.8, 106.0)}, trig_long=[5])})                 # trigger at day 5's close, entry day 6 open 100, target 100 + 3x2
    t = r["trades"][0]; assert t["side"] == "long" and t["entry_date"] == str(CAL[6].date()) and t["reason"] == "target" and t["exit"] == 106.0 and t["net"] < t["gross"]


def test_the_stop_wins_a_day_that_touches_both_and_a_gap_fills_at_the_open():
    t = run({"AAA": arrays({7: (100.0, 107.0, 96.0, 100.0)}, trig_long=[5])})["trades"][0]; assert t["reason"] == "stop" and t["exit"] == 97.0
    g = run({"AAA": arrays({7: (95.0, 95.5, 94.0, 95.0)}, trig_long=[5])})["trades"][0]; assert g["reason"] == "stop" and g["exit"] == 95.0


def test_a_short_profits_when_the_price_falls_and_the_time_limit_closes_a_quiet_trade():
    t = run({"ZZZ": arrays({7: (100.0, 100.2, 93.0, 94.0)}, trig_short=[5])})["trades"][0]
    assert t["side"] == "short" and t["reason"] == "target" and t["exit"] == 94.0 and t["gross"] > 0
    q = run({"AAA": arrays({}, trig_long=[5])})["trades"][0]; assert q["reason"] == "time" and q["exit_date"] == str(CAL[11].date()) and q["days"] == 5
    assert not run({"ZZZ": arrays({}, trig_short=[5])}, short=False)["trades"]


def test_the_stop_moves_to_the_entry_after_a_good_close_and_then_trails():
    r = run({"AAA": arrays({6: (100.0, 101.0, 99.9, 103.5), 7: (103.5, 104.0, 99.5, 101.0)}, trig_long=[5])})     # +3.5 at the close (> 1.5 ATR), next day dips to 99.5
    t = r["trades"][0]; assert t["reason"] == "stop" and t["exit"] == pytest.approx(100.5)                         # trailed to best close 103.5 - 3 = 100.5, above the entry


def test_size_risks_one_percent_and_respects_the_caps():
    r = run({"AAA": arrays({}, trig_long=[5], atr=0.5)})                                                             # tiny ATR: the 10% per-stock cap binds
    t = r["trades"][0]; assert t["capital"] <= S.P.START_CASH * 0.10 + 1
    r = run({"AAA": arrays({}, trig_long=[5], atr=4.0)}); t = r["trades"][0]
    assert t["qty"] * 1.5 * 4.0 <= S.P.START_CASH * 0.0101


def test_rsi2_and_the_lists_from_the_movers_ranking():
    assert S._rsi2(np.array([10, 11, 12, 13, 14.0]))[-1] > 90
    M = pd.DataFrame({"sym": [f"S{i}" for i in range(20)], "date": pd.Timestamp("2021-01-08"), "exp_move": np.linspace(0.02, -0.02, 20)})
    L = S.lists_from_movers(M, {pd.Timestamp("2021-01-07"): {"S19", "S18"}})[pd.Timestamp("2021-01-08")]
    assert L["long"] == ["S0", "S1"] and L["short"] == ["S19", "S18"]
    early = S.lists_from_movers(M.assign(date=pd.Timestamp("2019-01-04")), {pd.Timestamp("2021-01-07"): {"S19"}})[pd.Timestamp("2019-01-04")]
    assert early["short"] == []                                                                                      # no F&O data before 2020: no shorts
