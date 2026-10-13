"""
NSE board-meeting calendar, 2012 to today: which company meets on which day for what (results, dividend, fund raising, bonus, split), and WHEN it told the
exchange. The intimation time is what makes it usable for forecasting: a forecast made on a Friday may only use meetings intimated before that Friday.

  python scripts/events_calendar.py [--start 2012-01] [--end YYYY-MM]   -> data/aladin_movers/board_meetings.csv.gz (resumes; months already fetched are kept)

Source: NSE's own /api/corporate-board-meetings (the same cookie-handshake session as the tick daemon, about 3 requests a second). Nothing is inferred.
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "aladin_movers" / "board_meetings.csv.gz"
COLS = ["sym", "meeting", "intimated", "purpose", "results"]


def months(start, end):
    p = pd.Period(start, "M")
    while p <= pd.Period(end, "M"):
        yield p
        p += 1


def parse(rows):
    out = []
    for r in rows or []:
        sym, md, ts = r.get("bm_symbol"), r.get("bm_date"), r.get("bm_timestamp")
        if not sym or not md:
            continue
        purpose = " ".join(x for x in (r.get("bm_purpose"), (r.get("bm_desc") or "")[:300]) if x)
        try:
            mdt = pd.to_datetime(md, format="%d-%b-%Y")
            idt = pd.to_datetime(ts, format="%d-%b-%Y %H:%M:%S") if ts else pd.NaT
        except (ValueError, TypeError):
            continue
        out.append({"sym": sym, "meeting": mdt.date().isoformat(), "intimated": idt.isoformat() if not pd.isna(idt) else None,
                    "purpose": (r.get("bm_purpose") or "")[:80], "results": int("result" in purpose.lower())})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--start", default="2012-01"); ap.add_argument("--end", default=date.today().strftime("%Y-%m")); a = ap.parse_args()
    from aladin_ticker_daemon import NseSession
    s = NseSession(); OUT.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame(columns=COLS)
    done = set(pd.to_datetime(old["meeting"]).dt.to_period("M").astype(str)) if len(old) else set()
    last = pd.Period(a.end, "M"); rows = []
    for p in months(a.start, a.end):
        if str(p) in done and p < last - 1:                     # the latest two months are always fetched again (new intimations)
            continue
        f, t = p.start_time.strftime("%d-%m-%Y"), p.end_time.strftime("%d-%m-%Y")
        try:
            r = s.get_json(f"/api/corporate-board-meetings?index=equities&from_date={f}&to_date={t}")
        except Exception as e:  # noqa: BLE001
            print(f"{p}: failed ({type(e).__name__}), will be retried next run"); continue
        got = parse(r if isinstance(r, list) else []); rows += got; print(f"{p}: {len(got)} meetings", flush=True)
        time.sleep(0.4)
    new = pd.DataFrame(rows, columns=COLS)
    allr = pd.concat([old, new]).drop_duplicates(["sym", "meeting", "purpose"], keep="last").sort_values(["meeting", "sym"])
    allr.to_csv(OUT, index=False)
    print(f"board meetings: {len(allr):,} rows, {allr['sym'].nunique():,} companies, {allr['meeting'].min()} to {allr['meeting'].max()}, results meetings {int(allr['results'].sum()):,}")


if __name__ == "__main__":
    main()
