import pandas as pd
import pytest

from scripts.aladin2 import costs as C
from scripts.aladin2 import ledger as LG
from scripts.aladin2 import paper as P

CFG = C.load_cfg()
CAL = pd.bdate_range("2026-01-05", periods=30)                 # Monday 5 Jan 2026 onwards


def px(rows):
    """rows: {day_index: (o, h, l, c)}; every other day is flat at 100."""
    d = {i: (100.0, 100.5, 99.5, 100.0) for i in range(len(CAL))}; d.update(rows)
    return pd.DataFrame([{"o": v[0], "h": v[1], "l": v[2], "c": v[3], "v": 1e6} for v in (d[i] for i in range(len(CAL)))], index=CAL)


def book(stop=95.0, goal=108.0, adv=1_000_000):
    return {"as_of": str(CAL[1].date()), "picks": [{"sym": "AAA", "rank": 0.995, "stop": stop, "goal": goal, "adv_shares": adv, "decile": 2, "sector": "IT"}]}     # signal day index 1, entry day index 2


def run(prices, exits=("stop", "time"), **kw):
    return P.simulate([book(**kw)], {"AAA": prices}, CAL, CFG, exits=exits)


def test_entry_is_the_next_open_and_the_time_exit_is_the_open_of_the_fifth_day_after():
    r = run(px({2: (101.0, 102.0, 100.0, 101.5), 7: (104.0, 105.0, 103.0, 104.5)}))
    t = r["trades"][0]; assert t["entry"] == 101.0 and t["entry_date"] == str(CAL[2].date()) and t["exit_date"] == str(CAL[7].date()) and t["exit"] == 104.0 and t["reason"] == "time" and t["days"] == 5
    assert t["net"] == pytest.approx(t["gross"] - t["costs"]) and t["costs"] > 0 and t["gross"] == pytest.approx(t["qty"] * 3.0)


def test_a_stop_fills_at_the_stop_inside_the_day_and_at_the_open_when_the_stock_gaps_through_it():
    r = run(px({3: (100.0, 100.5, 94.0, 96.0)})); t = r["trades"][0]; assert t["reason"] == "stop" and t["exit"] == 95.0 and t["exit_date"] == str(CAL[3].date())
    g = run(px({3: (92.0, 93.0, 90.0, 91.0)}))["trades"][0]; assert g["reason"] == "stop" and g["exit"] == 92.0                       # opened under the stop: out at the open, a worse price than the stop


def test_the_target_is_only_an_order_when_the_rules_say_so_and_the_stop_wins_a_day_that_touches_both():
    prices = px({3: (100.0, 109.0, 99.0, 108.0)})
    assert run(prices, exits=("stop", "time"))["trades"][0]["reason"] == "time"                                                      # target is information, not an order
    assert run(prices, exits=("stop", "goal", "time"))["trades"][0]["exit"] == 108.0
    both = px({3: (100.0, 109.0, 94.0, 100.0)}); t = run(both, exits=("stop", "goal", "time"))["trades"][0]; assert t["reason"] == "stop" and t["exit"] == 95.0             # touched both: the cautious reading


def test_size_follows_the_risk_rules_and_cash_never_goes_negative():
    r = run(px({}), stop=95.0); op = r["trades"][0]; eq0 = P.START_CASH
    assert op["qty"] * (op["entry"] - op["stop"]) <= eq0 * 0.0101 and op["qty"] * op["entry"] <= eq0 * 0.1001                       # 1% of equity at risk, at most 10% in one stock
    assert all(row[2] >= 0 for row in r["equity"])
    tiny = run(px({}), adv=10)["skipped"]; assert tiny and "size 0" in tiny[0]["why"]                                                  # 5% of 10 shares is zero shares


def test_a_pick_that_opens_at_or_below_its_stop_is_skipped_and_says_why():
    r = run(px({2: (94.0, 95.0, 93.0, 94.0)})); assert not r["trades"] and r["skipped"][0]["why"] == "opened at or below the stop"


def test_equity_is_cash_plus_open_positions_at_the_close_and_a_trade_in_flight_is_reported():
    r = P.simulate([book()], {"AAA": px({4: (101.0, 103.0, 100.5, 102.0)})}, CAL, CFG, end=str(CAL[4].date()))
    assert r["open"] and r["open"][0]["sym"] == "AAA" and r["open"][0]["last"] == 102.0 and r["open"][0]["days_left"] == 3 and not r["trades"]
    row = r["equity"][-1]; assert row[3] == 1 and row[1] == pytest.approx(row[2] + r["open"][0]["qty"] * 102.0)


def test_live_books_only_count_friday_books_written_before_the_entry_open(tmp_path):
    def wk(d, created, levels=True):
        return {"t": "wk", "d": d, "H": 5, "created": created, "buy": [["AAA", 100.0, 0.995]], "sell": [], "universe": 1000, "weekday_validated": True, **({"levels": {"AAA": [95.0, 108.0, 2.5, 500000]}} if levels else {})}
    for rec in (wk("2026-10-09", "2026-10-10T20:00:00+00:00"), wk("2026-10-16", "2026-10-17T20:00:00+00:00"), wk("2026-10-15", "2026-10-15T20:00:00+00:00"), wk("2026-10-23", "2026-10-26T06:00:00+00:00")):
        LG.append(rec, tmp_path)
    got = P.live_books(tmp_path, CFG); assert [b["as_of"] for b in got] == ["2026-10-09", "2026-10-16"]                              # 10-15 is a Thursday, 10-23 was written after Monday's open
    assert got[0]["picks"][0]["stop"] == 95.0 and got[0]["picks"][0]["goal"] == 108.0


def test_stats_on_a_known_account():
    r = {"equity": [["2026-01-05", 1_000_000, 1_000_000, 0], ["2026-01-06", 1_100_000, 900_000, 1], ["2026-01-07", 990_000, 990_000, 0]], "trades": [{"net": 10000, "ret_pct": 1.0, "costs": 100, "days": 3, "reason": "time"}, {"net": -20000, "ret_pct": -2.0, "costs": 100, "days": 5, "reason": "stop"}]}
    s = P.stats(r); assert s["pnl"] == -10000 and s["max_drawdown_pct"] == -10.0 and s["win_rate"] == 0.5 and s["exits"]["stop"] == 1 and s["profit_factor"] == 0.5 and s["costs_paid"] == 200


def test_published_paper_files_use_no_banned_word_and_state_their_kind():
    import re
    from pathlib import Path
    for f in (P.OUT / "backtest.json", P.OUT / "live.json"):
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8"); assert not re.search(r"(buy|sell|target|recommendation|guaranteed)", txt, re.I), f.name
        assert ("HISTORICAL SIMULATION" in txt) if f.name == "backtest.json" else ("LIVE FRONT TEST" in txt)


def test_live_calendar_does_not_stop_at_a_stale_index_file(monkeypatch):
    stale = pd.Series(1.0, index=pd.bdate_range("2021-10-01", "2021-10-14"))                  # the GitHub runner's NIFTY file stopped here
    fresh = pd.DataFrame({"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0}, index=pd.bdate_range("2026-10-01", "2026-10-16"))
    monkeypatch.setattr(P.L, "load_index", lambda *a, **k: stale)
    monkeypatch.setattr(P.L, "load_prices", lambda s, *a, **k: fresh if s == "RELIANCE" else None)
    cal = P.trading_calendar({}, pd.Timestamp("2026-10-01"))
    assert cal[0] == pd.Timestamp("2026-10-01") and cal[-1] == pd.Timestamp("2026-10-16") and len(cal) == 12
