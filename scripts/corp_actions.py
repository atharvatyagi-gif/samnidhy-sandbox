"""NSE corporate actions (splits and bonuses) since 2008, for adjusting the survivorship-free price history (docs/blab/HEAD_TO_HEAD.md).

Found 2026-11-17, before any head-to-head result: the old daily files do NOT adjust the previous close for splits (ACE's 10->2
split on 13 Mar 2008 shows as a fall from 344.25 to 70.75), so returns need NSE's own record of splits and bonuses.

  python scripts/corp_actions.py --out ../SAMNIDHY_bhav            all months 2008 to now (resumable)
Source (free, no key): https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=&to_date=
Output: OUT/corporate_actions.json {"months_done": [...], "events": [[symbol, ex_date, factor, subject], ...]} where factor is
what the old price is multiplied by on the ex-date (split 10 -> 2: 0.2; bonus 1:1: 0.5).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPLIT = re.compile(r"(?:split|sub-?division).*?(?:from\s*)?(?:rs\.?|re\.?)\s*([\d.]+).*?to\s*(?:rs\.?|re\.?)\s*([\d.]+)", re.I)
BONUS = re.compile(r"bonus\D*(\d+)\s*:\s*(\d+)", re.I)


def factor(subject):
    """-> price factor for a split or bonus subject, else None. 'Fv Split Rs.10/- To Rs.2/' -> 0.2; 'Bonus 1:1' -> 0.5."""
    s = subject or ""
    m = SPLIT.search(s)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and new != old:
            return new / old
    m = BONUS.search(s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            return b / (a + b)
    return None


def months(start: date, end: date):
    d = date(start.year, start.month, 1)
    while d <= end:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        yield d, min(end, nxt - timedelta(days=1))
        d = nxt


def run(out: Path, start=date(2008, 1, 1), end=None, session=None, log=print):
    end = end or date.today()
    p = out / "corporate_actions.json"
    st = json.loads(p.read_text()) if p.exists() else {"months_done": [], "events": []}
    done = set(st["months_done"])
    have = {(e[0], e[1], round(e[2], 6)) for e in st["events"]}
    if session is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import aladin_ticker_daemon as d
        session = d.NseSession()
    this_month = date.today().strftime("%Y-%m")
    for a, b in months(start, end):
        key = a.strftime("%Y-%m")
        if key in done and key != this_month:
            continue
        j = session.get_json("/api/corporates-corporateActions", {"index": "equities", "from_date": a.strftime("%d-%m-%Y"), "to_date": b.strftime("%d-%m-%Y")},
                             referer="https://www.nseindia.com/companies-listing/corporate-filings-actions", max_tries=3)
        rows = j if isinstance(j, list) else (j or {}).get("data", [])
        for r in rows or []:
            f = factor(r.get("subject"))
            if f is None or not r.get("symbol"):
                continue
            try:
                ex = datetime.strptime(r.get("exDate", ""), "%d-%b-%Y").date().isoformat()
            except ValueError:
                continue
            k = (r["symbol"], ex, round(f, 6))
            if k not in have:
                st["events"].append([r["symbol"], ex, f, r.get("subject")]); have.add(k)
        if key != this_month:
            done.add(key)
        st["months_done"] = sorted(done)
        p.write_text(json.dumps(st, separators=(",", ":")))
        time.sleep(0.4)
    log(f"corporate actions: {len(st['events'])} splits and bonuses, {len(done)} months done")
    return st


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    run(Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
