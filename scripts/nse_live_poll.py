"""
NSE's own live numbers, straight from nseindia.com's public site API (the same JSON its own charts use),
not from Yahoo. This is an UNOFFICIAL technique: it is not a paid/licensed feed, NSE could block it at any
time without notice, and it does not need or use a broker account.

What it can and cannot get, found by testing every endpoint against nseindia.com directly (see the chat that
built this script for the full test log):
  - /api/quote-equity (an arbitrary single stock's price) is deliberately hardened -> always 403. No workaround.
  - /api/allIndices, /api/marketStatus, /api/live-analysis-variations (gainers/losers) and
    /api/live-analysis-most-active-securities (by volume and by value) all work with a plain requests.Session:
    visit a real referring page first (NSE sets the cookies its API checks), then call the API.
So this script gets NSE's own live index values and NSE's own live prices for whichever ~100-150 stocks are
currently in NSE's own gainers/losers/most-active lists. It is a supplement layered on top of the delayed
Yahoo prices (scripts/terminal_live.py), not a replacement: most of the ~2,950 covered stocks are not in these
lists at any given moment, and there is still no way to get an arbitrary single stock's live price this way.

If NSE blocks or errors, nothing is written: the site keeps showing the last successful poll (or, if there
never was one, just the Yahoo-delayed prices only). Nothing is estimated or invented.

  python scripts/nse_live_poll.py     -> data/nse_live/latest.json
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "nse_live" / "latest.json"
IST = timezone(timedelta(hours=5, minutes=30))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
BASE = "https://www.nseindia.com"

# Index names we show (a curated subset of allIndices; NSE's SENSEX is a BSE index and is not here).
INDEX_NAMES = ["NIFTY 50", "NIFTY BANK", "NIFTY NEXT 50", "NIFTY 500", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100",
              "NIFTY AUTO", "NIFTY IT", "NIFTY FMCG", "NIFTY PHARMA", "NIFTY METAL", "NIFTY REALTY",
              "NIFTY ENERGY", "NIFTY FIN SERVICE", "NIFTY PSU BANK", "INDIA VIX"]
MOVER_GROUPS = ["NIFTY", "BANKNIFTY", "NIFTYNEXT50", "SecGtr20", "SecLwr20", "FOSec"]
# readable names for the NSE list a stock's live figure was picked up from (there is no industry-sector field
# in NSE's live gainers/losers/most-active data; this is the closest real grouping it does carry)
GROUP_LABEL = {"NIFTY": "NIFTY 50", "BANKNIFTY": "Bank Nifty", "NIFTYNEXT50": "Nifty Next 50",
              "SecGtr20": "Price > ₹20", "SecLwr20": "Price ≤ ₹20", "FOSec": "F&O stocks",
              "volume": "Most active (volume)", "value": "Most active (value)"}


def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers["Referer"] = BASE + "/"
    s.get(BASE + "/", timeout=20)          # collects the cookies the API checks; not itself the data
    return s


def get(s, path, referer=None):
    if referer:
        s.headers["Referer"] = referer
    r = s.get(BASE + path, timeout=20)
    r.raise_for_status()
    return r.json()


def num(v):
    try:
        f = float(v)
        return None if f != f else f            # NaN check without importing math for one line
    except (TypeError, ValueError):
        return None


def indices(s):
    d = get(s, "/api/allIndices", BASE + "/market-data/live-market-indices")
    out = {}
    for row in d.get("data", []):
        name = row.get("index")
        if name not in INDEX_NAMES:
            continue
        out[name] = {"last": num(row.get("last")), "chg": num(row.get("variation")), "pct": num(row.get("percentChange")),
                     "open": num(row.get("open")), "high": num(row.get("high")), "low": num(row.get("low")),
                     "prev_close": num(row.get("previousClose")), "year_high": num(row.get("yearHigh")), "year_low": num(row.get("yearLow"))}
    return out


def market_status(s):
    d = get(s, "/api/marketStatus", BASE + "/market-data/live-market-indices")
    cap = next((m for m in d.get("marketState", []) if m.get("market") == "Capital Market"), None)
    if not cap:
        return None
    return {"status": cap.get("marketStatus"), "message": cap.get("marketStatusMessage"), "trade_date": cap.get("tradeDate")}


def add_group(out, sym, code):
    """Record that `sym` appeared in NSE's `code` list (NIFTY / BANKNIFTY / ... / volume / value), in order,
    without duplicates. This becomes the stock's "NSE group" column in the terminal."""
    rec = out.setdefault(sym, {"grp": []})
    label = GROUP_LABEL.get(code, code)
    if label not in rec["grp"]:
        rec["grp"].append(label)
    return rec


