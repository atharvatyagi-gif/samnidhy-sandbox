"""
Globe: real-time flights, real shipping traffic, real hazards, and real geopolitical news around the world's
shipping/oil chokepoints. -> data/globe/latest.json, published every ~45-60 minutes (not tied to NSE market
hours: geopolitics runs 24/7). Free, no-account sources, used directly, nothing in between:

  OpenSky Network    https://opensky-network.org/apidoc/  - real live ADS-B aircraft positions, a bounding-box
                     query per chokepoint. Anonymous use has a daily request budget, so this script only makes
                     one small bounding-box call per chokepoint (8 calls/run), never a global query.
  IMF PortWatch      https://portwatch.imf.org (ArcGIS FeatureServer, no key) - REAL daily vessel-transit
                     counts by type (tanker/container/dry-bulk/general-cargo/RoRo) for each chokepoint, and
                     real active disruption events (storms/quakes/conflict) with their port impact. This is
                     real cargo-ship *traffic data*, not invented ship icons - PortWatch itself lags a few
                     days (it's not live AIS), and that lag is shown on screen, never hidden.
  USGS / NASA EONET / GDACS   Real earthquakes (M4.5+, 7 days), natural-hazard events (storms, wildfires,
                     volcanoes, floods - last 7 days only, EONET's own `days` filter, not a client-side guess)
                     and disaster alerts (Green/Orange/Red), all free, no key.
  Google News RSS    Primary source for chokepoint/world news. GDELT DOC 2.0 (below) is attempted as a bonus
                     only when Google News comes up short - confirmed via a real GitHub Actions run (not just
                     claimed) that GDELT returns 429 from Actions' runner IPs, so it is no longer load-bearing.
  GDELT DOC 2.0      https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ - kept as an opportunistic extra
                     only (see above). Paced at GDELT_GAP seconds between calls, one retry on 429.

What this can't do: there is no free, reliable source of real-time (second-by-second) cargo-ship positions
(AIS data is sold by MarineTraffic/VesselFinder and similar) - PortWatch's daily counts are the real, free
alternative, clearly labelled with their own as-of date. Nor does OpenSky's anonymous tier give a flight's
route (origin/destination airport) - its /flights/aircraft endpoint returns 403 "You cannot access historical
flights" without a registered account, so that field is left out rather than guessed. Chokepoint "why it
matters" lines are widely-cited reference facts (EIA, UNCTAD), not live data.

If any one field can't be fetched this run, that field is simply left out (not invented); if nothing at all
could be fetched, the previous file is kept untouched.

  python scripts/globe_data.py
"""

import email.utils
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "globe" / "latest.json"
GDELT_GAP = 6          # seconds between GDELT calls (they ask for >= ~5s)
MAX_AGE_DAYS = 7       # FRESHNESS RULE: nothing older than this is published (items with no date can not be checked, so they are dropped too)
FLIGHT_MAX_AGE_S = 900 # a flight position older than 15 minutes at fetch time is not shown
UA = {"User-Agent": "Mozilla/5.0 (Samnidhy B-Lab globe; educational; contact via github.com/atharvatyagi-gif)"}
IST = timezone(timedelta(hours=5, minutes=30))
PW = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"


