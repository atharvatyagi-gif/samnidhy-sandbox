"""
Live prices and technicals for the screened stocks (data/screener/latest.json).
Run every 15 minutes during market hours; also fine to run when the market is closed
(it then shows the last session and says so).

For each stock:
  - live price (Yahoo Finance, a few minutes delayed), change vs the previous close, today's 5-minute candles
  - Heikin-Ashi candles (daily, last 6 months, and today's 5-minute)
  - RSI (14, Wilder) on daily closes and on today's 5-minute closes
  - Supertrend (ATR 10, multiplier 3) on daily candles
  - Fibonacci retracement between the 6-month swing high and low

  python scripts/live_technicals.py      saves data/screener/live.json
"""

import json
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
FIB = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
SWING_DAYS = 126            # about 6 months of trading days


# ---------------------------------------------------------------- indicators
def heikin_ashi(df):
    """HA close = average of O,H,L,C; HA open = midpoint of the previous HA candle."""
    ha_c = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    ha_o = np.empty(len(df))
    ha_o[0] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_o[i] = (ha_o[i - 1] + ha_c.iloc[i - 1]) / 2
    ha_o = pd.Series(ha_o, index=df.index)
    ha_h = pd.concat([df["High"], ha_o, ha_c], axis=1).max(axis=1)
    ha_l = pd.concat([df["Low"], ha_o, ha_c], axis=1).min(axis=1)
    return pd.DataFrame({"o": ha_o, "h": ha_h, "l": ha_l, "c": ha_c})


