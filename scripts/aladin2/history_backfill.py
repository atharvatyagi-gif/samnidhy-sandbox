"""
ALADIN 2.0 history backfill: longer, free, public history for the learner. Resumable; polite (one request at a time, a short pause); never committed.

  delivery   NSE sec_bhavdata_full_DDMMYYYY.csv  (delivery %, 2020 onward; earlier dates do not exist on NSE)  -> data/terminal/aladin2/deliv/<date>.csv.gz
  fno        NSE F&O bhavcopy (old format to 2024-07-05, UDiFF after), reduced to one row per underlying:
             futures open interest, its change, call and put open interest                                     -> data/terminal/aladin2/fno/<date>.json
  macro      Yahoo daily: India VIX, USDINR, Brent, S&P 500, Nikkei; FRED DGS10 when FRED_API_KEY is set       -> data/terminal/aladin2/macro/<name>.json
A date with no file (holiday, or NSE does not have it) is recorded in _none.json and not asked for again. Prices are NOT fetched here: daily bars already
come from data/terminal/daily + data/terminal/archive (the depth per stock is reported by `--report`).

  python scripts/aladin2/history_backfill.py --what delivery,fno,macro [--start 2020-01-01]
  python scripts/aladin2/history_backfill.py --report
"""
import argparse
import gzip
import io
import json
import os
import sys
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent.parent
_MAIN = ROOT.parent / "SAMNIDHY_EDUCATIONAL_DASHBOARD" / "data" / "terminal"        # the main working tree holds the price cache; this worktree has none
TERM = Path(os.environ["ALADIN2_TERM"]) if os.environ.get("ALADIN2_TERM") else (_MAIN if _MAIN.exists() and not (ROOT / "data" / "terminal" / "daily").exists() else ROOT / "data" / "terminal")
OUT = TERM / "aladin2"
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Referer": "https://www.nseindia.com/"}
PAUSE = 0.35
UDIFF_FROM = date(2024, 7, 8)                      # NSE switched the derivatives file format on this date
MACRO = {"india_vix": "^INDIAVIX", "usdinr": "INR=X", "brent": "BZ=F", "sp500": "^GSPC", "nikkei": "^N225"}


