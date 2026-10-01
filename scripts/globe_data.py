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
ship icons. Nor does OpenSky's anonymous tier give a flight's route (origin/destination airport) - its
/flights/aircraft endpoint returns 403 "You cannot access historical flights" without a registered account, so
that field is left out rather than guessed; everything else per aircraft (speed, altitude, heading, climb rate,
squawk, position age) is real, straight from /states/all. Chokepoint "why it matters" lines are widely-cited
reference facts (EIA, UNCTAD), not live data, and are clearly separate from the live flight counts and live
news next to them.

If a chokepoint's flights or news can't be fetched this run, that one field is simply left out (not
invented); if nothing at all could be fetched, the previous file is kept untouched.

Added sources (all free, no account or key):

  IMF PortWatch     https://portwatch.imf.org - the IMF/Oxford project's public ArcGIS services, built from
                    satellite AIS: daily ship transits by vessel type through 28 maritime chokepoints, daily
                    port calls at India's ports, and current port-disrupting events. This is real, counted
                    ship traffic (published with a lag of about one to two weeks), so it fills the gap the
                    note above describes - it is dated by the source's own latest day, never as "now".
                    Refreshed at most every PORTWATCH_HOURS (the source itself updates about weekly).
  USGS              earthquakes of magnitude 4.5+ in the past 7 days (earthquake.usgs.gov GeoJSON feed).
  NASA EONET        open natural events: wildfires, storms, volcanoes, floods, ice (eonet.gsfc.nasa.gov).
  GDACS             UN/EC disaster alerts (cyclones, floods, quakes, droughts) with Green/Orange/Red levels.
  Google News RSS   fallback for a chokepoint's headlines when GDELT refuses (GDELT has been rejecting every
                    request from GitHub's runners); the item's own publisher and time are kept.
  TeleGeography     submarine cables and landing points (submarinecablemap.com, CC BY-SA 4.0) - weekly.
  Wikidata          each NSE-listed company's headquarters and the facilities Wikidata records it (or a
                    subsidiary) as owning or operating, with coordinates - weekly. Coverage is Wikidata's own,
                    so many companies have only an HQ; nothing is added where Wikidata has nothing.

