"""
Fetches 5 years of daily OHLCV data for the five stocks + Nifty 50 benchmark
used by the dashboard, and saves one raw CSV per ticker to data/raw/.

Re-running this script re-downloads everything and overwrites the raw CSVs.
Downstream processing (process_data.py) always reads from data/raw/, so this
step only needs to be repeated when you want fresher data.
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ITC.NS", "INFY.NS", "^NSEI"]
YEARS_OF_HISTORY = 5
MAX_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 2

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def fetch_one(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Download one ticker with retry + exponential backoff. Raises on total failure."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=True,  # adjusts for splits and bonus issues
                progress=False,
                multi_level_index=False,
            )
            if df is None or df.empty:
                raise ValueError(f"empty dataframe returned for {ticker}")
            return df
        except Exception as exc:  # noqa: BLE001 - we want to retry on anything and report clearly
            last_error = exc
            if attempt < MAX_RETRIES:
                wait = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                print(f"  [retry] {ticker}: attempt {attempt} failed ({exc}); retrying in {wait}s")
                time.sleep(wait)
    raise RuntimeError(f"FAILED to fetch {ticker} after {MAX_RETRIES} attempts: {last_error}")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    end = datetime.today()
    start = end - timedelta(days=365 * YEARS_OF_HISTORY + 10)  # small buffer for weekends/holidays

    summary_rows = []
    failures = []

    for ticker in TICKERS:
        print(f"Fetching {ticker} ...")
        try:
            df = fetch_one(ticker, start, end)
        except RuntimeError as exc:
            print(f"  !!! {exc}", file=sys.stderr)
            failures.append(str(exc))
            continue

        df = df.sort_index()

        # Yahoo sometimes returns a trailing row for the still-in-progress trading
        # session with volume but null OHLC. Drop any such incomplete rows rather
        # than reporting a fake "missing value" in otherwise complete history.
        incomplete = df["Close"].isna()
        if incomplete.any():
            print(f"  dropping {int(incomplete.sum())} incomplete trailing row(s) for {ticker}")
            df = df.loc[~incomplete]

        out_path = RAW_DIR / f"{ticker.replace('^', 'IDX_')}.csv"
        df.to_csv(out_path)

        missing = int(df["Close"].isna().sum())
        summary_rows.append(
            {
                "ticker": ticker,
                "start_date": df.index.min().strftime("%Y-%m-%d"),
                "end_date": df.index.max().strftime("%Y-%m-%d"),
                "rows": len(df),
                "missing_values": missing,
                "first_close": round(float(df["Close"].iloc[0]), 2),
                "last_close": round(float(df["Close"].iloc[-1]), 2),
            }
        )

    print("\n=== Fetch summary ===")
    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        print(summary_df.to_string(index=False))
    if failures:
        print(f"\n{len(failures)} ticker(s) FAILED completely:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)

    print("\nAll tickers fetched successfully.")


if __name__ == "__main__":
    main()
