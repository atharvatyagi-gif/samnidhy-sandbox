"""
ALADIN fundamental front: Value / Quality / Fundamental-momentum composites, a distress band, and the F score.

  python scripts/aladin_fund.py                 fetch statements (rotating batch), then score everything cached
  python scripts/aladin_fund.py --no-fetch      score what is already cached
  python scripts/aladin_fund.py --batch 400     how many statements to refresh per run (default 400, NIFTY 500 first)

Inputs   Yahoo Finance annual + quarterly statements per stock (yfinance), cached in data/aladin_cache/statements/<SYM>.json
         and refreshed when older than 7 days; prices from data/terminal/daily; shares/market cap from data/terminal/fund.json.
Output   data/aladin_cache/fund_scores.json  (read by scripts/aladin_model.py, which puts it into aladin.json)

What is and is not measured (the same text is shown in the methodology drawer):
* Yahoo returns only about 4 annual and 5 quarterly periods for Indian stocks, so "earnings stability" (needs 8 quarterly EPS
  growth rates) and quarter-on-quarter revenue acceleration are usually "not measured"; revenue acceleration falls back to
  annual figures and says so. EPS surprise / revisions are not available for NSE names from Yahoo: not measured.
* Banks, NBFCs, insurers and other financial-services names use only book/price, ROE, earnings stability and momentum.
* Distress = the worse of a naive Merton distance-to-default and Altman Z'' (emerging-markets version). There is no free labelled
  dataset of Indian defaults, so no machine-learned default classifier is used. Distress is not applied to financials or to
  companies with no debt.
"""

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
TERM = ROOT / "data" / "terminal"
CACHE = ROOT / "data" / "aladin_cache" / "statements"
OUT = ROOT / "data" / "aladin_cache" / "fund_scores.json"
REFRESH_DAYS = 7
TAX = 0.25

LINES = {
    "inc": ["Total Revenue", "Gross Profit", "EBIT", "Operating Income", "Net Income", "Diluted EPS", "Pretax Income", "Interest Expense"],
    "bal": ["Total Assets", "Total Liabilities Net Minority Interest", "Total Debt", "Stockholders Equity", "Common Stock Equity", "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments", "Working Capital", "Retained Earnings", "Current Assets", "Current Liabilities"],
    "cf": ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"],
}


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def now_utc():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ fetching

def _frame_to_dict(df, names):
    """{line: [[YYYY-MM-DD, value], ...]} newest first, only the lines we use, NaN dropped."""
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for n in names:
        if n in df.index:
            row = df.loc[n]
            pts = [[c.strftime("%Y-%m-%d"), float(v)] for c, v in row.items() if v == v and v is not None]
            if pts:
                out[n] = sorted(pts, key=lambda p: p[0], reverse=True)
    return out


def fetch_statements(sym, tk=None, now=None):
    """yfinance annual + quarterly income / balance / cash flow, reduced to the lines used here. None if Yahoo has nothing."""
    now = now or now_utc()
    try:
        if tk is None:
            import yfinance as yf
            tk = yf.Ticker(sym + ".NS")
        out = {"sym": sym, "fetched": now.isoformat(timespec="seconds"), "ann": {}, "qtr": {}}
        for name, attr_a, attr_q in (("inc", "income_stmt", "quarterly_income_stmt"), ("bal", "balance_sheet", "quarterly_balance_sheet"), ("cf", "cashflow", "quarterly_cashflow")):
            out["ann"][name] = _frame_to_dict(getattr(tk, attr_a), LINES[name])
            out["qtr"][name] = _frame_to_dict(getattr(tk, attr_q), LINES[name])
        if not out["ann"]["inc"] and not out["ann"]["bal"]:
            return None
        return out
    except Exception:
        return None