def rsi(close, n=14):
    """Wilder's RSI: 100 - 100 / (1 + average gain / average loss)."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(~gain.isna())


def supertrend(df, n=10, mult=3.0):
    """Classic Supertrend: bands at (high+low)/2 +/- mult x ATR(n); the line flips when price crosses it."""
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    mid = (h + l) / 2
    ub, lb = (mid + mult * atr).values, (mid - mult * atr).values
    fu, fl = ub.copy(), lb.copy()
    line = np.full(len(df), np.nan)
    up = np.ones(len(df), dtype=bool)
    cv = c.values
    for i in range(1, len(df)):
        if np.isnan(atr.iloc[i]):
            continue
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or cv[i - 1] > fu[i - 1] or np.isnan(fu[i - 1])) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or cv[i - 1] < fl[i - 1] or np.isnan(fl[i - 1])) else fl[i - 1]
        if np.isnan(line[i - 1]):
            up[i] = cv[i] >= fl[i]
        elif up[i - 1]:
            up[i] = cv[i] >= fl[i]
        else:
            up[i] = cv[i] > fu[i]
        line[i] = fl[i] if up[i] else fu[i]
    return pd.Series(line, index=df.index), pd.Series(up, index=df.index), atr


def fibonacci(df, price):
    """Retracement levels between the swing high and low of the last ~6 months."""
    d = df.tail(SWING_DAYS)
    hi_t, lo_t = d["High"].idxmax(), d["Low"].idxmin()
    hi, lo = float(d.loc[hi_t, "High"]), float(d.loc[lo_t, "Low"])
    uptrend = lo_t < hi_t                      # low came first -> the move was up; retrace down from the high
    levels = []
    for f in FIB:
        lv = hi - (hi - lo) * f if uptrend else lo + (hi - lo) * f
        levels.append({"ratio": f, "price": round(lv, 2)})
    ordered = sorted(levels, key=lambda x: x["price"])
    below = max((x for x in ordered if x["price"] <= price), key=lambda x: x["price"], default=None)
    above = min((x for x in ordered if x["price"] > price), key=lambda x: x["price"], default=None)
    return {"swing_high": round(hi, 2), "swing_high_date": str(hi_t.date()),
            "swing_low": round(lo, 2), "swing_low_date": str(lo_t.date()),
            "direction": "up" if uptrend else "down", "levels": levels,
            "support": below, "resistance": above}


def r2(x):
    return None if x is None or pd.isna(x) else round(float(x), 2)


def candles(df, ts_fmt):
    return [[ts.strftime(ts_fmt), r2(o), r2(h), r2(l), r2(c)] for ts, o, h, l, c in
            zip(df.index, df["o"], df["h"], df["l"], df["c"])]


# ---------------------------------------------------------------- per stock
def analyse(p):
    t = p["yahoo_ticker"]
    for attempt in range(3):
        try:
            tk = yf.Ticker(t)
            daily = tk.history(period="1y", interval="1d", auto_adjust=True)
            intra = tk.history(period="1d", interval="5m", auto_adjust=True)
            break
        except Exception as exc:
            if attempt == 2:
                return {"symbol": p["symbol"], "error": f"download failed ({type(exc).__name__}: {str(exc)[:160]})"}
            time.sleep(3 * (attempt + 1))
    daily = daily.dropna(subset=["Close"])
    intra = intra.dropna(subset=["Close"])
    if len(daily) < 60 or intra.empty:
        return {"symbol": p["symbol"], "error": f"not enough price data (daily rows {len(daily)}, 5-min rows {len(intra)})"}
    daily.index = daily.index.tz_convert(IST) if daily.index.tz else daily.index.tz_localize(IST)
    intra.index = intra.index.tz_convert(IST)
    session_day = intra.index[-1].date()
    # the daily table may or may not already contain today's candle; keep only days before the session
    prev = daily[daily.index.date < session_day]
    prev_close = float(prev["Close"].iloc[-1])
    price = float(intra["Close"].iloc[-1])
    # today's candle built from the 5-minute bars, so daily indicators include the live price
    today = pd.DataFrame({"Open": [intra["Open"].iloc[0]], "High": [intra["High"].max()],
                          "Low": [intra["Low"].min()], "Close": [price], "Volume": [intra["Volume"].sum()]},
                         index=[pd.Timestamp(session_day, tz=IST)])
    d = pd.concat([prev[["Open", "High", "Low", "Close", "Volume"]], today])

    ha_d = heikin_ashi(d).tail(SWING_DAYS)
    ha_i = heikin_ashi(intra)
    rsi_d = rsi(d["Close"])
    rsi_i = rsi(intra["Close"])
    st_line, st_up, atr = supertrend(d)
    fib = fibonacci(d, price)
    last_ha = ha_d.iloc[-1]
    ha_run = 0                                   # how many HA candles in a row share today's colour
    for o, c in zip(ha_d["o"][::-1], ha_d["c"][::-1]):
        if (c >= o) == (last_ha["c"] >= last_ha["o"]):
            ha_run += 1
        else:
            break
    tail = d.tail(SWING_DAYS)
    return {
        "symbol": p["symbol"],
        "price": r2(price), "prev_close": r2(prev_close),
        "change": r2(price - prev_close), "change_pct": r2((price / prev_close - 1) * 100),
        "day_open": r2(intra["Open"].iloc[0]), "day_high": r2(intra["High"].max()), "day_low": r2(intra["Low"].min()),
        "volume": int(intra["Volume"].sum()),
        "session_date": str(session_day), "last_bar_ist": intra.index[-1].strftime("%H:%M"),
        "rsi_daily": r2(rsi_d.iloc[-1]), "rsi_5m": r2(rsi_i.iloc[-1]) if len(intra) > 15 else None,
        "supertrend": {"value": r2(st_line.iloc[-1]), "trend": "up" if st_up.iloc[-1] else "down",
                       "atr": r2(atr.iloc[-1]),
                       "since": str(next((ts.date() for ts, u in zip(st_up.index[::-1], st_up[::-1]) if u != st_up.iloc[-1]), d.index[0].date()))},
        "heikin_ashi": {"colour": "green" if last_ha["c"] >= last_ha["o"] else "red", "run": ha_run,
                        "no_lower_wick": bool(abs(min(last_ha["o"], last_ha["c"]) - last_ha["l"]) < 1e-9),
                        "no_upper_wick": bool(abs(last_ha["h"] - max(last_ha["o"], last_ha["c"])) < 1e-9)},
        "fibonacci": fib,
        "series": {
            "dates": [ts.strftime("%Y-%m-%d") for ts in tail.index],
            "close": [r2(x) for x in tail["Close"]],
            "supertrend": [r2(x) for x in st_line.tail(SWING_DAYS)],
            "supertrend_up": [bool(x) for x in st_up.tail(SWING_DAYS)],
            "rsi": [r2(x) for x in rsi_d.tail(SWING_DAYS)],
            "ha_daily": candles(ha_d, "%Y-%m-%d"),
            "ha_5m": candles(ha_i, "%H:%M"),
            "rsi_5m": [r2(x) for x in rsi_i],
        },
    }


def market_state(now_ist, session_day):
    open_t, close_t = now_ist.replace(hour=9, minute=15, second=0), now_ist.replace(hour=15, minute=30, second=0)
    if session_day == now_ist.date() and open_t <= now_ist <= close_t:
        return "open"
    return "closed"


def main():
    picks = json.loads((DIR / "latest.json").read_text(encoding="utf-8"))["picks"]
    with ThreadPoolExecutor(max_workers=5) as ex:
        rows = list(ex.map(analyse, picks))
    ok = [r for r in rows if "error" not in r]
    if not ok:
        # Publish the reason (no prices are ever invented); the page shows "Prices unavailable".
        now = datetime.now(IST)
        DIR.mkdir(parents=True, exist_ok=True)
        (DIR / "live.json").write_text(json.dumps({
            "error": "no live prices could be fetched",
            "generated_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "generated_ist": now.strftime("%d %b %Y, %I:%M %p IST"),
            "stocks": {r["symbol"]: r for r in rows}}, allow_nan=False), encoding="utf-8")
        for r in rows:
            print(f"  {r['symbol']}: {r['error']}")
        raise RuntimeError("no live prices could be fetched")
    now = datetime.now(IST)
    session = max(r["session_date"] for r in ok)
    out = {
        "generated_ist": now.strftime("%d %b %Y, %I:%M %p IST"),
        "generated_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "market": market_state(now, datetime.fromisoformat(session).date()),
        "session_date": session,
        "last_bar_ist": max(r["last_bar_ist"] for r in ok if r["session_date"] == session),
        "stocks": {r["symbol"]: r for r in rows},
    }
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "live.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"market {out['market']}, session {session}, last bar {out['last_bar_ist']} IST")
    print(f"{'Stock':<11} {'Price':>9} {'Chg%':>6} {'RSI d':>6} {'RSI 5m':>6}  {'Supertrend':<16} {'HA':<10} Fib zone")
    for r in rows:
        if "error" in r:
            print(f"{r['symbol']:<11} ERROR {r['error']}")
            continue
        st, ha, fb = r["supertrend"], r["heikin_ashi"], r["fibonacci"]
        zone = (f"{fb['support']['ratio'] * 100:.1f}%-{fb['resistance']['ratio'] * 100:.1f}%"
                if fb["support"] and fb["resistance"] else "outside swing")
        print(f"{r['symbol']:<11} {r['price']:>9.2f} {r['change_pct']:>+6.2f} {r['rsi_daily']:>6.1f} "
              f"{(r['rsi_5m'] or float('nan')):>6.1f}  {st['trend']:>4} @ {st['value']:<9.2f} {ha['colour']:>5} x{ha['run']:<3} {zone} ({fb['direction']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
