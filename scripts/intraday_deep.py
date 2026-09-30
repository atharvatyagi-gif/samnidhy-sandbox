"""
Deep intraday history for the Expert terminal's scroll-back (NIFTY 500 + NIFTY 50 + BANK NIFTY):
  m5  = 5-minute candles for the last ~60 days  (Yahoo's limit for 5-minute data)
  h1  = 1-hour candles for the last ~2 years    (Yahoo's limit for hourly data)
-> data/terminal/deep/<key>.json, published by the daily job to the repository's "intraday" branch (replaced
each day, so it never piles up). The chart fetches a stock's file only when you scroll an intraday chart back
past what the website already has, the same way older daily history comes from the "history" branch.
Real Yahoo candles only; missing minutes stay missing.

  python scripts/intraday_deep.py
"""

import json
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from terminal_hist import key

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "terminal" / "deep"
BATCH = 100
INDEXES = ["^NSEI", "^NSEBANK"]


def rows(df):
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return []
    df.index = df.index.tz_convert("Asia/Kolkata")
    nd = 2 if float(df["Close"].iloc[-1]) >= 1 else 4
    return [[ts.strftime("%Y-%m-%d %H:%M"), round(float(r.Open), nd), round(float(r.High), nd), round(float(r.Low), nd), round(float(r.Close), nd),
             int(r.Volume) if pd.notna(r.Volume) else 0] for ts, r in df.iterrows() if 555 <= ts.hour * 60 + ts.minute <= 929]


def fetch(tickers, period, interval):
    got = {}
    for i in range(0, len(tickers), BATCH):
        part = tickers[i:i + BATCH]
        for attempt in range(2):
            try:
                d = yf.download(part, period=period, interval=interval, group_by="ticker", auto_adjust=False, progress=False, threads=True, prepost=False)
                break
            except Exception as exc:
                print("  retry", exc); time.sleep(10)
        else:
            continue
        for t in part:
            try:
                got[t] = rows(d[t] if isinstance(d.columns, pd.MultiIndex) else d)
            except KeyError:
                pass
        time.sleep(2)
    return got


def main():
    syms = pd.read_csv(ROOT / "data" / "universe" / "nifty500.csv")["Symbol"].str.strip().tolist()
    tickers = [s + ".NS" for s in syms] + INDEXES
    m5 = fetch(tickers, "60d", "5m")
    h1 = fetch(tickers, "730d", "1h")
    for per in ("365d", "180d"):                          # recent listings: Yahoo refuses 730 days, try shorter
        miss = [x for x in tickers if not h1.get(x)]
        if miss:
            h1.update({k: v for k, v in fetch(miss, per, "1h").items() if v})
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for t in tickers:
        sym = t[:-3] if t.endswith(".NS") else t
        a, b = m5.get(t) or [], h1.get(t) or []
        if not a and not b:
            continue
        (OUT / f"{key(sym)}.json").write_text(json.dumps({"s": sym, "src": "Yahoo Finance intraday candles", "m5": a, "h1": b}, separators=(",", ":")), encoding="utf-8")
        n += 1
    print(f"deep intraday: {n} symbols · 5-minute from {min((v[0][0] for v in m5.values() if v), default='-')} · hourly from {min((v[0][0] for v in h1.values() if v), default='-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
