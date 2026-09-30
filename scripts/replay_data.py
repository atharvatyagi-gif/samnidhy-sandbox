"""
Replay library for the Expert terminal: real 1-minute NSE candles for the NIFTY 50 stocks + the NIFTY 50 index,
one file per trading day -> data/terminal/replay/<YYYY-MM-DD>.json  (+ index.json)

Source: Yahoo Finance 1-minute candles (Yahoo keeps the last ~7 days; run daily, the library grows to KEEP days).
Only completed sessions are saved (today is added after the close). Minutes Yahoo has no trade for are left out,
never filled in. The terminal plays a day back minute by minute ("bar replay", like TradingView's), clearly
labelled REPLAY; nothing here is shown as live.

  python scripts/replay_data.py
"""

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "terminal" / "replay"
IST = timezone(timedelta(hours=5, minutes=30))
KEEP = 20
LISTS = ["https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
         "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"]


def nifty50():
    for u in LISTS:
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            r.raise_for_status()
            syms = pd.read_csv(io.StringIO(r.text))["Symbol"].str.strip().tolist()
            if len(syms) >= 45:
                return syms
        except Exception as exc:
            print("  list", u, exc)
    raise SystemExit("could not load the NIFTY 50 list")


def main():
    syms = nifty50()
    tickers = [s + ".NS" for s in syms] + ["^NSEI"]
    data = yf.download(tickers, period="7d", interval="1m", group_by="ticker", auto_adjust=False, progress=False, prepost=False, threads=True)
    daily = yf.download(tickers, period="1mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    now = datetime.now(IST)
    days = {}
    for t in tickers:
        sym = "^NSEI" if t == "^NSEI" else t[:-3]
        try:
            d = data[t].dropna(subset=["Open", "High", "Low", "Close"])
        except KeyError:
            continue
        if d.empty:
            continue
        d.index = d.index.tz_convert("Asia/Kolkata")
        for day, g in d.groupby(d.index.date):
            if day == now.date() and now.hour * 60 + now.minute < 15 * 60 + 45:
                continue                                      # only completed sessions
            g = g[(g.index.hour * 60 + g.index.minute >= 555) & (g.index.hour * 60 + g.index.minute <= 929)]
            nd = 2 if float(g["Close"].iloc[-1]) >= 1 else 4
            days.setdefault(day.isoformat(), {})[sym] = [[ts.strftime("%H:%M"), round(float(r.Open), nd), round(float(r.High), nd), round(float(r.Low), nd),
                                                           round(float(r.Close), nd), int(r.Volume) if pd.notna(r.Volume) else 0] for ts, r in g.iterrows()]
    OUT.mkdir(parents=True, exist_ok=True)
    added = []
    for day, rows in sorted(days.items()):
        if len(rows) < 40:
            continue
        pcs = {}
        for t in tickers:                                    # previous session's official close from daily candles
            sym = "^NSEI" if t == "^NSEI" else t[:-3]
            try:
                c = daily[t]["Close"].dropna()
            except KeyError:
                continue
            prev = c[c.index.date < datetime.fromisoformat(day).date()]
            if len(prev):
                pcs[sym] = round(float(prev.iloc[-1]), 2)
        (OUT / f"{day}.json").write_text(json.dumps({"date": day, "source": "Yahoo Finance 1-minute candles (NSE)", "pc": pcs, "bars": rows},
                                                    separators=(",", ":")), encoding="utf-8")
        added.append(day)
    files = sorted(OUT.glob("????-??-??.json"))
    for f in files[:-KEEP]:
        f.unlink()
    kept = [f.stem for f in sorted(OUT.glob("????-??-??.json"))]
    (OUT / "index.json").write_text(json.dumps({"days": kept, "symbols": syms, "updated_ist": now.strftime("%d %b %Y, %I:%M %p IST")}), encoding="utf-8")
    print(f"replay library: {len(kept)} days ({kept[0] if kept else '-'} .. {kept[-1] if kept else '-'}); refreshed {len(added)}; {len(syms)} stocks + NIFTY 50")
    return 0


if __name__ == "__main__":
    sys.exit(main())
