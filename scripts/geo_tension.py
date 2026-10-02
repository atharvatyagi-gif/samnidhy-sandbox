"""
Geopolitical NEWS-ATTENTION index for the Globe's map layer. It measures how much, and in what tone, the news is
talking about a region right now compared with that region's own recent normal. It does not measure events.

Source: Google News RSS (no key; reliable from GitHub Actions). The brief's first choice, GDELT's DOC API, answers
HTTP 429 from both GitHub Actions and this PC, so it is not used. Consequences, stated in the output and the UI:
  * Google returns at most 100 items per query, and has no history endpoint. So the baseline is built from this
    script's OWN samples (one per run, kept in data/aladin/geo_history.json for 30 days). Until a region has
    MIN_SAMPLES samples over at least MIN_DAYS distinct days it shows "building baseline" and NO score.
  * Volume = headlines per hour over the last 6 h. When the 100-item cap is hit the rate is estimated from the
    time span those 100 items cover (a lower bound; flagged `capped`).
  * Tone = a transparent word-list score of the headline titles (data/config/tone_words.json), not a language model.

score = round(100 * sigmoid(0.9 * z_vol - 0.6 * z_tone)), z-scores against the 30-day baseline, clipped to +-4.
Levels: <35 Low, 35-50 Guarded, 50-65 Elevated, 65-80 High, >=80 Severe.

  python scripts/geo_tension.py            writes data/aladin/geo.json (skips if it is younger than 55 minutes)
  python scripts/geo_tension.py --force
"""

import argparse
import email.utils
import json
import math
import re
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "data" / "config" / "geo_exposure.json"
TONE = ROOT / "data" / "config" / "tone_words.json"
OUT = ROOT / "data" / "aladin" / "geo.json"
HIST = ROOT / "data" / "aladin" / "geo_history.json"
UA = {"User-Agent": "Mozilla/5.0 (Samnidhy B-Lab geo index; educational; contact via github.com/atharvatyagi-gif)"}
MIN_AGE_S = 55 * 60
MIN_SAMPLES, MIN_DAYS, KEEP_DAYS, GAP_S, CAP = 48, 3, 30, 1.5, 100
LEVELS = [(80, "Severe"), (65, "High"), (50, "Elevated"), (35, "Guarded"), (-1, "Low")]


def level(score):
    return next(name for floor, name in LEVELS if score >= floor)


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def now_utc():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ fetching

def rss_items(query, window, fetch=None):
    """Newest-first list of {title,url,source,seen_utc} for `query when:<window>` (Google caps this at 100), or None on failure."""
    fetch = fetch or _fetch
    raw = fetch(f"{query} when:{window}")
    if raw is None:
        time.sleep(3)                                             # one polite retry: Google answers the odd request with an error page
        raw = fetch(f"{query} when:{window}")
    if raw is None:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    out = []
    for item in root.findall(".//item"):
        title, link, pub = item.findtext("title") or "", item.findtext("link") or "", item.findtext("pubDate") or ""
        src = item.find("source")
        try:
            iso = email.utils.parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            iso = None
        if title and link:
            out.append({"title": title, "url": link, "source": src.text if src is not None else None, "seen_utc": iso})
    out.sort(key=lambda a: a["seen_utc"] or "", reverse=True)
    return out


