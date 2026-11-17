"""B-Lab Sentiment division, step 5 (scripts/blab/sentiment.py), on made-up data. No network, no AI calls, no keys."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from blab import core  # noqa: E402
from blab import sentiment as S  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Pharma stocks slide - Business Standard</title><link>https://news.example/a</link><source>Business Standard</source><pubDate>Mon, 16 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>No link here</title></item>
<item><title>Wall Street rallies</title><link>https://news.example/b</link></item>
</channel></rss>"""


def test_rss_reader_strips_the_source_and_skips_broken_items():
    got = S.parse_rss(RSS, "Feed")
    assert got[0] == {"t": "Pharma stocks slide", "u": "https://news.example/a", "src": "Business Standard", "pub": "2026-11-16T08:00:00Z"}
    assert len(got) == 2 and got[1]["src"] == "Feed" and got[1]["pub"] is None


def test_news_store_keeps_each_headline_once_and_survives_a_dead_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STORE", tmp_path)
    ctx = core.Ctx(now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
    ctx.rss_fetch = lambda url: RSS if "ok" in url else (_ for _ in ()).throw(OSError("down"))
    rows, n, errs = S.collect_news(ctx, [("IN", "Pharma", "A", "http://ok/1"), ("IN", "Pharma", "B", "http://ok/2"), ("IN", "IT", "C", "http://bad")], "n.json")
    assert n == 2 and len(rows) == 2 and errs == ["C: OSError"]


def row(i, region, pub):
    return [f"id{i}", region, "x", f"headline {i}", f"https://n.example/{i}", "src", pub, pub]


def test_pick_caps_us_headlines_and_skips_what_was_read():
    india = [row(i, "IN", f"2026-11-16T0{i % 10}:00:00Z") for i in range(40)]
    us = [row(100 + i, "US", f"2026-11-16T1{i % 10}:00:00Z") for i in range(20)]
    got = S.pick_items(india, us, done={"id1"})
    assert len(got) == 30 and sum(r[1] == "US" for r in got) == 10 and "id1" not in {r[0] for r in got}


def test_only_high_confidence_effects_on_named_indian_companies_and_their_unnamed_neighbours():
    items = [row(1, "IN", "2026-11-16T08:00:00Z"), row(2, "US", "2026-11-16T08:00:00Z"), row(3, "IN", "2026-11-16T08:00:00Z")]
    names = {"power grid": "POWERGRID", "ganesh green": "GGBL", "nvidia": None}
    resolve = lambda n: names.get(n.lower())  # noqa: E731
    graph = {"edges": [{"s": "TARIL", "d": "POWERGRID", "conf": 0.9}, {"s": "POWERGRID", "d": "KEC", "conf": 0.5}, {"s": "POWERGRID", "d": "ANON_X", "conf": 1}]}
    res = [{"i": 1, "event": "capex or expansion", "india_effect": "positive", "confidence": "high", "companies": ["Power Grid"], "why": "investment"},
           {"i": 2, "event": "labor strike", "india_effect": "negative", "confidence": "high", "companies": ["Nvidia"], "why": "us"},
           {"i": 3, "event": "earnings", "india_effect": "positive", "confidence": "medium", "companies": ["Ganesh Green"], "why": "x"}]
    f = S.interpret(res, items, resolve, {"POWERGRID", "TARIL", "KEC", "GGBL"}, graph)
    assert [(x["sym"], x["kind"], x["direction"]) for x in f] == [("POWERGRID", "news: capex or expansion", 1), ("TARIL", "exposed via supply chain", 1), ("KEC", "exposed via supply chain", 1)]
    assert all(x["event"].startswith("ai id1") for x in f)


def test_neighbours_use_the_graph_fields_and_strongest_first():
    g = {"edges": [{"s": "A", "d": "B", "conf": 0.2}, {"s": "C", "d": "A", "conf": 0.9}, {"s": "A", "d": "B", "conf": 0.5}]}
    assert S.neighbours("A", g) == ["C", "B"]


def test_event_study_needs_twelve_months_and_measures_from_monthly_averages():
    idd = [(date(2023, 1, 2) + timedelta(days=i)).isoformat() for i in range(900)]
    idv = [100.0] * len(idd)
    closes, events = {}, []
    for k in range(60):                                                      # 60 events over 24 months, each followed by a +3% drift
        sym, d0 = f"S{k}", idd[10 + k * 13]
        v = [100.0] * len(idd)
        j = idd.index(d0)
        for t in range(j + 2, len(v)):
            v[t] = 103.0
        closes[sym] = (idd, v)
        events.append((sym, d0, "Order win"))
    out = S.event_study(events, closes, (idd, idv))["Order win"]
    assert out["5"]["verdict"] == "measurably above the market" and out["5"]["months"] >= 12 and out["5"]["mean_pct"] == 3.0
    dense = []                                                              # 40 events packed into about 5 months: not enough months
    for k in range(40):
        sym, d0 = f"D{k}", idd[10 + k * 4]
        v = [100.0] * len(idd)
        for t in range(idd.index(d0) + 2, len(v)):
            v[t] = 103.0
        closes[sym] = (idd, v)
        dense.append((sym, d0, "Dense"))
    few = S.event_study(dense, closes, (idd, idv))["Dense"]
    assert few["5"]["n"] == 40 and few["5"]["verdict"].startswith("too few months")


def test_analyst_reports_the_free_limit_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STORE", tmp_path)
    class Budget(Exception):
        pass
    Budget.__name__ = "LLMBudget"
    class Fake:
        model = "fake"
        def complete(self, system, user):
            raise Budget("the free daily quota is used up on every configured model")
    ctx = core.Ctx(now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
    ctx.llm, ctx.resolve = Fake(), (lambda n: None)
    ctx.shared["S3"] = [row(1, "IN", "2026-11-16T08:00:00Z")]
    with pytest.raises(core.Limit):
        S.s6_ai_analyst(ctx)
    r = core.run_bot(core.Bot("S6", "sentiment", "a", "analyst", "d", ["s"], 24, S.s6_ai_analyst), ctx)
    assert r["state"] == "limit" and "free" in r["detail"]


def test_analyst_stores_its_readings_and_files_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STORE", tmp_path)
    class Fake:
        model = "fake-model"
        def complete(self, system, user):
            assert "NOT the other side of a deal" in system and "1. [India] headline 1" in user
            return json.dumps({"items": [{"i": 1, "event": "order or contract win", "india_effect": "positive", "confidence": "high", "companies": ["Acme"], "sectors": ["Power"], "why": "won"}]})
    ctx = core.Ctx(now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
    ctx.llm, ctx.resolve = Fake(), (lambda n: "RELIANCE" if n == "Acme" else None)
    ctx.shared["S3"] = [row(1, "IN", "2026-11-16T08:00:00Z")]
    r = S.s6_ai_analyst(ctx)
    assert [f["sym"] for f in r["findings"]][:1] == ["RELIANCE"] and r["items"] == 1
    st = json.loads((tmp_path / "ai_news.json").read_text())
    assert st["rows"][0]["model"] == "fake-model" and st["rows"][0]["effect"] == "positive"
    r2 = S.s6_ai_analyst(ctx)
    assert r2["items"] == 0                                                   # already read: not sent to the model again
