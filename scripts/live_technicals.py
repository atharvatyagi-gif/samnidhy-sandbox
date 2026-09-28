"""
Live prices, research-backed price signals and market conditions for the Advanced page.
Run every 15 minutes during market hours (and by the daily update); when the market is closed it
shows the last session and says so.

Per screened stock (data/screener/latest.json):
  - delayed live price (Yahoo Finance), change vs the previous close, today's 5-minute candles
  - Trend: price vs the 200-day moving average, and the 50/200-day crossover
      (Brock, Lakonishok & LeBaron 1992; Faber 2007)
  - Momentum 12-1: return from 12 months ago to 1 month ago, ranked against the NIFTY 500
      (Jegadeesh & Titman 1993)
  - Nearness to the 52-week high (George & Hwang 2004)
  - 1-year volatility, ranked against the NIFTY 500 (low-volatility effect: Blitz & van Vliet 2007;
      Baker, Bradley & Wurgler 2011)
Market conditions: Nifty 50 / Bank Nifty (with the 200-day trend), India VIX, USD/INR, Brent crude,
gold, US 10-year yield, S&P 500, Nikkei 225.

  python scripts/live_technicals.py      saves data/screener/live.json
"""

import bisect
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import ROOT  # noqa: E402

DIR = ROOT / "data" / "screener"
IST = timezone(timedelta(hours=5, minutes=30))
CHART_DAYS = 252            # one trading year on the chart

MARKETS = [  # (Yahoo ticker, name, group, unit)
    ("^NSEI", "Nifty 50", "India", "pts"),
    ("^NSEBANK", "Bank Nifty", "India", "pts"),
    ("^INDIAVIX", "India VIX", "India", "pts"),
    ("INR=X", "US dollar in rupees", "Currency & commodities", "Rs"),
    ("BZ=F", "Brent crude", "Currency & commodities", "$/bbl"),
    ("GC=F", "Gold", "Currency & commodities", "$/oz"),
    ("^TNX", "US 10-year yield", "World", "%"),
    ("^GSPC", "S&P 500 (US)", "World", "pts"),
    ("^N225", "Nikkei 225 (Japan)", "World", "pts"),
]


def r2(x, d=2):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, d)


def percentile(sorted_vals, v):
    """Share of NIFTY 500 stocks with a value at or below v (0-100)."""
    if not sorted_vals or v is None:
        return None
    return round(100 * bisect.bisect_right(sorted_vals, v) / len(sorted_vals), 1)


def since(flags):
    """Date the latest run of equal True/False values began."""
    last = flags.iloc[-1]
    for i in range(len(flags) - 1, -1, -1):
        if flags.iloc[i] != last:
            return str(flags.index[i + 1].date())
    return str(flags.index[0].date())