def _fetch(q):
    try:
        r = requests.get("https://news.google.com/rss/search", params={"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}, headers=UA, timeout=25)
        return r.content if r.status_code == 200 else None
    except requests.RequestException:
        return None


# ------------------------------------------------------------------ measures

def rate_per_hour(items, window_h):
    """Headlines per hour. Below the 100-item cap: count / window. At the cap the true count is unknown, so use the
    time span the 100 newest items cover (a lower bound); returns (rate, capped)."""
    n = len(items)
    if n < CAP:
        return n / window_h, False
    ts = sorted(datetime.fromisoformat(a["seen_utc"]) for a in items if a["seen_utc"])
    span_h = max(0.25, (ts[-1] - ts[0]).total_seconds() / 3600) if len(ts) > 1 else window_h
    return n / min(span_h, window_h), True


def load_tone(path=TONE):
    j = json.loads(Path(path).read_text(encoding="utf-8"))
    return set(j["negative"]), set(j["positive"])


def title_tone(title, neg, pos):
    """(positive - negative) / (positive + negative + 1) over words in the headline (publisher suffix removed)."""
    t = re.sub(r"\s+-\s+[^-]+$", "", title.lower())
    words = re.findall(r"[a-z][a-z\-']+", t)
    bigrams = {" ".join(p) for p in zip(words, words[1:])}
    n = sum(1 for w in words if w in neg) + sum(1 for b in bigrams if b in neg)
    p = sum(1 for w in words if w in pos) + sum(1 for b in bigrams if b in pos)
    return (p - n) / (p + n + 1)


def mean_tone(items, neg, pos):
    return statistics.fmean(title_tone(a["title"], neg, pos) for a in items) if items else None


def _z(x, series, floor_frac, floor_abs):
    mu = statistics.fmean(series)
    sd = statistics.pstdev(series) if len(series) > 1 else 0.0
    return max(-4.0, min(4.0, (x - mu) / max(sd, abs(mu) * floor_frac, floor_abs)))


def baseline_state(samples):
    days = {s["t"][:10] for s in samples}
    return {"n": len(samples), "need": MIN_SAMPLES, "days": len(days), "need_days": MIN_DAYS,
            "ready": len(samples) >= MIN_SAMPLES and len(days) >= MIN_DAYS}


def score_region(rate, tone, samples):
    """samples = this region's PREVIOUS samples (not including the current one). Returns (score|None, z_vol, z_tone, baseline)."""
    b = baseline_state(samples)
    if not b["ready"] or tone is None:
        return None, None, None, b
    zv = _z(rate, [s["r"] for s in samples], 0.25, 0.5)
    tones = [s["tone"] for s in samples if s.get("tone") is not None]
    zt = _z(tone, tones, 0.0, 0.05) if len(tones) >= 2 else 0.0
    return round(100 * sigmoid(0.9 * zv - 0.6 * zt)), round(zv, 2), round(zt, 2), b


def daily_spark(samples, now, days=30):
    """Mean headlines/hour for each of the last `days` calendar days (oldest first); None where there is no sample."""
    by = {}
    for s in samples:
        by.setdefault(s["t"][:10], []).append(s["r"])
    out = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        out.append(round(statistics.fmean(by[d]), 2) if d in by else None)
    return out


# ------------------------------------------------------------------ run

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run(fetch=None, now=None, cfg_path=CFG, hist_path=HIST, out_path=OUT, tone_path=TONE, sleep=time.sleep):
    now = now or now_utc()
    cfg = load_json(cfg_path, {"regions": []})
    neg, pos = load_tone(tone_path)
    hist = load_json(hist_path, {"samples": {}})["samples"]
    prev = {r["id"]: r for r in load_json(out_path, {"regions": []}).get("regions", [])}
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    regions, ok_n = [], 0
    for reg in cfg["regions"]:
        past = [s for s in hist.get(reg["id"], []) if s["t"] >= cutoff]
        items6 = rss_items(reg["news_query"], "6h", fetch)
        sleep(GAP_S)
        items24 = rss_items(reg["news_query"], "1d", fetch)
        sleep(GAP_S)
        base = {"id": reg["id"], "name": reg["name"], "kind": reg["kind"], "lat": reg["lat"], "lon": reg["lon"], "exposure": reg["exposure"]}
        if items6 is None or items24 is None:                     # keep the last good values, flagged stale
            old = prev.get(reg["id"])
            regions.append({**(old or {**base, "score": None, "level": "No data", "spark": [], "heads": [], "baseline": baseline_state(past)}), "stale": True})
            hist[reg["id"]] = past
            continue
        ok_n += 1
        rate, capped = rate_per_hour(items6, 6)
        tone = mean_tone(items24, neg, pos)
        score, zv, zt, b = score_region(rate, tone, past)
        sample = {"t": now.isoformat(timespec="seconds"), "r": round(rate, 3), "tone": None if tone is None else round(tone, 3), "n24": len(items24)}
        hist[reg["id"]] = past + [sample]
        regions.append({**base, "score": score, "level": level(score) if score is not None else "Building baseline", "z_vol": zv, "z_tone": zt,
                        "rate_h": round(rate, 2), "capped": capped, "n24": len(items24), "tone": None if tone is None else round(tone, 3),
                        "baseline": baseline_state(past), "spark": daily_spark(hist[reg["id"]], now), "heads": items24[:5], "stale": False})
    out = {"generated_utc": now.isoformat(timespec="seconds"), "version": 1,
           "method": ("News attention and tone, not events. Google News RSS headlines per hour (last 6 h) and a word-list tone score of headline titles, "
                      "compared with the region's own 30-day history of this index's samples. Needs 48 samples over 3 days before a score appears. "
                      "Google caps results at 100 per query, so very busy regions are a lower bound (flagged). Tone is a crude word count, not a language model."),
           "source": "Google News RSS", "ok_regions": ok_n, "regions": regions}
    return out, hist


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    old = load_json(OUT, {})
    if not a.force and old.get("generated_utc"):
        age = (now_utc() - datetime.fromisoformat(old["generated_utc"])).total_seconds()
        if age < MIN_AGE_S:
            print(f"geo.json is {age / 60:.0f} min old (< 55): skipped")
            return 0
    out, hist = run()
    if out["ok_regions"] == 0:
        print("Google News unreachable for every region; keeping the previous geo.json")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    HIST.write_text(json.dumps({"samples": hist}, separators=(",", ":")), encoding="utf-8")
    ready = sum(1 for r in out["regions"] if r["score"] is not None)
    print(f"geo: {out['ok_regions']}/{len(out['regions'])} regions fetched, {ready} with a score (rest still building a baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