def get(url, tries=3):
    """-> bytes, or None when NSE has no file for this date (404). Raises after repeated network or 403/5xx failures."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEAD, timeout=40)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"{url}: {last}")


def weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _none_set(folder):
    p = folder / "_none.json"
    return p, set(json.loads(p.read_text())) if p.exists() else set()


def delivery(start, end):
    folder = OUT / "deliv"; folder.mkdir(parents=True, exist_ok=True)
    nonef, none = _none_set(folder); new = 0
    for d in weekdays(start, end):
        k = d.isoformat()
        if (folder / f"{k}.csv.gz").exists() or (k in none and (end - d).days > 5):
            continue
        raw = get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv")
        time.sleep(PAUSE)
        if raw is None:
            none.add(k); continue
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding="latin-1"); df.columns = [c.strip() for c in df.columns]; df["SYMBOL"]
        except Exception as e:                                       # noqa: BLE001  an error page or an odd file: recorded, not guessed at
            print(f"delivery {k}: unreadable ({type(e).__name__}), skipped"); none.add(k); continue
        for c in ("SYMBOL", "SERIES"):
            df[c] = df[c].astype(str).str.strip()
        df = df[df["SERIES"].isin(["EQ", "BE", "BZ"])]
        df["DELIV_PER"] = pd.to_numeric(df["DELIV_PER"].astype(str).str.strip(), errors="coerce")
        df["DELIV_QTY"] = pd.to_numeric(df["DELIV_QTY"].astype(str).str.strip(), errors="coerce")
        with gzip.open(folder / f"{k}.csv.gz", "wt", encoding="utf-8") as f:
            df[["SYMBOL", "SERIES", "CLOSE_PRICE", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"]].to_csv(f, index=False)
        new += 1
        if new % 50 == 0:
            nonef.write_text(json.dumps(sorted(none))); print(f"delivery: {new} new, at {k}", flush=True)
    nonef.write_text(json.dumps(sorted(none))); print(f"delivery: done, {new} new files")


def _fno_url(d):
    if d >= UDIFF_FROM:
        return f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{d:%Y}/{d:%b}".replace(f"{d:%b}", d.strftime("%b").upper()) + f"/fo{d:%d}{d.strftime('%b').upper()}{d:%Y}bhav.csv.zip"


def reduce_fno(raw, d):
    """One row per underlying: {sym: [fut_oi, fut_oi_chg, call_oi, put_oi]}. Index and stock derivatives are both kept (the sym tells them apart in analysis)."""
    z = zipfile.ZipFile(io.BytesIO(raw)); df = pd.read_csv(z.open(z.namelist()[0]), encoding="latin-1"); df.columns = [c.strip() for c in df.columns]
    if d >= UDIFF_FROM:
        s, t, oi, ch, op = df["TckrSymb"].str.strip(), df["FinInstrmTp"].str.strip(), df["OpnIntrst"], df["ChngInOpnIntrst"], df["OptnTp"].astype(str).str.strip()
        fut, opt = t.isin(["STF", "IDF"]), t.isin(["STO", "IDO"])
    else:
        s, t, oi, ch, op = df["SYMBOL"].str.strip(), df["INSTRUMENT"].str.strip(), df["OPEN_INT"], df["CHG_IN_OI"], df["OPTION_TYP"].astype(str).str.strip()
        fut, opt = t.isin(["FUTSTK", "FUTIDX"]), t.isin(["OPTSTK", "OPTIDX"])
    X = pd.DataFrame({"s": s, "oi": pd.to_numeric(oi, errors="coerce"), "ch": pd.to_numeric(ch, errors="coerce"), "fut": fut, "ce": opt & (op == "CE"), "pe": opt & (op == "PE")})
    out = {}
    for sym, g in X.groupby("s"):
        out[sym] = [int(g.loc[g.fut, "oi"].sum()), int(g.loc[g.fut, "ch"].sum()), int(g.loc[g.ce, "oi"].sum()), int(g.loc[g.pe, "oi"].sum())]
    return out


def fno(start, end):
    folder = OUT / "fno"; folder.mkdir(parents=True, exist_ok=True)
    nonef, none = _none_set(folder); new = 0
    for d in weekdays(start, end):
        k = d.isoformat()
        if (folder / f"{k}.json").exists() or (k in none and (end - d).days > 5):
            continue
        raw = get(_fno_url(d)); time.sleep(PAUSE)
        if raw is None:
            none.add(k); continue
        (folder / f"{k}.json").write_text(json.dumps({"fmt": "udiff" if d >= UDIFF_FROM else "old", "cols": ["fut_oi", "fut_oi_chg", "call_oi", "put_oi"], "d": reduce_fno(raw, d)}, separators=(",", ":")))
        new += 1
        if new % 50 == 0:
            nonef.write_text(json.dumps(sorted(none))); print(f"fno: {new} new, at {k}", flush=True)
    nonef.write_text(json.dumps(sorted(none))); print(f"fno: done, {new} new files")


def macro():
    folder = OUT / "macro"; folder.mkdir(parents=True, exist_ok=True)
    for name, sym in MACRO.items():
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}?period1=946684800&period2=" + str(int(time.time()) + 86400) + "&interval=1d", headers=HEAD, timeout=40); r.raise_for_status()
            res = r.json()["chart"]["result"][0]; ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
            rows = [[datetime.fromtimestamp(t, UTC).date().isoformat(), round(c, 4)] for t, c in zip(ts, cl) if c is not None]
            (folder / f"{name}.json").write_text(json.dumps({"src": f"Yahoo {sym}", "d": rows}, separators=(",", ":"))); print(f"macro {name}: {len(rows)} days from {rows[0][0]}")
        except Exception as e:                                       # noqa: BLE001
            print(f"macro {name}: NOT AVAILABLE ({e})")
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        for f in (TERM.parent.parent / ".env", ROOT / ".env"):          # tiny .env reader (no dependency); the value is never printed
            if f.exists() and not key:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.startswith("FRED_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        print("macro us10y: FRED_API_KEY not set, not measured"); return
    try:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={"series_id": "DGS10", "file_type": "json", "api_key": key}, timeout=40); r.raise_for_status()
        rows = [[o["date"], float(o["value"])] for o in r.json()["observations"] if o["value"] not in (".", "")]
        (folder / "us10y.json").write_text(json.dumps({"src": "FRED DGS10", "d": rows}, separators=(",", ":"))); print(f"macro us10y: {len(rows)} days from {rows[0][0]}")
    except Exception as e:                                           # noqa: BLE001
        print("macro us10y: NOT AVAILABLE (", type(e).__name__, ")")       # never print the request: it carries the key


def report():
    t = TERM
    n = {}
    for f in (t / "daily").glob("*.json"):
        a = json.load(open(f)); a = a.get("d", []) if isinstance(a, dict) else a
        g = t / "archive" / f.name
        b = json.load(open(g)) if g.exists() else []; b = b.get("d", []) if isinstance(b, dict) else b
        n[f.stem] = len({r[0] for r in a} | {r[0] for r in b})
    s = pd.Series(n)
    print(f"daily depth: {len(s)} stocks, median {int(s.median())} bars, >=750: {(s >= 750).sum()}, >=2500: {(s >= 2500).sum()}")
    for sub in ("deliv", "fno"):
        fs = sorted(OUT.joinpath(sub).glob("2*"))
        print(f"{sub}: {len(fs)} files" + (f", {fs[0].stem[:10]} .. {fs[-1].stem[:10]}" if fs else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", default="delivery,fno,macro"); ap.add_argument("--start", default="2020-01-01"); ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        report(); sys.exit()
    s, e = date.fromisoformat(a.start), date.today()
    for w in a.what.split(","):
        {"delivery": lambda: delivery(s, e), "fno": lambda: fno(s, e), "macro": macro}[w.strip()]()
