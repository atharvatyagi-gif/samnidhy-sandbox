"""
Every stock on NSE, from NSE's official end-of-day files ("bhavcopies"), for the expert terminal.

1. Keeps ~13 months of daily bhavcopies in data/terminal/bhav/ (downloads only the days it doesn't
   have yet; the first run fetches about 260 files). These are a cache: not stored in git.
2. Builds
     data/terminal/universe.json   one row per stock: name, series, ISIN, industry, the last session's
                                   OHLC / volume / turnover / delivery %, 52-week range, returns, breadth
     data/terminal/hist/<k>.json   one year of daily OHLCV per stock, grouped by the symbol's first
                                   character (the terminal loads one small group when a stock is opened)

Series kept: EQ (normal), BE/BZ (trade-for-trade), SM/ST (SME). Numbers are NSE's own; nothing is estimated.

  python scripts/nse_eod.py
"""

import gzip
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import ROOT, NoSessionFile, download, load_config, load_universe  # noqa: E402

OUT = ROOT / "data" / "terminal"
BHAV = OUT / "bhav"
HIST = OUT / "hist"
SERIES = ["EQ", "BE", "BZ", "SM", "ST"]
DAYS_BACK = 400                      # calendar days kept (~13 months of sessions)
LISTS = {
    "main": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "sme": "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
    "etf": "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv",
}
COLS = ["SYMBOL", "SERIES", "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE",
        "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES", "DELIV_PER"]


def shard(sym):
    c = sym[0].upper()
    return c if c.isalpha() else "0"


def sync_bhavcopies(cfg):
    """Download any missing session files (the session date is read from inside each file)."""
    BHAV.mkdir(parents=True, exist_ok=True)
    have = {p.name[:10] for p in BHAV.glob("*.csv.gz")}
    tried = BHAV / "_checked.json"                      # calendar dates already known to have no new file
    checked = set(json.loads(tried.read_text())) if tried.exists() else set()
    today = date.today()
    new = 0
    for back in range(DAYS_BACK):
        d = today - timedelta(days=back)
        if d.weekday() >= 5 or d.isoformat() in have or (d.isoformat() in checked and back > 3):
            continue
        try:
            raw = download(cfg["source"]["bhavcopy_url"].format(date=d), cfg["source"]["retries"])
        except NoSessionFile:
            checked.add(d.isoformat())
            continue
        df = pd.read_csv(io.BytesIO(raw))
        df.columns = [c.strip() for c in df.columns]
        session = pd.to_datetime(df["DATE1"].astype(str).str.strip().iloc[0], format="%d-%b-%Y").date().isoformat()
        checked.add(d.isoformat())
        if session in have:
            continue
        for c in ("SYMBOL", "SERIES"):
            df[c] = df[c].astype(str).str.strip()
        df = df[df["SERIES"].isin(SERIES)][COLS]
        df["DELIV_PER"] = pd.to_numeric(df["DELIV_PER"].astype(str).str.strip(), errors="coerce")
        with gzip.open(BHAV / f"{session}.csv.gz", "wt", encoding="utf-8") as f:
            df.to_csv(f, index=False)
        have.add(session)
        new += 1
    tried.write_text(json.dumps(sorted(checked)[-DAYS_BACK:]))
    # drop files older than the window
    cutoff = (today - timedelta(days=DAYS_BACK)).isoformat()
    for p in BHAV.glob("*.csv.gz"):
        if p.name[:10] < cutoff:
            p.unlink()
    print(f"bhavcopies: {len(have)} sessions cached ({new} new)")


def names():
    out = {}
    for kind, url in LISTS.items():
        try:
            df = pd.read_csv(io.BytesIO(download(url, 3)), encoding="latin-1")
        except Exception as exc:
            print(f"  ! {kind} list not available ({exc})")
            continue
        df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]
        if kind == "etf":
            df = df.rename(columns={"SECURITYNAME": "NAME_OF_COMPANY", "ISINNUMBER": "ISIN_NUMBER", "DATEOFLISTING": "DATE_OF_LISTING"})
        name_col = "NAME_OF_COMPANY"
        isin_col = "ISIN_NUMBER" if "ISIN_NUMBER" in df.columns else None
        for _, r in df.iterrows():
            out[str(r["SYMBOL"]).strip()] = {
                "name": str(r[name_col]).strip(),
                "isin": str(r[isin_col]).strip() if isin_col else None,
                "listed": str(r.get("DATE_OF_LISTING", "")).strip() or None,
                "board": "SME" if kind == "sme" else "Main",
                "etf": kind == "etf",
            }
    return out


