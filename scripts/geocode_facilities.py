"""
Puts coordinates on the plants/mines/ports named in the filings (data/supply_graph.json "fac"), using OpenStreetMap's Nominatim.

Rules: <= 1 request per second, a descriptive User-Agent that includes GEOCODE_CONTACT, every answer cached forever by normalised address,
results outside India rejected, and the precision is whatever the result type says: building/house -> exact, suburb/village/hamlet -> locality,
county/state_district/district -> district, city/town -> city. A coordinate is never filled from memory; no match -> stays without coordinates.
    python scripts/geocode_facilities.py [--limit 60]
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "data" / "supply_graph.json"
CACHE = ROOT / "data" / "nexus_cache" / "geocode.json"
URL = "https://nominatim.openstreetmap.org/search"

PRECISION = {"building": "exact", "house": "exact", "industrial": "exact", "works": "exact", "factory": "exact", "plant": "exact",
             "suburb": "locality", "neighbourhood": "locality", "village": "locality", "hamlet": "locality", "quarter": "locality",
             "county": "district", "state_district": "district", "district": "district", "region": "district",
             "city": "city", "town": "city", "municipality": "city", "administrative": "city"}


def norm_addr(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w, ]+", " ", (s or "").lower())).strip()


def precision_of(hit):
    for k in (hit.get("addresstype"), hit.get("type"), hit.get("class")):
        if k in PRECISION:
            return PRECISION[k]
    return None


def in_india(hit):
    return (hit.get("address") or {}).get("country_code", "").lower() == "in"


def pick(hits):
    """First result that is inside India and has a recognisable precision -> (lat, lon, precision) or None."""
    for h in hits or []:
        p = precision_of(h)
        if p and in_india(h):
            return round(float(h["lat"]), 5), round(float(h["lon"]), 5), p
    return None


def geocode(doc, query_fn, cache, limit=60, sleep=time.sleep):
    """Fills lat/lon/geo_prec on facilities that have an address but no coordinates. -> number of new lookups."""
    n = 0
    for fid, f in doc.get("fac", {}).items():
        if f.get("lat") is not None or not f.get("addr"):
            continue
        k = norm_addr(f["addr"])
        if k not in cache:
            if n >= limit:
                continue
            sleep(1.05)
            cache[k] = query_fn(f["addr"])
            n += 1
        hit = cache[k]
        if hit:
            f["lat"], f["lon"], f["geo_prec"] = hit
    by = {fid: f for fid, f in doc.get("fac", {}).items()}
    for nd in doc.get("nodes", []):
        f = by.get(nd["id"])
        if f:
            nd["lat"], nd["lon"], nd["geo_prec"] = f["lat"], f["lon"], f["geo_prec"]
    return n


def nominatim(addr):
    import requests
    contact = os.environ.get("GEOCODE_CONTACT", "").strip()
    ua = "B-Lab-Desk/1.0 (%s)" % (contact or "educational project")
    r = requests.get(URL, params={"q": addr, "format": "jsonv2", "addressdetails": 1, "limit": 3, "countrycodes": "in"}, headers={"User-Agent": ua}, timeout=30)
    r.raise_for_status()
    return pick(r.json())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args(argv)
    if not GRAPH.exists():
        print("supply_graph.json not built yet: nothing to geocode")
        return 0
    doc = json.loads(GRAPH.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    n = geocode(doc, nominatim, cache, a.limit)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    GRAPH.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    done = sum(1 for f in doc.get("fac", {}).values() if f.get("lat") is not None)
    print(f"geocoded {n} new addresses; {done} of {len(doc.get('fac', {}))} facilities now have coordinates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
