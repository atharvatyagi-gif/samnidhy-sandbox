"""
Every Indian index for the Expert terminal's Indices tab, plus Bitcoin.

  NSE   all indices (about 167: broad, sectoral, thematic, strategy, bond, VIX) from NSE's official end-of-day
        file https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv  (open, high, low, close,
        P/E, P/B, dividend yield). One raw file per session is kept in data/terminal/idx/raw/ (a cache, not in git).
        The first runs backfill YEARS years, at most MAX_NEW files a run, newest first, so the history fills in
        over a few days of scheduled runs.
  BSE   SENSEX, BSE 100 and BSE 500 from Yahoo Finance (the only BSE indices Yahoo carries; the others are listed
        as not available, never estimated).
  CRYPTO Bitcoin in rupees and in US dollars from Yahoo Finance (trades every day of the week).

Outputs (copied to site/t/x/ by build_site.py):
  data/terminal/idx/out/index.json      one row per index: group, last, change, 1-month / 1-year return, 52-week range, P/E, P/B, yield
  data/terminal/idx/out/d/<key>.json    daily candles [[date, o, h, l, c], ...] for the chart

  python scripts/indices_eod.py              (scheduled in Daily update)
  python scripts/indices_eod.py --max-new 2000   (a local one-off backfill)
"""

import argparse
import gzip
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import ROOT, NoSessionFile, download  # noqa: E402

IDX = ROOT / "data" / "terminal" / "idx"
RAW, OUT = IDX / "raw", IDX / "out"
URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
YEARS = 5
MAX_NEW = 150
YAHOO = [("BSE", "^BSESN", "S&P BSE SENSEX"), ("BSE", "BSE-100.BO", "S&P BSE 100"), ("BSE", "BSE-500.BO", "S&P BSE 500"),
         ("Crypto", "BTC-INR", "Bitcoin (INR)"), ("Crypto", "BTC-USD", "Bitcoin (USD)")]
BSE_NOT_AVAILABLE = ["S&P BSE MidCap", "S&P BSE SmallCap", "S&P BSE Bankex", "S&P BSE IT", "S&P BSE 200"]

BROAD = {"nifty 50", "nifty next 50", "nifty 100", "nifty 200", "nifty 500", "nifty midcap 50", "nifty midcap 100", "nifty smallcap 100", "nifty smallcap 250", "nifty smallcap 50",
         "nifty midcap 150", "nifty midcap select", "nifty largemidcap 250", "nifty500 multicap 50:25:25", "nifty microcap 250", "nifty total market", "nifty midsmallcap 400",
         "nifty next 100", "nifty smallcap 500", "nifty sme emerge", "nifty midcap liquid 15", "nifty100 liquid 15", "nifty midsmallcap400 50:50", "nifty500 largemidsmall equal-cap weighted"}
SECTOR = {"nifty auto", "nifty bank", "nifty energy", "nifty financial services", "nifty fmcg", "nifty it", "nifty media", "nifty metal", "nifty pharma", "nifty psu bank", "nifty realty",
          "nifty private bank", "nifty oil & gas", "nifty financial services 25/50", "nifty healthcare index", "nifty consumer durables", "nifty financial services ex-bank", "nifty chemicals",
          "nifty cement", "nifty construction", "nifty insurance", "nifty power", "nifty retail", "nifty telecommunications", "nifty capital goods", "nifty nbfc", "nifty hospitals",
          "nifty housing finance", "nifty500 healthcare", "nifty midsmall financial services", "nifty midsmall healthcare", "nifty midsmall it & telecom"}
STRATEGY_WORDS = ("alpha", "momentum", "quality", "value", "low volatility", "low-volatility", "equal weight", "dividend", "beta", "growth", "multifactor", "flexicap", "esg", "shariah", "ahimsa")
OTHER_WORDS = ("g-sec", "bharat bond", "1d rate", "vix", "inverse", "leverage", "futures", "arbitrage", "usd", "dividend points", "tr index")


