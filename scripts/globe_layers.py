"""
Globe: slow-changing map layers - shipping lanes, submarine cables, power plants. None of this changes day to
day, so each file is only regenerated when it's more than MAX_AGE_DAYS old (or missing) - unlike
scripts/globe_data.py, which runs hourly. Three free, no-key sources:

  Shipping lanes    github.com/newzealandpaul/Shipping-Lanes (CC BY 4.0) - real traffic-density lane
                    geometry (Major/Middle/Minor). Decimated here (every 4th point kept) to keep the file a
                    sane size for the browser - still the real lane shapes, just fewer points per line; this
                    is a size optimisation, not a data change.
  Submarine cables  submarinecablemap.com (TeleGeography, CC BY-SA) - real cable routes + landing points.
                    India landing points are flagged by a precise ", India" suffix match on the real name
                    field (caught live: a naive "india" substring match would have wrongly included "Diego
                    Garcia, British Indian Ocean Territory" - a different place entirely).
  Power plants      WRI Global Power Plant Database (CC BY 4.0, github.com/wri/global-power-plant-database) -
                    filtered to India, >=100 MW (the plan's own threshold). Each plant's own
                    year_of_capacity_data is kept and shown on screen - this dataset is not real-time, and is
                    not presented as if it were.

If a source fails, that file is simply left as whatever it was before (same never-invent rule as
scripts/globe_data.py) - never partially written or guessed.

  python scripts/globe_layers.py [--force]
"""

import csv
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "globe" / "layers"
MAX_AGE_DAYS = 7
UA = {"User-Agent": "Mozilla/5.0 (Samnidhy B-Lab globe; educational; contact via github.com/atharvatyagi-gif)"}


def stale(path):
    # NOT filesystem mtime: a GitHub Actions checkout resets every file's mtime to "now" on every single run,
    # so an mtime-based check would never see staleness in CI at all (caught before shipping, not after) -
    # the file's own generated_utc field, written below, is the real signal that survives a fresh checkout.
    if not path.exists():
        return True
    try:
        gen = datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["generated_utc"])
    except Exception:
        return True
    return (datetime.now(timezone.utc) - gen).total_seconds() > MAX_AGE_DAYS * 86400


def decimate(coords, keep_every=4, nd=3):
    if len(coords) <= 2:
        pts = coords
    else:
        pts = coords[::keep_every]
        if pts[-1] != coords[-1]:
            pts.append(coords[-1])
    return [[round(x, nd), round(y, nd)] for x, y in pts]


def shipping_lanes():
    r = requests.get("https://raw.githubusercontent.com/newzealandpaul/Shipping-Lanes/main/data/Shipping_Lanes_v1.geojson", headers=UA, timeout=30)
    r.raise_for_status()
    lanes = [{"type": f["properties"].get("Type"), "lines": [decimate(line) for line in f["geometry"]["coordinates"]]}
             for f in r.json().get("features", [])]
    return {"source": "newzealandpaul/Shipping-Lanes on GitHub, CC BY 4.0", "lanes": lanes}


def submarine_cables():
    rc = requests.get("https://www.submarinecablemap.com/api/v3/cable/cable-geo.json", headers=UA, timeout=30)
    rc.raise_for_status()
    rl = requests.get("https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json", headers=UA, timeout=30)
    rl.raise_for_status()
    cables = []
    for f in rc.json().get("features", []):
        geom = f.get("geometry", {})
        if geom.get("type") != "MultiLineString":
            continue
        cables.append({"name": (f.get("properties") or {}).get("name"), "lines": [decimate(line, keep_every=3) for line in geom["coordinates"]]})
    landings = []
    for f in rl.json().get("features", []):
        name = (f.get("properties") or {}).get("name") or ""
        coords = (f.get("geometry") or {}).get("coordinates")
        if not coords:
            continue
        landings.append({"name": name, "lon": round(coords[0], 3), "lat": round(coords[1], 3), "india": name.endswith(", India")})
    return {"source": "TeleGeography submarinecablemap.com, CC BY-SA", "cables": cables, "landing_points": landings,
            "n_india_landings": sum(1 for l in landings if l["india"])}


def power_plants_india(min_mw=100):
    r = requests.get("https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv", headers=UA, timeout=60)
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        if row.get("country") != "IND":
            continue
        try:
            mw = float(row["capacity_mw"])
        except (TypeError, ValueError):
            continue
        if mw < min_mw:
            continue
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (TypeError, ValueError):
            continue
        out.append({"name": row.get("name"), "capacity_mw": round(mw, 1), "fuel": row.get("primary_fuel"),
                    "lat": round(lat, 3), "lon": round(lon, 3), "commissioning_year": row.get("commissioning_year") or None,
                    "data_vintage": row.get("year_of_capacity_data") or None})
    return {"source": "WRI Global Power Plant Database, CC BY 4.0 - not real-time; see each plant's own data_vintage", "plants": out}


def company_assets():
    """Real facilities ('owned by', P127) of NSE-listed companies (P414 = NSE, wd:Q638740), from Wikidata.
    Checked live before building this: a single-company query ("Reliance Industries" by name) came back with
    zero results - not because the data doesn't exist, but because that query's property path was wrong. The
    right approach is this one broad query across every NSE-listed company at once, grouped to one row per
    real facility. Coverage is genuinely thin (checked live: ~24 facilities across ~17 of the NIFTY 500's 500
    companies) - shown as what it is, not padded out, and the terminal's own UI says plainly when a company
    has none mapped rather than leaving a blank space that looks broken."""
    query = """SELECT ?companyLabel ?facilityLabel ?coord (SAMPLE(?typeLabel) AS ?type) WHERE {
      ?company wdt:P414 wd:Q638740 .
      ?facility wdt:P127 ?company .
      ?facility wdt:P625 ?coord .
      OPTIONAL { ?facility wdt:P31 ?type0 . ?type0 rdfs:label ?typeLabel . FILTER(LANG(?typeLabel)="en") }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    } GROUP BY ?companyLabel ?facilityLabel ?coord LIMIT 300"""
    r = requests.get("https://query.wikidata.org/sparql", params={"query": query, "format": "json"},
                     headers={**UA, "Accept": "application/sparql-results+json"}, timeout=30)
    r.raise_for_status()
    out = []
    for b in r.json().get("results", {}).get("bindings", []):
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", (b.get("coord") or {}).get("value", ""))
        if not m:
            continue
        out.append({"company": (b.get("companyLabel") or {}).get("value"), "facility": (b.get("facilityLabel") or {}).get("value"),
                    "type": (b.get("type") or {}).get("value"), "lon": round(float(m.group(1)), 3), "lat": round(float(m.group(2)), 3)})
    return {"source": "Wikidata (query.wikidata.org/sparql), CC0 - real but thin coverage, not every company has mapped facilities", "assets": out}


LAYERS = {"shipping_lanes.json": shipping_lanes, "cables.json": submarine_cables, "power_plants_india.json": power_plants_india, "company_assets.json": company_assets}


def main():
    force = "--force" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done, skipped, errors = [], [], []
    for fname, fn in LAYERS.items():
        path = OUT_DIR / fname
        if not force and not stale(path):
            skipped.append(fname)
            continue
        try:
            data = fn()
            data["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            path.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
            done.append(f"{fname} ({path.stat().st_size // 1024} KB)")
        except Exception as exc:
            errors.append(f"{fname}: {type(exc).__name__} {exc}")
    print(f"globe layers: wrote {done or 'none'}; skipped (fresh) {skipped or 'none'}" + (f"; errors: {errors}" if errors else ""))
    if errors and not done and not skipped:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
