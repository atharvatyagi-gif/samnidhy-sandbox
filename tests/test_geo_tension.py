"""Geo news-attention index: measures, baseline gating, stale handling, config checks. No network."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_geo  # noqa: E402
import geo_tension as g  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def items(n, span_h=6, now=NOW):
    return [{"title": f"t{i}", "url": f"u{i}", "source": "s", "seen_utc": (now - timedelta(hours=span_h * i / max(n, 1))).isoformat(timespec="seconds")} for i in range(n)]


def rss(titles_with_age_h, now=NOW):
    body = "".join(f"<item><title>{t}</title><link>http://x/{i}</link><pubDate>{(now - timedelta(hours=a)).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate><source>Src</source></item>" for i, (t, a) in enumerate(titles_with_age_h))
    return f"<rss><channel>{body}</channel></rss>".encode()


def samples(n, per_day=24, rate=5.0, tone=0.0, start=NOW - timedelta(days=10)):
    return [{"t": (start + timedelta(hours=24 / per_day * i)).isoformat(timespec="seconds"), "r": rate + (i % 3) * 0.5, "tone": tone + (i % 2) * 0.02, "n24": 100} for i in range(n)]


def test_levels():
    assert [g.level(s) for s in (0, 34, 35, 49, 50, 64, 65, 79, 80, 100)] == ["Low", "Low", "Guarded", "Guarded", "Elevated", "Elevated", "High", "High", "Severe", "Severe"]


def test_rate_uncapped_and_capped():
    r, cap = g.rate_per_hour(items(12), 6)
    assert (r, cap) == (2.0, False)
    r, cap = g.rate_per_hour(items(100, span_h=3), 6)           # 100 items cover only ~3 h: true rate is at least ~33/h
    assert cap and 30 < r < 40


def test_tone_words_and_publisher_suffix_ignored():
    neg, pos = g.load_tone(ROOT / "data" / "config" / "tone_words.json")
    assert g.title_tone("Missile attack kills dozens - Reuters", neg, pos) < -0.4
    assert g.title_tone("Talks resume, peace deal reached", neg, pos) > 0.4
    assert g.title_tone("Markets open flat today - War News Daily", neg, pos) == 0     # 'war' only in the publisher name
    assert g.title_tone("", neg, pos) == 0


def test_no_score_until_baseline_is_ready():
    few = samples(30, per_day=24)                                # 30 samples over 2 days: not enough on both counts
    s, zv, zt, b = g.score_region(10, 0.0, few)
    assert s is None and not b["ready"] and b["n"] == 30
    enough_samples_one_day = samples(60, per_day=60)             # 60 samples inside one day
    assert g.score_region(10, 0.0, enough_samples_one_day)[0] is None
    s, zv, zt, b = g.score_region(10, 0.0, samples(120, per_day=24))
    assert b["ready"] and s is not None


def test_score_rises_with_volume_and_falls_with_tone():
    base = samples(120, per_day=24, rate=5.0, tone=0.0)
    calm = g.score_region(5.2, 0.0, base)[0]
    busy = g.score_region(30.0, 0.0, base)[0]
    busy_grim = g.score_region(30.0, -0.5, base)[0]
    assert calm < 60 and busy > calm and busy_grim >= busy
    assert 0 <= calm <= 100 and busy_grim <= 100
    assert g.score_region(1.0, 0.0, base)[0] < calm              # quieter than normal -> lower


def test_z_scores_are_clipped_and_flat_history_does_not_explode():
    flat = [{"t": (NOW - timedelta(hours=i * 8)).isoformat(timespec="seconds"), "r": 5.0, "tone": 0.0, "n24": 1} for i in range(120)]
    s, zv, zt, b = g.score_region(500.0, 0.0, flat)
    assert zv == 4.0 and s is not None and s <= 100


def test_spark_has_30_days_with_gaps_as_none():
    sp = g.daily_spark(samples(30, per_day=3, start=NOW - timedelta(days=9)), NOW)
    assert len(sp) == 30 and sp[0] is None and sp[-1] is not None


def run_with(tmp_path, fetch, past=None, prev_geo=None):
    cfg = {"regions": [{"id": "a", "name": "A", "kind": "conflict", "lat": 1, "lon": 2, "news_query": "qa", "exposure": [{"sym": "X", "dir": "+", "why": "w"}]},
                       {"id": "b", "name": "B", "kind": "policy", "lat": 3, "lon": 4, "news_query": "qb", "exposure": [{"ind": "Power", "dir": "-", "why": "w"}]}]}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg))
    (tmp_path / "hist.json").write_text(json.dumps({"samples": past or {}}))
    if prev_geo:
        (tmp_path / "geo.json").write_text(json.dumps(prev_geo))
    return g.run(fetch=fetch, now=NOW, cfg_path=tmp_path / "cfg.json", hist_path=tmp_path / "hist.json", out_path=tmp_path / "geo.json",
                 tone_path=ROOT / "data" / "config" / "tone_words.json", sleep=lambda s: None)


def test_run_builds_contract_and_records_a_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    out, hist = run_with(tmp_path, lambda q: rss([("Missile attack - X", 1), ("Peace talks resume - Y", 2)]))
    assert out["ok_regions"] == 2 and out["source"] == "Google News RSS"
    r = out["regions"][0]
    assert r["score"] is None and r["level"] == "Building baseline" and r["baseline"]["n"] == 0
    assert len(r["heads"]) == 2 and len(r["spark"]) == 30 and r["exposure"][0]["sym"] == "X" and r["stale"] is False
    assert len(hist["a"]) == 1 and hist["a"][0]["n24"] == 2


def test_failed_fetch_keeps_last_good_values_marked_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    prev = {"regions": [{"id": "a", "name": "A", "kind": "conflict", "lat": 1, "lon": 2, "score": 71, "level": "High", "heads": [], "spark": [], "exposure": [], "baseline": {}}]}
    out, hist = run_with(tmp_path, lambda q: None, prev_geo=prev)
    a, b = out["regions"]
    assert a["score"] == 71 and a["stale"] is True                # last good kept, flagged
    assert b["score"] is None and b["level"] == "No data" and b["stale"] is True
    assert out["ok_regions"] == 0


def test_real_config_passes_the_checker():
    if not (ROOT / "data" / "terminal" / "universe.json").exists():
        return
    regions, problems = check_geo.check()
    assert len(regions) == 10 and problems == []


def test_checker_catches_bad_symbols_and_industries(tmp_path):
    cfg = {"regions": [{"id": "r", "lat": 1, "lon": 2, "news_query": "q", "exposure": [
        {"sym": "NOPE", "dir": "+"}, {"ind": "Not An Industry", "dir": "-"}, {"sym": "A", "ind": "Power", "dir": "?"}]}]}
    (tmp_path / "c.json").write_text(json.dumps(cfg))
    (tmp_path / "u.json").write_text(json.dumps({"stocks": [{"s": "A", "ind": "Power"}]}))
    _, problems = check_geo.check(tmp_path / "c.json", tmp_path / "u.json")
    text = " | ".join(problems)
    assert "NOPE" in text and "Not An Industry" in text and "bad dir" in text and "exactly one" in text
