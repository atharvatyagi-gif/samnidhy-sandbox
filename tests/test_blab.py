"""B-Lab research desk (scripts/blab): the framework on made-up bots and prices. No network, no keys (.env is never read)."""
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from blab import core  # noqa: E402
from blab import run as R  # noqa: E402
from blab.bots import BOTS, _s5_scorer  # noqa: E402

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def ctx(files=None):
    c = core.Ctx(now=NOW, fetch=lambda url: (files or {})[url.replace(core.SITE_URL, "")])
    return c


def test_registry_is_mece_and_complete():
    ids = [b.id for b in BOTS]
    assert len(ids) == len(set(ids))
    assert {b.division for b in BOTS} == set(core.DIVISIONS)
    for b in BOTS:
        assert b.id[0] == {"fundamental": "F", "technical": "T", "macro": "M", "sentiment": "S"}[b.division]
        assert b.role in ("scout", "analyst") and b.does and b.sources


def test_states_fresh_stale_error_planned_and_no_key():
    def fresh(c): return {"items": 3, "as_of": "2026-11-16T10:00:00Z"}
    def old(c): return {"items": 3, "as_of": "2026-11-01"}
    def boom(c): raise ValueError("bad file")
    def nodate(c): return {"items": 1}
    def nokey(c): raise core.NoKey("FRED: no key yet")
    bots = [core.Bot("X1", "macro", "a", "scout", "d", ["s"], 24, fresh), core.Bot("X2", "macro", "b", "scout", "d", ["s"], 24, old),
            core.Bot("X3", "macro", "c", "scout", "d", ["s"], 24, boom), core.Bot("X4", "macro", "e", "scout", "d", ["s"], 24, None, 4),
            core.Bot("X5", "macro", "f", "scout", "d", ["s"], 24, nodate), core.Bot("X6", "macro", "g", "scout", "d", ["s"], 24, nokey)]
    got = {b["id"]: b for b in core.run_division(bots, "macro", ctx())["bots"]}
    assert got["X1"]["state"] == "ok" and got["X1"]["age_h"] == 2.0
    assert got["X2"]["state"] == "stale"
    assert got["X3"]["state"] == "error" and "bad file" in got["X3"]["errors"][0]
    assert got["X4"]["state"] == "planned" and "step 4" in got["X4"]["detail"]
    assert got["X5"]["state"] == "error" and "no date" in got["X5"]["detail"]
    assert got["X6"]["state"] == "no_key" and "FRED" in got["X6"]["detail"]
    morning = core.Ctx(now=datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc))               # 09:30 IST, before the 15:30 close
    today = core.run_bot(core.Bot("X7", "macro", "h", "scout", "d", ["s"], 24, lambda c: {"items": 1, "as_of": "2026-11-16"}), morning)
    assert today["age_h"] == 0.0 and today["state"] == "ok"                                  # a date-only "today" is never a negative age


def test_a_division_runs_its_bots_at_the_same_time():
    def slow(c): time.sleep(0.5); return {"items": 1, "as_of": "2026-11-16T11:00:00Z"}
    bots = [core.Bot(f"T{i}", "technical", "s", "scout", "d", ["s"], 24, slow) for i in range(6)]
    t0 = time.perf_counter(); core.run_division(bots, "technical", ctx()); took = time.perf_counter() - t0
    assert took < 1.5, took                                                              # 6 x 0.5 s in sequence would be 3 s


def test_dates_of_every_kind_parse():
    assert core.parse_when("2026-11-13") == datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
    assert core.parse_when("2026-11-15T16:02:24+00:00").hour == 16
    assert core.parse_when("2026-11-15T15:38:41Z").minute == 38
    assert core.parse_when("15 Nov 2026, 09:02 PM IST") == datetime(2026, 11, 15, 15, 32, tzinfo=timezone.utc)
    assert core.parse_when("not a date") is None and core.parse_when(None) is None


