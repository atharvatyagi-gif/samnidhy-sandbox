"""
Picks the day's stocks for Samnidhy Sandbox: the top gainers and top losers of the
last completed NSE trading session, using NSE's official end-of-day file (the
"bhavcopy") and the settings in config.toml.

This file is used by scripts/update.py (which runs the whole daily update), and can
also be run on its own to preview the picks:

  python scripts/pick_movers.py                    # last completed session as of now
  python scripts/pick_movers.py --as-of 2026-09-20 # last session on or before that date

Running it on its own only prints the picks; saving is done by update.py, so that a
day is only saved when every step of the update has worked.
"""

import argparse
import io
import sys
import time
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
UNIVERSE_CACHE = ROOT / "data" / "universe" / "nifty500.csv"

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "text/csv,*/*",
}


class NoSessionFile(Exception):
    """NSE has no file for this date (weekend, holiday, or not published yet)."""


def load_config() -> dict:
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def download(url: str, retries: int) -> bytes:
    """GET with retries. A 404 means 'no file for this date' and is not retried."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                raise NoSessionFile(url)
            r.raise_for_status()
            return r.content
        except NoSessionFile:
            raise
        except Exception as exc:  # network error, 403 block, 5xx...
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed after {retries} attempts: {url} ({last_error})")


def load_universe(cfg: dict) -> tuple[pd.DataFrame, str]:
    """Index constituents. Falls back to the last saved copy if the download fails
    (the list changes only a few times a year), and says so."""
    f = cfg["filters"]
    try:
        raw = download(f["universe_url"], cfg["source"]["retries"])
        df = pd.read_csv(io.BytesIO(raw))
        if "Symbol" not in df.columns or len(df) < 100:
            raise RuntimeError("index list looks wrong (missing Symbol column or too few rows)")
        UNIVERSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        UNIVERSE_CACHE.write_bytes(raw)
        source = "downloaded"
    except Exception as exc:
        if not UNIVERSE_CACHE.exists():
            raise RuntimeError(f"could not get the {f['universe_name']} list and no saved copy exists: {exc}")
        print(f"  ! {f['universe_name']} list download failed ({exc}); using the saved copy")
        df = pd.read_csv(UNIVERSE_CACHE)
        source = "saved copy"
    df.columns = [c.strip() for c in df.columns]
    df["Symbol"] = df["Symbol"].astype(str).str.strip()
    return df, source


def find_last_session(cfg: dict, as_of: date) -> tuple[date, pd.DataFrame, str]:
    """Walk back from as_of until NSE has a bhavcopy. The session date is read from inside
    the file, never assumed from the calendar (NSE serves copies of the previous session's
    file for some weekend and holiday dates)."""
    src = cfg["source"]
    for back in range(src["lookback_days"] + 1):
        d = as_of - timedelta(days=back)
        url = src["bhavcopy_url"].format(date=d)
        try:
            raw = download(url, src["retries"])
        except NoSessionFile:
            continue
        df = pd.read_csv(io.BytesIO(raw))
        df.columns = [c.strip() for c in df.columns]
        if "SYMBOL" not in df.columns or "DATE1" not in df.columns:
            raise RuntimeError(f"unexpected file format from NSE: {url}")
        for c in ("SYMBOL", "SERIES", "DATE1"):
            df[c] = df[c].astype(str).str.strip()
        dates = df["DATE1"].unique()
        if len(dates) != 1:
            raise RuntimeError(f"file contains several dates {list(dates)}: {url}")
        session = datetime.strptime(dates[0], "%d-%b-%Y").date()
        return session, df, url
    raise RuntimeError(f"no NSE session file found in the {src['lookback_days']} days up to {as_of}")


def rank_movers(cfg: dict, bhav: pd.DataFrame, universe: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Apply the filters and return every eligible stock, best to worst by % change."""
    f = cfg["filters"]
    for c in ("PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS"):
        bhav[c] = pd.to_numeric(bhav[c], errors="coerce")

    symbols = {s for s in universe["Symbol"] if not any(s.upper().startswith(x) for x in f["exclude_prefixes"])}
    symbols -= set(f["exclude_symbols"])

    df = bhav[bhav["SERIES"].isin(f["series"]) & bhav["SYMBOL"].isin(symbols)].copy()
    in_universe = len(df)
    df = df.dropna(subset=["PREV_CLOSE", "CLOSE_PRICE", "TURNOVER_LACS"])
    df = df[(df["PREV_CLOSE"] > 0)
            & (df["CLOSE_PRICE"] > f["min_price"])
            & (df["TURNOVER_LACS"] / 100 >= f["min_turnover_crore"])]
    df["pct_change"] = (df["CLOSE_PRICE"] / df["PREV_CLOSE"] - 1) * 100

    for _, r in df[df["pct_change"].abs() > f["max_abs_move_pct"]].iterrows():
        print(f"  ! skipped {r['SYMBOL']}: {r['pct_change']:+.1f}% is above the {f['max_abs_move_pct']}% limit "
              f"(usually a split or bonus issue)")
    df = df[df["pct_change"].abs() <= f["max_abs_move_pct"]]

    # Ties are broken by traded value, so the ranking is always the same for the same data.
    ranked = df.sort_values(["pct_change", "TURNOVER_LACS"], ascending=[False, False]).reset_index(drop=True)
    return ranked, in_universe