def parse_iso(s):
    """ISO-ish timestamp (with or without a zone, 'Z' ok) -> aware UTC datetime, or None."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def fresh(ts, now, days=MAX_AGE_DAYS):
    """True if `ts` (ISO string or datetime) is within `days` of `now`. Undated -> False: an age that can not be checked is not shown."""
    d = ts if isinstance(ts, datetime) else parse_iso(ts)
    return d is not None and d >= now - timedelta(days=days)


def gdacs_recent(fromdate, todate, now, short_days=30):
    """A GDACS alert is shown if the event STARTED within the freshness window, or it is a short episode (<= `short_days` long: a cyclone, flood,
    quake sequence) that ENDED within the window. A months-long drought that GDACS still lists as current is not news for a market decision."""
    f, t = parse_iso(fromdate), parse_iso(todate)
    if f is not None and fresh(f, now):
        return True
    return t is not None and f is not None and fresh(t, now) and (t - f) <= timedelta(days=short_days)


def only_fresh(items, key, now):
    return [a for a in (items or []) if fresh(a.get(key), now)]


def pw_query(layer, params):
    """ArcGIS FeatureServer query, with a real safety net: a malformed query returns HTTP 200 with an
    {"error": ...} body (confirmed live - found by a real bug here: a date filter in the wrong literal syntax
    silently came back as "0 results" instead of an error). raise_for_status() alone misses that entirely, so
    this checks for the error body too and raises - a real failure must never be mistaken for real zero data."""
    r = requests.get(f"{PW}/{layer}/FeatureServer/0/query", params={**params, "f": "json"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"ArcGIS query error on {layer}: {j['error']}")
    return j

# id, display name, centre lat/lon, half-width of the OpenSky bounding box (degrees), search keywords, a
# short widely-cited reference fact (not live data), and the matching IMF PortWatch chokepoint id (verified
# against PortWatch_chokepoints_database directly - see docs/TERMINAL_PLAN.md).
CHOKEPOINTS = [
    ("hormuz", "Strait of Hormuz", 26.6, 56.3, 1.3, '"Strait of Hormuz" OR Hormuz',
     "The narrow gap between Iran and Oman that oil tankers from Saudi Arabia, Iraq, the UAE, Kuwait and Qatar sail through — commonly cited as around a fifth of the world's oil consumption.", "chokepoint6"),
    ("bab_el_mandeb", "Bab-el-Mandeb", 12.6, 43.4, 0.8, '"Bab-el-Mandeb" OR "Bab el-Mandeb" OR "Red Sea shipping"',
     "The strait between Yemen and Djibouti linking the Red Sea to the Gulf of Aden; the route to and from the Suez Canal for Asia-Europe trade and Gulf oil.", "chokepoint4"),
    ("suez", "Suez Canal", 30.5, 32.3, 0.7, '"Suez Canal"',
     "Egypt's canal linking the Mediterranean to the Red Sea; commonly cited as carrying over a tenth of world trade by volume.", "chokepoint1"),
    ("malacca", "Strait of Malacca", 2.8, 101.2, 1.5, '"Strait of Malacca" OR "Malacca Strait"',
     "The main sea route between the Indian Ocean and the South China Sea, between Indonesia, Malaysia and Singapore — one of the world's busiest shipping lanes.", "chokepoint5"),
    ("taiwan", "Taiwan Strait", 24.0, 119.5, 1.3, '"Taiwan Strait" OR "Taiwan Strait tension" OR "China Taiwan military"',
     "Separates Taiwan from mainland China; a flashpoint for semiconductor supply chains (Taiwan makes most of the world's advanced chips) and regional security.", "chokepoint11"),
    ("panama", "Panama Canal", 9.1, -79.7, 0.6, '"Panama Canal"',
     "Links the Atlantic and Pacific; a shortcut for trade between Asia and the US East Coast, avoiding the trip around South America.", "chokepoint2"),
    ("bosphorus", "Bosphorus Strait", 41.1, 29.1, 0.5, '"Bosphorus Strait" OR Bosporus',
     "Istanbul's strait linking the Black Sea to the Mediterranean — the route for Russian and other Black Sea oil and grain exports.", "chokepoint3"),
]
GENERAL_QUERY = '(tariff OR sanctions OR "trade war" OR embargo OR "supply chain" OR "oil price" OR OPEC OR pipeline OR "military build" OR "shipping disruption") sourcelang:english'


def flights(lat, lon, half):
    # OpenSky's anonymous /flights/aircraft (route history) endpoint returns 403 "You cannot access historical
    # flights" for unauthenticated requests (confirmed live) - so no destination/origin airport is available
    # here; every field below comes from the one anonymous endpoint this script is allowed to use, /states/all.
    r = requests.get("https://opensky-network.org/api/states/all",
                     params={"lamin": lat - half, "lamax": lat + half, "lomin": lon - half, "lomax": lon + half}, timeout=20)
    r.raise_for_status()
    now = time.time()
    states = r.json().get("states") or []
    sample = [{
        "icao24": s[0], "callsign": (s[1] or "").strip(), "country": s[2],
        "lat": s[6], "lon": s[5], "alt_m": s[7], "geo_alt_m": s[13], "on_ground": s[8],
        "velocity_ms": s[9], "heading": s[10], "vrate_ms": s[11], "squawk": s[14],
        "src": s[16], "age_s": round(now - s[4]) if s[4] else None,
    } for s in states if s[5] is not None and s[6] is not None and s[4] and now - s[4] <= FLIGHT_MAX_AGE_S][:60]
    live = [s for s in states if s[4] and now - s[4] <= FLIGHT_MAX_AGE_S]
    return {"count": len(live), "sample": sample, "fetched_utc": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds")}


def portwatch_vessels(pw_id):
    """Real daily vessel-transit counts by type for one chokepoint, plus a 90-day sparkline and a real
    7-day-average vs prior-90-day-average % (both computed only from real daily records, never estimated)."""
    # orderByFields date ASC + a resultRecordCount cap would return the OLDEST 90 records in the whole table
    # (confirmed live: that returned 2019 data for Hormuz, years stale) - DESC gets the real most-recent ones,
    # then reversed here for the sparkline's chronological order.
    j = pw_query("Daily_Chokepoints_Data", {
        "where": f"portid='{pw_id}'", "outFields": "date,n_total,n_tanker,n_container,n_dry_bulk,n_general_cargo,n_roro",
        "orderByFields": "date DESC", "resultRecordCount": 90,
    })
    feats = [f["attributes"] for f in j.get("features", [])][::-1]
    if not feats:
        return None
    last = feats[-1]
    if not fresh(str(last["date"])[:10] + "T00:00:00+00:00", datetime.now(timezone.utc)):
        return None                                   # PortWatch's newest day is older than a week: not shown (the chokepoint card says so)
    last7, prior = feats[-7:], feats[:-7]
    avg7 = sum(f["n_total"] for f in last7) / len(last7)
    avg_prior = (sum(f["n_total"] for f in prior) / len(prior)) if prior else None
    return {
        "date": str(last["date"])[:10], "n_total": last["n_total"], "n_tanker": last["n_tanker"],
        "n_container": last["n_container"], "n_dry_bulk": last["n_dry_bulk"],
        "n_general_cargo": last["n_general_cargo"], "n_roro": last["n_roro"],
        "sparkline_90d": [f["n_total"] for f in feats],
        "avg7_vs_prior90_pct": round((avg7 - avg_prior) / avg_prior * 100, 1) if avg_prior else None,
    }


def portwatch_industries():
    """One batched query for all 7 chokepoints' top industries (static-ish reference field, cheap to refresh)."""
    ids = ",".join(f"'{c[-1]}'" for c in CHOKEPOINTS)
    j = pw_query("PortWatch_chokepoints_database", {"where": f"portid IN ({ids})", "outFields": "portid,industry_top1,industry_top2,industry_top3"})
    return {f["attributes"]["portid"]: [f["attributes"].get(k) for k in ("industry_top1", "industry_top2", "industry_top3") if f["attributes"].get(k)]
            for f in j.get("features", [])}


