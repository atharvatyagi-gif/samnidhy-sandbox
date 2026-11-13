"""The Friday report of model E's paper account (scripts/aladin_e_weekly.py), on made-up numbers only."""
import copy
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_e_weekly as W  # noqa: E402

DAYS = pd.to_datetime(["2026-11-06", "2026-11-09", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"])
N5 = pd.Series([100, 100, 101, 102, 101, 102, 103, 104, 103, 105.0], index=DAYS)
CFG7 = {"start": "2026-11-09", "reports": ["2026-11-13", "2026-11-20", "2026-11-27", "2026-12-04"], "verdict_on": "2026-12-04",
        "stop": {"risk_limit_pct": -25.0, "since_start_pct": -13.71}, "fix": {"since_start_pct": -7.21, "max_not_filled": 2},
        "not_filled_before_logging": [], "fixes": []}
RANGES = {"week_5_sessions": {"p01": -7.55, "p05": -4.33, "p25": -1.08, "p50": 0.55, "p75": 2.13, "p95": 5.07},
          "four_weeks_19_sessions": {"p01": -13.71, "p05": -7.21, "p25": -1.6, "p50": 1.71, "p75": 5.08, "p95": 11.56}}
FR = {"AAA": pd.DataFrame({"o": [50.0, 50.0], "c": [51.0, 52.0], "v": [1, 1]}, index=pd.to_datetime(["2026-11-11", "2026-11-13"]))}


def world(v13=101000.0):
    acct = {"capital": 100000, "cash": 30000.0, "costs_paid": 10.0, "kill": None, "peak": 101500.0,
            "positions": {"AAA": {"shares": 1400, "entry_px": 50.0, "entry_date": "2026-11-11", "buy_cost": 10.0}},
            "history": [["2026-11-09", 100000.0, None], ["2026-11-11", 99900.0, 0.7], ["2026-11-12", 101500.0, 0.7], ["2026-11-13", v13, 0.7]],
            "trades": [{"sym": "AAA", "side": "enter", "date": "2026-11-11", "px": 50.0, "shares": 1400, "cost": 10.0, "why": "joined the best 5%"}]}
    last = (v13 - 30000.0) / 1400
    latest = {"as_of": "2026-11-13", "generated_utc": "2026-11-13T13:56:00Z", "status": "running",
              "holdings": [{"sym": "AAA", "shares": 1400, "entry_px": 50.0, "last_close": last}], "paper": {"equity": v13},
              "signals": {"buy": [{"sym": "AAA", "state": "held", "ref_price": 50.0}]},
              "risk": {"risk_on": True, "invested_share": 0.7, "nifty500_close": 101, "nifty500_ma200": 95}, "next_rebalance_in_sessions": 60}
    return acct, latest


def rep(acct, latest, asof="2026-11-13", prev=None, cfg=CFG7):
    return W.build(acct, latest, N5, FR, pd.Timestamp(asof), cfg, RANGES, prev)


def test_rupees_use_indian_grouping():
    assert W.rs(101121.01) == "Rs 1,01,121" and W.rs(999) == "Rs 999" and W.rs(-2500000) == "-Rs 25,00,000"


def test_report_days():
    assert W.due(pd.Timestamp("2026-11-13"), datetime(2026, 11, 13, 19, 30))
    assert not W.due(pd.Timestamp("2026-11-12"), datetime(2026, 11, 12, 19, 30))
    assert W.due(pd.Timestamp("2026-11-12"), datetime(2026, 11, 13, 19, 30))       # Friday a holiday: Thursday's session, reported on Friday
    assert not W.due(pd.Timestamp("2026-11-12"), datetime(2026, 11, 16, 19, 30))   # next week: too late, not a new report


def test_week_one_numbers_and_all_checks_ok():
    r = rep(*world())
    assert r["week"] == 1 and r["since"] == "2026-11-09" and r["sessions_in_week"] == 3
    assert r["account"]["week_pct"] == 1.0 and r["account"]["since_start_pct"] == 1.0
    assert r["account"]["from_peak_pct"] == round((101000 / 101500 - 1) * 100, 2)
    assert r["nifty500"]["week_pct"] == 1.0
    assert "3 sessions" in r["backtest"]["week_band"]                               # a short week is not compared with 5-session spans
    assert all(c["ok"] for c in r["checks"]), r["checks"]
    assert r["rules"]["verdict"] == "Continue" and not r["rules"]["final"] and r["rules"]["label"] == "So far, by the rules"


def test_second_week_runs_from_the_last_report():
    acct, latest = world()
    acct["history"] += [["2026-11-16", 101000.0, 0.7], ["2026-11-17", 101000.0, 0.7], ["2026-11-18", 101000.0, 0.7], ["2026-11-19", 101000.0, 0.7], ["2026-11-20", 102010.0, 0.7]]
    latest = {**latest, "as_of": "2026-11-20", "generated_utc": "2026-11-20T13:56:00Z", "paper": {"equity": 102010.0},
              "holdings": [{**latest["holdings"][0], "last_close": (102010.0 - 30000) / 1400}]}
    r = rep(acct, latest, "2026-11-20", "2026-11-13")
    assert r["week"] == 2 and r["sessions_in_week"] == 5 and r["account"]["week_pct"] == 1.0
    assert r["backtest"]["week_band"] == "in the middle half of back-test spans"


def test_missing_day_and_early_run_are_fix():
    acct, latest = world()
    del acct["history"][2]
    latest["generated_utc"] = "2026-11-13T06:27:00Z"
    r = rep(acct, latest)
    assert r["rules"]["verdict"] == "Fix" and len(r["rules"]["fix"]) == 2 and any("2026-11-12" in x for x in r["rules"]["fix"])


def test_bookkeeping_errors_are_stop():
    acct, latest = world()
    latest["paper"]["equity"] += 50                                                  # value does not add up
    assert any("reported value" in x for x in rep(acct, latest)["rules"]["stop"])
    acct, latest = world()
    acct["trades"][0]["px"] = 51.0                                                    # not at the open
    assert any("opening price" in x for x in rep(acct, latest)["rules"]["stop"])
    acct, latest = world()
    latest["signals"]["buy"][0]["ref_price"] = 49.0                                   # signals disagree with the account
    assert rep(acct, latest)["rules"]["verdict"] == "Stop"


def test_return_lines():
    assert rep(*world(91000.0))["rules"]["verdict"] == "Fix"                        # -9%: weak, inside the range
    r = rep(*world(85000.0))                                                           # -15%: outside the back-test
    assert r["rules"]["verdict"] == "Stop" and any(x.startswith("S2") for x in r["rules"]["stop"]) and not any(x.startswith("F2") for x in r["rules"]["fix"])
    acct, latest = world()
    acct["kill"] = {"since": "2026-11-13", "reason": "x"}
    assert any(x.startswith("S1") for x in rep(acct, latest)["rules"]["stop"])


def test_not_filled_orders():
    acct, latest = world()
    cfg = copy.deepcopy(CFG7)
    cfg["not_filled_before_logging"] = [{"date": "2026-11-11", "sym": "BBB", "side": "enter", "why": "x"}]
    acct["not_filled"] = [{"date": "2026-11-12", "sym": "CCC", "side": "enter", "why": "x"}]
    assert rep(acct, latest, cfg=cfg)["rules"]["verdict"] == "Continue"              # 2 is allowed
    acct["not_filled"].append({"date": "2026-11-13", "sym": "DDD", "side": "enter", "why": "x"})
    assert rep(acct, latest, cfg=cfg)["rules"]["verdict"] == "Fix"


def test_final_verdict_only_on_the_last_report():
    acct, latest = world()
    cfg = {**CFG7, "verdict_on": "2026-11-13"}
    assert rep(acct, latest, prev="2026-11-06", cfg=cfg)["rules"]["final"]
    assert rep(acct, latest, prev="2026-11-06", cfg=cfg)["rules"]["label"] == "Phase 7 verdict"
    assert not rep(acct, latest, prev=None, cfg=cfg)["rules"]["final"]


def test_markdown_is_plain_and_honest():
    md = W.markdown(rep(*world()))
    assert "week 1" in md and "Rs 1,01,000" in md and "+1.00%" in md and "not investment advice" in md
    assert "So far, by the rules: **Continue**" in md and "PHASE7_RULES.md" in md
    assert not re.search(r"\b(target|recommendation|guaranteed)\b", md, re.I)