def load_cached(sym):
    p = CACHE / f"{key(sym)}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def refresh_batch(symbols, n500, batch=400, now=None, fetch=fetch_statements, workers=6):
    """NIFTY 500 first, then everything else; within each group the stalest (or never-fetched) first. Fetches at most `batch`."""
    now = now or now_utc()
    def age(s):
        c = load_cached(s)
        return (now - datetime.fromisoformat(c["fetched"])).total_seconds() / 86400 if c else 1e9
    due = [s for s in symbols if age(s) >= REFRESH_DAYS]
    due.sort(key=lambda s: (s not in n500, -age(s)))
    todo = due[:batch]
    CACHE.mkdir(parents=True, exist_ok=True)
    def one(s):
        for attempt in range(2):
            r = fetch(s, now=now)
            if r:
                (CACHE / f"{key(s)}.json").write_text(json.dumps(r, separators=(",", ":")), encoding="utf-8")
                return s, True
            time.sleep(1.5 * (attempt + 1))
        return s, False
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, todo))
    return {"due": len(due), "tried": len(todo), "ok": sum(1 for _, ok in res if ok)}


# ------------------------------------------------------------------ raw metrics

def _val(d, line, i=0):
    pts = d.get(line) or []
    return pts[i][1] if len(pts) > i else None


def _first(d, lines, i=0):
    for l in lines:
        v = _val(d, l, i)
        if v is not None:
            return v
    return None


def _safe_div(a, b):
    return None if a is None or b is None or b == 0 or not math.isfinite(a) or not math.isfinite(b) else a / b


def reverse_dcf_growth(ev, fcf, r=0.12, g_term=0.05, years=10):
    """The constant growth rate g over `years` that makes the discounted free cash flows (then a terminal value at g_term)
    equal today's enterprise value. Lower = the market expects less = cheaper. None if FCF <= 0 or no solution in [-30%, 60%]."""
    if ev is None or fcf is None or fcf <= 0 or ev <= 0:
        return None
    def pv(g):
        tot, cf = 0.0, fcf
        for t in range(1, years + 1):
            cf *= 1 + g
            tot += cf / (1 + r) ** t
        return tot + cf * (1 + g_term) / (r - g_term) / (1 + r) ** years
    lo, hi = -0.30, 0.60
    if (pv(lo) - ev) * (pv(hi) - ev) > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if (pv(lo) - ev) * (pv(mid) - ev) <= 0:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 5)


def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def merton_dd(E, D, sigma_E, mu, T=1.0):
    """Bharath-Shumway naive distance to default. Returns (DD, PD)."""
    if not (E and E > 0 and D and D > 0 and sigma_E and sigma_E > 0):
        return None, None
    sigma_D = 0.05 + 0.25 * sigma_E
    V = E + D
    sigma_V = (E / V) * sigma_E + (D / V) * sigma_D
    dd = (math.log(V / D) + (mu - 0.5 * sigma_V ** 2) * T) / (sigma_V * math.sqrt(T))
    return round(dd, 3), round(norm_cdf(-dd), 6)


def altman_z2(wc, re, ebit, be, ta, tl):
    """Altman Z'' for emerging markets: 3.25 + 6.56 WC/TA + 3.26 RE/TA + 6.72 EBIT/TA + 1.05 BE/TL."""
    if None in (wc, re, ebit, be, ta, tl) or not ta or not tl:
        return None
    return round(3.25 + 6.56 * wc / ta + 3.26 * re / ta + 6.72 * ebit / ta + 1.05 * be / tl, 3)


def distress_band(dd, z2):
    """Worse of the two. Merton: DD < 1.5 High, < 3 Moderate. Altman: < 4.15 High, < 5.85 Moderate (grey zone)."""
    rank = {"Low": 0, "Moderate": 1, "High": 2}
    bands = []
    if dd is not None:
        bands.append("High" if dd < 1.5 else "Moderate" if dd < 3 else "Low")
    if z2 is not None:
        bands.append("High" if z2 < 4.15 else "Moderate" if z2 < 5.85 else "Low")
    return max(bands, key=lambda b: rank[b]) if bands else None


