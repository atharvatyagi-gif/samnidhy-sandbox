"""Survivorship-free daily price history of every NSE equity, from NSE's own daily files ("bhavcopy"), 2008 to today.

Why: the price caches the site uses cover only companies listed today, which flatters every backtest (survivorship bias).
NSE's daily file lists EVERY security that traded that day, including companies later delisted or merged away.

  python scripts/bhav_history.py --from 2008-01-01 --to 2026-11-17 --out data/bhav      backfill (resumable)
  python scripts/bhav_history.py --days 10 --out data/bhav                               recent days (daily job)

Sources (free, no key; checked 2026-11-17):
  old format to June 2024: https://nsearchives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip
  new format from July 2024: https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
Output: one small gzip CSV per trading day, OUT/YYYY/YYYY-MM-DD.csv.gz (each evening adds one file; nothing is rewritten),
rows "date,symbol,series,open,high,low,close,prevclose,qty,value,isin", equity series only
(EQ, BE, BZ, SM, ST). Returns are built from close / prevclose, which NSE adjusts for splits and bonuses on the ex-date.
A day with no file (holiday, weekend) is recorded in _missing.json so it is not fetched again.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import time
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

SERIES = {"EQ", "BE", "BZ", "SM", "ST"}
UA = "Mozilla/5.0 (B-Lab research desk, educational)"
OLD = "https://nsearchives.nseindia.com/content/historical/EQUITIES/{y}/{mon}/cm{dd}{mon}{y}bhav.csv.zip"
NEW = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
SWITCH = date(2024, 7, 1)


def url_for(d: date):
    if d < SWITCH:
        mon = d.strftime("%b").upper()
        return OLD.format(y=d.year, mon=mon, dd=d.strftime("%d"))
    return NEW.format(ymd=d.strftime("%Y%m%d"))


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(raw: bytes, d: date):
    """-> rows [date, symbol, series, open, high, low, close, prevclose, qty, value, isin] for equity series."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    text = io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8", errors="replace")
    rd = csv.DictReader(text)
    out, day = [], d.isoformat()
    for r in rd:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if "SYMBOL" in r:                                                # old format
            sym, ser = r.get("SYMBOL"), r.get("SERIES")
            vals = (r.get("OPEN"), r.get("HIGH"), r.get("LOW"), r.get("CLOSE"), r.get("PREVCLOSE"), r.get("TOTTRDQTY"), r.get("TOTTRDVAL"), r.get("ISIN"))
        else:                                                            # new (UDiFF) format
            sym, ser = r.get("TckrSymb"), r.get("SctySrs")
            vals = (r.get("OpnPric"), r.get("HghPric"), r.get("LwPric"), r.get("ClsPric"), r.get("PrvsClsgPric"), r.get("TtlTradgVol"), r.get("TtlTrfVal"), r.get("ISIN"))
        if ser not in SERIES or not sym:
            continue
        o, h, lo, c, pc, q, v = (_num(x) for x in vals[:7])
        if not c or c <= 0:
            continue
        out.append([day, sym, ser, o, h, lo, c, pc, int(q or 0), round(v or 0, 2), vals[7]])
    return out


def fetch(d: date, tries=3, get=None):
    """-> raw zip bytes, or None when NSE has no file for that day (holiday)."""
    get = get or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=40).read())
    for k in range(tries):
        try:
            return get(url_for(d))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            time.sleep(2 * (k + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"{d}: NSE archive unreachable after {tries} tries")


def day_file(out: Path, d: date):
    return out / str(d.year) / f"{d.isoformat()}.csv.gz"


def save_day(out: Path, d: date, rows):
    p = day_file(out, d)
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "symbol", "series", "open", "high", "low", "close", "prevclose", "qty", "value", "isin"])
    w.writerows(rows)
    with gzip.GzipFile(p, "wb", mtime=0) as f:                           # mtime 0: the same day always gives the same bytes
        f.write(buf.getvalue().encode("utf-8"))


def load_all(out: Path, start: str = "0000", end: str = "9999"):
    """-> list of rows across all saved days in [start, end] (strings as saved)."""
    rows = []
    for p in sorted(out.glob("*/*.csv.gz")):
        if start <= p.stem[:10] <= end:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                rows += list(csv.reader(f))[1:]
    return rows


def run(start: date, end: date, out: Path, log=print, get=None, budget_s=None, workers=4):
    """Fetch every weekday in [start, end] not saved yet and not a known no-file day, `workers` at a time. Resumable."""
    from concurrent.futures import ThreadPoolExecutor
    out.mkdir(parents=True, exist_ok=True)
    miss_p = out / "_missing.json"
    missing = set(json.loads(miss_p.read_text())) if miss_p.exists() else set()
    todo, d = [], start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in missing and not day_file(out, d).exists():
            todo.append(d)
        d += timedelta(days=1)
    t0, got, none = time.time(), 0, 0

    def one(day):
        time.sleep(0.2)
        raw = fetch(day, get=get)
        return day, (parse(raw, day) if raw is not None else None)

    for k in range(0, len(todo), 40):                                    # in chunks, so progress is saved as it goes
        if budget_s and time.time() - t0 > budget_s:
            log(f"bhav: time budget used; {len(todo) - k} day(s) left (run again to continue)"); break
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for day, rows in ex.map(one, todo[k:k + 40]):
                if rows is None:
                    missing.add(day.isoformat()); none += 1
                elif rows:
                    save_day(out, day, rows); got += 1
                else:
                    missing.add(day.isoformat())
        miss_p.write_text(json.dumps(sorted(missing)))
        log(f"bhav: {got} saved, {none} no-file so far ({k + 40} of {len(todo)} checked)")
    miss_p.write_text(json.dumps(sorted(missing)))
    log(f"bhav: {got} new day(s) saved, {none} day(s) with no file (holidays); {len(missing)} known no-file days in total")
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start"); ap.add_argument("--to", dest="end"); ap.add_argument("--days", type=int)
    ap.add_argument("--out", default="data/bhav"); ap.add_argument("--budget-min", type=float)
    a = ap.parse_args()
    end = date.fromisoformat(a.end) if a.end else date.today()
    start = date.fromisoformat(a.start) if a.start else end - timedelta(days=a.days or 10)
    run(start, end, Path(a.out), budget_s=a.budget_min * 60 if a.budget_min else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