def group_of(name):
    n = name.lower().strip()
    if n in BROAD:
        return "Broad market"
    if n in SECTOR:
        return "Sectoral"
    if any(w in n for w in OTHER_WORDS):
        return "Bonds, VIX and others"
    if any(w in n for w in STRATEGY_WORDS):
        return "Strategy"
    return "Thematic"


def key(name):
    """File-safe key: letters and digits kept, anything else -> _<hex> (the same rule as the terminal's dkey)."""
    return "".join(c if c.isalnum() and c.isascii() else "_" + format(ord(c), "x") for c in name)


def _num(x):
    try:
        v = float(str(x).strip())
        return v if v == v else None
    except ValueError:
        return None


def _fin(v):
    try:
        v = float(v)
        return round(v, 2) if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


def sync_nse(max_new=MAX_NEW, today=None):
    """Download missing session files, newest first, back to YEARS years. -> number of new files."""
    RAW.mkdir(parents=True, exist_ok=True); today = today or date.today()
    have = {p.name[:10] for p in RAW.glob("*.csv.gz")}; tried_f = RAW / "_checked.json"
    checked = set(json.loads(tried_f.read_text())) if tried_f.exists() else set(); new = 0
    for back in range(YEARS * 366):
        if new >= max_new:
            break
        d = today - timedelta(days=back)
        if d.weekday() >= 5 or d.isoformat() in have or (d.isoformat() in checked and back > 3):
            continue
        try:
            raw = download(URL.format(d=d), 2)
        except NoSessionFile:
            checked.add(d.isoformat()); continue
        except Exception as e:                                                   # noqa: BLE001  a block or timeout: stop, keep what we have
            print(f"NSE indices: download stopped at {d} ({type(e).__name__})"); break
        df = pd.read_csv(io.BytesIO(raw)); df.columns = [c.strip() for c in df.columns]
        if "Index Name" not in df.columns or df.empty:
            checked.add(d.isoformat()); continue
        session = pd.to_datetime(str(df["Index Date"].iloc[0]).strip(), format="%d-%m-%Y").date().isoformat()
        checked.add(d.isoformat())
        if session not in have:
            with gzip.open(RAW / f"{session}.csv.gz", "wt", encoding="utf-8") as f:
                df.to_csv(f, index=False)
            have.add(session); new += 1
    tried_f.write_text(json.dumps(sorted(checked)))
    return new


def load_nse():
    """{index name: DataFrame(date, o, h, l, c, pe, pb, dy)} from every raw file."""
    rows = []
    for p in sorted(RAW.glob("*.csv.gz")):
        df = pd.read_csv(p); d = p.name[:10]
        for r in df.itertuples(index=False):
            name = str(r[0]).strip(); c = _num(r[5])
            if not name or c is None:
                continue
            rows.append((name, d, _num(r[2]), _num(r[3]), _num(r[4]), c, _num(r[10]), _num(r[11]), _num(r[12])))
    if not rows:
        return {}
    A = pd.DataFrame(rows, columns=["name", "date", "o", "h", "l", "c", "pe", "pb", "dy"])
    return {n: g.drop(columns="name").sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True) for n, g in A.groupby("name")}


def load_yahoo():
    import yfinance as yf
    out = {}
    for grp, tick, name in YAHOO:
        try:
            h = yf.Ticker(tick).history(period=f"{YEARS}y", auto_adjust=False)
        except Exception as e:                                                   # noqa: BLE001
            print(f"Yahoo {tick}: not available ({type(e).__name__})"); continue
        if h is None or h.empty:
            print(f"Yahoo {tick}: no data"); continue
        h = h.dropna(subset=["Close"])
        out[name] = (grp, tick, pd.DataFrame({"date": [x.strftime("%Y-%m-%d") for x in h.index], "o": h["Open"].values, "h": h["High"].values, "l": h["Low"].values, "c": h["Close"].values,
                                              "pe": None, "pb": None, "dy": None}))
    return out


