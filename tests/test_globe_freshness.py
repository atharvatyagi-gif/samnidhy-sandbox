"""The Globe generator's 7-day freshness rule (scripts/globe_data.py)."""
import sys
import xml.etree.ElementTree  # noqa: F401
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import globe_data as g  # noqa: E402

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def iso(days=0, hours=0):
    return (NOW - timedelta(days=days, hours=hours)).isoformat(timespec="seconds")


def test_fresh_window_and_undated_items():
    assert g.fresh(iso(6.9), NOW) and g.fresh(iso(0), NOW)
    assert not g.fresh(iso(7.1), NOW) and not g.fresh(None, NOW) and not g.fresh("garbage", NOW) and not g.fresh("", NOW)
    assert g.fresh("2026-10-01T00:00:00", NOW)                                  # no zone: read as UTC
    assert g.fresh("2026-10-01T00:00:00Z", NOW)
    assert g.MAX_AGE_DAYS == 7


def test_only_fresh_filters_a_list():
    items = [{"t": iso(1)}, {"t": iso(8)}, {"t": None}, {}]
    assert g.only_fresh(items, "t", NOW) == [{"t": iso(1)}]


def test_gdacs_shows_new_events_and_short_ones_that_just_ended_but_not_long_running_ones():
    assert g.gdacs_recent(iso(2).replace("+00:00", ""), None, NOW)                                       # started two days ago
    assert g.gdacs_recent(iso(11), iso(2), NOW)                                                          # a 9-day cyclone that ended two days ago
    assert not g.gdacs_recent(iso(285), iso(0), NOW)                                                     # a drought listed since last winter, "updated" today
    assert not g.gdacs_recent(iso(40), iso(20), NOW)                                                     # ended three weeks ago
    assert not g.gdacs_recent(None, None, NOW)                                                           # undated: not shown


def test_google_news_query_asks_for_the_last_7_days_and_drops_old_items(monkeypatch):
    seen = {}
    rss = "<rss><channel>" + "".join(
        f"<item><title>{t}</title><link>http://x/{i}</link><pubDate>{(datetime.now(timezone.utc) - timedelta(days=d)).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
        for i, (t, d) in enumerate([("new", 0.2), ("recent", 5), ("old", 9), ("older", 40)])) + "</channel></rss>"

    class R:
        status_code, content = 200, rss.encode()

        def raise_for_status(self):
            pass

    def fake_get(url, params=None, **kw):
        seen["q"] = params["q"]
        return R()
    monkeypatch.setattr(g.requests, "get", fake_get)
    out = g.google_news('(tariff OR OPEC) sourcelang:english', 6)
    assert "when:7d" in seen["q"] and "sourcelang" not in seen["q"]                                      # sourcelang is a GDELT operator and breaks Google's search
    assert [a["title"] for a in out] == ["new", "recent"]


def test_published_file_states_the_rule():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "globe_data.py").read_text(encoding="utf-8")
    assert "freshness_rule" in src and "max_age_days" in src
