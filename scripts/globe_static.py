"""
Globe: slow-changing reference layers for the Expert terminal's map, written once (re-run by hand to refresh):

  data/globe/layers/lanes.json   Global shipping lanes (Major / Middle / Minor), simplified for the web.
                                 Benden, P. (2022). Global Shipping Lanes. Zenodo, doi:10.5281/zenodo.6361763,
                                 georeferenced from the CIA "Map of the World's Oceans" (2012). CC BY 4.0.
                                 https://github.com/newzealandpaul/Shipping-Lanes
  data/globe/layers/power_in.json  India power plants of 100 MW and above, from the WRI Global Power Plant
                                 Database v1.3 (CC BY 4.0, https://github.com/wri/global-power-plant-database).
                                 Its data vintage is 2019-2021, so it is labelled as reference data, not live.

Both are real, published datasets used as they are: lines are only simplified (Douglas-Peucker, ~2 km) and
coordinates rounded to 3 decimals so the files stay small; no feature is added or moved.

  python scripts/globe_static.py
"""

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "globe" / "layers"
LANES_URL = "https://raw.githubusercontent.com/newzealandpaul/Shipping-Lanes/main/data/Shipping_Lanes_v1.geojson"
GPPD_URL = "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv"


def _perp(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** 0.5


def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0, None
        for k in range(i + 1, j):
            d = _perp(pts[k], pts[i], pts[j])
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def lanes():
    gj = requests.get(LANES_URL, timeout=120).json()
    out = []
    for f in gj["features"]:
        typ = (f.get("properties") or {}).get("Type") or "Minor"
        g = f["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        for part in parts:
            s = simplify([tuple(c[:2]) for c in part], 0.02)
            if len(s) >= 2:
                out.append({"t": typ, "c": [[round(y, 3), round(x, 3)] for x, y in s]})   # Leaflet order: lat, lon
    return {"source": "Benden (2022), Global Shipping Lanes, CC BY 4.0, from the CIA Map of the World's Oceans (2012)",
            "url": "https://github.com/newzealandpaul/Shipping-Lanes", "lines": out}


def power_in():
    text = requests.get(GPPD_URL, timeout=180).text
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["country"] != "IND":
            continue
        mw = float(r["capacity_mw"] or 0)
        if mw < 100:
            continue
        rows.append({"n": r["name"].strip(), "mw": round(mw), "f": r["primary_fuel"], "lat": round(float(r["latitude"]), 4),
                     "lon": round(float(r["longitude"]), 4), "y": r["commissioning_year"][:4] or None, "o": r["owner"].strip() or None})
    rows.sort(key=lambda x: -x["mw"])
    return {"source": "WRI Global Power Plant Database v1.3, CC BY 4.0 (data vintage 2019-2021)",
            "url": "https://datasets.wri.org/dataset/globalpowerplantdatabase", "plants": rows}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, fn in (("lanes", lanes), ("power_in", power_in)):
        d = fn()
        d["generated_utc"] = stamp
        (OUT / f"{name}.json").write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
        print(f"{name}: {(OUT / f'{name}.json').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
