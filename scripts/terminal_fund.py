"""
Company fundamentals for the terminal's DES panel, from Yahoo Finance, for the NIFTY 500 (run daily).
Stocks outside the NIFTY 500 show NSE's price data only; their fundamentals are not loaded (not guessed).

  python scripts/terminal_fund.py      writes data/terminal/fund.json
"""

import json
import math
import sys
import time
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


def main():
    uni, _ = load_universe(load_config())
    syms = sorted(s for s in uni["Symbol"] if not s.startswith("DUMMY"))
    old = json.loads(OUT.read_text(encoding="utf-8"))["stocks"] if OUT.exists() else {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = dict(ex.map(one, syms))
    stocks = {s: r for s, r in res.items() if r}
    kept = [s for s, r in res.items() if not r and s in old]
    for s in kept:                                       # a failed download keeps yesterday's figures
        stocks[s] = old[s]
    now = datetime.now(IST)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated_ist": now.strftime("%d %b %Y, %I:%M %p IST"), "stocks": stocks},
                              separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"fundamentals: {len(stocks)}/{len(syms)} NIFTY 500 stocks ({len(kept)} kept from the previous run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