# ---------------------------------------------------------------- per stock
def analyse(p, ustats):
    t = p["yahoo_ticker"]
    for attempt in range(3):
        try:
            tk = yf.Ticker(t)
            daily = tk.history(period="2y", interval="1d", auto_adjust=True)   # 2y so the 200-day line spans the chart
            intra = tk.history(period="5d", interval="5m", auto_adjust=True)   # 5d: always has the last session
            break
        except Exception as exc:
            if attempt == 2:
                return {"symbol": p["symbol"], "error": f"download failed ({type(exc).__name__}: {str(exc)[:160]})"}
            time.sleep(3 * (attempt + 1))
    daily = daily.dropna(subset=["Close"])
    intra = intra.dropna(subset=["Close"])
    if len(daily) < 210 or intra.empty:
        return {"symbol": p["symbol"], "error": f"not enough price data (daily rows {len(daily)}, 5-min rows {len(intra)})"}
    daily.index = daily.index.tz_convert(IST) if daily.index.tz else daily.index.tz_localize(IST)
    intra.index = intra.index.tz_convert(IST)
    session_day = intra.index[-1].date()
    intra = intra[intra.index.date == session_day]     # only the latest trading session's bars
    prev = daily[daily.index.date < session_day]
    prev_close = float(prev["Close"].iloc[-1])
    price = float(intra["Close"].iloc[-1])
    # today's candle is built from the 5-minute bars, so every signal includes the live price
    today = pd.DataFrame({"Open": [intra["Open"].iloc[0]], "High": [intra["High"].max()],
                          "Low": [intra["Low"].min()], "Close": [price], "Volume": [intra["Volume"].sum()]},
                         index=[pd.Timestamp(session_day, tz=IST)])
    d = pd.concat([prev[["Open", "High", "Low", "Close", "Volume"]], today])
    c = d["Close"]
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    above = (c > sma200)[sma200.notna()]
    golden = (sma50 > sma200)[sma200.notna()]
    trend = {"sma50": r2(sma50.iloc[-1]), "sma200": r2(sma200.iloc[-1]),
             "above_200": bool(above.iloc[-1]), "since": since(above),
             "gap_pct": r2((price / sma200.iloc[-1] - 1) * 100),
             "golden_cross": bool(golden.iloc[-1]), "cross_since": since(golden)}
    mom = float(c.iloc[-22] / c.iloc[-253] - 1) if len(c) >= 253 else None
    hi52, lo52 = float(d["High"].tail(252).max()), float(d["Low"].tail(252).min())
    hi_ratio = price / hi52
    vol = float(np.log(c).diff().tail(252).std() * math.sqrt(252))
    tail = d.tail(CHART_DAYS)
    return {
        "symbol": p["symbol"],
        "price": r2(price), "prev_close": r2(prev_close),
        "change": r2(price - prev_close), "change_pct": r2((price / prev_close - 1) * 100),
        "day_open": r2(intra["Open"].iloc[0]), "day_high": r2(intra["High"].max()), "day_low": r2(intra["Low"].min()),
        "volume": int(intra["Volume"].sum()),
        "session_date": str(session_day), "last_bar_ist": intra.index[-1].strftime("%H:%M"),
        "trend": trend,
        "momentum": {"value": r2(mom, 4), "percentile": percentile(ustats.get("momentum_12_1"), mom)},
        "high52": {"high": r2(hi52), "low": r2(lo52), "ratio": r2(hi_ratio, 4),
                   "percentile": percentile(ustats.get("high_52w_ratio"), hi_ratio)},
        "volatility": {"value": r2(vol, 4), "percentile": percentile(ustats.get("vol_1y"), vol)},
        "series": {
            "daily": [[ts.strftime("%Y-%m-%d"), r2(o), r2(h), r2(l), r2(cl)] for ts, o, h, l, cl in
                      zip(tail.index, tail["Open"], tail["High"], tail["Low"], tail["Close"])],
            "sma50": [r2(x) for x in sma50.tail(CHART_DAYS)],
            "sma200": [r2(x) for x in sma200.tail(CHART_DAYS)],
            "intraday": [[ts.strftime("%H:%M"), r2(o), r2(h), r2(l), r2(cl), int(v) if v == v else None] for ts, o, h, l, cl, v in
                         zip(intra.index, intra["Open"], intra["High"], intra["Low"], intra["Close"], intra["Volume"])],
        },
    }


# ---------------------------------------------------------------- market conditions
def markets():
    tickers = [m[0] for m in MARKETS]
    data = yf.download(tickers, period="14mo", interval="1d", group_by="ticker", auto_adjust=False,
                       threads=True, progress=False)
    out = []
    for tkr, name, group, unit in MARKETS:
        row = {"ticker": tkr, "name": name, "group": group, "unit": unit}
        try:
            s = data[tkr]["Close"].dropna()
        except KeyError:
            s = pd.Series(dtype=float)
        if len(s) < 2:
            row["error"] = "not available"
            out.append(row)
            continue
        row.update({"value": r2(s.iloc[-1]), "prev": r2(s.iloc[-2]),
                    "change_pct": r2((s.iloc[-1] / s.iloc[-2] - 1) * 100),
                    "as_of": str(s.index[-1].date()), "spark": [r2(x) for x in s.tail(60)]})
        if len(s) >= 200:
            sma = s.rolling(200).mean()
            row["sma200"] = r2(sma.iloc[-1])
            row["above_200"] = bool(s.iloc[-1] > sma.iloc[-1])
        if len(s) >= 253:
            row["change_1y_pct"] = r2((s.iloc[-1] / s.iloc[-253] - 1) * 100)
        out.append(row)
    return out


