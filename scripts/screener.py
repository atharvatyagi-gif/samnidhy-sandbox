"""
Stock screener: picks the stocks for the "Stock Screener" section, once a day.

Funnel (every step is counted and shown on the site):
  1. Universe: NIFTY 500 (same official list as the daily movers).
  2. Drop industries the Magic Formula is not meant for (banks/NBFCs/insurers, power utilities).
  3. Liquidity: price and average daily traded value over the last 3 months (from Yahoo prices),
     and at least one year of price history so every technical signal on the Advanced page can be
     calculated (200-day average, 12-1 momentum, 52-week high, volatility).
  4. Fundamentals from the last two annual reports (Yahoo Finance):
       - Piotroski F-Score (Piotroski, 2000): 9 yes/no health checks. Keep scores >= min_fscore.
       - Greenblatt Magic Formula (The Little Book That Beats the Market, 2005):
           return on capital = EBIT / (net working capital + net fixed assets)
           earnings yield    = EBIT / enterprise value
         rank each, add the two ranks, lowest total wins.
  5. The best `count` stocks by Magic Formula rank.

Every stock that passes step 4 is also saved to data/screener/candidates.json, so that
scripts/screener_live.py can re-rank them on live prices every 15 minutes in market hours
(earnings yield moves with the share price; the annual-report numbers do not).

A stock with a missing number is never guessed: it is left out and the reason is counted.

  python scripts/screener.py            run and save data/screener/latest.json
"""

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_movers import ROOT, load_config, load_universe  # noqa: E402

OUT_DIR = ROOT / "data" / "screener"
IST = timezone(timedelta(hours=5, minutes=30))


