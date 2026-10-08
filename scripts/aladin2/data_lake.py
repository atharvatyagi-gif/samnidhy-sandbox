"""
ALADIN 2.0 point-in-time feature store.

Rule of the whole engine: a feature in row t uses information that was public by the close of day t, and may only drive a trade at the OPEN of t+1.
Everything here is causal (trailing windows only, no centred windows, no shift(-n)); tests/aladin2/test_leakage.py enforces it.

Each non-price source has a publication lag, in trading days, applied BEFORE it is joined (value dated D is first usable on row D + lag):
  SOURCE_LAG_D below. Quarterly fundamentals use the real filing date when known; with only a period end the lag is FUNDAMENTAL_LAG_CAL_D (60 calendar days).
Prices come from data/terminal/daily (5 years, split-adjusted, NOT dividend-adjusted) joined with data/terminal/archive (older years). A one-day move
beyond +-35% is flagged `suspect_action` (an unadjusted split/bonus would look like that) and is excluded from return statistics by the callers.
Missing inputs stay NaN. Nothing is imputed; callers that need a value say "not measured".
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
_MAIN = ROOT.parent / "SAMNIDHY_EDUCATIONAL_DASHBOARD" / "data" / "terminal"
TERM = Path(os.environ["ALADIN2_TERM"]) if os.environ.get("ALADIN2_TERM") else (_MAIN if _MAIN.exists() and not (ROOT / "data" / "terminal" / "daily").exists() else ROOT / "data" / "terminal")

# trading days between a value's date and the first decision row allowed to use it (conservative: evening publications are lagged a full day)
SOURCE_LAG_D = {"price": 0, "india_vix": 0, "delivery": 1, "fno_oi": 1, "fii_dii": 1, "usdinr": 1, "brent": 1, "sp500": 1, "nikkei": 1, "us10y": 1, "news": 1, "wiki": 1}
FUNDAMENTAL_LAG_CAL_D = 60
ASOF = os.environ.get("ALADIN2_ASOF") or None      # replay mode: every loader returns only data up to this date (set by run_nightly.py --replay; never set in production)
SUSPECT_MOVE = 0.35


# ------------------------------------------------------------------ prices

def _rows(path):
    if not path.exists():
        return []
    d = json.loads(path.read_text(encoding="utf-8"))
    return d["d"] if isinstance(d, dict) else d


def load_prices(sym, term=None):
    """Daily bars (archive + daily, newest file wins on overlap) -> DataFrame indexed by date with o,h,l,c,v; or None."""
    t = Path(term) if term else TERM
    rows = {}
    for f in (t / "archive" / f"{sym}.json", t / "daily" / f"{sym}.json"):
        for r in _rows(f):
            rows[r[0]] = r
    if not rows:
        return None
    k = sorted(rows)
    df = pd.DataFrame([rows[x][:6] for x in k], columns=["d", "o", "h", "l", "c", "v"])
    df["d"] = pd.to_datetime(df["d"])
    df = df.set_index("d").astype(float)
    if ASOF:
        df = df[df.index <= pd.Timestamp(ASOF)]
    return df[(df["c"] > 0) & (df["o"] > 0)]


def clean_prices(px):
    """Data hygiene, no imputation. (1) A one-bar spike (|move| > 35% that reverses to within 20% of the earlier price on the next bar) is a bad print: the bar is DROPPED,
    so it is simply a missing day (no fill). (2) A persistent jump beyond 35% is an unadjusted split/bonus/merger in the source: it stays in the data but is flagged
    `suspect_action`; the 250 bars after it are `post_break` (long-window features are mixed-scale there, so no new entries), and the backtest discards any trade that
    holds across it. Adds columns: pc (previous close), suspect_action, post_break, locked (one-price day)."""
    px = px.copy()
    for _ in range(3):
        c = px["c"]; mv = (c / c.shift() - 1).abs(); back = (c.shift(-1) / c.shift() - 1).abs()
        spike = (mv > SUSPECT_MOVE) & (back < 0.2)
        if not spike.any():
            break
        px = px[~spike]
    px["pc"] = px["c"].shift()
    px["suspect_action"] = (px["c"] / px["pc"] - 1).abs() > SUSPECT_MOVE
    px["post_break"] = px["suspect_action"].astype(int).rolling(250, min_periods=1).max().astype(bool)
    px["locked"] = (px["h"] == px["l"]) & (px["o"] == px["c"])
    return px


# ------------------------------------------------------------------ side series with publication lags

def lag_series(s, lag_d):
    """Shift a date-indexed series forward by `lag_d` rows of ITS OWN calendar so that value dated D first appears on D + lag (rows, not calendar days)."""
    return s.shift(lag_d) if lag_d else s


def attach(df, series, name, lag_d=None):
    """Join a (date -> value) Series onto the decision frame `df` as column `name`, using the last value published on or before each row's date after the lag.
    The series is lagged on its own trading calendar first, then forward-filled onto df's dates with merge_asof (backward only, never forward-looking)."""
    lag = SOURCE_LAG_D.get(name, 1) if lag_d is None else lag_d
    s = series.dropna().sort_index(); s = lag_series(s, lag).dropna()
    m = pd.merge_asof(pd.DataFrame({"d": df.index}), s.rename(name).rename_axis("d").reset_index(), on="d", direction="backward")
    out = df.copy(); out[name] = m[name].values
    return out