def test_the_same_finding_counts_once_a_week():
    led = []
    f = {"bot": "S5", "division": "sentiment", "sym": "IDEA", "kind": "headline tone", "direction": -1, "text": "t"}
    assert core.add_findings(led, [f], date(2026, 11, 10)) == 1
    assert core.add_findings(led, [f], date(2026, 11, 12)) == 0                        # same mood two days later: not new
    assert core.add_findings(led, [{**f, "direction": 1}], date(2026, 11, 12)) == 1     # the lean flipped: new
    assert core.add_findings(led, [f], date(2026, 11, 17)) == 1                         # a week later: new
    assert len({x["id"] for x in led}) == 3


def test_scoring_starts_the_day_after_and_removes_the_market():
    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(80)]
    idx = {d: 100 * (1.01 ** i) for i, d in enumerate(days)}                             # the market rises 1% a day
    up = {d: 50 * (1.01 ** i) * (1.002 ** i) for i, d in enumerate(days)}               # this stock beats it by 0.2% a day
    x, d0 = core.forward(up, idx, days[3], 5)
    assert d0 == days[4]                                                                  # not the day it was seen
    assert abs(x - ((1.002 ** 9 / 1.002 ** 4) * (1.01 ** 9 / 1.01 ** 4) - 1 - (1.01 ** 9 / 1.01 ** 4 - 1))) < 1e-9
    assert core.forward(up, idx, days[-3], 5) is None                                     # not enough days yet
    led = [{"bot": "S5", "sym": f"S{i}", "direction": 1 if i % 2 else -1, "seen": days[i]} for i in range(30)]
    prices = {f"S{i}": up for i in range(30)}
    card = core.scorecard(led, prices, idx)["S5"]
    assert card["directional"] == 30 and card["5"]["n"] == 30 and card["63"]["n"] == 16
    assert card["5"]["right_pct"] == 50.0                                                 # half said up, half down, the stock went up
    assert "too few" in card["63"]["verdict"]


def test_collect_writes_status_and_ledger_and_reports_a_missing_division(tmp_path):
    part = core.run_division([core.Bot("S9", "sentiment", "x", "analyst", "d", ["s"], 24,
                                       lambda c: {"items": 1, "as_of": "2026-11-16T11:00:00Z", "findings": [{"sym": "AAA", "kind": "k", "direction": 1, "text": "t"}]})], "sentiment", ctx())
    doc = R.collect([part], now=NOW, prices=({}, {}), out=tmp_path)
    st = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert st["findings_total"] == 1 and doc["findings_added"] == 1
    assert {d["id"] for d in st["divisions"]} == set(core.DIVISIONS)
    tech = [b for b in st["bots"] if b["division"] == "technical"]
    assert tech and all(b["state"] in ("error", "planned") for b in tech)                 # no report from that job: errors, not gone
    assert any("did not report" in b["detail"] for b in tech)
    assert "not investment advice" in st["note"]


def test_headline_scorer_uses_named_news_only_and_its_declared_rule():
    s = {"generated_utc": "2026-11-16T10:00:00+00:00", "stocks": {
        "AAA": {"items": [["a", "u1", "Mint", 1, -0.6, "name"], ["b", "u2", "ET", 2, -0.4, "name"]], "parts": {"news": -0.5, "flow": 0.9}},
        "BBB": {"items": [["a", "u", "Mint", 1, 0.9, "group"], ["b", "u", "ET", 2, 0.9, "group"]]},          # group news only: no finding
        "CCC": {"items": [["a", "u", "Mint", 1, 0.9, "name"]]},                                              # one headline: no finding
        "DDD": {"items": [["a", "u", "Mint", 1, 0.2, "name"], ["b", "u", "ET", 2, 0.1, "name"]]}}}          # too mild: no finding
    c = core.Ctx(now=NOW)
    c.read = lambda repo_path=None, site_path=None: (s, "x")
    r = _s5_scorer(c)
    assert [(f["sym"], f["direction"]) for f in r["findings"]] == [("AAA", -1)]
    assert r["findings"][0]["evidence"][0]["url"] == "u1"


def test_no_bot_reads_the_env_file():
    for p in (ROOT / "scripts" / "blab").glob("*.py"):              # keys come from the environment (GitHub secrets), never from .env
        assert ".env" not in p.read_text(encoding="utf-8"), p.name
