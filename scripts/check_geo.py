"""
Checks data/config/geo_exposure.json against data/terminal/universe.json: every `sym` must exist and every `ind` must
be an exact industry name used by at least one stock. Also checks coordinates and that each region has a query.
Exits non-zero on any problem.

  python scripts/check_geo.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check(cfg_path=ROOT / "data" / "config" / "geo_exposure.json", universe_path=ROOT / "data" / "terminal" / "universe.json"):
    regions = json.loads(Path(cfg_path).read_text(encoding="utf-8"))["regions"]
    stocks = json.loads(Path(universe_path).read_text(encoding="utf-8"))["stocks"]
    syms, inds = {s["s"] for s in stocks}, {s["ind"] for s in stocks if s.get("ind")}
    problems, ids = [], set()
    for r in regions:
        if r["id"] in ids:
            problems.append(f"duplicate region id {r['id']}")
        ids.add(r["id"])
        if not (-90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180):
            problems.append(f"{r['id']}: bad coordinates")
        if not r.get("news_query"):
            problems.append(f"{r['id']}: no news_query")
        if not r.get("exposure"):
            problems.append(f"{r['id']}: no exposure lines")
        for e in r["exposure"]:
            if e.get("dir") not in ("+", "-"):
                problems.append(f"{r['id']}: bad dir {e.get('dir')!r}")
            if "sym" in e and e["sym"] not in syms:
                problems.append(f"{r['id']}: symbol {e['sym']} is not in universe.json")
            if "ind" in e and e["ind"] not in inds:
                problems.append(f"{r['id']}: industry {e['ind']!r} is not an exact universe.json industry")
            if ("sym" in e) == ("ind" in e):
                problems.append(f"{r['id']}: each exposure needs exactly one of sym / ind")
    return regions, problems


def main():
    regions, problems = check()
    for p in problems:
        print("PROBLEM:", p)
    print(f"{len(regions)} regions, {sum(len(r['exposure']) for r in regions)} exposure lines, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