def movers(s):
    """Every symbol in NSE's own gainers + losers lists (all groups, deduplicated)."""
    out = {}
    for kind in ("gainers", "loosers"):
        d = get(s, f"/api/live-analysis-variations?index={kind}", BASE + "/market-data/live-equity-market")
        for grp in MOVER_GROUPS:
            for row in d.get(grp, {}).get("data", []):
                sym = row.get("symbol")
                if not sym:
                    continue
                rec = add_group(out, sym, grp)
                p, pc = num(row.get("ltp")), num(row.get("prev_price"))
                rec.update({"p": p, "pc": pc, "chg": round(p - pc, 2) if p is not None and pc is not None else None,
                           "pct": num(row.get("perChange")), "o": num(row.get("open_price")), "h": num(row.get("high_price")),
                           "l": num(row.get("low_price")), "v": num(row.get("trade_quantity")), "src": "movers"})
    return out


def most_active(s):
    """Every symbol in NSE's own most-active-by-volume and most-active-by-value lists."""
    out = {}
    for kind in ("volume", "value"):
        d = get(s, f"/api/live-analysis-most-active-securities?index={kind}", BASE + "/market-data/live-equity-market")
        for row in d.get("data", []):
            sym = row.get("symbol")
            if not sym:
                continue
            rec = add_group(out, sym, kind)
            rec.update({"p": num(row.get("lastPrice")), "pc": num(row.get("previousClose")), "chg": num(row.get("change")),
                       "pct": num(row.get("pChange")), "o": num(row.get("open")), "h": num(row.get("dayHigh")), "l": num(row.get("dayLow")),
                       "v": num(row.get("totalTradedVolume")), "t": row.get("lastUpdateTime"), "src": "most_active"})
    return out


def main():
    s = session()
    idx = mkt = None
    stocks = {}
    errors = []
    for name, fn, sink in [("indices", indices, "idx"), ("market status", market_status, "mkt"),
                           ("movers", movers, "stocks"), ("most-active", most_active, "stocks")]:
        for attempt in range(2):
            try:
                res = fn(s)
                if sink == "idx":
                    idx = res
                elif sink == "mkt":
                    mkt = res
                else:
                    for sym, rec in res.items():   # most-active's fresher price/timestamp wins, but group lists are kept from both passes
                        prev_grp = stocks.get(sym, {}).get("grp", [])
                        stocks[sym] = {**rec, "grp": prev_grp + [g for g in rec.get("grp", []) if g not in prev_grp]}
                break
            except Exception as exc:
                if attempt == 0:
                    time.sleep(3)
                    continue
                errors.append(f"{name}: {type(exc).__name__} {exc}")
    if not idx and not stocks:
        raise RuntimeError("NSE did not return anything usable: " + "; ".join(errors) if errors else "unknown failure")

    now = datetime.now(timezone.utc)
    res = {
        "generated_utc": now.isoformat(timespec="seconds"),
        "generated_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M:%S %p IST"),
        "source": "nseindia.com public site API (unofficial; not a paid/licensed vendor feed)",
        "market_status": mkt,
        "indices": idx or {},
        "stocks": stocks,
        "partial_errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, allow_nan=False), encoding="utf-8")
    print(f"NSE live poll: {len(idx or {})} indices, {len(stocks)} stocks (from movers + most-active lists)"
          + (f"; partial errors: {errors}" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