def factors(stmt, px, financial=False):
    """Raw metrics for one stock. px = {"mcap": Rs, "ret1y": float, "vol1y": daily std, "last": price}. Missing inputs -> None (never guessed)."""
    a, q = stmt["ann"], stmt["qtr"]
    inc, bal, cf = a["inc"], a["bal"], a["cf"]
    mcap = px.get("mcap")
    ebit = _first(inc, ["EBIT", "Operating Income"])
    ta, tl = _val(bal, "Total Assets"), _val(bal, "Total Liabilities Net Minority Interest")
    debt = _val(bal, "Total Debt")
    eq = _first(bal, ["Stockholders Equity", "Common Stock Equity"])
    cash = _first(bal, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"])
    ni, rev = _val(inc, "Net Income"), _val(inc, "Total Revenue")
    fcf = _val(cf, "Free Cash Flow")
    cfo = _val(cf, "Operating Cash Flow")
    ev = None if mcap is None else mcap + (debt or 0) - (cash or 0)
    r = {"fy": (inc.get("Total Revenue") or [[None]])[0][0]}
    # value
    r["ebit_ev"] = None if financial else _safe_div(ebit, ev)
    r["fcf_mcap"] = None if financial else _safe_div(fcf, mcap)
    r["book_price"] = _safe_div(eq, mcap)
    r["ta_ev_inv"] = None if financial else _safe_div(ev, ta)             # EV / total assets, inverted by the caller (lower EV/TA = cheaper)
    r["rdcf_g"] = None if financial else reverse_dcf_growth(ev, fcf)
    # quality
    inv_cap = None if debt is None or eq is None else debt + eq - (cash or 0)
    r["roic"] = None if financial or ebit is None else _safe_div(ebit * (1 - TAX), inv_cap)
    r["gp_assets"] = None if financial else _safe_div(_val(inc, "Gross Profit"), ta)
    ta2 = _val(bal, "Total Assets", 1)
    avg_ta = None if ta is None else (ta + ta2) / 2 if ta2 else ta
    r["accrual"] = None if financial or ni is None or cfo is None else _safe_div(ni - cfo, avg_ta)   # lower is better
    r["roe"] = _safe_div(ni, eq)
    eps_q = [p[1] for p in (q["inc"].get("Diluted EPS") or [])]
    growth = [(eps_q[i] - eps_q[i + 1]) / abs(eps_q[i + 1]) for i in range(len(eps_q) - 1) if eps_q[i + 1]]
    r["eps_stab"] = (1 / float(np.std(growth))) if len(growth) >= 6 and np.std(growth) > 0 else None   # needs 8 quarters: usually not measured
    # fundamental momentum
    revq = [p[1] for p in (q["inc"].get("Total Revenue") or [])]
    if len(revq) >= 6:
        yoy0, yoy1 = revq[0] / revq[4] - 1 if revq[4] else None, revq[1] / revq[5] - 1 if revq[5] else None
        r["rev_acc"], r["rev_acc_basis"] = (None if yoy0 is None or yoy1 is None else yoy0 - yoy1), "qtr"
    else:
        ra = [p[1] for p in (inc.get("Total Revenue") or [])]
        if len(ra) >= 3 and ra[1] and ra[2]:
            r["rev_acc"], r["rev_acc_basis"] = (ra[0] / ra[1] - 1) - (ra[1] / ra[2] - 1), "ann"
        else:
            r["rev_acc"], r["rev_acc_basis"] = None, None
    om0, om1 = _safe_div(_first(inc, ["Operating Income", "EBIT"]), rev), _safe_div(_first(inc, ["Operating Income", "EBIT"], 1), _val(inc, "Total Revenue", 1))
    r["opm_chg"] = None if financial or om0 is None or om1 is None else om0 - om1
    # distress inputs
    dd = pd_ = z2 = None
    if not financial and debt and debt > 0 and mcap:
        sigE = px.get("vol1y")
        dd, pd_ = merton_dd(mcap, debt, None if sigE is None else sigE * math.sqrt(252), px.get("ret1y") or 0.0)
        z2 = altman_z2(_val(bal, "Working Capital"), _val(bal, "Retained Earnings"), ebit, eq, ta, tl)
    r["dd"], r["pd"], r["z2"] = dd, pd_, z2
    r["band"] = distress_band(dd, z2)
    return r


# ------------------------------------------------------------------ cross-section

def winsorise_z(df, cols, p=(0.025, 0.975)):
    out = df.copy()
    for c in cols:
        s = df[c].astype(float)
        if s.notna().sum() < 5:
            out[c] = np.nan
            continue
        lo, hi = s.quantile(p[0]), s.quantile(p[1])
        s = s.clip(lo, hi)
        sd = s.std()
        out[c] = (s - s.mean()) / sd if sd and sd > 0 else 0.0
    return out


def orthogonalise(df, y_col, controls):
    """OLS residual of `y_col` on `controls` (rows with all values present), re-z-scored. Returns (residual Series aligned to df.index, R^2)."""
    d = df[[y_col] + controls].dropna()
    if len(d) < len(controls) + 10:
        return pd.Series(np.nan, index=df.index), None
    X = np.column_stack([np.ones(len(d))] + [d[c].values for c in controls])
    y = d[y_col].values
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (res ** 2).sum() / ss_tot if ss_tot > 0 else None
    sd = res.std(ddof=1)
    out = pd.Series(np.nan, index=df.index)
    out.loc[d.index] = (res - res.mean()) / sd if sd > 0 else 0.0
    return out, None if r2 is None else round(float(r2), 3)


def composites(raw, industries, mcaps, financial):
    """raw: DataFrame (index = symbol) of factors(); returns DataFrame of Value, Quality, FMom (orthogonalised z) plus the R^2 values."""
    df = raw.copy()
    df["_ep"] = -df["ta_ev_inv"]                   # lower EV/TA = cheaper -> higher value
    df["_rd"] = -df["rdcf_g"]                      # lower implied growth = cheaper
    df["_acc"] = -df["accrual"]                    # lower accruals = better
    cols = ["ebit_ev", "fcf_mcap", "book_price", "_ep", "_rd", "roic", "gp_assets", "_acc", "roe", "eps_stab", "rev_acc", "opm_chg"]
    z = winsorise_z(df, cols)
    fin = pd.Series([bool(financial.get(s)) for s in df.index], index=df.index)
    def avg(cols_nonfin, cols_fin):
        """Average of the available z-scores: at least 2 for ordinary companies, at least 1 for financials (who have only 1-2 usable metrics)."""
        a = z[cols_nonfin].where(~fin, np.nan).mean(axis=1, skipna=True).where(z[cols_nonfin].where(~fin, np.nan).notna().sum(axis=1) >= 2)
        b = z[cols_fin].mean(axis=1, skipna=True).where(z[cols_fin].notna().sum(axis=1) >= 1)
        return a.where(~fin, b)
    value = avg(["ebit_ev", "fcf_mcap", "book_price", "_ep", "_rd"], ["book_price"])
    quality = avg(["roic", "gp_assets", "_acc", "roe", "eps_stab"], ["roe", "eps_stab"])
    fmom = avg(["rev_acc", "opm_chg"], ["rev_acc"])
    for name, s in (("value", value), ("quality", quality), ("fmom", fmom)):
        z[name] = s
    z["lm"] = np.log(pd.Series(mcaps).reindex(df.index).astype(float))
    dummies = pd.get_dummies(pd.Series(industries).reindex(df.index).fillna("none"), drop_first=True, dtype=float)
    ctl = pd.concat([z[["lm"]], dummies], axis=1)
    ctl = ctl.loc[:, ctl.std() > 0]
    work = pd.concat([z[["value", "quality", "fmom"]], ctl], axis=1)
    cl = list(ctl.columns)
    q_o, r2q = orthogonalise(work, "quality", cl)
    work["quality_o"] = q_o
    v_o, r2v = orthogonalise(work, "value", cl + ["quality_o"])
    work["value_o"] = v_o
    m_o, r2m = orthogonalise(work, "fmom", cl + ["quality_o", "value_o"])
    out = pd.DataFrame({"value": v_o, "quality": q_o, "fmom": m_o})
    return out, {"value": r2v, "quality": r2q, "fmom": r2m}


PENALTY = {"High": 1.0, "Moderate": 0.4}


def f_score(value, quality, fmom, nlp, band):
    """z = 0.35 Value + 0.35 Quality + 0.20 FMom + 0.10 NLP - penalty, weights renormalised over the parts present; F = 100 tanh(z/1.5).
    Returns (F | None, coverage share of the four parts present)."""
    parts = {"value": (0.35, value), "quality": (0.35, quality), "fmom": (0.20, fmom), "nlp": (0.10, nlp)}
    have = {k: (w, v) for k, (w, v) in parts.items() if v is not None and v == v}
    cov = len(have) / 4
    if not have:
        return None, 0.0
    wsum = sum(w for w, _ in have.values())
    z = sum(w / wsum * v for w, v in have.values()) - PENALTY.get(band, 0.0)
    return round(100 * math.tanh(z / 1.5), 1), cov


# ------------------------------------------------------------------ driver

def price_stats(sym):
    p = TERM / "daily" / f"{key(sym)}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))["d"]
    except (OSError, ValueError, KeyError):
        return None
    c = np.array([r[4] for r in d[-253:]], dtype=float)
    if len(c) < 120 or (c <= 0).any():
        return None
    lr = np.diff(np.log(c))
    return {"last": float(c[-1]), "vol1y": float(lr.std()), "ret1y": float(c[-1] / c[0] - 1), "date": d[-1][0]}


def score_all(now=None):
    uni = json.loads((TERM / "universe.json").read_text(encoding="utf-8"))["stocks"]
    fund = json.loads((TERM / "fund.json").read_text(encoding="utf-8")).get("stocks", {}) if (TERM / "fund.json").exists() else {}
    scr = {}
    try:
        scr = {p["symbol"]: p for p in json.loads((ROOT / "data" / "screener" / "latest.json").read_text(encoding="utf-8")).get("picks", [])}
    except (OSError, ValueError):
        pass
    raws, ind, mc, fin, meta = {}, {}, {}, {}, {}
    for s in uni:
        sym = s["s"]
        if s.get("series") != "EQ" or s.get("etf") or s.get("board") != "Main":
            continue
        st = load_cached(sym)
        px = price_stats(sym)
        f = fund.get(sym, {})
        if not st or not px:
            continue
        sh = f.get("sh")
        mcap = sh * px["last"] if sh else f.get("mcap")
        if not mcap:
            continue
        is_fin = (s.get("ind") == "Financial Services") or (f.get("sector") == "Financial Services")
        r = factors(st, {**px, "mcap": mcap}, is_fin)
        raws[sym], ind[sym], mc[sym], fin[sym] = r, s.get("ind"), mcap, is_fin
        meta[sym] = {"fetched": st["fetched"][:10], "fy": r.get("fy")}
    if not raws:
        return {"generated_utc": (now or now_utc()).isoformat(timespec="seconds"), "stocks": {}, "r2": {}, "n": 0}
    raw = pd.DataFrame(raws).T
    for c in raw.columns:
        if c not in ("fy", "rev_acc_basis", "band"):
            raw[c] = pd.to_numeric(raw[c], errors="coerce")
    comp, r2 = composites(raw, ind, mc, fin)
    out = {}
    for sym in raw.index:
        r = raws[sym]
        v, qy, m = (None if pd.isna(comp.at[sym, k]) else round(float(comp.at[sym, k]), 3) for k in ("value", "quality", "fmom"))
        out[sym] = {"v": v, "q": qy, "m": m, "dist": {"band": r["band"], "dd": r["dd"], "pd": r["pd"], "z2": r["z2"]} if r["band"] else None,
                    "fin": fin[sym], "fscore": (scr.get(sym) or {}).get("fscore"), "meta": meta[sym], "acc_basis": r.get("rev_acc_basis"),
                    "raw": {k: (None if (isinstance(r[k], float) and not math.isfinite(r[k])) else (None if r[k] is None else round(r[k], 4) if isinstance(r[k], float) else r[k]))
                            for k in ("ebit_ev", "fcf_mcap", "book_price", "rdcf_g", "roic", "gp_assets", "accrual", "roe", "rev_acc", "opm_chg")}}
    return {"generated_utc": (now or now_utc()).isoformat(timespec="seconds"), "n": len(out), "r2": r2, "stocks": out}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--batch", type=int, default=400)
    a = ap.parse_args(argv)
    uni = json.loads((TERM / "universe.json").read_text(encoding="utf-8"))["stocks"]
    syms = [s["s"] for s in uni if s.get("series") == "EQ" and not s.get("etf") and s.get("board") == "Main"]
    if not a.no_fetch:
        n500 = {s["s"] for s in uni if s.get("n500")}
        print("statements:", refresh_batch(syms, n500, a.batch))
    res = score_all()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    print(f"fundamental front: {res['n']} stocks scored; R^2 of orthogonalisation {res.get('r2')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