def fundamentals_available_at(period_end, filing_date=None):
    """Earliest date a quarterly figure may be used: the filing date if known, else period end + 60 calendar days."""
    if filing_date is not None and not pd.isna(filing_date):
        return pd.Timestamp(filing_date)
    return pd.Timestamp(period_end) + pd.Timedelta(days=FUNDAMENTAL_LAG_CAL_D)


def load_macro(name, term=None):
    p = (Path(term) if term else TERM) / "aladin2" / "macro" / f"{name}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())["d"]
    return pd.Series([v for _, v in d], index=pd.to_datetime([k for k, _ in d]), name=name)


def load_delivery(sym, term=None):
    """Delivery % series for one stock from the backfilled daily files (gzip csv). Empty Series when the backfill has not run."""
    import gzip
    folder = (Path(term) if term else TERM) / "aladin2" / "deliv"
    out = {}
    for f in sorted(folder.glob("2*.csv.gz")):
        with gzip.open(f, "rt") as h:
            for line in h:
                if line.startswith(sym + ","):
                    p = line.rstrip().split(","); out[f.name[:10]] = float(p[5]) if p[5] not in ("", "nan") else np.nan; break
    return pd.Series(out, dtype=float, index=pd.to_datetime(list(out))) if out else pd.Series(dtype=float)


def load_delivery_panel(term=None):
    """All backfilled delivery files as {symbol: Series(date -> delivery %)}, read once (the per-stock reader above rescans every file)."""
    import gzip
    folder = (Path(term) if term else TERM) / "aladin2" / "deliv"; frames = []
    for f in sorted(folder.glob("2*.csv.gz")):
        d = pd.read_csv(f, usecols=["SYMBOL", "SERIES", "DELIV_PER"]); d = d[d["SERIES"] == "EQ"]; d["d"] = pd.Timestamp(f.name[:10]); frames.append(d[["d", "SYMBOL", "DELIV_PER"]])
    if not frames:
        return {}
    A = pd.concat(frames); return {sym: g.set_index("d")["DELIV_PER"].astype(float) for sym, g in A.groupby("SYMBOL")}


def load_index(name="_5eNSEI", term=None):
    """NIFTY 50 closes (archive + daily, like any stock), or None."""
    px = load_prices(name, term)
    return None if px is None else px["c"].rename("nifty")


# ------------------------------------------------------------------ features (all causal)

def _rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def price_features(px):
    """Price/volume features from daily bars. Row t uses bars up to and including t only. Returns a new DataFrame with the same index."""
    c, o, h, l, v = px["c"], px["o"], px["h"], px["l"], px["v"]
    lr = np.log(c / c.shift())
    lr = lr.where(~((c / c.shift() - 1).abs() > SUSPECT_MOVE))            # an unadjusted corporate action is not a return
    F = pd.DataFrame(index=px.index)
    F["lr1"] = lr
    for n in (5, 10, 20, 60, 120, 250):
        F[f"r{n}"] = lr.rolling(n, min_periods=int(n * 0.8)).sum()
    F["mom12_1"] = lr.shift(21).rolling(231, min_periods=200).sum()
    for n in (20, 50, 200):
        sma = c.rolling(n, min_periods=int(n * 0.8)).mean(); F[f"d_sma{n}"] = c / sma - 1
    F["sma50_slope"] = c.rolling(50).mean().pct_change(10)
    pc = c.shift(); tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    F["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean(); F["atr_pct"] = F["atr14"] / c
    F["vol20"] = lr.rolling(20, min_periods=16).std(); F["vol60"] = lr.rolling(60, min_periods=48).std(); F["vol_ratio"] = F["vol20"] / F["vol60"]
    F["rsi2"] = _rsi(c, 2); F["rsi14"] = _rsi(c, 14)
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std(); F["bb_z"] = (c - m20) / s20; F["bb_w"] = 4 * s20 / m20
    F["hi52"] = c / c.rolling(250, min_periods=200).max() - 1; F["lo52"] = c / c.rolling(250, min_periods=200).min() - 1
    F["don20_hi"] = (c >= h.rolling(20).max()).astype(float); F["don20_lo"] = (c <= l.rolling(20).min()).astype(float)
    F["gap"] = np.log(o / pc); F["overnight20"] = F["gap"].rolling(20).sum(); F["intraday20"] = np.log(c / o).rolling(20).sum()
    F["vz20"] = np.log((v + 1) / (v.rolling(20, min_periods=16).mean() + 1))
    F["adv_cr"] = (c * v).rolling(20, min_periods=16).mean() / 1e7
    F["range_pct"] = (h - l) / c; F["nr7"] = (F["range_pct"] <= F["range_pct"].rolling(7).min()).astype(float)
    return F


def build_frame(sym, term=None, with_side=True):
    """Prices + price features + any available side series, each attached with its publication lag. -> DataFrame (or None when the stock has no data)."""
    px = load_prices(sym, term)
    if px is None:
        return None
    px = clean_prices(px); F = pd.concat([px, price_features(px)], axis=1)
    if with_side:
        for name in ("india_vix", "usdinr", "brent", "sp500", "nikkei", "us10y"):
            s = load_macro(name, term)
            if s is not None:
                F = attach(F, s, name)
        d = load_delivery(sym, term)
        if len(d):
            F = attach(F, d, "delivery")
    return F


FEATURE_META = {   # feature group -> (source, lag in trading days); used by the ablation report and the UI "what went in"
    "price": ("t/d daily bars", 0), "macro": ("Yahoo / FRED daily", 1), "delivery": ("NSE delivery %", 1), "fno_oi": ("NSE F&O bhavcopy", 1), "fundamental": ("filings", "filing date, else period end + 60 days")}
