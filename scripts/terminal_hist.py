"""
Long daily price history for the Expert terminal chart -> data/terminal/daily/<key>.json

NSE's own daily files (scripts/nse_eod.py) are the official prices but are NOT adjusted for splits and
bonus issues, so a 1:5 split would draw as an -80% crash. Charts need split-adjusted history, like
TradingView shows. For every main-board stock and ETF this fetches up to YEARS years of daily candles
from Yahoo Finance, whose Open/High/Low/Close/Volume are split-adjusted (not dividend-adjusted, the same
convention TradingView uses by default).

Checks, so a bad Yahoo series never replaces the NSE one:
  - the last Yahoo close must be within 3% of NSE's own close for that day (else the stock keeps NSE data)
  - a quick update (last month only) that disagrees with the saved history by more than 2% on any common
    day means a split/bonus happened: that stock is re-fetched in full.
Full refetch for everything once a week (Sunday runs or files older than 7 days); other days only the last
month is downloaded and merged. Indices for "Compare" are saved too (NIFTY 50, BANK NIFTY, SENSEX).

The file name for a symbol is key(sym): letters/digits kept, anything else -> _<hex>  (M&M -> M_26M).
terminal.js uses the same rule.

  python scripts/terminal_hist.py
"""

import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
TERM = ROOT / "data" / "terminal"
OUT = TERM / "daily"
META = OUT / "_meta.json"
YEARS = 5
BATCH = 150
INDICES = [("^NSEI", "NIFTY 50"), ("^NSEBANK", "BANK NIFTY"), ("^BSESN", "SENSEX")]


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def rows_of(df):
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    out = []
    for ts, r in df.iterrows():
        c = float(r["Close"])
        nd = 2 if c >= 1 else 4
        out.append([ts.date().isoformat(), round(float(r["Open"]), nd), round(float(r["High"]), nd), round(float(r["Low"]), nd),
                    round(c, nd), int(r["Volume"]) if pd.notna(r["Volume"]) else 0])
    return out


def download(tickers, period):
    """{ticker: rows} for a list of Yahoo tickers, in batches (Yahoo throttles big requests)."""
    got = {}
    for i in range(0, len(tickers), BATCH):
        part = tickers[i:i + BATCH]
        for attempt in range(2):
            try:
                data = yf.download(part, period=period, interval="1d", group_by="ticker", auto_adjust=False,
                                   actions=False, threads=True, progress=False)
                break
            except Exception as exc:
                print(f"  batch {i // BATCH + 1}: {exc}; retrying")
                time.sleep(10)
        else:
            continue
        for t in part:
            try:
                d = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            except KeyError:
                continue
            r = rows_of(d)
            if r:
                got[t] = r
        time.sleep(2)
    return got


def main():
    uni = json.loads((TERM / "universe.json").read_text(encoding="utf-8"))
    stocks = [s for s in uni["stocks"] if s.get("board") == "Main"]
    OUT.mkdir(parents=True, exist_ok=True)
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    today = date.today()
    weekly = datetime.now(timezone.utc).weekday() == 6
    full, quick = [], []
    for s in stocks:
        m = meta.get(s["s"])
        stale = not m or not (OUT / f"{key(s['s'])}.json").exists() or (today - date.fromisoformat(m["full"])).days >= 7
        (full if stale or weekly else quick).append(s)
    print(f"{len(stocks)} main-board symbols: {len(full)} full {YEARS}y downloads, {len(quick)} quick updates")

    nse = {s["s"]: s for s in stocks}

    def check_and_save(sym, rows, is_full):
        e = nse[sym]
        last = {r[0]: r for r in rows}.get(e["date"])
        if last and e.get("c"):
            ratio = last[4] / e["c"]
            if not 0.97 <= ratio <= 1.03:
                return "mismatch"
        path = OUT / f"{key(sym)}.json"
        if not is_full and path.exists():
            old = {r[0]: r for r in json.loads(path.read_text(encoding="utf-8"))["d"]}
            for r in rows:
                o = old.get(r[0])
                if o and o[4] and abs(r[4] / o[4] - 1) > 0.02:
                    return "split"                      # history changed: needs a full refetch
            old.update({r[0]: r for r in rows})
            rows = [old[d] for d in sorted(old)]
        cutoff = (today - timedelta(days=int(YEARS * 365.25) + 5)).isoformat()
        rows = [r for r in rows if r[0] >= cutoff]
        path.write_text(json.dumps({"s": sym, "src": "Yahoo Finance, split-adjusted", "d": rows}, separators=(",", ":")), encoding="utf-8")
        m = meta.setdefault(sym, {"full": today.isoformat()})
        if is_full:
            m["full"] = today.isoformat()
        m["last"] = rows[-1][0] if rows else None
        return "ok"

    stats = {"ok": 0, "mismatch": 0, "split": 0, "missing": 0}
    refetch = []
    for group, period, is_full in ((quick, "1mo", False), (full, f"{YEARS}y", True)):
        if not group:
            continue
        got = download([s["s"] + ".NS" for s in group], period)
        for s in group:
            rows = got.get(s["s"] + ".NS")
            if not rows:
                stats["missing"] += 1
                continue
            res = check_and_save(s["s"], rows, is_full)
            stats[res] += 1
            if res == "split":
                refetch.append(s)
    if refetch:
        print(f"re-fetching {len(refetch)} stocks in full (split or bonus detected)")
        got = download([s["s"] + ".NS" for s in refetch], f"{YEARS}y")
        for s in refetch:
            if s["s"] + ".NS" in got:
                check_and_save(s["s"], got[s["s"] + ".NS"], True)

    idx = download([t for t, _ in INDICES], f"{YEARS}y")
    for t, name in INDICES:
        if t in idx:
            (OUT / f"{key(t)}.json").write_text(json.dumps({"s": name, "src": "Yahoo Finance", "d": idx[t]}, separators=(",", ":")),
                                                encoding="utf-8")
    META.write_text(json.dumps(meta), encoding="utf-8")
    print(f"saved: {stats['ok']} ok · {stats['mismatch']} kept on NSE data (Yahoo price disagreed with NSE) · "
          f"{stats['missing']} not on Yahoo · {len(refetch)} split/bonus refetches · indices: {len(idx)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
