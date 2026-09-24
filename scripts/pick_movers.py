"""
Picks the day's stocks for Samnidhy Sandbox: the top gainers and top losers of the
last completed NSE trading session, using NSE's official end-of-day file (the
"bhavcopy") and the settings in config.toml.

Output (all under data/picks/):
  <YYYY-MM-DD>.json   the picks for that session (kept forever, so past days can be shown)
  latest.json         a copy of the most recent successful picks
  index.json          list of every session date saved so far
  status.json         result of the latest attempt; the website uses it to show
                      "Data not updated" when something went wrong

If anything fails, latest.json is left untouched (the last good day stays on the site)
and the script exits with an error. It never invents or substitutes stocks.

Usage:
  python scripts/pick_movers.py                    # last completed session as of now
  python scripts/pick_movers.py --as-of 2026-09-20 # last session on or before that date
"""

import argparse
import io
import json
import sys
import time
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
PICKS_DIR = ROOT / "data" / "picks"
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
    the file, never assumed from the calendar."""
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


def pick(cfg: dict, bhav: pd.DataFrame, universe: pd.DataFrame) -> dict:
    f, p = cfg["filters"], cfg["picks"]
    for c in ("PREV_CLOSE", "CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS"):
        bhav[c] = pd.to_numeric(bhav[c], errors="coerce")

    names = universe.set_index("Symbol")
    symbols = set(universe["Symbol"])
    symbols = {s for s in symbols if not any(s.upper().startswith(x) for x in f["exclude_prefixes"])}
    symbols -= set(f["exclude_symbols"])

    df = bhav[bhav["SERIES"].isin(f["series"]) & bhav["SYMBOL"].isin(symbols)].copy()
    in_universe = len(df)
    df = df.dropna(subset=["PREV_CLOSE", "CLOSE_PRICE", "TURNOVER_LACS"])
    df = df[(df["PREV_CLOSE"] > 0)
            & (df["CLOSE_PRICE"] > f["min_price"])
            & (df["TURNOVER_LACS"] / 100 >= f["min_turnover_crore"])]
    df["pct_change"] = (df["CLOSE_PRICE"] / df["PREV_CLOSE"] - 1) * 100

    too_big = df[df["pct_change"].abs() > f["max_abs_move_pct"]]
    for _, r in too_big.iterrows():
        print(f"  ! skipped {r['SYMBOL']}: {r['pct_change']:+.1f}% is above the {f['max_abs_move_pct']}% limit "
              f"(usually a split or bonus issue)")
    df = df[df["pct_change"].abs() <= f["max_abs_move_pct"]]

    need = p["gainers_count"] + p["losers_count"]
    if len(df) < need:
        raise RuntimeError(f"only {len(df)} stocks passed the filters; need at least {need}")

    # Ties are broken by traded value, so the ranking is always the same for the same data.
    ranked = df.sort_values(["pct_change", "TURNOVER_LACS"], ascending=[False, False])

    def row(r, label, rank):
        info = names.loc[r["SYMBOL"]] if r["SYMBOL"] in names.index else None
        return {
            "rank": rank,
            "label": f"{label} #{rank}",
            "symbol": r["SYMBOL"],
            "yahoo_ticker": f"{r['SYMBOL']}.NS",
            "name": None if info is None else str(info.get("Company Name", "")).strip() or None,
            "industry": None if info is None else str(info.get("Industry", "")).strip() or None,
            "prev_close": round(float(r["PREV_CLOSE"]), 2),
            "close": round(float(r["CLOSE_PRICE"]), 2),
            "pct_change": round(float(r["pct_change"]), 4),
            "volume": int(r["TTL_TRD_QNTY"]),
            "turnover_crore": round(float(r["TURNOVER_LACS"]) / 100, 2),
        }

    gainers = [row(r, "Top Gainer", i + 1) for i, (_, r) in enumerate(ranked.head(p["gainers_count"]).iterrows())]
    losers = [row(r, "Top Loser", i + 1) for i, (_, r) in enumerate(ranked.iloc[::-1].head(p["losers_count"]).iterrows())]

    if any(g["pct_change"] <= 0 for g in gainers) or any(l["pct_change"] >= 0 for l in losers):
        print("  ! note: a very one-sided day; some 'gainers' fell or some 'losers' rose")

    return {"gainers": gainers, "losers": losers, "universe_count": in_universe, "eligible_count": int(len(df))}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic: a half-written file can never be published


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", help="find the last session on or before this date (YYYY-MM-DD)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    as_of = date.fromisoformat(args.as_of) if args.as_of else now.astimezone(IST).date()
    status = {
        "last_attempt_utc": now.isoformat(timespec="seconds"),
        "last_attempt_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
    }

    try:
        cfg = load_config()
        print(f"Looking for the last NSE session on or before {as_of}...")
        session, bhav, bhav_url = find_last_session(cfg, as_of)
        print(f"  found session {session} ({bhav_url})")
        universe, universe_source = load_universe(cfg)
        print(f"  {cfg['filters']['universe_name']} list: {len(universe)} rows ({universe_source})")
        result = pick(cfg, bhav, universe)
    except Exception as exc:
        status.update({"ok": False, "error": str(exc)})
        write_json(PICKS_DIR / "status.json", status)
        print(f"\nFAILED: {exc}\nThe last good picks were left in place.", file=sys.stderr)
        return 1

    picks = {
        "session_date": session.isoformat(),
        "fetched_at_utc": now.isoformat(timespec="seconds"),
        "fetched_at_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "source": {"session_file": bhav_url, "universe": cfg["filters"]["universe_url"], "universe_source": universe_source},
        "settings": {"picks": cfg["picks"], "filters": cfg["filters"]},
        **result,
    }
    write_json(PICKS_DIR / f"{session.isoformat()}.json", picks)
    if not args.as_of or not (PICKS_DIR / "latest.json").exists() or \
            session.isoformat() >= json.loads((PICKS_DIR / "latest.json").read_text(encoding="utf-8"))["session_date"]:
        write_json(PICKS_DIR / "latest.json", picks)
    saved = sorted(p.stem for p in PICKS_DIR.glob("????-??-??.json"))
    write_json(PICKS_DIR / "index.json", {"sessions": saved[::-1]})
    status.update({"ok": True, "session_date": session.isoformat(), "error": None})
    write_json(PICKS_DIR / "status.json", status)

    print(f"\nSession {session}: {result['eligible_count']} of {result['universe_count']} stocks passed the filters")
    for group in ("gainers", "losers"):
        for s in picks[group]:
            print(f"  {s['label']:14s} {s['symbol']:12s} {s['pct_change']:+7.2f}%  "
                  f"Rs {s['prev_close']:>9,.2f} -> Rs {s['close']:>9,.2f}  traded Rs {s['turnover_crore']:,.0f} cr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
