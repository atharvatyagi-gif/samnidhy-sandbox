"""
Computes every statistic the dashboard shows for the day's picked stocks.

All comparisons between stocks use ONE shared analysis window: the dates on which every
picked stock and the benchmark have a price (capped at the configured number of years).
A stock that listed recently therefore shortens the window for everyone; the window is
saved in the output so the site can say so.

Per stock, over the window:
  - annualised return (CAGR), annualised volatility (std of daily returns x sqrt(252)),
    maximum drawdown, beta against the benchmark, total return
Per stock, from other sources:
  - the session move from NSE (label, % change, closes, traded value) - from the picks
  - trailing P/E and market cap from yfinance .info (null if unavailable, never guessed)
Across the stocks, over the window:
  - correlation matrix and annualised covariance matrix of daily returns
Benchmark:
  - the same window statistics, plus its annualised return over its full history
    (the SIP lesson's default, independent of which stocks were picked)
Weekly closes (last close of each week) for every series, for the race and hero charts.

Used by scripts/update.py; it is not run on its own.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

TRADING_DAYS_PER_YEAR = 252
MIN_WINDOW_DAYS = 20  # fewer shared trading days than this and the comparisons mean nothing


def cagr(close: pd.Series) -> float:
    years = (close.index[-1] - close.index[0]).days / 365.25
    return float((close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1)


def max_drawdown(close: pd.Series) -> float:
    return float((close / close.cummax() - 1).min())


def beta(stock_ret: pd.Series, bench_ret: pd.Series) -> float:
    return float(np.cov(stock_ret, bench_ret)[0, 1] / np.var(bench_ret, ddof=1))


def info_fields(ticker: str) -> dict:
    """Trailing P/E and market cap. Either may be missing (e.g. no P/E for a loss-making
    company); missing values are stored as null, never estimated."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not read company details for {ticker}: {exc}")
        info = {}

    def get(key):
        v = info.get(key)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else v

    return {"trailing_pe": get("trailingPE"), "market_cap": get("marketCap")}


def weekly_closes(series: dict[str, pd.Series], session: pd.Timestamp) -> dict:
    """Last close of each week per series, on one shared week index. Weeks before a stock
    listed are null; nothing is filled in."""
    frame = pd.DataFrame(series).sort_index()
    weekly = frame.resample("W-FRI").last()
    weekly.index = list(weekly.index[:-1]) + [session]  # last week ends on the session, not a future Friday
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
        "close": {t: [None if pd.isna(v) else round(float(v), 2) for v in weekly[t]] for t in weekly.columns},
    }


def analyse(picks: dict, history: dict[str, pd.DataFrame], cfg: dict, sources: dict[str, str],
            bench_session: dict | None) -> dict:
    """sources says, per ticker, whether the session-day price came from Yahoo or NSE.
    bench_session is NSE's official session move for the benchmark (None if unavailable)."""
    bench = cfg["history"]["benchmark"]
    meta = picks["gainers"] + picks["losers"]
    order = [s["yahoo_ticker"] for s in meta]
    closes = {t: history[t]["Close"].astype(float) for t in order}
    bench_close = history[bench]["Close"].astype(float)
    session = pd.Timestamp(picks["session_date"])

    # ---- shared analysis window ----
    frame = pd.DataFrame({**closes, bench: bench_close}).dropna()
    if len(frame) < MIN_WINDOW_DAYS:
        raise RuntimeError(f"the six stocks share only {len(frame)} trading days of prices; "
                           f"at least {MIN_WINDOW_DAYS} are needed for the comparisons")
    returns = frame.pct_change().dropna()
    w_start, w_end = frame.index[0], frame.index[-1]
    w_years = (w_end - w_start).days / 365.25
    youngest = [t for t in order if closes[t].index[0] == w_start]

    # ---- per stock ----
    stocks = {}
    for s in meta:
        t = s["yahoo_ticker"]
        print(f"  company details for {t} ...")
        own = closes[t]
        stocks[t] = {
            **{k: s[k] for k in ("symbol", "name", "industry", "group", "rank", "label")},
            "session": {k: s[k] for k in ("prev_close", "close", "pct_change", "volume", "turnover_crore")},
            "latest_close": round(float(own.iloc[-1]), 2),
            **info_fields(t),
            "history": {
                "first_date": own.index[0].strftime("%Y-%m-%d"),
                "trading_days": int(len(own)),
                "years": round((own.index[-1] - own.index[0]).days / 365.25, 2),
                "session_price_from": sources[t],
            },
            "annualised_return": round(cagr(frame[t]), 6),
            "total_return": round(float(frame[t].iloc[-1] / frame[t].iloc[0] - 1), 6),
            "annualised_volatility": round(float(returns[t].std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 6),
            "max_drawdown": round(max_drawdown(frame[t]), 6),
            "beta": round(beta(returns[t], returns[bench]), 4),
        }

    corr = returns[order].corr()
    cov = returns[order].cov() * TRADING_DAYS_PER_YEAR

    now = datetime.now(timezone.utc)
    return {
        "site_name": "Samnidhy Sandbox",
        "generated_on": now.isoformat(timespec="seconds"),
        "session_date": picks["session_date"],
        "source": "NSE end-of-day file (picks and session moves); Yahoo Finance via yfinance (price history, P/E, market cap)",
        "trading_days_per_year": TRADING_DAYS_PER_YEAR,
        "selection": {
            "universe_name": picks["settings"]["filters"]["universe_name"],
            "universe_count": picks["universe_count"],
            "eligible_count": picks["eligible_count"],
            "gainers_count": len(picks["gainers"]),
            "losers_count": len(picks["losers"]),
            "min_price": picks["settings"]["filters"]["min_price"],
            "min_turnover_crore": picks["settings"]["filters"]["min_turnover_crore"],
            "min_history_years": picks["settings"]["filters"].get("min_history_years", 0),
            "skipped": picks.get("skipped", []),
            "session_file": picks["source"]["session_file"],
        },
        "order": order,
        "stocks": stocks,
        "analysis_window": {
            "start": w_start.strftime("%Y-%m-%d"),
            "end": w_end.strftime("%Y-%m-%d"),
            "trading_days": int(len(frame)),
            "years": round(w_years, 2),
            "limited_by": youngest if w_years < cfg["history"]["years"] - 0.1 else [],
            "short": w_years < 1,
        },
        "benchmark": {
            "ticker": bench,
            "name": "Nifty 50",
            "annualised_return_full": round(cagr(bench_close), 6),
            "full_history": {
                "start": bench_close.index[0].strftime("%Y-%m-%d"),
                "end": bench_close.index[-1].strftime("%Y-%m-%d"),
                "years": round((bench_close.index[-1] - bench_close.index[0]).days / 365.25, 2),
                "session_price_from": sources[bench],
            },
            "latest_close": round(float(bench_close.iloc[-1]), 2),
            # From NSE's official index file (Yahoo's index history can skip a day); null if unavailable.
            "session_pct_change": None if bench_session is None else bench_session["pct_change"],
            "annualised_return": round(cagr(frame[bench]), 6),
            "total_return": round(float(frame[bench].iloc[-1] / frame[bench].iloc[0] - 1), 6),
            "annualised_volatility": round(float(returns[bench].std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 6),
            "max_drawdown": round(max_drawdown(frame[bench]), 6),
        },
        "correlation_matrix": {r: {c: round(float(corr.loc[r, c]), 4) for c in order} for r in order},
        "covariance_matrix": {r: {c: round(float(cov.loc[r, c]), 6) for c in order} for r in order},
        "weekly": weekly_closes({**closes, bench: bench_close}, session),
    }