def r2(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else round(x, 2)


def build(cfg):
    files = sorted(BHAV.glob("*.csv.gz"))
    if not files:
        raise RuntimeError("no bhavcopies available")
    frames = []
    for p in files:
        df = pd.read_csv(p)
        df["DATE"] = p.name[:10]
        frames.append(df)
    allx = pd.concat(frames, ignore_index=True).sort_values(["SYMBOL", "DATE"])
    # one row per symbol per day (a stock can move between EQ and BE; keep the traded row)
    allx = allx.drop_duplicates(["SYMBOL", "DATE"], keep="last")
    last_day = allx["DATE"].max()
    uni, _ = load_universe(cfg)
    industry = dict(zip(uni["Symbol"], uni["Industry"]))
    nm = names()
    rows, hist = {}, {}
    adv = dec = unch = 0
    recent = sorted(allx["DATE"].unique())[-10:]         # listed now = traded in one of the last 10 sessions
    for sym, g in allx.groupby("SYMBOL", sort=False):
        g = g.tail(260)
        if g["DATE"].iloc[-1] not in recent:
            continue
        last = g.iloc[-1]
        closes = g["CLOSE_PRICE"].astype(float)
        yr = g.tail(252)

        def ret(n):
            return r2((closes.iloc[-1] / closes.iloc[-1 - n] - 1) * 100) if len(closes) > n and closes.iloc[-1 - n] else None
        live = last["DATE"] == last_day
        chg = float(last["CLOSE_PRICE"]) - float(last["PREV_CLOSE"])
        if live:
            adv += chg > 0
            dec += chg < 0
            unch += chg == 0
        info = nm.get(sym, {})
        rows[sym] = {
            "s": sym, "n": info.get("name") or sym, "series": last["SERIES"], "board": info.get("board") or ("SME" if last["SERIES"] in ("SM", "ST") else "Main"),
            "isin": info.get("isin"), "listed": info.get("listed"), "ind": industry.get(sym), "n500": sym in industry,
            "etf": bool(info.get("etf")),
            "date": last["DATE"], "traded_last_session": bool(live),
            "o": r2(last["OPEN_PRICE"]), "h": r2(last["HIGH_PRICE"]), "l": r2(last["LOW_PRICE"]), "c": r2(last["CLOSE_PRICE"]),
            "pc": r2(last["PREV_CLOSE"]), "chg": r2(chg), "pct": r2(chg / float(last["PREV_CLOSE"]) * 100) if float(last["PREV_CLOSE"]) else None,
            "v": int(last["TTL_TRD_QNTY"]), "val_cr": r2(float(last["TURNOVER_LACS"]) / 100), "trades": int(last["NO_OF_TRADES"]),
            "deliv": r2(last["DELIV_PER"]),
            "hi52": r2(yr["HIGH_PRICE"].max()), "lo52": r2(yr["LOW_PRICE"].min()),
            "avgv20": int(g["TTL_TRD_QNTY"].tail(20).mean()),
            "r1m": ret(21), "r3m": ret(63), "r6m": ret(126), "r1y": ret(251),
        }
        hist.setdefault(shard(sym), {})[sym] = [
            [d, r2(o), r2(h), r2(l), r2(c), int(v)] for d, o, h, l, c, v in
            zip(yr["DATE"], yr["OPEN_PRICE"], yr["HIGH_PRICE"], yr["LOW_PRICE"], yr["CLOSE_PRICE"], yr["TTL_TRD_QNTY"])]
    OUT.mkdir(parents=True, exist_ok=True)
    HIST.mkdir(parents=True, exist_ok=True)
    for p in HIST.glob("*.json"):
        p.unlink()
    for k, v in hist.items():
        (HIST / f"{k}.json").write_text(json.dumps(v, separators=(",", ":")), encoding="utf-8")
    uni_out = {"session_date": last_day, "sessions": len(files),
               "breadth": {"advances": int(adv), "declines": int(dec), "unchanged": int(unch)},
               "count": len(rows), "stocks": list(rows.values())}
    (OUT / "universe.json").write_text(json.dumps(uni_out, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"universe: {len(rows)} stocks, session {last_day}, A/D {adv}/{dec}, {len(hist)} history shards")


def main():
    cfg = load_config()
    sync_bhavcopies(cfg)
    build(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