def portwatch_disruptions(limit=25, recent_days=MAX_AGE_DAYS):
    """Real disruption events (storms/quakes/conflict etc.) with real port impact counts, either still ongoing
    (todate in the future) or recent enough to still matter (a point event like a quake has fromdate==todate,
    so "still ongoing" alone would exclude it the moment it happens - recency is the more useful real signal).
    Window = the 7-day freshness rule (it was 90 days: that let weeks-old events sit on the map). An empty layer
    simply means nothing was reported in the last week. Each event's own real date is shown on screen."""
    # fromdate/todate are esriFieldTypeDate fields: ArcGIS's WHERE clause needs the SQL `timestamp '...'`
    # literal syntax for date comparisons, not a raw epoch-ms number (confirmed live: the numeric form gets a
    # silent HTTP-200 {"error":...} body - no exception, just an empty "features" list - the real bug here).
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    since_ts = (datetime.now(timezone.utc) - timedelta(days=recent_days)).strftime("%Y-%m-%d %H:%M:%S")
    j = pw_query("portwatch_disruptions_database", {
        "where": f"todate >= timestamp '{now_ts}' OR fromdate >= timestamp '{since_ts}'",
        "outFields": "eventtype,eventname,alertlevel,country,fromdate,todate,severitytext,n_affectedports,lat,long",
        "orderByFields": "n_affectedports DESC", "resultRecordCount": limit,
    })
    out = []
    for f in j.get("features", []):
        a = f["attributes"]
        out.append({"type": a.get("eventtype"), "name": a.get("eventname"), "alert": a.get("alertlevel"),
                    "country": a.get("country"), "severity": a.get("severitytext"), "n_ports": a.get("n_affectedports"),
                    "lat": a.get("lat"), "lon": a.get("long"),
                    "from_utc": datetime.fromtimestamp(a["fromdate"] / 1000, tz=timezone.utc).isoformat(timespec="seconds") if a.get("fromdate") else None,
                    "to_utc": datetime.fromtimestamp(a["todate"] / 1000, tz=timezone.utc).isoformat(timespec="seconds") if a.get("todate") else None})
    now = datetime.now(timezone.utc)
    return [e for e in out if fresh(e["to_utc"], now) or fresh(e["from_utc"], now)]


