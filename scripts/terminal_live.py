"""
Delayed live prices for every main-board NSE stock that Yahoo Finance carries (~2,500), for the terminal.
Run every 15 minutes in market hours (and by the daily update, when it captures the last session).

Reads data/terminal/universe.json (from nse_eod.py) and writes
  data/terminal/quotes.json        latest delayed price for each covered stock
  data/terminal/intra/<k>.json     per stock {"d": latest session 5-min candles, "w": last 5 sessions 15-min candles},
                                   grouped by the symbol's first character
Stocks Yahoo does not carry (all SME stocks, some others) keep NSE's official end-of-day price and are
marked as such in the terminal. Nothing is estimated.

  python scripts/terminal_live.py
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import ROOT  # noqa: E402

OUT = ROOT / "data" / "terminal"
INTRA = OUT / "intra"
IST = timezone(timedelta(hours=5, minutes=30))
BATCH = 150


def shard(sym):
    c = sym[0].upper()
    return c if c.isalpha() else "0"


def r2(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else round(x, 2)


def fetch(tickers):
    got = {}
    for i in range(0, len(tickers), BATCH):
        part = tickers[i:i + BATCH]
        try:
            q = yf.download(part, period="5d", interval="5m", group_by="ticker", threads=4, progress=False, auto_adjust=True)
        except Exception:
            time.sleep(5)
            continue
        for t in part:
            try:
                d = q[t].dropna(subset=["Close"])
            except KeyError:
                continue
            if len(d):
                got[t] = d
        time.sleep(1.5)
    return got


def main():
    uni = json.loads((OUT / "universe.json").read_text(encoding="utf-8"))
    eod_date = uni["session_date"]
    stocks = {s["s"]: s for s in uni["stocks"] if s["board"] == "Main" and s["series"] in ("EQ", "BE", "BZ")}
    tickers = [s + ".NS" for s in stocks]
    t0 = time.time()
    got = fetch(tickers)
    missing = [t for t in tickers if t not in got]
    if missing:                                           # one slower retry pass for throttled batches
        time.sleep(10)
        got.update(fetch(missing))
    quotes, intra = {}, {}
    last_ts, rejected = None, 0
    for t, d in got.items():
        sym = t[:-3]
        d.index = d.index.tz_convert(IST)
        day = d.index[-1].date()
        full = d                                          # up to 5 sessions, for the 5D / 15m / 1h views
        d = d[d.index.date == day]
        s = stocks[sym]
        # previous close: NSE's official close for the session before this one when NSE's file has it;
        # otherwise (NSE's file not in yet) the previous session's last traded price from the same 5-min data
        prior_days = sorted({x for x in full.index.date if x < day})
        prev_day = prior_days[-1].isoformat() if prior_days else None
        if day.isoformat() == eod_date:
            prev = s["pc"]
        elif s["date"] == prev_day:
            prev = s["c"]
        elif prev_day and day.isoformat() > eod_date:
            prev = float(full[full.index.date == prior_days[-1]]["Close"].iloc[-1])
        else:
            continue                                      # Yahoo is behind NSE's own file: keep NSE's EOD
        last = float(d["Close"].iloc[-1])
        ref = s["c"] or prev
        if not prev or not ref or not (0.6 < last / ref < 1.6):
            rejected += 1
            continue                                      # keep NSE's official price instead
        quotes[sym] = {"p": r2(last), "chg": r2(last - prev) if prev else None,
                       "pct": r2((last / prev - 1) * 100) if prev else None,
                       "o": r2(d["Open"].iloc[0]), "h": r2(d["High"].max()), "l": r2(d["Low"].min()),
                       "v": int(d["Volume"].sum()), "t": d.index[-1].strftime("%H:%M"), "d": day.isoformat()}
        w = full.resample("15min", label="left", closed="left").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])
        intra.setdefault(shard(sym), {})[sym] = {
            "d": [[ts.strftime("%H:%M"), r2(o), r2(h), r2(l), r2(c), int(v)] for ts, o, h, l, c, v in
                  zip(d.index, d["Open"], d["High"], d["Low"], d["Close"], d["Volume"])],        # latest session, 5-min
            "w": [[ts.strftime("%Y-%m-%d %H:%M"), r2(o), r2(h), r2(l), r2(c), int(v)] for ts, o, h, l, c, v in
                  zip(w.index, w["Open"], w["High"], w["Low"], w["Close"], w["Volume"])],        # last 5 sessions, 15-min
        }
        last_ts = max(last_ts or d.index[-1], d.index[-1])
    if not quotes:
        raise RuntimeError("no live prices could be fetched; the terminal keeps NSE's end-of-day prices")
    now = datetime.now(IST)
    session = max(q["d"] for q in quotes.values())
    open_t, close_t = now.replace(hour=9, minute=15, second=0), now.replace(hour=15, minute=30, second=0)
    INTRA.mkdir(parents=True, exist_ok=True)
    for p in INTRA.glob("*.json"):
        p.unlink()
    for k, v in intra.items():
        (INTRA / f"{k}.json").write_text(json.dumps(v, separators=(",", ":")), encoding="utf-8")
    out = {"generated_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
           "generated_ist": now.strftime("%d %b %Y, %I:%M %p IST"),
           "session_date": session, "last_bar_ist": last_ts.strftime("%H:%M") if last_ts else None,
           "market": "open" if session == now.date().isoformat() and open_t <= now <= close_t else "closed",
           "covered": len(quotes), "main_board": len(stocks), "rejected": rejected, "quotes": quotes}
    (OUT / "quotes.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"live: {len(quotes)}/{len(stocks)} main-board stocks ({rejected} rejected: price disagreed with NSE), session {session}, last bar {out['last_bar_ist']} IST, "
          f"{time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
