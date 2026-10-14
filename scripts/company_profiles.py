"""
Sector, industry and business description of every listed company (not just the NIFTY 500), for the NEXUS link-prediction
model (scripts/nexus_predict.py). Source: Yahoo Finance's company profile. ETFs are skipped. A company Yahoo has no
profile for (most SME-board stocks) is recorded as {"none": date} and retried after RETRY_DAYS; nothing is guessed.

  python scripts/company_profiles.py [--max N]     -> data/nexus_predict/profiles.json (resumes: missing first, then the oldest)
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "data" / "terminal" / "universe.json"
OUT = ROOT / "data" / "nexus_predict" / "profiles.json"
REFRESH_DAYS, RETRY_DAYS, DESC_CHARS = 90, 30, 900


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def companies(universe):
    return sorted({s["s"] for s in universe.get("stocks", []) if not s.get("etf")})


def due(symbols, old, today, cap):
    """Missing first, then profiles older than REFRESH_DAYS (or empty answers older than RETRY_DAYS), oldest first."""
    def age(sym):
        r = old.get(sym)
        if not r:
            return None
        return (today - date.fromisoformat(r.get("at") or r.get("none"))).days
    missing = [s for s in symbols if s not in old]
    stale = sorted((s for s in symbols if s in old and age(s) >= (RETRY_DAYS if "none" in old[s] else REFRESH_DAYS)),
                   key=lambda s: -age(s))
    return (missing + stale)[:cap]


def row_from_info(info, today):
    sec, ind, desc = (info or {}).get("sector"), (info or {}).get("industry"), (info or {}).get("longBusinessSummary")
    if not (sec or ind or desc):
        return {"none": today.isoformat()}
    return {"sec": sec or None, "ind": ind or None, "desc": (desc or "")[:DESC_CHARS] or None, "at": today.isoformat()}


def fetch(sym):
    import yfinance as yf
    for attempt in range(3):
        try:
            return sym, yf.Ticker(sym + ".NS").info
        except Exception:  # noqa: BLE001 - network/rate limit: retry, then give up for this run (not recorded)
            time.sleep(3 * (attempt + 1))
    return sym, False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=4000)
    a = ap.parse_args(argv)
    uni = load(UNIVERSE, {})
    if not uni.get("stocks"):
        print("profiles: no data/terminal/universe.json; nothing done")
        return 0
    old = load(OUT, {}).get("cos", {})
    today = date.today()
    todo = due(companies(uni), old, today, a.max)
    t = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (sym, info) in enumerate(ex.map(fetch, todo), 1):
            if info is not False:
                old[sym] = row_from_info(info, today)
            if i % 250 == 0:
                print(f"  {i}/{len(todo)} ({time.time() - t:.0f} s)", flush=True)
                OUT.write_text(json.dumps({"v": 1, "cos": old}, separators=(",", ":")), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"v": 1, "src": "Yahoo Finance company profile", "cos": old}, separators=(",", ":")), encoding="utf-8")
    have = sum(1 for r in old.values() if r.get("ind"))
    print(f"profiles: {len(todo)} fetched this run; {have} of {len(companies(uni))} companies have an industry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