def usgs_quakes(min_mag=4.5, limit=40):
    r = requests.get(f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{min_mag}_week.geojson", timeout=20)
    r.raise_for_status()
    feats = sorted(r.json().get("features", []), key=lambda f: f["properties"]["mag"], reverse=True)[:limit]
    return [{"mag": f["properties"]["mag"], "place": f["properties"]["place"], "tsunami": bool(f["properties"].get("tsunami")),
             "alert": f["properties"].get("alert"), "time_utc": datetime.fromtimestamp(f["properties"]["time"] / 1000, tz=timezone.utc).isoformat(timespec="seconds"),
             "lat": f["geometry"]["coordinates"][1], "lon": f["geometry"]["coordinates"][0], "url": f["properties"].get("url")} for f in feats]


def eonet_events(days=7, limit=60):
    r = requests.get("https://eonet.gsfc.nasa.gov/api/v3/events", params={"status": "open", "days": days}, timeout=20)
    r.raise_for_status()
    out = []
    for e in r.json().get("events", [])[:limit]:
        geo = (e.get("geometry") or [])
        if not geo or "coordinates" not in geo[-1]:
            continue
        g = geo[-1]  # most recent position for a moving event (storms etc.)
        if not fresh(g.get("date"), datetime.now(timezone.utc)):
            continue                                   # still "open" in EONET but its latest report is older than a week
        out.append({"title": e.get("title"), "category": (e.get("categories") or [{}])[0].get("title"),
                    "lat": g["coordinates"][1], "lon": g["coordinates"][0], "date": g.get("date"), "url": e.get("link")})
    return out


def gdacs_events(limit=40):
    r = requests.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH", timeout=20)
    r.raise_for_status()
    out = []
    for f in r.json().get("features", []):
        p = f["properties"]
        if str(p.get("iscurrent")).lower() != "true":
            continue
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        now = datetime.now(timezone.utc)
        if not gdacs_recent(p.get("fromdate"), p.get("todate"), now):
            continue                                   # "current" in GDACS but not a new event or a short one that ended in the last week (e.g. a drought running since last winter)
        out.append({"type": p.get("eventtype"), "name": p.get("eventname") or p.get("name"), "alert": p.get("alertlevel"),
                    "country": p.get("country"), "lat": g["coordinates"][1], "lon": g["coordinates"][0],
                    "from_utc": p.get("fromdate"), "to_utc": p.get("todate"), "url": (p.get("url") or {}).get("report")})
    out.sort(key=lambda e: {"Red": 0, "Orange": 1, "Green": 2}.get(e["alert"], 3))
    return out[:limit]


_last_gdelt = 0.0


def gdelt(query, n=6):
    global _last_gdelt
    wait = GDELT_GAP - (time.time() - _last_gdelt)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(2):
        try:
            r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
                             params={"query": query, "mode": "artlist", "maxrecords": n, "format": "json", "sort": "datedesc"},
                             headers=UA, timeout=25)
        except requests.RequestException:
            return None             # connection-level failure (timeout, DNS, refused) - GDELT is opportunistic only, never fatal
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
                if not fresh(iso, datetime.now(timezone.utc)):
                    continue
                out.append({"title": a.get("title"), "url": a.get("url"), "source": a.get("domain"), "country": a.get("sourcecountry"), "seen_utc": iso})
            return out
        if r.status_code == 429 and attempt == 0:
            time.sleep(20)
            continue
        return None
    return None


