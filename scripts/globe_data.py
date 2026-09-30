"""
Globe: real-time flights, real geopolitical news and the shipping/oil chokepoints they move through.
-> data/globe/latest.json, published every ~45-60 minutes (not tied to NSE market hours: geopolitics runs
24/7). Two free, no-account sources, used directly, nothing in between:

  OpenSky Network  https://opensky-network.org/apidoc/  - real live ADS-B aircraft positions, a bounding-box
                   query per chokepoint. Anonymous use has a daily request budget, so this script only makes
                   one small bounding-box call per chokepoint (8 calls/run), never a global query.
  GDELT DOC 2.0    https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ - a free global news/event index,
                   updated every 15 minutes, searchable by keyword. GDELT asks for at least ~1 request per
                   several seconds; this script waits GDELT_GAP seconds between every call and retries once
                   on a 429 before giving up on that one query (keeping whatever ran before it).

What this can't do: there is no free, reliable source of real-time cargo-ship positions (AIS data is sold by
MarineTraffic/VesselFinder and similar). So "cargo" here means real news about each chokepoint, not invented
ship icons. Chokepoint "why it matters" lines are widely-cited reference facts (EIA, UNCTAD), not live data,
and are clearly separate from the live flight counts and live news next to them.

If a chokepoint's flights or news can't be fetched this run, that one field is simply left out (not
invented); if nothing at all could be fetched, the previous file is kept untouched.

  python scripts/globe_data.py
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "globe" / "latest.json"
GDELT_GAP = 6          # seconds between GDELT calls (they ask for >= ~5s)
UA = {"User-Agent": "Mozilla/5.0 (Samnidhy B-Lab globe; educational; contact via github.com/atharvatyagi-gif)"}
IST = timezone(timedelta(hours=5, minutes=30))

# id, display name, centre lat/lon, half-width of the OpenSky bounding box (degrees), search keywords for
# GDELT, and a short, widely-cited reference fact (not live data).
CHOKEPOINTS = [
    ("hormuz", "Strait of Hormuz", 26.6, 56.3, 1.3, '"Strait of Hormuz" OR Hormuz',
     "The narrow gap between Iran and Oman that oil tankers from Saudi Arabia, Iraq, the UAE, Kuwait and Qatar sail through — commonly cited as around a fifth of the world's oil consumption."),
    ("bab_el_mandeb", "Bab-el-Mandeb", 12.6, 43.4, 0.8, '"Bab-el-Mandeb" OR "Bab el-Mandeb" OR "Red Sea shipping"',
     "The strait between Yemen and Djibouti linking the Red Sea to the Gulf of Aden; the route to and from the Suez Canal for Asia-Europe trade and Gulf oil."),
    ("suez", "Suez Canal", 30.5, 32.3, 0.7, '"Suez Canal"',
     "Egypt's canal linking the Mediterranean to the Red Sea; commonly cited as carrying over a tenth of world trade by volume."),
    ("malacca", "Strait of Malacca", 2.8, 101.2, 1.5, '"Strait of Malacca" OR "Malacca Strait"',
     "The main sea route between the Indian Ocean and the South China Sea, between Indonesia, Malaysia and Singapore — one of the world's busiest shipping lanes."),
    ("taiwan", "Taiwan Strait", 24.0, 119.5, 1.3, '"Taiwan Strait" OR "Taiwan Strait tension" OR "China Taiwan military"',
     "Separates Taiwan from mainland China; a flashpoint for semiconductor supply chains (Taiwan makes most of the world's advanced chips) and regional security."),
    ("panama", "Panama Canal", 9.1, -79.7, 0.6, '"Panama Canal"',
     "Links the Atlantic and Pacific; a shortcut for trade between Asia and the US East Coast, avoiding the trip around South America."),
    ("bosphorus", "Bosphorus Strait", 41.1, 29.1, 0.5, '"Bosphorus Strait" OR Bosporus',
     "Istanbul's strait linking the Black Sea to the Mediterranean — the route for Russian and other Black Sea oil and grain exports."),
]
GENERAL_QUERY = '(tariff OR sanctions OR "trade war" OR embargo OR "supply chain" OR "oil price" OR OPEC OR pipeline OR "military build" OR "shipping disruption") sourcelang:english'


def flights(lat, lon, half):
    r = requests.get("https://opensky-network.org/api/states/all",
                     params={"lamin": lat - half, "lamax": lat + half, "lomin": lon - half, "lomax": lon + half}, timeout=20)
    r.raise_for_status()
    states = r.json().get("states") or []
    sample = [{"callsign": (s[1] or "").strip(), "lat": s[6], "lon": s[5], "alt_m": s[7], "heading": s[10], "country": s[2]}
             for s in states if s[5] is not None and s[6] is not None][:60]
    return {"count": len(states), "sample": sample}


_last_gdelt = 0.0


def gdelt(query, n=6):
    global _last_gdelt
    wait = GDELT_GAP - (time.time() - _last_gdelt)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(2):
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
                         params={"query": query, "mode": "artlist", "maxrecords": n, "format": "json", "sort": "datedesc"},
                         headers=UA, timeout=25)
        _last_gdelt = time.time()
        if r.status_code == 200:
            try:
                arts = r.json().get("articles", [])
            except ValueError:
                return None
            out = []
            for a in arts:
                sd = a.get("seendate", "")     # GDELT's own format: YYYYMMDDHHMMSSZ (UTC)
                iso = f"{sd[0:4]}-{sd[4:6]}-{sd[6:8]}T{sd[8:10]}:{sd[10:12]}:{sd[12:14]}+00:00" if len(sd) >= 14 else None
                out.append({"title": a.get("title"), "url": a.get("url"), "source": a.get("domain"), "country": a.get("sourcecountry"), "seen_utc": iso})
            return out
        if r.status_code == 429 and attempt == 0:
            time.sleep(20)
            continue
        return None
    return None


def main():
    now = datetime.now(timezone.utc)
    points, errors = [], []
    for cid, name, lat, lon, half, kw, why in CHOKEPOINTS:
        p = {"id": cid, "name": name, "lat": lat, "lon": lon, "why": why}
        try:
            p["flights"] = flights(lat, lon, half)
        except Exception as exc:
            errors.append(f"{name} flights: {type(exc).__name__} {exc}")
        news = gdelt(kw)
        if news is not None:
            p["news"] = news
        else:
            errors.append(f"{name} news: GDELT unavailable")
        points.append(p)
        time.sleep(0.5)

    events = gdelt(GENERAL_QUERY, n=20)
    if events is None:
        errors.append("general events: GDELT unavailable")

    got_anything = any("flights" in p or "news" in p for p in points) or events is not None
    if not got_anything:
        raise RuntimeError("Neither OpenSky nor GDELT returned anything this run: " + "; ".join(errors))

    res = {
        "generated_utc": now.isoformat(timespec="seconds"),
        "generated_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "sources": {"flights": "OpenSky Network (opensky-network.org), free public ADS-B data",
                   "news": "GDELT Project (gdeltproject.org), free global news index, updated every 15 min"},
        "chokepoints": points,
        "events": events or [],
        "partial_errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, allow_nan=False), encoding="utf-8")
    fcount = sum(p.get("flights", {}).get("count", 0) for p in points)
    ncount = sum(len(p.get("news", [])) for p in points)
    print(f"globe: {fcount} live flights across {len(points)} chokepoints, {ncount} chokepoint headlines, {len(events or [])} general headlines"
         + (f"; partial errors: {errors}" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