def num(df, row, col=0):
    """A number from a Yahoo statement table, or None if it is missing (never a guess)."""
    if df is None or df.empty or row not in df.index or col >= df.shape[1]:
        return None
    v = df.loc[row].iloc[col]
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def clean(v):
    """A ratio from Yahoo's summary, or None when it is missing or not a real number."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def first(df, rows, col=0):
    for r in rows:
        v = num(df, r, col)
        if v is not None:
            return v
    return None


def price_study(tickers):
    """One bulk download (~14 months) for every universe stock. Returns, per stock, liquidity and the
    research-backed price signals, used for the liquidity filter, for ranking the picks against the
    whole index, and for market breadth."""
    data = yf.download(tickers, period="14mo", interval="1d", group_by="ticker", auto_adjust=True,
                       threads=True, progress=False)
    out = {}
    for t in tickers:
        try:
            d = data[t].dropna(subset=["Close"])
        except KeyError:
            continue
        d = d[d["Volume"] > 0]
        if len(d) < 40:
            continue
        c = d["Close"]
        last = float(c.iloc[-1])
        row = {"price": last, "turnover_cr": float((c.tail(63) * d["Volume"].tail(63)).median() / 1e7)}
        if len(c) >= 200:
            row["above_200dma"] = bool(last > c.tail(200).mean())
        if len(c) >= 253:
            row["momentum_12_1"] = float(c.iloc[-22] / c.iloc[-253] - 1)
            row["high_52w_ratio"] = float(last / d["High"].tail(252).max())
            row["vol_1y"] = float(np.log(c).diff().tail(252).std() * math.sqrt(252))
        out[t] = row
    return out


def piotroski(inc, bs, cf):
    """The nine Piotroski checks, latest year (0) vs previous year (1). None = data missing."""
    ni0, ni1 = num(inc, "Net Income", 0), num(inc, "Net Income", 1)
    ta0, ta1 = num(bs, "Total Assets", 0), num(bs, "Total Assets", 1)
    cfo0 = first(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0)
    debt = ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]
    ltd0, ltd1 = first(bs, debt, 0), first(bs, debt, 1)
    if ltd0 is None and ltd1 is None and ta0 is not None:       # no long-term debt line = debt-free
        ltd0 = ltd1 = 0.0
    ca0, ca1 = num(bs, "Current Assets", 0), num(bs, "Current Assets", 1)
    cl0, cl1 = num(bs, "Current Liabilities", 0), num(bs, "Current Liabilities", 1)
    sh0, sh1 = first(bs, ["Ordinary Shares Number", "Share Issued"], 0), first(bs, ["Ordinary Shares Number", "Share Issued"], 1)
    rev0, rev1 = num(inc, "Total Revenue", 0), num(inc, "Total Revenue", 1)

    def gross(col):
        gp = num(inc, "Gross Profit", col)
        if gp is None:
            r, c = num(inc, "Total Revenue", col), num(inc, "Cost Of Revenue", col)
            gp = r - c if r is not None and c is not None else None
        return gp
    gp0, gp1 = gross(0), gross(1)

    def ok(*vals):
        return all(v is not None for v in vals)

    def div(a, b):
        return a / b if b else None
    roa0, roa1 = (div(ni0, ta0), div(ni1, ta1)) if ok(ni0, ta0, ni1, ta1) else (None, None)
    checks = {
        "Profitable (net income > 0)": (ni0 > 0) if ok(ni0) else None,
        "Cash from operations > 0": (cfo0 > 0) if ok(cfo0) else None,
        "Return on assets improved": (roa0 > roa1) if ok(roa0, roa1) else None,
        "Cash profit above book profit": (cfo0 > ni0) if ok(cfo0, ni0) else None,
        "Long-term debt ratio fell (or none)": (div(ltd0, ta0) <= div(ltd1, ta1)) if ok(ltd0, ltd1, ta0, ta1) else None,
        "Current ratio improved": (div(ca0, cl0) > div(ca1, cl1)) if ok(ca0, cl0, ca1, cl1) and cl0 and cl1 else None,
        "No new shares issued": (sh0 <= sh1 * 1.001) if ok(sh0, sh1) else None,
        "Gross margin improved": (div(gp0, rev0) > div(gp1, rev1)) if ok(gp0, rev0, gp1, rev1) else None,
        "Asset turnover improved": (div(rev0, ta0) > div(rev1, ta1)) if ok(rev0, ta0, rev1, ta1) else None,
    }
    return checks


def fundamentals(t):
    """Everything needed for one stock, or a reason it cannot be scored."""
    for attempt in range(3):
        try:
            tk = yf.Ticker(t)
            inc, bs, cf = tk.income_stmt, tk.balance_sheet, tk.cashflow
            info = tk.info
            break
        except Exception as exc:  # network hiccup / rate limit: wait and retry
            if attempt == 2:
                return {"ticker": t, "skip": f"download failed ({type(exc).__name__})"}
            time.sleep(3 * (attempt + 1))
    if inc is None or inc.empty or bs is None or bs.empty or inc.shape[1] < 2 or bs.shape[1] < 2:
        return {"ticker": t, "skip": "fewer than 2 annual reports"}
    if info.get("financialCurrency") not in (None, "INR"):
        return {"ticker": t, "skip": f"accounts in {info.get('financialCurrency')}"}
    ebit = num(inc, "EBIT")
    ca, cl, ppe = num(bs, "Current Assets"), num(bs, "Current Liabilities"), num(bs, "Net PPE")
    cash = first(bs, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]) or 0.0
    sti = num(bs, "Other Short Term Investments") or 0.0
    cur_debt = first(bs, ["Current Debt", "Current Debt And Capital Lease Obligation"]) or 0.0
    total_debt = num(bs, "Total Debt") or 0.0
    mcap = info.get("marketCap")
    if None in (ebit, ca, cl, ppe) or not mcap:
        return {"ticker": t, "skip": "missing EBIT, balance-sheet items or market value"}
    nwc = max((ca - cash - sti) - (cl - cur_debt), 0.0)       # operating working capital only
    capital = nwc + ppe
    ev = mcap + total_debt - cash - sti
    if capital <= 0 or ev <= 0:
        return {"ticker": t, "skip": "capital or enterprise value not positive"}
    checks = piotroski(inc, bs, tk.cashflow if cf is None else cf)
    known = [v for v in checks.values() if v is not None]
    if len(known) < 8:
        return {"ticker": t, "skip": "not enough data for the F-Score"}
    return {
        "ticker": t,
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "fy_end": str(inc.columns[0].date()),
        "ebit": ebit, "capital": capital, "ev": ev, "market_cap": mcap,
        "roc": ebit / capital, "earnings_yield": ebit / ev,
        "fscore": sum(1 for v in known if v), "fscore_known": len(known),
        "checks": {k: v for k, v in checks.items()},
        "pe": info.get("trailingPE"), "pb": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"), "debt_to_equity": info.get("debtToEquity"),
        "dividend_yield": info.get("dividendYield"),
        "held_institutions": info.get("heldPercentInstitutions"), "held_insiders": info.get("heldPercentInsiders"),
        "analysts": info.get("numberOfAnalystOpinions"), "recommendation": info.get("recommendationKey"),
        "recommendation_mean": info.get("recommendationMean"),
        "target_mean": info.get("targetMeanPrice"), "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "eps": info.get("trailingEps"), "shares_out": info.get("sharesOutstanding"),
        "employees": info.get("fullTimeEmployees"), "website": info.get("website"),
        "city": info.get("city"), "beta": info.get("beta"),
        "summary": (info.get("longBusinessSummary") or "")[:1200] or None,
    }


def rank(candidates, count):
    """Magic Formula: rank return on capital and earnings yield (higher = better), add the two ranks,
    lowest total wins (ties: higher return on capital). Returns the best `count`, numbered."""
    df = pd.DataFrame({"i": range(len(candidates)), "roc": [c["roc"] for c in candidates],
                       "earnings_yield": [c["earnings_yield"] for c in candidates]})
    df["rank_roc"] = df["roc"].rank(ascending=False, method="min")
    df["rank_ey"] = df["earnings_yield"].rank(ascending=False, method="min")
    df["magic_score"] = df["rank_roc"] + df["rank_ey"]
    df = df.sort_values(["magic_score", "roc"], ascending=[True, False]).reset_index(drop=True)
    out = []
    for i, c in enumerate(df.head(count).to_dict("records")):
        rec = dict(candidates[int(c["i"])])        # the original record: missing values stay None, never NaN
        rec.update(magic_rank=i + 1, rank_roc=int(c["rank_roc"]), rank_ey=int(c["rank_ey"]), of=len(df))
        out.append(rec)
    return out


def run():
    cfg = load_config()
    sc = cfg["screener"]
    uni, uni_source = load_universe(cfg)
    uni = uni[~uni["Symbol"].str.startswith(tuple(cfg["filters"]["exclude_prefixes"]))]
    funnel = [{"step": f"{cfg['filters']['universe_name']} stocks", "count": len(uni)}]
    keep = uni[~uni["Industry"].isin(sc["exclude_industries"])]
    funnel.append({"step": "Not a bank, NBFC, insurer or power utility", "count": len(keep)})
    names = dict(zip(keep["Symbol"] + ".NS", keep["Company Name"]))
    industry = dict(zip(keep["Symbol"] + ".NS", keep["Industry"]))

    all_t = list(uni["Symbol"] + ".NS")
    print(f"Price study for {len(all_t)} stocks...")
    liq = price_study(all_t)
    liquid = [t for t, v in liq.items() if t in names
              and v["price"] >= sc["min_price"] and v["turnover_cr"] >= sc["min_avg_turnover_crore"]]
    funnel.append({"step": f"Price above Rs {sc['min_price']} and trades Rs {sc['min_avg_turnover_crore']} Cr+ a day",
                   "count": len(liquid)})
    liquid = [t for t in liquid if "momentum_12_1" in liq[t]]
    funnel.append({"step": "1 year+ of price history, so the technicals can be calculated", "count": len(liquid)})

    print(f"Fundamentals for {len(liquid)} stocks...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(fundamentals, sorted(liquid)))
    skipped = {}
    good = [r for r in rows if "skip" not in r]
    for r in rows:
        if "skip" in r:
            skipped.setdefault(r["skip"], []).append(r["ticker"].removesuffix(".NS"))
    funnel.append({"step": "Complete annual-report data", "count": len(good)})
    healthy = [r for r in good if r["fscore"] >= sc["min_fscore"]]
    funnel.append({"step": f"Piotroski F-Score {sc['min_fscore']} or more (out of 9)", "count": len(healthy)})
    if len(healthy) < sc["count"]:
        raise RuntimeError(f"only {len(healthy)} stocks passed the screen (need {sc['count']})")

    candidates = []
    for r in healthy:
        t = r["ticker"]
        candidates.append({
            "symbol": t.removesuffix(".NS"), "yahoo_ticker": t, "name": names.get(t) or r["name"],
            "industry": industry.get(t), "sector": r["sector"], "fy_end": r["fy_end"],
            "price": round(liq[t]["price"], 2), "avg_turnover_cr": round(liq[t]["turnover_cr"], 1),
            "roc": round(r["roc"], 4), "earnings_yield": round(r["earnings_yield"], 4),
            "fscore": int(r["fscore"]), "fscore_known": int(r["fscore_known"]), "checks": r["checks"],
            "ebit_cr": round(r["ebit"] / 1e7, 1), "capital_cr": round(r["capital"] / 1e7, 1),
            "ev_cr": round(r["ev"] / 1e7, 1), "market_cap_cr": round(r["market_cap"] / 1e7, 1),
            "pe": clean(r["pe"]), "pb": clean(r["pb"]), "roe": clean(r["roe"]),
            "debt_to_equity": clean(r["debt_to_equity"]), "dividend_yield": clean(r["dividend_yield"]),
            "held_institutions": clean(r["held_institutions"]), "held_insiders": clean(r["held_insiders"]),
            "analysts": int(r["analysts"]) if clean(r["analysts"]) else None,
            "recommendation": r["recommendation"] if r["recommendation"] not in (None, "none") else None,
            "recommendation_mean": clean(r["recommendation_mean"]),
            "target_mean": clean(r["target_mean"]), "target_high": clean(r["target_high"]),
            "target_low": clean(r["target_low"]),
            "eps": clean(r["eps"]), "shares_out": clean(r["shares_out"]), "employees": clean(r["employees"]),
            "website": r["website"], "city": r["city"], "beta": clean(r["beta"]), "summary": r["summary"],
        })
    picks = rank(candidates, sc["count"])
    funnel.append({"step": f"Best {sc['count']} by Magic Formula rank", "count": len(picks)})
    def dist(key):
        return sorted(round(v[key], 5) for v in liq.values() if key in v)
    trend = [v["above_200dma"] for v in liq.values() if "above_200dma" in v]
    universe_stats = {
        "breadth_above_200dma": round(sum(trend) / len(trend), 4) if trend else None,
        "breadth_count": len(trend),
        "momentum_12_1": dist("momentum_12_1"), "high_52w_ratio": dist("high_52w_ratio"), "vol_1y": dist("vol_1y"),
    }
    now = datetime.now(timezone.utc)
    return candidates, {
        "universe_stats": universe_stats,
        "generated_utc": now.isoformat(timespec="seconds"),
        "generated_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "screened_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "ranked_on": "closing prices",
        "universe_source": uni_source,
        "rules": {"min_fscore": sc["min_fscore"], "count": sc["count"],
                  "exclude_industries": sc["exclude_industries"]},
        "funnel": funnel,
        "skipped": {k: sorted(v) for k, v in skipped.items()},
        "picks": picks,
    }


def main():
    t0 = time.time()
    candidates, res = run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "candidates.json").write_text(json.dumps({"generated_utc": res["generated_utc"], "count": res["rules"]["count"],
                                                         "stocks": candidates}, default=str, allow_nan=False), encoding="utf-8")
    (OUT_DIR / "latest.json").write_text(json.dumps(res, indent=1, default=str, allow_nan=False), encoding="utf-8")
    day = datetime.now(IST).strftime("%Y-%m-%d")
    (OUT_DIR / "history").mkdir(exist_ok=True)
    (OUT_DIR / "history" / f"{day}.json").write_text(json.dumps(res, indent=1, default=str, allow_nan=False), encoding="utf-8")
    for f in res["funnel"]:
        print(f"  {f['count']:4d}  {f['step']}")
    for k, v in res["skipped"].items():
        print(f"  skipped ({k}): {len(v)}")
    print(f"\n{'#':>2} {'Symbol':<12} {'ROC':>7} {'EY':>7} {'F':>3} {'P/E':>6}  Name")
    for p in res["picks"]:
        pe = f"{p['pe']:.1f}" if p["pe"] else "-"
        print(f"{p['magic_rank']:>2} {p['symbol']:<12} {p['roc']:7.1%} {p['earnings_yield']:7.1%} {p['fscore']:>3} {pe:>6}  {p['name']}")
    print(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