Each block keeps the previous run's copy (with that copy's own as-of time) when its source fails this run.
The slow layers go to data/globe/layers/*.json; scripts/globe_static.py writes the static ones.

  python scripts/globe_data.py
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "globe" / "latest.json"
LAYERS = ROOT / "data" / "globe" / "layers"
PORTWATCH_HOURS = 12
WEEKLY_HOURS = 24 * 7
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
PW_NAME = {"hormuz": "Strait of Hormuz", "bab_el_mandeb": "Bab el-Mandeb Strait", "suez": "Suez Canal", "malacca": "Malacca Strait",
           "taiwan": "Taiwan Strait", "panama": "Panama Canal", "bosphorus": "Bosporus Strait"}
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
    } for s in states if s[5] is not None and s[6] is not None][:60]
    return {"count": len(states), "sample": sample}


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
            _last_gdelt = time.time()
            return None
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


# ---------------------------------------------------------------- Google News RSS (fallback for GDELT)
def gnews(query, n=6):
    q = query.replace(" sourcelang:english", "")
    try:
        r = requests.get(f"https://news.google.com/rss/search?q={quote(q + ' when:7d')}&hl=en-IN&gl=IN&ceid=IN:en", headers=UA, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return None
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        source = src.text.strip() if src is not None and src.text else None
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        try:
            iso = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:
            iso = None
        out.append({"title": title, "url": it.findtext("link"), "source": source, "country": None, "seen_utc": iso, "via": "Google News"})
        if len(out) >= n:
            break
    return out


def news_for(query, n=6):
    got = gdelt(query, n)
    return got if got else gnews(query, n)


# ---------------------------------------------------------------- IMF PortWatch (ArcGIS, no key)
PW = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/{}/FeatureServer/0/query"


def pw_query(service, **params):
    base = {"f": "json", "returnGeometry": "false", "outFields": "*", "where": "1=1"}
    base.update(params)
    r = requests.get(PW.format(service), params=base, headers=UA, timeout=45)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"{service}: {d['error'].get('message')}")
    return [f["attributes"] for f in d.get("features", [])]


def pw_date(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%Y-%m-%d")
    return str(v)[:10] if v else None


PW_DIS_FIELDS = "eventid,eventtype,eventname,htmldescription,alertlevel,country,fromdate,todate,severitytext,lat,long,n_affectedports"


def pw_disruptions():
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    try:
        dis = pw_query("portwatch_disruptions_database", where=f"todate >= TIMESTAMP '{since} 00:00:00'", orderByFields="fromdate DESC",
                       resultRecordCount=80, outFields=PW_DIS_FIELDS)
    except Exception:              # date-filter syntax varies between ArcGIS versions: take the newest and filter here
        dis = pw_query("portwatch_disruptions_database", orderByFields="ObjectId DESC", resultRecordCount=150, outFields=PW_DIS_FIELDS)
        dis = [d for d in dis if (pw_date(d.get("todate")) or "") >= since]
    return [{"id": d["eventid"], "type": d.get("eventtype"), "name": d.get("eventname"), "desc": d.get("htmldescription"),
             "alert": d.get("alertlevel"), "country": d.get("country"), "from": pw_date(d.get("fromdate")), "to": pw_date(d.get("todate")),
             "severity": d.get("severitytext"), "lat": d.get("lat"), "lon": d.get("long"), "ports_hit": d.get("n_affectedports")}
            for d in dis if d.get("lat") is not None]


def portwatch():
    cps = pw_query("PortWatch_chokepoints_database")
    out = []
    for c in cps:
        rows = pw_query("Daily_Chokepoints_Data", where=f"portid='{c['portid']}'", orderByFields="date DESC", resultRecordCount=120,
                        outFields="date,n_total,n_tanker,n_container,n_dry_bulk,n_general_cargo,n_roro,capacity")
        series = sorted(([pw_date(r["date"]), r.get("n_total"), r.get("n_tanker"), r.get("n_container"), r.get("n_dry_bulk"),
                          r.get("n_general_cargo"), r.get("n_roro")] for r in rows if r.get("date") is not None), key=lambda x: x[0])
        out.append({"id": c["portid"], "name": c["portname"], "lat": round(c["lat"], 3), "lon": round(c["lon"], 3),
                    "industries": [c.get(k) for k in ("industry_top1", "industry_top2", "industry_top3") if c.get(k)],
                    "annual_vessels": c.get("vessel_count_total"),
                    "annual_by_type": {k: c.get("vessel_count_" + k) for k in ("tanker", "container", "dry_bulk", "general_cargo", "RoRo")},
                    "series": series})
        time.sleep(0.3)
    ports = pw_query("PortWatch_ports_database", where="ISO3='IND'")
    ports.sort(key=lambda p: -(p.get("vessel_count_total") or 0))
    pout, daily_ok, t0 = [], True, time.time()
    for p in ports[:30]:
        rows = []
        if daily_ok and time.time() - t0 < 240:       # the daily-ports service can be slow; one failure or 4 min -> ports keep only reference data
            try:
                rows = pw_query("Daily_Ports_Data", where=f"portid='{p['portid']}'", orderByFields="date DESC", resultRecordCount=60)
            except Exception:
                daily_ok = False
        keys = [k for k in (rows[0] if rows else {}) if k.startswith("portcalls") or k in ("import", "export")]
        series = sorted(([pw_date(r["date"])] + [r.get(k) for k in keys] for r in rows if r.get("date") is not None), key=lambda x: x[0])
        pout.append({"id": p["portid"], "name": p["portname"], "lat": round(p["lat"], 3), "lon": round(p["lon"], 3),
                     "annual_vessels": p.get("vessel_count_total"),
                     "industries": [p.get(k) for k in ("industry_top1", "industry_top2", "industry_top3") if p.get(k)],
                     "fields": keys, "series": series})
        time.sleep(0.3)
    try:
        dout = pw_disruptions()
    except Exception:
        dout = None                                # disruptions are optional; transits and ports still publish
    latest = max((c["series"][-1][0] for c in out if c["series"]), default=None)
    return {"fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_through": latest,
            "source": "IMF PortWatch (portwatch.imf.org), daily counts from satellite AIS",
            "series_cols": ["date", "total", "tanker", "container", "dry_bulk", "general_cargo", "roro"],
            "chokepoints": out, "india_ports": pout, "disruptions": dout or []}


# ---------------------------------------------------------------- natural hazards
def quakes():
    r = requests.get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson", headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for f in r.json()["features"]:
        p, (lon, lat, depth) = f["properties"], f["geometry"]["coordinates"][:3]
        out.append({"mag": p.get("mag"), "place": p.get("place"), "time_utc": datetime.fromtimestamp(p["time"] / 1000, timezone.utc).isoformat(timespec="seconds"),
                    "lat": round(lat, 3), "lon": round(lon, 3), "depth_km": round(depth or 0), "tsunami": bool(p.get("tsunami")),
                    "alert": p.get("alert"), "url": p.get("url")})
    return out


def eonet():
    r = requests.get("https://eonet.gsfc.nasa.gov/api/v3/events", params={"status": "open", "days": 30}, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for e in r.json().get("events", []):
        geos = [g for g in e.get("geometry", []) if g.get("type") == "Point"]
        if not geos:
            continue
        g = geos[-1]
        track = [[round(x["coordinates"][1], 2), round(x["coordinates"][0], 2)] for x in geos][-40:] if len(geos) > 1 else None
        out.append({"title": e.get("title"), "cat": (e.get("categories") or [{}])[0].get("title"), "date": g.get("date"),
                    "lat": round(g["coordinates"][1], 3), "lon": round(g["coordinates"][0], 3), "track": track,
                    "url": (e.get("sources") or [{}])[0].get("url")})
    return out


def gdacs():
    today = datetime.now(timezone.utc).date()
    try:
        r = requests.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH", headers=UA, timeout=30,
                         params={"eventlist": "EQ;TC;FL;VO;DR;WF", "fromDate": str(today - timedelta(days=30)), "toDate": str(today),
                                 "alertlevel": "Green;Orange;Red"})
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception:
        return gdacs_rss()
    out = []
    for f in feats:
        p, g = f.get("properties", {}), f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        out.append({"type": p.get("eventtype"), "name": p.get("name") or p.get("eventname"), "alert": p.get("alertlevel"),
                    "country": p.get("country"), "from": (p.get("fromdate") or "")[:10], "to": (p.get("todate") or "")[:10],
                    "severity": (p.get("severitydata") or {}).get("severitytext"), "lat": round(g["coordinates"][1], 3),
                    "lon": round(g["coordinates"][0], 3), "url": (p.get("url") or {}).get("report")})
    return out


def gdacs_rss():
    r = requests.get("https://www.gdacs.org/xml/rss.xml", headers=UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = {"geo": "http://www.w3.org/2003/01/geo/wgs84_pos#", "gdacs": "http://www.gdacs.org"}
    out = []
    for it in root.iter("item"):
        lat, lon = it.findtext("geo:Point/geo:lat", namespaces=ns), it.findtext("geo:Point/geo:long", namespaces=ns)
        if lat is None or lon is None:
            continue
        out.append({"type": it.findtext("gdacs:eventtype", namespaces=ns), "name": it.findtext("gdacs:eventname", namespaces=ns) or it.findtext("title"),
                    "alert": it.findtext("gdacs:alertlevel", namespaces=ns), "country": it.findtext("gdacs:country", namespaces=ns),
                    "from": (it.findtext("gdacs:fromdate", namespaces=ns) or "")[:16], "to": (it.findtext("gdacs:todate", namespaces=ns) or "")[:16],
                    "severity": it.findtext("gdacs:severity", namespaces=ns), "lat": round(float(lat), 3), "lon": round(float(lon), 3), "url": it.findtext("link")})
    return out


# ---------------------------------------------------------------- weekly layers
def _simplify(pts, tol):
    from globe_static import simplify
    return simplify(pts, tol)


def cables():
    base = "https://www.submarinecablemap.com/api/v3"
    cg = requests.get(f"{base}/cable/cable-geo.json", headers=UA, timeout=60).json()
    lg = requests.get(f"{base}/landing-point/landing-point-geo.json", headers=UA, timeout=60).json()
    lines = []
    for f in cg["features"]:
        p, g = f["properties"], f["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        segs = []
        for part in parts:
            s = _simplify([tuple(c[:2]) for c in part], 0.05)
            if len(s) >= 2:
                segs.append([[round(y, 2), round(x, 2)] for x, y in s])
        if segs:
            lines.append({"id": p.get("id"), "n": p.get("name"), "col": p.get("color"), "segs": segs})
    pts = [{"id": f["properties"].get("id"), "n": f["properties"].get("name"),
            "lat": round(f["geometry"]["coordinates"][1], 3), "lon": round(f["geometry"]["coordinates"][0], 3)}
           for f in lg["features"] if f.get("geometry")]
    return {"source": "TeleGeography Submarine Cable Map (submarinecablemap.com), CC BY-SA 4.0", "cables": lines, "landings": pts}


UNIVERSE = ROOT / "data" / "universe" / "nifty500.csv"


def isin_map():                                  # ISIN -> NSE symbol, from the site's own NIFTY 500 list (an exact key; no name matching)
    import csv
    with open(UNIVERSE, encoding="utf-8") as fh:
        return {r["ISIN Code"].strip(): r["Symbol"].strip() for r in csv.DictReader(fh) if r.get("ISIN Code")}


WD_HQ = """SELECT ?co ?coLabel ?isin ?f ?fLabel ?coord WHERE {{
  {listed}
  {{ ?co wdt:P159 ?f . ?f wdt:P625 ?coord . }} UNION {{ ?co wdt:P625 ?coord . BIND(?co AS ?f) }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}"""
WD_LISTED = "VALUES ?isin {{ {isins} }} ?co wdt:P946 ?isin ."
WD_FAC = {
    "owner": "?f wdt:P127 ?co .",
    "operator": "?f wdt:P137 ?co .",
    "via subsidiary": "?via wdt:P749 ?co . ?f wdt:P127 ?via .",
}
WD_FAC_Q = """SELECT ?isin ?co ?f ?fLabel ?typeLabel ?coord ?viaLabel WHERE {{
  {listed}
  {link}
  ?f wdt:P625 ?coord .
  OPTIONAL {{ ?f wdt:P31 ?type }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }} LIMIT 8000"""


def _sparql(q):
    r = requests.post("https://query.wikidata.org/sparql", data={"query": q, "format": "json"},
                      headers={**UA, "Accept": "application/sparql-results+json"}, timeout=90)
    r.raise_for_status()
    return r.json()["results"]["bindings"]


def _pt(wkt):                                   # "Point(lon lat)"
    try:
        lon, lat = wkt[wkt.index("(") + 1: wkt.index(")")].split()
        return round(float(lat), 4), round(float(lon), 4)
    except Exception:
        return None


def companies():
    v = lambda b, k: (b.get(k) or {}).get("value")
    out, isins = {}, isin_map()
    listed = WD_LISTED.format(isins=" ".join(f'"{i}"' for i in isins))
    tick = lambda b: isins.get((v(b, "isin") or "").strip())
    for b in _sparql(WD_HQ.format(listed=listed)):
        t, pt = tick(b), _pt(v(b, "coord") or "")
        if not t or not pt:
            continue
        c = out.setdefault(t, {"name": v(b, "coLabel"), "qid": v(b, "co").rsplit("/", 1)[-1], "hq": None, "sites": {}})
        if c["hq"] is None:
            c["hq"] = {"n": v(b, "fLabel"), "lat": pt[0], "lon": pt[1]}
    failed = []
    for rel, link in WD_FAC.items():
        time.sleep(2)
        try:
            rows = _sparql(WD_FAC_Q.format(listed=listed, link=link))
        except Exception as exc:
            failed.append(f"{rel}: {type(exc).__name__}")
            continue
        for b in rows:
            t, pt = tick(b), _pt(v(b, "coord") or "")
            if not t or not pt:
                continue
            c = out.setdefault(t, {"name": None, "qid": v(b, "co").rsplit("/", 1)[-1], "hq": None, "sites": {}})
            q = v(b, "f").rsplit("/", 1)[-1]
            s_ = c["sites"].setdefault(q, {"q": q, "n": v(b, "fLabel"), "lat": pt[0], "lon": pt[1], "types": [], "rel": rel, "via": v(b, "viaLabel")})
            ty = v(b, "typeLabel")
            if ty and ty not in s_["types"] and len(s_["types"]) < 3:
                s_["types"].append(ty)
    for c in out.values():
        c["sites"] = list(c["sites"].values())[:150]
    return {"source": "Wikidata (CC0): NIFTY 500 companies matched by ISIN, their headquarters and the facilities Wikidata lists them, or a subsidiary, as owning or operating",
            "partial": failed, "companies": out}


def weekly(name, fn, errors):
    path = LAYERS / f"{name}.json"
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated_utc"])).total_seconds() / 3600
            if age_h < WEEKLY_HOURS:
                return
        except Exception:
            pass
    try:
        d = fn()
    except Exception as exc:
        errors.append(f"{name}: {type(exc).__name__} {exc}")
        return
    d["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    LAYERS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def main():
    now = datetime.now(timezone.utc)
    points, errors = [], []
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    except Exception:
        prev = {}
    for cid, name, lat, lon, half, kw, why in CHOKEPOINTS:
        p = {"id": cid, "name": name, "lat": lat, "lon": lon, "why": why}
        try:
            p["flights"] = flights(lat, lon, half)
        except Exception as exc:
            errors.append(f"{name} flights: {type(exc).__name__} {exc}")
        news = news_for(kw)
        if news:
            p["news"] = news
        else:
            errors.append(f"{name} news: GDELT unavailable")
        points.append(p)
        time.sleep(0.5)

    events = news_for(GENERAL_QUERY, n=20)
    if events is None:
        errors.append("general events: GDELT unavailable")

    # IMF PortWatch: refreshed at most every PORTWATCH_HOURS; otherwise (or on failure) the previous copy is kept
    pw = prev.get("portwatch")
    pw_age = None
    if pw and pw.get("fetched_utc"):
        pw_age = (now - datetime.fromisoformat(pw["fetched_utc"])).total_seconds() / 3600
    if pw is None or pw_age is None or pw_age >= PORTWATCH_HOURS:
        try:
            pw = portwatch()
        except Exception as exc:
            errors.append(f"PortWatch: {type(exc).__name__} {exc}" + (" (kept previous copy)" if pw else ""))
    if pw:
        by_name = {c["name"]: c for c in pw.get("chokepoints", [])}
        for p in points:
            c = by_name.get(PW_NAME.get(p["id"], ""))
            if c:
                p["portwatch_id"] = c["id"]

    hazards = {}
    for key, fn in (("quakes", quakes), ("eonet", eonet), ("gdacs", gdacs)):
        try:
            hazards[key] = {"fetched_utc": now.isoformat(timespec="seconds"), "items": fn()}
        except Exception as exc:
            old = (prev.get("hazards") or {}).get(key)
            errors.append(f"{key}: {type(exc).__name__} {exc}" + (" (kept previous copy)" if old else ""))
            if old:
                hazards[key] = old

    for name, fn in (("cables", cables), ("companies", companies)):
        weekly(name, fn, errors)

    got_anything = any("flights" in p or "news" in p for p in points) or bool(events) or bool(pw) or bool(hazards)
    if not got_anything:
        raise RuntimeError("No source returned anything this run: " + "; ".join(errors))

    res = {
        "generated_utc": now.isoformat(timespec="seconds"),
        "generated_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "sources": {"flights": "OpenSky Network (opensky-network.org), free public ADS-B data",
                   "news": "GDELT Project (gdeltproject.org), free global news index; Google News RSS when GDELT refuses",
                   "ships": "IMF PortWatch (portwatch.imf.org), daily ship transits from satellite AIS",
                   "quakes": "USGS Earthquake Hazards Program", "eonet": "NASA EONET", "gdacs": "GDACS (UN / European Commission)"},
        "chokepoints": points,
        "events": events or [],
        "portwatch": pw,
        "hazards": hazards,
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
