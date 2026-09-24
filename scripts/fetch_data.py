"""
Downloads daily price history from Yahoo Finance (via yfinance) for the day's picked
stocks and the benchmark index, up to and including the NSE session date.

Cleaning applied to every series:
  - rows after the session date are dropped (Yahoo can include a live, unfinished session)
  - rows with no closing price are dropped
  - for stocks, "holiday" rows are dropped: Yahoo adds rows for market holidays with a flat
    price (open = high = low = close) and zero volume; they are not real trading days and
    would add fake 0% days to every calculation

The session day itself:
  - if Yahoo has it, its close must match NSE's official close
  - if Yahoo hasn't published it yet (this happens, sometimes for hours), the session row is
    taken from NSE's official files instead - the bhavcopy for stocks, the index closing file
    for the benchmark - but only when Yahoo's latest close matches NSE's "previous close",
    which proves no trading day is missing in between

Any failed check stops the update; nothing is invented.

Used by scripts/update.py. Run on its own, it fetches history for the most recent saved
picks (data/picks/latest.json) and prints the summary table:

  python scripts/fetch_data.py
"""

import io
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import download, load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
MAX_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 2
MATCH_TOLERANCE = 0.01  # Yahoo vs NSE prices may differ by at most 1%


def raw_path(ticker: str) -> Path:
    return RAW_DIR / f"{ticker.replace('^', 'IDX_')}.csv"


def download_one(ticker: str, start: date, end_inclusive: date) -> pd.DataFrame:
    """Download one ticker with retry + exponential backoff. Raises on total failure."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = yf.download(
                ticker,
                start=start,
                end=end_inclusive + timedelta(days=1),  # yfinance's end date is exclusive
                auto_adjust=True,                       # adjusts for splits, bonus issues and dividends
                progress=False,
                multi_level_index=False,
            )
            if df is None or df.empty:
                raise ValueError("empty dataframe returned")
            return df
        except Exception as exc:  # noqa: BLE001 - retry on anything, report clearly at the end
            last_error = exc
            if attempt < MAX_RETRIES:
                wait = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                print(f"  [retry] {ticker}: attempt {attempt} failed ({exc}); retrying in {wait}s")
                time.sleep(wait)
    raise RuntimeError(f"could not download {ticker} from Yahoo after {MAX_RETRIES} attempts: {last_error}")


def clean(df: pd.DataFrame, session: date, is_index: bool) -> tuple[pd.DataFrame, int]:
    df = df.sort_index()[["Open", "High", "Low", "Close", "Volume"]]
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[(df.index.date <= session) & df["Close"].notna()]
    if is_index:
        return df, 0
    fake = (df["Volume"] == 0) & (df["High"] == df["Low"])
    return df[~fake], int(fake.sum())


def nse_index_row(cfg: dict, session: date) -> dict:
    """The benchmark's session-day values from NSE's official index closing file."""
    url = cfg["source"]["index_close_url"].format(date=session)
    df = pd.read_csv(io.BytesIO(download(url, cfg["source"]["retries"])))
    df.columns = [c.strip() for c in df.columns]
    row = df[df["Index Name"].astype(str).str.strip().str.lower() == cfg["source"]["benchmark_index_name"].lower()]
    if len(row) != 1:
        raise RuntimeError(f"{cfg['source']['benchmark_index_name']} not found in {url}")
    r = row.iloc[0]
    close = float(r["Closing Index Value"])
    return {"open": float(r["Open Index Value"]), "high": float(r["High Index Value"]),
            "low": float(r["Low Index Value"]), "close": close,
            "prev_close": close - float(r["Points Change"]), "volume": float(r["Volume"])}


def fetch_history(picks: dict, cfg: dict) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Returns ({ticker: cleaned daily OHLCV}, {ticker: 'Yahoo' or 'NSE'}) for every picked
    stock plus the benchmark. The second dict says where the session-day price came from."""
    benchmark, years = cfg["history"]["benchmark"], cfg["history"]["years"]
    session = date.fromisoformat(picks["session_date"])
    start = session - timedelta(days=round(365.25 * years) + 7)
    stocks = picks["gainers"] + picks["losers"]
    nse = {s["yahoo_ticker"]: s for s in stocks}
    tickers = [s["yahoo_ticker"] for s in stocks] + [benchmark]

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    history, sources, summary, problems = {}, {}, [], []
    for ticker in tickers:
        print(f"Fetching {ticker} ...")
        try:
            df, holidays = clean(download_one(ticker, start, session), session, is_index=ticker == benchmark)
            if df.empty:
                raise RuntimeError(f"{ticker}: Yahoo returned no usable prices")

            if df.index[-1].date() == session:
                sources[ticker] = "Yahoo"
                if ticker in nse:
                    gap = abs(float(df["Close"].iloc[-1]) / nse[ticker]["close"] - 1)
                    if gap > MATCH_TOLERANCE:
                        raise RuntimeError(f"{ticker}: Yahoo's session close Rs {df['Close'].iloc[-1]:,.2f} differs "
                                           f"from NSE's Rs {nse[ticker]['close']:,.2f} by {gap:.1%}")
            else:
                # Yahoo is late: take the session row from NSE, if it joins on without a gap.
                official = nse[ticker] if ticker in nse else nse_index_row(cfg, session)
                last_close = float(df["Close"].iloc[-1])
                gap = abs(last_close / official["prev_close"] - 1)
                if gap > MATCH_TOLERANCE:
                    raise RuntimeError(f"{ticker}: Yahoo has no price for {session} yet, and its latest close "
                                       f"({df.index[-1].date()}: {last_close:,.2f}) does not match NSE's previous "
                                       f"close ({official['prev_close']:,.2f}), so a day may be missing")
                df.loc[pd.Timestamp(session)] = [official["open"], official["high"], official["low"],
                                                 official["close"], official["volume"]]
                sources[ticker] = "NSE"
                print(f"  Yahoo has no {session} price yet; used NSE's official session prices "
                      f"(Yahoo's {df.index[-2].date()} close matches NSE's previous close)")
        except Exception as exc:
            problems.append(str(exc))
            continue

        df.to_csv(raw_path(ticker))
        history[ticker] = df
        summary.append({
            "ticker": ticker,
            "start_date": df.index[0].strftime("%Y-%m-%d"),
            "end_date": df.index[-1].strftime("%Y-%m-%d"),
            "rows": len(df),
            "missing_values": int(df["Close"].isna().sum()),
            "holiday_rows_removed": holidays,
            "session_price_from": sources[ticker],
            "first_close": round(float(df["Close"].iloc[0]), 2),
            "last_close": round(float(df["Close"].iloc[-1]), 2),
        })

    # Keep data/raw tidy: only the current picks and the benchmark.
    keep = {raw_path(t).name for t in tickers}
    for f in RAW_DIR.glob("*.csv"):
        if f.name not in keep:
            f.unlink()

    print("\n=== Price history summary ===")
    if summary:
        print(pd.DataFrame(summary).to_string(index=False))
    if problems:
        raise RuntimeError("price history failed:\n  - " + "\n  - ".join(problems))
    return history, sources


def main() -> int:
    picks = json.loads((ROOT / "data" / "picks" / "latest.json").read_text(encoding="utf-8"))
    try:
        fetch_history(picks, load_config())
    except RuntimeError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    print("\nAll price histories fetched and checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