INDICES = [  # World Equity Indices panel of the expert terminal: (Yahoo ticker, short code, name, region)
    ("^GSPC", "SPX", "S&P 500", "Americas"), ("^NDX", "NDX", "Nasdaq 100", "Americas"),
    ("^DJI", "INDU", "Dow Jones Industrials", "Americas"),
    ("^FTSE", "UKX", "FTSE 100", "EMEA"), ("^GDAXI", "DAX", "DAX", "EMEA"), ("^FCHI", "CAC", "CAC 40", "EMEA"),
    ("^N225", "NKY", "Nikkei 225", "Asia/Pacific"), ("^HSI", "HSI", "Hang Seng", "Asia/Pacific"),
    ("^KS11", "KOSPI", "KOSPI", "Asia/Pacific"),
    ("^NSEI", "NIFTY", "Nifty 50", "Asia/Pacific"), ("^BSESN", "SENSEX", "BSE Sensex", "Asia/Pacific"),
    ("^NSEBANK", "NSEBANK", "Nifty Bank", "Asia/Pacific"),
]


def world_indices():
    """Value, net/% change, time of last price (IST) and year-to-date % for each index. Missing -> error."""
    tickers = [i[0] for i in INDICES]
    daily = yf.download(tickers, period="14mo", interval="1d", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    intra = yf.download(tickers, period="5d", interval="15m", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    today = datetime.now(IST).date()
    out = []
    for tkr, code, name, region in INDICES:
        row = {"ticker": tkr, "code": code, "name": name, "region": region}
        try:
            d = daily[tkr]["Close"].dropna()
        except KeyError:
            d = pd.Series(dtype=float)
        if len(d) < 2:
            row["error"] = "not available"
            out.append(row)
            continue
        last, when, day = float(d.iloc[-1]), None, d.index[-1].date()
        try:
            i = intra[tkr]["Close"].dropna()
            if len(i):
                # dates are compared in the exchange's own timezone (a US Friday close is Saturday in IST)
                last, day, when = float(i.iloc[-1]), i.index[-1].date(), i.index[-1].tz_convert(IST)
        except KeyError:
            pass
        # previous close = last daily close before the latest price's own trading day
        prior = d[[ix.date() < day for ix in d.index]]
        prev = float(prior.iloc[-1]) if len(prior) else float(d.iloc[-2])
        ye = d[[ix.year < day.year for ix in d.index]]
        row.update({
            "value": r2(last), "net": r2(last - prev), "pct": r2((last / prev - 1) * 100),
            "time": (when.strftime("%H:%M") if when.date() == today else when.strftime("%d %b")) if when is not None else str(d.index[-1].date()),
            "ytd": r2((last / float(ye.iloc[-1]) - 1) * 100) if len(ye) else None,
        })
        out.append(row)
    return out


def headlines(picks):
    """Latest real headlines from Yahoo Finance for the screened stocks and the main indices."""
    items = {}
    for sym, t in [(p["symbol"], p["yahoo_ticker"]) for p in picks] + [("NIFTY", "^NSEI"), ("SPX", "^GSPC")]:
        try:
            news = yf.Ticker(t).news or []
        except Exception:
            continue
        for n in news:
            c = n.get("content") or {}
            nid, title, when = c.get("id") or n.get("id"), c.get("title"), c.get("pubDate") or c.get("displayTime")
            if not (nid and title and when):
                continue
            it = items.setdefault(nid, {"title": title, "time_utc": when,
                                        "publisher": ((c.get("provider") or {}).get("displayName")),
                                        "url": ((c.get("canonicalUrl") or {}).get("url")), "tickers": []})
            if sym not in it["tickers"]:
                it["tickers"].append(sym)
    return sorted(items.values(), key=lambda x: x["time_utc"], reverse=True)[:60]


def market_state(now_ist, session_day):
    open_t, close_t = now_ist.replace(hour=9, minute=15, second=0), now_ist.replace(hour=15, minute=30, second=0)
    return "open" if session_day == now_ist.date() and open_t <= now_ist <= close_t else "closed"


def main():
    screen = json.loads((DIR / "latest.json").read_text(encoding="utf-8"))
    picks, ustats = screen["picks"], screen.get("universe_stats", {})
    with ThreadPoolExecutor(max_workers=5) as ex:
        rows = list(ex.map(lambda p: analyse(p, ustats), picks))
    try:
        weather = markets()
    except Exception as exc:
        weather = [{"ticker": m[0], "name": m[1], "group": m[2], "unit": m[3],
                    "error": f"not available ({type(exc).__name__})"} for m in MARKETS]
    try:
        wei = world_indices()
    except Exception as exc:
        wei = [{"ticker": i[0], "code": i[1], "name": i[2], "region": i[3], "error": f"not available ({type(exc).__name__})"} for i in INDICES]
    try:
        news = headlines(picks)
    except Exception:
        news = []
    ok = [r for r in rows if "error" not in r]
    now = datetime.now(IST)
    DIR.mkdir(parents=True, exist_ok=True)
    if not ok:
        # Publish the reason (no prices are ever invented); the page shows "Prices unavailable".
        (DIR / "live.json").write_text(json.dumps({
            "error": "no live prices could be fetched",
            "generated_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "generated_ist": now.strftime("%d %b %Y, %I:%M %p IST"),
            "markets": weather, "indices": wei, "news": news, "stocks": {r["symbol"]: r for r in rows}}, allow_nan=False), encoding="utf-8")
        for r in rows:
            print(f"  {r['symbol']}: {r['error']}")
        raise RuntimeError("no live prices could be fetched")
    session = max(r["session_date"] for r in ok)
    out = {
        "generated_ist": now.strftime("%d %b %Y, %I:%M %p IST"),
        "generated_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "market": market_state(now, datetime.fromisoformat(session).date()),
        "session_date": session,
        "last_bar_ist": max(r["last_bar_ist"] for r in ok if r["session_date"] == session),
        "markets": weather,
        "indices": wei,
        "news": news,
        "stocks": {r["symbol"]: r for r in rows},
    }
    (DIR / "live.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"market {out['market']}, session {session}, last bar {out['last_bar_ist']} IST; {len(news)} headlines")
    for w in wei:
        print(f"  {w['code']:<8} {w.get('value', w.get('error'))!s:>11} {w.get('pct', '')!s:>6}% {w.get('time', '')!s:>7} YTD {w.get('ytd', '')}")
    for m in weather:
        extra = f"  200-DMA {'above' if m['above_200'] else 'below'}" if "above_200" in m else ""
        print(f"  {m['name']:<22} {m.get('value', m.get('error'))!s:>12} {m.get('change_pct', '')!s:>7}%{extra}")
    print(f"{'Stock':<11} {'Price':>9} {'Chg%':>6}  {'vs200DMA':>8} {'50/200':>7}  {'Mom12-1':>8} {'pctl':>5}  {'52wH':>6} {'pctl':>5}  {'Vol':>6} {'pctl':>5}")
    for r in rows:
        if "error" in r:
            print(f"{r['symbol']:<11} ERROR {r['error']}")
            continue
        tr, mo, hi, vo = r["trend"], r["momentum"], r["high52"], r["volatility"]
        print(f"{r['symbol']:<11} {r['price']:>9.2f} {r['change_pct']:>+6.2f}  {tr['gap_pct']:>+7.1f}% {('golden' if tr['golden_cross'] else 'death'):>7}  "
              f"{(mo['value'] or 0) * 100:>+7.1f}% {mo['percentile'] or 0:>5.0f}  {hi['ratio'] * 100:>5.1f}% {hi['percentile'] or 0:>5.0f}  "
              f"{vo['value'] * 100:>5.1f}% {vo['percentile'] or 0:>5.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
