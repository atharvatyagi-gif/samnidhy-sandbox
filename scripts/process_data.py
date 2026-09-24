"""
Reads the raw per-ticker CSVs in data/raw/ and computes every statistic the
dashboard needs, writing the result to data/data.json.

Metrics per stock:
  - daily returns (used internally, not stored raw)
  - annualised return over the full period
  - annualised volatility (std dev of daily returns * sqrt(252))
  - maximum drawdown
  - beta against the Nifty 50
  - latest close, trailing P/E, market cap, sector (from yfinance .info;
    any field yfinance doesn't provide is stored as null - never guessed)

Across the set:
  - correlation matrix of daily returns
  - covariance matrix of daily returns (annualised) - needed so the
    dashboard can compute true portfolio risk, not a weighted average
  - Nifty 50 annualised return over the period

TRADING_DAYS_PER_YEAR = 252 is the standard convention for annualising
Indian/US equity daily data.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ITC.NS", "INFY.NS"]
BENCHMARK = "^NSEI"
TRADING_DAYS_PER_YEAR = 252

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_PATH = ROOT / "data" / "data.json"


def raw_path(ticker: str) -> Path:
    return RAW_DIR / f"{ticker.replace('^', 'IDX_')}.csv"


def load_close_series(ticker: str) -> pd.Series:
    df = pd.read_csv(raw_path(ticker), index_col=0, parse_dates=True)
    return df["Close"].astype(float)


def annualised_return(close: pd.Series) -> float:
    years = (close.index[-1] - close.index[0]).days / 365.25
    total_growth = close.iloc[-1] / close.iloc[0]
    return float(total_growth ** (1 / years) - 1)


def annualised_volatility(daily_returns: pd.Series) -> float:
    return float(daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(close: pd.Series) -> float:
    running_max = close.cummax()
    drawdown = close / running_max - 1
    return float(drawdown.min())


def beta_vs_benchmark(stock_returns: pd.Series, bench_returns: pd.Series) -> float:
    aligned = pd.concat([stock_returns, bench_returns], axis=1, join="inner").dropna()
    cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])[0, 1]
    var = np.var(aligned.iloc[:, 1], ddof=1)
    return float(cov / var)


def safe_info_field(info: dict, key: str):
    value = info.get(key)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return value


def weekly_growth_series(closes: dict, bench_close: pd.Series) -> dict:
    """
    Growth of 1 unit invested on the first day, sampled weekly (last close of each
    week, Friday-ending), for every stock and the benchmark. Used by the dashboard's
    animated "growth race" and hero chart.

    Each column takes its own last available close in each week, so no prices are
    filled or interpolated. The first point is the exact first trading day (value 1.0)
    and the final point is relabelled to the last real trading date, so final values
    equal last close / first close — consistent with annualised_return.
    """
    frame = pd.DataFrame({**closes, BENCHMARK: bench_close}).sort_index()
    start = frame.iloc[0]
    if start.isna().any():
        raise ValueError(f"missing first-day close for: {list(start[start.isna()].index)}")

    weekly = frame.resample("W-FRI").last()
    weekly.index = list(weekly.index[:-1]) + [frame.index[-1]]
    weekly = pd.concat([frame.iloc[[0]], weekly])
    rebased = weekly / start

    return {
        "note": "Value of 1 unit invested on the first date, weekly closes (last trading day of each week).",
        "dates": [d.strftime("%Y-%m-%d") for d in rebased.index],
        "series": {col: [round(float(v), 4) for v in rebased[col]] for col in rebased.columns},
    }


def main() -> None:
    print("Loading raw price series...")
    closes = {t: load_close_series(t) for t in TICKERS}
    bench_close = load_close_series(BENCHMARK)

    returns = {t: c.pct_change().dropna() for t, c in closes.items()}
    bench_returns = bench_close.pct_change().dropna()

    print("Computing per-stock metrics...")
    stocks = {}
    for ticker in TICKERS:
        close = closes[ticker]
        ret = returns[ticker]

        print(f"  fetching .info for {ticker} (P/E, market cap, sector)...")
        info = yf.Ticker(ticker).info or {}

        stocks[ticker] = {
            "name": safe_info_field(info, "shortName"),
            "sector": safe_info_field(info, "sector"),
            "latest_close": round(float(close.iloc[-1]), 2),
            "trailing_pe": safe_info_field(info, "trailingPE"),
            "market_cap": safe_info_field(info, "marketCap"),
            "annualised_return": round(annualised_return(close), 6),
            "annualised_volatility": round(annualised_volatility(ret), 6),
            "max_drawdown": round(max_drawdown(close), 6),
            "beta": round(beta_vs_benchmark(ret, bench_returns), 4),
            "trading_days": int(len(close)),
        }

    print("Computing correlation and covariance matrices...")
    returns_df = pd.DataFrame(returns).dropna()
    correlation_matrix = returns_df.corr().round(4)
    # Annualised covariance matrix (daily covariance * trading days/year) so the
    # dashboard can compute portfolio variance = w' * Cov * w directly.
    covariance_matrix = (returns_df.cov() * TRADING_DAYS_PER_YEAR).round(6)

    nifty_annualised_return = annualised_return(bench_close)

    output = {
        "generated_on": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Yahoo Finance (via yfinance), NSE-listed tickers",
        "trading_days_per_year": TRADING_DAYS_PER_YEAR,
        "period": {
            "start": returns_df.index.min().strftime("%Y-%m-%d"),
            "end": returns_df.index.max().strftime("%Y-%m-%d"),
        },
        "benchmark": {
            "ticker": BENCHMARK,
            "annualised_return": round(nifty_annualised_return, 6),
        },
        "stocks": stocks,
        "correlation_matrix": {
            row: {col: correlation_matrix.loc[row, col] for col in correlation_matrix.columns}
            for row in correlation_matrix.index
        },
        "covariance_matrix": {
            row: {col: covariance_matrix.loc[row, col] for col in covariance_matrix.columns}
            for row in covariance_matrix.index
        },
        "weekly_growth": weekly_growth_series(closes, bench_close),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
