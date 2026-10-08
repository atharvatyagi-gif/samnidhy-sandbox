import json

import pandas as pd

from scripts.aladin2 import costs as C
from scripts.aladin2 import ledger as LG
from scripts.aladin2 import weekly as W

CFG = C.load_cfg()


def world(n=200):
    """n liquid stocks with a descending 5-day probability, plus a few illiquid ones that must never be ranked."""
    stocks = [{"s": f"S{i:03d}", "n": f"Stock {i}", "board": "Main", "etf": False, "ind": "IT" if i % 2 else "Banks", "avgv20": 1_000_000, "c": 100.0} for i in range(n)]
    stocks += [{"s": "TINY", "n": "Tiny", "board": "Main", "etf": False, "ind": "IT", "avgv20": 1000, "c": 10.0}, {"s": "SME1", "n": "Sme", "board": "SME", "etf": False, "ind": "IT", "avgv20": 9_000_000, "c": 100.0}]
    al = {"as_of": "2026-10-09", "stocks": {s["s"]: {"t": {"p": {"5": round(0.30 + 0.40 * (1 - i / n), 3)}}, "comb": {"5": [0.5, "Low", "1/2"]}} for i, s in enumerate(stocks)}}
    return stocks, al


def test_universe_is_liquid_main_board_only_and_ranks_are_percentiles():
    stocks, al = world(); liq = W.liquid(stocks); assert "TINY" not in liq and "SME1" not in liq and len(liq) == 200            # Rs 1m shares x Rs 100 = Rs 10 crore a day
    R = W.rank_universe(al, liq); assert list(R["sym"][:2]) == ["S000", "S001"] and R["pct"].iloc[0] > 0.99 and R["pct"].iloc[-1] < 0.01 and R["pct"].is_monotonic_decreasing


def test_rule_gives_best_one_percent_bull_and_worst_five_percent_bear_and_exit_is_five_trading_days():
    stocks, al = world(400); book = W.build("2026-10-09", al, stocks, CFG)                                                              # a Friday
    assert book["counts"] == {"bull": 4, "bear": 20, "hold": 376} and [r["sym"] for r in book["bull"]] == ["S000", "S001", "S002", "S003"]
    b = book["bull"][0]; assert b["weekday_validated"] and b["state"] == "Provisional" and b["entry_zone"][0] < b["close"] < b["entry_zone"][1] and b["invalidation"] < b["close"]
    assert "2026-10-19" in b["exit"] and "leave at the open of the 5th trading day" in b["what_to_do"] and b["round_trip_cost_bps"] > 30
    assert all(r["signal"] == "bear" and r["rank_pct"] <= 0.05 for r in book["bear"]) and "Cash shares cannot be shorted" in book["bear"][0]["what_to_do"]
    assert W.business_day("2026-10-09", 6) == "2026-10-19" and W.business_day("2026-10-07", 1) == "2026-10-08"                                # weekends skipped


def test_published_text_uses_neutral_action_words_and_no_banned_word_in_keys_or_values():
    import re
    stocks, al = world(400); book = W.build("2026-10-09", al, stocks, CFG); t = json.dumps(book)
    assert not re.search(r"buy|sell|target|recommend|guaranteed", t, re.I)


def test_midweek_signal_is_marked_as_not_covered_by_the_friday_study():
    stocks, al = world(400); assert W.build("2026-10-07", al, stocks, CFG)["bull"][0]["weekday_validated"] is False