def describe(r: pd.Series, universe: pd.DataFrame, group: str, rank: int) -> dict:
    info = universe[universe["Symbol"] == r["SYMBOL"]]
    first = info.iloc[0] if len(info) else None
    label = "Top Gainer" if group == "gainer" else "Top Loser"
    return {
        "group": group,
        "rank": rank,
        "label": f"{label} #{rank}",
        "symbol": r["SYMBOL"],
        "yahoo_ticker": f"{r['SYMBOL']}.NS",
        "name": None if first is None else str(first.get("Company Name", "")).strip() or None,
        "industry": None if first is None else str(first.get("Industry", "")).strip() or None,
        "prev_close": round(float(r["PREV_CLOSE"]), 2),
        "open": round(float(r["OPEN_PRICE"]), 2),
        "high": round(float(r["HIGH_PRICE"]), 2),
        "low": round(float(r["LOW_PRICE"]), 2),
        "close": round(float(r["CLOSE_PRICE"]), 2),
        "pct_change": round(float(r["pct_change"]), 4),
        "volume": int(r["TTL_TRD_QNTY"]),
        "turnover_crore": round(float(r["TURNOVER_LACS"]) / 100, 2),
    }


def compute_picks(cfg: dict, as_of: date) -> dict:
    """Everything needed to show the day's picks. Raises on any failure; writes nothing."""
    p = cfg["picks"]
    print(f"Looking for the last NSE session on or before {as_of}...")
    session, bhav, bhav_url = find_last_session(cfg, as_of)
    print(f"  found session {session} ({bhav_url})")
    universe, universe_source = load_universe(cfg)
    print(f"  {cfg['filters']['universe_name']} list: {len(universe)} rows ({universe_source})")

    ranked, in_universe = rank_movers(cfg, bhav, universe)
    need = p["gainers_count"] + p["losers_count"]
    if len(ranked) < need:
        raise RuntimeError(f"only {len(ranked)} stocks passed the filters; need at least {need}")

    gainers = [describe(r, universe, "gainer", i + 1) for i, (_, r) in enumerate(ranked.head(p["gainers_count"]).iterrows())]
    losers = [describe(r, universe, "loser", i + 1)
              for i, (_, r) in enumerate(ranked.iloc[::-1].head(p["losers_count"]).iterrows())]
    if any(g["pct_change"] <= 0 for g in gainers) or any(l["pct_change"] >= 0 for l in losers):
        print("  ! note: a very one-sided day; some 'gainers' fell or some 'losers' rose")

    return {
        "session_date": session.isoformat(),
        "source": {"session_file": bhav_url, "universe": cfg["filters"]["universe_url"], "universe_source": universe_source},
        "settings": {"picks": cfg["picks"], "filters": cfg["filters"]},
        "universe_count": in_universe,
        "eligible_count": int(len(ranked)),
        "gainers": gainers,
        "losers": losers,
    }


def print_picks(picks: dict) -> None:
    print(f"\nSession {picks['session_date']}: {picks['eligible_count']} of {picks['universe_count']} stocks passed the filters")
    for s in picks["gainers"] + picks["losers"]:
        print(f"  {s['label']:14s} {s['symbol']:12s} {s['pct_change']:+7.2f}%  "
              f"Rs {s['prev_close']:>9,.2f} -> Rs {s['close']:>9,.2f}  traded Rs {s['turnover_crore']:,.0f} cr")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", help="find the last session on or before this date (YYYY-MM-DD)")
    args = ap.parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).astimezone(IST).date()
    try:
        print_picks(compute_picks(load_config(), as_of))
    except Exception as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