def summary(name, grp, src, df):
    """One row of index.json from a daily frame (dates as strings, ascending)."""
    c = df["c"].astype(float).values; dts = pd.to_datetime(df["date"]); last = dts.iloc[-1]
    def ret_since(days):
        m = dts <= last - pd.Timedelta(days=days)
        return round((c[-1] / c[m.values][-1] - 1) * 100, 2) if m.any() else None
    yr = dts > last - pd.Timedelta(days=365); hi, lo = float(df["h"].fillna(df["c"])[yr].max()), float(df["l"].fillna(df["c"])[yr].min())
    tail = df.iloc[-1]
    return {"name": name, "key": key(name), "group": grp, "source": src, "as_of": df["date"].iloc[-1], "last": round(float(c[-1]), 2), "prev": round(float(c[-2]), 2) if len(c) > 1 else None,
            "pct": round((c[-1] / c[-2] - 1) * 100, 2) if len(c) > 1 and c[-2] else None, "r1m": ret_since(30), "r1y": ret_since(365), "hi52": round(hi, 2), "lo52": round(lo, 2),
            "pe": _fin(tail["pe"]), "pb": _fin(tail["pb"]), "dy": _fin(tail["dy"]), "days": int(len(df)), "from": df["date"].iloc[0]}


def build(nse, yahoo):
    (OUT / "d").mkdir(parents=True, exist_ok=True); rows = []
    def write(name, df):
        cand = [[d, *(None if v is None or v != v else round(float(v), 2) for v in (o, h, l, c))] for d, o, h, l, c in zip(df["date"], df["o"], df["h"], df["l"], df["c"])]
        (OUT / "d" / f"{key(name)}.json").write_text(json.dumps({"name": name, "d": cand}, separators=(",", ":")), encoding="utf-8")
    nse_last = max((df["date"].iloc[-1] for df in nse.values() if len(df)), default=None); gone = []
    for name, df in nse.items():
        if len(df) < 2:
            continue
        if (pd.Timestamp(nse_last) - pd.Timestamp(df["date"].iloc[-1])).days > 10:                    # renamed, merged or matured: NSE no longer publishes it
            gone.append({"name": name, "last_date": df["date"].iloc[-1]}); continue
        rows.append(summary(name, group_of(name), "NSE end-of-day file", df)); write(name, df)
    for name, (grp, tick, df) in yahoo.items():
        if len(df) < 2:
            continue
        rows.append(summary(name, grp, f"Yahoo Finance {tick}", df)); write(name, df)
    for name in BSE_NOT_AVAILABLE:
        rows.append({"name": name, "key": None, "group": "BSE", "source": None, "missing": "not available: no free daily source for this BSE index"})
    order = ["Broad market", "Sectoral", "Thematic", "Strategy", "Bonds, VIX and others", "BSE", "Crypto"]
    rows.sort(key=lambda r: (order.index(r["group"]), r["name"].lower()))
    doc = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "groups": order, "count": sum(1 for r in rows if r.get("key")), "indices": rows, "discontinued": gone,
           "note": "NSE indices from NSE's official end-of-day file; BSE and Bitcoin from Yahoo Finance. Index P/E, P/B and dividend yield are NSE's own. Educational analysis only, not investment advice."}
    (OUT / "index.json").write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False, default=lambda v: None), encoding="utf-8")
    return doc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--max-new", type=int, default=MAX_NEW); ap.add_argument("--no-yahoo", action="store_true"); a = ap.parse_args()
    n = sync_nse(a.max_new); nse = load_nse(); yh = {} if a.no_yahoo else load_yahoo(); doc = build(nse, yh)
    days = max((len(v) for v in nse.values()), default=0)
    print(f"indices: {n} new NSE files, {len(nse)} NSE indices (up to {days} sessions), {len(yh)} from Yahoo; {doc['count']} published")


if __name__ == "__main__":
    main()