def google_news(query, n=6):
    try:
        r = requests.get("https://news.google.com/rss/search", params={"q": f"{query.replace(' sourcelang:english', '')} when:{MAX_AGE_DAYS}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}, headers=UA, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        out = []
        for item in root.findall(".//item")[:n * 3]:
            title, link, pub = item.findtext("title") or "", item.findtext("link") or "", item.findtext("pubDate") or ""
            src_el = item.find("source")
            try:
                iso = email.utils.parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat(timespec="seconds")
            except Exception:
                iso = None
            if title and link and fresh(iso, datetime.now(timezone.utc)):
                out.append({"title": title, "url": link, "source": (src_el.text if src_el is not None else None), "country": None, "seen_utc": iso})
        return out[:n]
    except Exception:
        return None


def news_for(query, n=6):
    """Google News RSS first (confirmed reliable from GitHub Actions); GDELT only tops up if that came up
    short, since GDELT is confirmed to 429 from Actions' runner IPs most of the time."""
    primary = google_news(query, n) or []
    if len(primary) >= n:
        return primary
    extra = gdelt(query, n - len(primary))
    if extra:
        seen = {a["url"] for a in primary}
        primary += [a for a in extra if a["url"] not in seen]
    return primary or None


def main():
    now = datetime.now(timezone.utc)
    points, errors = [], []

    try:
        industries = portwatch_industries()
    except Exception as exc:
        industries = {}
        errors.append(f"PortWatch industries: {type(exc).__name__} {exc}")

    for cid, name, lat, lon, half, kw, why, pw_id in CHOKEPOINTS:
        p = {"id": cid, "name": name, "lat": lat, "lon": lon, "why": why}
        try:
            p["flights"] = flights(lat, lon, half)
        except Exception as exc:
            errors.append(f"{name} flights: {type(exc).__name__} {exc}")
        try:
            v = portwatch_vessels(pw_id)
            if v:
                if industries.get(pw_id):
                    v["industries"] = industries[pw_id]
                p["vessels"] = v
        except Exception as exc:
            errors.append(f"{name} vessels (PortWatch): {type(exc).__name__} {exc}")
        news = news_for(kw)
        if news is not None:
            p["news"] = news
        else:
            errors.append(f"{name} news: unavailable (Google News + GDELT both failed)")
        points.append(p)
        time.sleep(0.3)

    events = news_for(GENERAL_QUERY, n=20)
    if events is None:
        errors.append("general events: unavailable (Google News + GDELT both failed)")

    hazards = {}
    for key, fn in [("disruptions", portwatch_disruptions), ("earthquakes", usgs_quakes), ("natural_events", eonet_events), ("alerts", gdacs_events)]:
        try:
            hazards[key] = fn()
        except Exception as exc:
            errors.append(f"hazards.{key}: {type(exc).__name__} {exc}")

    got_anything = any("flights" in p or "news" in p or "vessels" in p for p in points) or events is not None or hazards
    if not got_anything:
        raise RuntimeError("Nothing could be fetched this run: " + "; ".join(errors))

    res = {
        "generated_utc": now.isoformat(timespec="seconds"),
        "generated_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "sources": {
            "flights": "OpenSky Network (opensky-network.org), free public ADS-B data",
            "vessels": "IMF PortWatch (portwatch.imf.org), free daily vessel-transit counts - not live AIS, see each chokepoint's own date",
            "news": "Google News RSS, primary; GDELT Project tops up when available",
            "hazards": "IMF PortWatch disruptions, USGS (earthquakes), NASA EONET (natural events), GDACS (disaster alerts) - all free, no key",
        },
        "max_age_days": MAX_AGE_DAYS,
        "freshness_rule": f"Nothing older than {MAX_AGE_DAYS} days is published; undated items are dropped; flights are positions from this run (each at most {FLIGHT_MAX_AGE_S // 60} minutes old when fetched).",
        "chokepoints": points,
        "events": events or [],
        "hazards": hazards,
        "partial_errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, allow_nan=False), encoding="utf-8")
    fcount = sum(p.get("flights", {}).get("count", 0) for p in points)
    vcount = sum(p.get("vessels", {}).get("n_total", 0) for p in points if p.get("vessels"))
    ncount = sum(len(p.get("news", [])) for p in points)
    print(f"globe: {fcount} live flights, {vcount} real vessel transits (most recent day), {ncount} chokepoint headlines, "
         f"{len(events or [])} general headlines, {sum(len(v) for v in hazards.values())} hazard records across {len(points)} chokepoints"
         + (f"; partial errors: {errors}" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
