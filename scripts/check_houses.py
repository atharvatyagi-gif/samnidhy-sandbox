"""
Checks data/config/business_houses.json against data/terminal/universe.json. Exits non-zero if a symbol is missing
from the universe (renamed, delisted or mistyped), a symbol sits in two groups, or a group is empty or duplicated.

  python scripts/check_houses.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check(houses_path=ROOT / "data" / "config" / "business_houses.json", universe_path=ROOT / "data" / "terminal" / "universe.json"):
    houses = json.loads(Path(houses_path).read_text(encoding="utf-8"))["houses"]
    universe = {s["s"] for s in json.loads(Path(universe_path).read_text(encoding="utf-8"))["stocks"]}
    problems, seen, ids = [], {}, set()
    for h in houses:
        if h["id"] in ids:
            problems.append(f"duplicate group id {h['id']}")
        ids.add(h["id"])
        if not h["symbols"]:
            problems.append(f"{h['id']}: no symbols")
        for s in h["symbols"]:
            if s not in universe:
                problems.append(f"{h['id']}: {s} is not in universe.json")
            if s in seen and seen[s] != h["id"]:
                problems.append(f"{s} is in both {seen[s]} and {h['id']}")
            if seen.get(s) == h["id"]:
                problems.append(f"{h['id']}: {s} listed twice")
            seen[s] = h["id"]
    return houses, problems


def main():
    houses, problems = check()
    for p in problems:
        print("PROBLEM:", p)
    print(f"{len(houses)} groups, {sum(len(h['symbols']) for h in houses)} symbols, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
