"""
Company fundamentals for the terminal's DES panel and the Houses tab, from Yahoo Finance (run daily).
NIFTY 500 every run; the other main-board EQ stocks one fifth per run (fixed by symbol hash); business-house
members always. Each stock carries `at` (fetch date). A stock Yahoo has nothing for gets no figures, never a guess.

  python scripts/terminal_fund.py      writes data/terminal/fund.json
"""

import json
import math
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import ROOT, load_config, load_universe  # noqa: E402

OUT = ROOT / "data" / "terminal" / "fund.json"
IST = timezone(timedelta(hours=5, minutes=30))
FIELDS = {
    "mcap": "marketCap", "ev": "enterpriseValue", "pe": "trailingPE", "fpe": "forwardPE", "pb": "priceToBook",
    "eps": "trailingEps", "dy": "dividendYield", "roe": "returnOnEquity", "roa": "returnOnAssets",
    "pm": "profitMargins", "om": "operatingMargins", "rev": "totalRevenue", "revg": "revenueGrowth",
    "eg": "earningsGrowth", "de": "debtToEquity", "cr": "currentRatio", "beta": "beta", "sh": "sharesOutstanding",
    "inst": "heldPercentInstitutions", "ins": "heldPercentInsiders", "emp": "fullTimeEmployees",
    "tgt": "targetMeanPrice", "tgt_hi": "targetHighPrice", "tgt_lo": "targetLowPrice", "an": "numberOfAnalystOpinions",
    "rec": "recommendationKey", "sector": "sector", "industry": "industry", "web": "website", "city": "city",
    "desc": "longBusinessSummary",
}


SLIM = {"mcap", "sh", "pe", "pb", "eps", "dy", "beta", "sector", "industry", "at"}


def clean(v):
    if isinstance(v, str):
        return v.strip() or None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, 4)


def one(sym):
    for attempt in range(3):
        try:
            info = yf.Ticker(sym + ".NS").info
            break
        except Exception:
            if attempt == 2:
                return sym, None
            time.sleep(3 * (attempt + 1))
    row = {k: clean(info.get(v)) for k, v in FIELDS.items()}
    if row.get("desc"):
        row["desc"] = row["desc"][:1500]
    if row.get("rec") == "none":
        row["rec"] = None
    return sym, row


def rotation_slot(sym, today, parts=5):
    """Which of `parts` daily runs refreshes this stock: a fixed hash of the symbol, so a stock is fetched on the
    same weekday-cycle every time and the whole main board is covered every `parts` runs."""
    return zlib.crc32(sym.encode()) % parts == today.toordinal() % parts


def pick_symbols(nifty500, main_board, today, extra=()):
    """NIFTY 500 every run; every other main-board EQ stock once per 5 runs; `extra` (e.g. business-house members)
    always, since the Houses tab needs their share counts."""
    core = {s for s in nifty500 if not s.startswith("DUMMY")}
    rest = {s for s in main_board if s not in core and not s.startswith("DUMMY") and rotation_slot(s, today)}
    return sorted(core | rest | set(extra))


def main():
    uni, _ = load_universe(load_config())
    nifty500 = list(uni["Symbol"])
    main_board, extra = [], []
    try:
        U = json.loads((ROOT / "data" / "terminal" / "universe.json").read_text(encoding="utf-8"))["stocks"]
        main_board = [s["s"] for s in U if s.get("board") == "Main" and s.get("series") == "EQ"]
        houses = json.loads((ROOT / "data" / "config" / "business_houses.json").read_text(encoding="utf-8"))["houses"]
        extra = [s for h in houses for s in h["symbols"]]
    except (OSError, ValueError, KeyError):
        pass                                             # no universe yet: NIFTY 500 only, as before
    today = datetime.now(IST).date()
    syms = pick_symbols(nifty500, main_board, today, extra)
    old = json.loads(OUT.read_text(encoding="utf-8"))["stocks"] if OUT.exists() else {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = dict(ex.map(one, syms))
    stocks = {s: r for s, r in res.items() if r}
    n500 = set(nifty500)
    for s, r in stocks.items():
        r["at"] = today.isoformat()                      # fetch date, so the page can say how old each figure is
        if s not in n500:                                # outside the NIFTY 500 keep only the slim set: this file loads at page start
            for k in [k for k in r if k not in SLIM]:
                del r[k]
    kept = [s for s, r in res.items() if not r and s in old]
    for s in kept:                                       # a failed download keeps yesterday's figures
        stocks[s] = old[s]
    for s, r in old.items():                             # stocks not due today keep their last figures (and their own `at`)
        if s not in stocks:
            stocks[s] = r
    now = datetime.now(IST)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated_ist": now.strftime("%d %b %Y, %I:%M %p IST"), "stocks": stocks},
                              separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"fundamentals: {len(stocks)}/{len(syms)} NIFTY 500 stocks ({len(kept)} kept from the previous run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