def test_ledger_book_resolution_and_the_live_rule(tmp_path):
    stocks, al = world(400); book = W.build("2026-10-09", al, stocks, CFG)
    wk = W.ledger_record(book, "2026-10-09T10:00:00+00:00"); assert LG.append(wk, tmp_path) == "written" and LG.append(wk, tmp_path) == "duplicate" and LG.has("wk", "2026-10-09", tmp_path, H=5)
    assert W.made_in_time(wk) and not W.made_in_time({**wk, "created": "2026-10-12T04:00:00+00:00"}) and W.made_in_time({**wk, "created": "2026-10-12T03:00:00+00:00"})      # entry open Monday 09:15 IST = 03:45 UTC
    idx = pd.bdate_range("2026-10-01", periods=20)
    def prices(sym):
        o = pd.Series(100.0, index=idx); o.iloc[12:] = 102.0 if sym in ("S000", "S001", "S002", "S003") else 98.0        # entry day = 12 Oct (index 7); exit open 5 days later (index 12) is 102 for bulls, 98 for bears
        return pd.DataFrame({"o": o, "c": o}, index=idx)
    res = W.resolve(wk, prices, CFG, lambda s: 3, 0.004); assert res and res["on"] == "2026-10-19" and all(abs(r[1] - 0.02) < 1e-9 for r in res["buy"]) and all(abs(r[1] + 0.02) < 1e-9 for r in res["sell"]) and res["mkt"] == 0.004
    LG.append(res, tmp_path); rec = W.live_record(tmp_path)
    assert rec["weeks_resolved"] == 1 and rec["bull"]["n"] == 4 and rec["bull"]["share_up"] == 1.0 and rec["bear"]["share_up"] == 0.0 and abs(rec["bull"]["mean_excess_bps"] - 160) < 1e-6
    assert rec["bull"]["mean_excess_net_bps"] < rec["bull"]["mean_excess_bps"] and abs(rec["bear"]["mean_excess_bps"] + 240) < 1e-6
    late = {**wk, "d": "2026-10-02", "created": "2026-10-05T09:00:00+00:00"}; LG.append(late, tmp_path); LG.append({**res, "d": "2026-10-02"}, tmp_path)
    assert W.live_record(tmp_path)["weeks_resolved"] == 1                                                        # a book written after its entry open never counts as live
    assert W.resolve(wk, lambda s: pd.DataFrame({"o": [100.0] * 5}, index=pd.bdate_range("2026-10-08", periods=5)), CFG, lambda s: 3, 0.0) is None          # exit open not in the data yet


def test_the_study_behind_the_rule_is_on_disk_with_the_numbers_the_page_quotes():
    st = W.study(); assert st and st["weeks"] > 600 and st["record"]["sell"]["years_below_market"] == "14/14" and st["record"]["sell"]["gross_excess_bps"] < -50 and st["record"]["sell"]["gross_excess_ci95_bps"][1] < 0
    assert st["record"]["buy"]["net_ci95_bps"][0] > 0 and "four thresholds" in st["thresholds_looked_at"]["note"] and st["scores"]["s_aladin"]["top_decile"]["net_excess_bps"] < 0       # the best 10% does NOT pay; only the best 1%


def test_goal_and_stop_for_every_signal_the_goal_is_the_50_percent_range_edge_and_never_invented():
    stocks, al = world(400)
    fc = {"S000": {"bands5": [98.0, 103.0, 96.0, 105.0, 94.0, 108.0], "bands20": [0] * 6}, "S001": {"bands5": [97.0, 102.0, 95.0, 104.0, 93.0, 107.0], "bands20": [0] * 6}}
    book = W.build("2026-10-09", al, stocks, CFG, forecasts=fc)
    b = book["bull"][0]; assert b["goal"] == 103.0 and "upper edge" in b["goal_basis"] and b["stop"] < b["close"] and b["stop"] == b["invalidation"] and b["reward_risk"] > 0
    assert abs(b["reward_risk"] - (103.0 - b["close"]) / (b["close"] - b["stop"])) < 0.01 and b["evidence"]["range_5d_50pct"] == [98.0, 103.0]
    nb = book["bull"][3]; assert nb["goal"] is None and nb["reward_risk"] is None and "not measured" in nb["goal_basis"] and nb["stop"] < nb["close"]                       # no forecast range for this stock: not measured, the stop still exists
    s = W.build("2026-10-09", al, stocks, CFG, forecasts={"S399": {"bands5": [90.0, 96.0, 88.0, 98.0, 85.0, 101.0], "bands20": [0] * 6}})["bear"][-1]
    assert s["signal"] == "bear" and s["goal"] == 90.0 and "lower edge" in s["goal_basis"] and s["stop"] > s["close"]                                                              # a weak view is wrong when the price closes ABOVE the stop
