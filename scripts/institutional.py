"""
Daily FII/FPI and DII net buying in the cash market, from NSE's FII/DII report
(https://www.nseindia.com/reports/fii-dii). NSE only shows the latest day, so each day is saved to
data/institutional/fii_dii.json and the history builds up over time.

If NSE cannot be reached (it sometimes blocks automated requests), nothing is written: the
page keeps the days already saved and says when the last figure is from. Numbers are never estimated.

  python scripts/institutional.py
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import ROOT  # noqa: E402
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from analyst_fields import flow_doc  # noqa: E402

OUT = ROOT / "data" / "institutional" / "fii_dii.json"
PAGE = "https://www.nseindia.com/reports/fii-dii"
API = "https://www.nseindia.com/api/fiidiiTradeReact"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": PAGE,
}
IST = timezone(timedelta(hours=5, minutes=30))
KEEP_DAYS = 250


def fetch():
    last = None
    for attempt in range(3):
        try:
            s = requests.Session()
            s.get(PAGE, headers=HEADERS, timeout=20)          # NSE sets the cookies its API needs
            r = s.get(API, headers=HEADERS, timeout=20)
            r.raise_for_status()
            rows = r.json()
            if not isinstance(rows, list) or not rows:
                raise ValueError("empty report")
            return rows
        except Exception as exc:
            last = exc
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"NSE FII/DII report not available: {last}")


def main():
    rows = fetch()
    day = {}
    for r in rows:
        date = datetime.strptime(r["date"], "%d-%b-%Y").date().isoformat()
        key = "fii" if "FII" in r["category"].upper() else "dii" if "DII" in r["category"].upper() else None
        if key is None:
            continue
        day.setdefault(date, {"date": date})[key] = {
            "in_cr": float(r["buyValue"]), "out_cr": float(r["sellValue"]), "net_cr": float(r["netValue"])}
    hist = flow_doc(json.loads(OUT.read_text(encoding="utf-8"))) if OUT.exists() else {"days": []}      # older saved days used the sources' own names
    by_date = {d["date"]: d for d in hist["days"]}
    for date, d in day.items():
        if "fii" in d and "dii" in d:
            by_date[date] = d
    hist["days"] = sorted(by_date.values(), key=lambda d: d["date"])[-KEEP_DAYS:]
    hist["source"] = "NSE FII/DII report (provisional, cash market, Rs crore)"
    hist["updated_ist"] = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    for date, d in sorted(day.items()):
        print(f"{date}: FII net {d['fii']['net_cr']:+,.2f} Cr, DII net {d['dii']['net_cr']:+,.2f} Cr")
    print(f"saved {len(hist['days'])} day(s) to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
