"""B-Lab Fundamental division, step 2 (scripts/blab/fundamental.py): the red-flag rules and the NSE stores, on made-up data. No network."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from blab import core  # noqa: E402
from blab import fundamental as F  # noqa: E402

TODAY = date(2026, 11, 16)


def stmt(ni, ocf, debt, rev):
    yrs = ["2026-03-31", "2025-03-31", "2024-03-31"]
    return {"ann": {"inc": {"Net Income": list(zip(yrs, ni)), "Total Revenue": list(zip(yrs, rev))}, "cf": {"Operating Cash Flow": list(zip(yrs, ocf))},
                    "bal": {"Total Debt": list(zip(yrs, debt))}}}


def kinds(fs):
    return sorted(f["kind"] for f in fs)


def test_dates():
    assert F.nse_day("30-SEP-2026") == "2026-09-30" and F.nse_day("14-Nov-2026 23:59:39") == "2026-11-14" and F.nse_day("15-Nov-2026 10:02") == "2026-11-15"
    assert F.nse_day("") is None and F.nse_day("soon") is None


def test_r1_promoter_stake_down_needs_two_points_against_a_year_earlier():
    shp = {"q": [["2026-09-30", 71.97, 28.03, "2026-10-12", "1"], ["2026-06-30", 74.84, 25.1, None, "2"], ["2025-09-30", 73.97, 26.0, None, "3"]]}
    fs = F.flags("ADANIENT", shp, [], [], None, False, TODAY)
    assert kinds(fs) == ["promoter stake down"] and "down 2.00 points" in fs[0]["text"] and fs[0]["direction"] == -1 and fs[0]["event"] == "shp 2026-09-30"
    shp["q"][2][1] = 73.0                                                          # 1.03 points: not enough
    assert F.flags("ADANIENT", shp, [], [], None, False, TODAY) == []
    assert F.flags("X", {"q": [["2026-09-30", 50, 50, None, "1"], ["2026-06-30", 60, 40, None, "2"]]}, [], [], None, False, TODAY) == []   # no quarter a year back


def test_r2_only_a_promoters_own_open_market_sale_in_the_last_30_days():
    row = ["180544", "GALLANTT", "Sale", "2026-11-13", True, "Open Market", 2651975.0, 0.0, "Gallantt Industry Pvt Ltd", "https://x/a.zip"]
    assert kinds(F.flags("GALLANTT", None, [row], [], None, False, TODAY)) == ["promoter selling"]
    for change in ({4: False}, {5: "Inter-se transfer"}, {2: "Acquisition"}, {3: "2026-09-01"}, {1: "OTHER"}):
        r = list(row)
        for i, v in change.items():
            r[i] = v
        assert F.flags("GALLANTT", None, [r], [], None, False, TODAY) == [], change


def test_announcement_rules_and_the_insolvency_refinement():
    ann = [["1", "PGEL", "Resignation of Statutory Auditor", "2026-10-24", "PG Electroplast has informed the Exchange about Resignation of Statutory Auditor", "u1"],
           ["2", "POLYCAB", "Corporate Insolvency Resolution Process", "2026-10-30", "order passed by NCLAT setting aside the order of NCLT", "u2"],
           ["4", "SKIL", "Corporate Insolvency Resolution Process", "2026-11-02", "15th Committee of Creditors Meeting", "u4"],
           ["3", "SKIL", "Corporate Insolvency Resolution Process", "2026-10-27", "postponement of the 14th Committee of Creditors Meeting", "u3"],
           ["5", "DLY", "Reasons for Delayed/Non-submission of Financial Results", "2026-11-14", "delay", "u5"],
           ["6", "OLD", "Resignation of Statutory Auditor", "2026-09-01", "old", "u6"],
           ["7", "HERO", "Credit Rating", "2026-11-01", "Hero MotoCorp Limited has informed the Exchange about Credit Rating", "u7"]]
    got = {s: kinds(F.flags(s, None, [], ann, None, False, TODAY)) for s in ("PGEL", "POLYCAB", "SKIL", "DLY", "OLD", "HERO")}
    assert got == {"PGEL": ["auditor resigned"], "POLYCAB": [], "SKIL": ["insolvency"], "DLY": ["results delayed"], "OLD": [], "HERO": []}
    assert F.flags("SKIL", None, [], ann, None, False, TODAY)[0]["event"] == "ann 3"            # the earliest in the window, once


def test_r8_profit_without_cash_and_r9_debt_jump_skip_financials():
    bad = stmt(ni=[100e7, 80e7, 60e7], ocf=[10e7, 20e7, 30e7], debt=[300e7, 150e7, 140e7], rev=[1000e7, 980e7, 900e7])
    assert kinds(F.flags("X", None, [], [], bad, False, TODAY)) == ["debt jump", "profit without cash"]
    assert F.flags("X", None, [], [], bad, True, TODAY) == []                                       # a bank or NBFC: not applied
    good = stmt(ni=[100e7, 80e7, 60e7], ocf=[120e7, 90e7, 70e7], debt=[160e7, 150e7, 140e7], rev=[1200e7, 980e7, 900e7])
    assert F.flags("X", None, [], [], good, False, TODAY) == []
    small = stmt(ni=[10e7, 8e7, 6e7], ocf=[1e7, 1e7, 1e7], debt=[150e7, 80e7, 70e7], rev=[100e7, 98e7, 90e7])   # debt up only Rs 70 Cr
    assert kinds(F.flags("X", None, [], [], small, False, TODAY)) == ["profit without cash"]
    assert "without wrongdoing" in F.flags("X", None, [], [], small, False, TODAY)[0]["text"]


class FakeNse:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def get_json(self, path, params=None, referer=None, max_tries=2):
        self.calls.append((path, dict(params or {})))
        r = self.answer(path, params)
        if isinstance(r, Exception):
            raise r
        return r


def test_rolling_store_fetches_only_new_days_and_keeps_its_place_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STORE", tmp_path)
    rows = [{"seq_id": 1, "symbol": "A", "desc": "Resignation of Statutory Auditor", "an_dt": "14-Nov-2026 10:00:00", "attchmntText": "t", "attchmntFile": "u"},
            {"seq_id": 2, "symbol": "B", "desc": "Press Release", "an_dt": "14-Nov-2026 11:00:00"}]
    compact = lambda r: [str(r["seq_id"]), r["symbol"], r["desc"], F.nse_day(r["an_dt"]), r.get("attchmntText", ""), r.get("attchmntFile")]  # noqa: E731
    nse = FakeNse(lambda p, q: rows)
    ctx = core.Ctx(now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc)); ctx.nse = nse
    got, to, err = F.collect_range(ctx, "a.json", "/api/corporate-announcements", "p", TODAY, 6, 3, keep=lambda r: r.get("desc") in F.GOV, compact=compact)
    assert [r[0] for r in got] == ["1"] and to == "2026-11-16" and not err and len(nse.calls) == 3     # 6 days in 3-day chunks, deduplicated
    nse.calls.clear()
    F.collect_range(ctx, "a.json", "/api/corporate-announcements", "p", TODAY, 6, 3, keep=lambda r: r.get("desc") in F.GOV, compact=compact)
    assert nse.calls[0][1]["from_date"] == "14-11-2026"                                                # next run: from 2 days before where it stopped
    ctx.nse = FakeNse(lambda p, q: ConnectionError("down"))
    _, to2, err2 = F.collect_range(ctx, "a.json", "/api/corporate-announcements", "p", date(2026, 11, 20), 6, 3, keep=lambda r: True, compact=compact)
    assert err2 and to2 == "2026-11-16"                                                                 # a failure keeps the old place


def test_scouts_run_before_analysts_and_hand_over_their_data():
    order = []

    def scout(c):
        order.append("s"); c.shared["S"] = 5
        return {"items": 1, "as_of": "2026-11-16T10:00:00Z"}

    def analyst(c):
        order.append("a")
        return {"items": c.shared["S"], "as_of": "2026-11-16T10:00:00Z"}

    bots = [core.Bot("F9", "fundamental", "a", "analyst", "d", ["s"], 24, analyst), core.Bot("F8", "fundamental", "s", "scout", "d", ["s"], 24, scout)]
    res = core.run_division(bots, "fundamental", core.Ctx(now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc)))
    assert order == ["s", "a"] and [b["id"] for b in res["bots"]] == ["F9", "F8"] and res["bots"][0]["items"] == 5


def test_a_finding_tied_to_a_filing_counts_once_ever():
    led = []
    f = {"bot": "F5", "division": "fundamental", "sym": "PGEL", "kind": "auditor resigned", "direction": -1, "event": "ann 1", "text": "t"}
    assert core.add_findings(led, [f], date(2026, 11, 16)) == 1
    assert core.add_findings(led, [f], date(2026, 12, 30)) == 0
    assert core.add_findings(led, [{**f, "event": "ann 2"}], date(2026, 12, 30)) == 1
