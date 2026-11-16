"""B-Lab Technical division, step 3 (docs/blab/PLAN.md): what trading produces. The regime bot names today's market state, the
strategy lab tests a fixed library of strategies in every past state, the analog finder finds the past days most like today.

Data: daily prices in data/terminal (the daily job's cache): the NSE index files (idx/out/d, from Oct 2021) and each stock's
file (daily/, from Oct 2021), joined with the older history the daily job keeps on the "history" branch (archive/: stocks
from 1996, NIFTY 50 from 2007, Bank Nifty), at their overlapping days (they agree to the paisa there). Companies listed
today only (survivorship), so the strategy results flatter every long-only rule a little.

RULES (declared 2026-11-16, before any result was looked at):
  State (T3)   trend: NIFTY 50 close above / below its 200-session average -> up / down.
               volatility: 20-session realised volatility against its own previous 750 sessions (about 3 years):
               at or above the 70th percentile high, at or below the 30th low, else normal.  6 states = trend x volatility.
               breadth (share of the 500 stocks above their own 200-session average) is shown, not part of the state.
  Strategies (T4), on the 500 most-traded stocks (model E's list) with 260 sessions of prices and a price of Rs 10 or
               more on the day; each picks the best 10% by its signal on day t, buys at the close of t+1, sells at the
               close of t+22 (21 sessions), equal weight; every 5th session is a start day:
                 momentum        return from t-252 to t-21, highest
                 reversal        5-session return, lowest
                 52-week high    close / highest close of 252 sessions, highest
                 low volatility  standard deviation of 60 daily returns, lowest
                 quality trend   126-session return / its volatility, highest
                 trend           above its 50- and 200-session averages, then 63-session return, highest
               Low volatility and quality trend skip a stock whose daily moves average under 0.1% (a stuck or suspended price).
               Result: the picks' average return minus the average of all eligible stocks over the same days, after a
               0.4% round-trip cost, grouped by the state on day t. 95% range from start-day values, widened by
               sqrt(21/5) for overlapping windows. "Measurable" = the range is clear of zero with at least 30 start days.
               Findings: only for a strategy measurably positive in TODAY's state: its 10 strongest current picks.
  Analogs (T5) features on day t: NIFTY 50 return over 5, 21, 63 and 126 sessions, 20-session volatility, distance from
               the 200-session average, and breadth (when 100+ stocks have prices). Standardised over all days; the 10
               nearest days that are at least 63 sessions old and 21 sessions apart. Reported: what NIFTY 50 and Bank Nifty
               did over the next 21 and 63 sessions, against all days. A lean only when 8+ of the 10 went the same way
               over 21 sessions; scored on NIFTY 50 itself.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import warnings
from pathlib import Path

from .core import DATA

for _msg in ("All-NaN slice", "Mean of empty slice", "Degrees of freedom", "invalid value", "divide by zero"):   # windows before a stock listed: expected, handled as NaN
    warnings.filterwarnings("ignore", message=f".*{_msg}.*", category=RuntimeWarning)
TERM = DATA / "terminal"
STORE = DATA / "blab" / "store"
LAB_REFRESH_DAYS = 7
STRATS = ["momentum", "reversal", "52-week high", "low volatility", "quality trend", "trend"]
COST = 0.004
HOLD, STEP = 21, 5


def _rows(p):
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return d.get("d", d) if isinstance(d, dict) else d


def key(sym):
    return "".join(c if c.isalnum() else "_" + format(ord(c), "x") for c in sym)


def joined(archive_name, current_rows):
    """Archive (older) + current rows -> {date: close}, rescaled at the overlap if the two bases differ."""
    old = {r[0]: r[4] for r in _rows(TERM / "archive" / archive_name) if r[4]}
    new = {r[0]: r[4] for r in current_rows if r[4]}
    common = sorted(set(old) & set(new))
    k = new[common[-1]] / old[common[-1]] if common and old[common[-1]] else 1.0
    out = {d: v * k for d, v in old.items() if not new or d < min(new)}
    out.update(new)
    return out


def market_series():
    n50 = joined("_5eNSEI.json", _rows(TERM / "idx" / "out" / "d" / "Nifty_2050.json"))
    bank = joined("_5eNSEBANK.json", _rows(TERM / "idx" / "out" / "d" / "Nifty_20Bank.json"))
    return n50, bank


def stock_series(sym):
    return joined(f"{key(sym)}.json", _rows(TERM / "daily" / f"{key(sym)}.json"))


# ------------------------------------------------------------------ the maths (numpy)

def build(n50, stocks):
    import numpy as np
    dates = sorted(n50)
    idx = {d: i for i, d in enumerate(dates)}
    m = np.array([n50[d] for d in dates], float)
    syms = sorted(stocks)
    P = np.full((len(dates), len(syms)), np.nan)
    for j, s in enumerate(syms):
        for d, v in stocks[s].items():
            i = idx.get(d)
            if i is not None and v and v > 0:
                P[i, j] = v
    for j in range(P.shape[1]):                                    # carry the last close over a missing day (holiday mismatch), never backwards
        col = P[:, j]; last = np.nan
        for i in range(len(col)):
            if np.isnan(col[i]):
                col[i] = last
            else:
                last = col[i]
    return dates, m, syms, P


def rolling_mean(x, n):
    import numpy as np
    c = np.cumsum(np.insert(np.nan_to_num(x), 0, 0.0))
    out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def states(m):
    """Trend and volatility state per day (no look-ahead: each uses only data up to that day)."""
    import numpy as np
    ma200 = rolling_mean(m, 200)
    r = np.diff(np.log(m), prepend=np.nan)
    vol = np.full(len(m), np.nan)
    for i in range(20, len(m)):
        vol[i] = np.nanstd(r[i - 19:i + 1]) * math.sqrt(252)
    trend = np.where(np.isnan(ma200), None, np.where(m > ma200, "up", "down"))
    vstate = np.full(len(m), None, dtype=object)
    for i in range(len(m)):
        past = vol[max(0, i - 750):i]
        past = past[~np.isnan(past)]
        if len(past) >= 250 and not np.isnan(vol[i]):
            p = (past < vol[i]).mean()
            vstate[i] = "high" if p >= 0.70 else "low" if p <= 0.30 else "normal"
    st = [f"{t} trend, {v} volatility" if t and v else None for t, v in zip(trend, vstate)]
    return st, vol, ma200


def breadth(P):
    import numpy as np
    out = np.full(P.shape[0], np.nan)
    ma = np.full(P.shape, np.nan)
    for j in range(P.shape[1]):
        ma[:, j] = rolling_mean(P[:, j], 200)
        ma[np.isnan(P[:, j]) | (np.cumsum(~np.isnan(P[:, j])) < 200), j] = np.nan
    ok = ~np.isnan(ma)
    n = ok.sum(1)
    above = ((P > ma) & ok).sum(1)
    out[n >= 100] = above[n >= 100] / n[n >= 100]
    return out


def signals(P, t):
    """Each strategy's score for every stock on day t (higher = picked); NaN = not eligible."""
    import numpy as np
    p = P[t]
    elig = (~np.isnan(P[max(0, t - 259)])) & (~np.isnan(p)) & (p >= 10) & (t >= 259)
    def ret(a, b):
        with np.errstate(divide="ignore", invalid="ignore"):
            return P[t - b] / P[t - a] - 1
    r = np.diff(np.log(P[max(0, t - 126):t + 1]), axis=0)
    with np.errstate(invalid="ignore"):
        vol60 = np.nanstd(r[-60:], axis=0)
        vol126 = np.nanstd(r, axis=0)
        hi252 = np.nanmax(P[t - 251:t + 1], axis=0)
        ma50, ma200 = np.nanmean(P[t - 49:t + 1], axis=0), np.nanmean(P[t - 199:t + 1], axis=0)
        moving60, moving126 = vol60 > 0.001, vol126 > 0.001        # a stuck price (e.g. suspended) has ~0 volatility: never "lowest" or divided by
        s = {"momentum": ret(252, 21), "reversal": -ret(5, 0), "52-week high": p / hi252, "low volatility": np.where(moving60, -vol60, np.nan),
             "quality trend": np.where(moving126, ret(126, 0) / (vol126 * math.sqrt(126)), np.nan),
             "trend": np.where((p > ma50) & (p > ma200), ret(63, 0), np.nan)}
    out = {k: np.where(elig & np.isfinite(v), v, np.nan) for k, v in s.items()}
    out["_eligible"] = elig
    return out


def lab(dates, P, st, today_state):
    """Strategy x state record. -> {state: {strategy: {...}}}, plus the start-day count."""
    import numpy as np
    vals = {}
    for t in range(259, len(dates) - HOLD - 1, STEP):
        if not st[t]:
            continue
        a, b = P[t + 1], P[t + 1 + HOLD]
        with np.errstate(divide="ignore", invalid="ignore"):
            fwd = b / a - 1
        sig = signals(P, t)
        base_ok = sig.pop("_eligible") & np.isfinite(fwd)          # the average eligible stock over the same days
        if base_ok.sum() < 50:
            continue
        base = float(np.mean(fwd[base_ok]))
        for k, v in sig.items():
            ok = np.isfinite(v) & np.isfinite(fwd)
            if ok.sum() < 50:
                continue
            cut = np.quantile(v[ok], 0.9)
            pick = ok & (v >= cut)
            if pick.sum() < 5:
                continue
            vals.setdefault(st[t], {}).setdefault(k, []).append(float(np.mean(fwd[pick]) - base - COST))
    out = {}
    for s, by in vals.items():
        out[s] = {}
        for k, xs in by.items():
            n = len(xs); mu = sum(xs) / n
            sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else 0
            half = 1.96 * sd / math.sqrt(n) * math.sqrt(HOLD / STEP) if n > 1 else None
            lo, hi = (None, None) if half is None else (mu - half, mu + half)
            verdict = "too few start days" if n < 30 else "measurably better than the average stock" if lo > 0 else "measurably worse than the average stock" if hi < 0 else "no measurable difference"
            out[s][k] = {"n": n, "mean_pct": round(mu * 100, 2), "ci95_pct": None if lo is None else [round(lo * 100, 2), round(hi * 100, 2)], "verdict": verdict}
    return out


def analogs(dates, m, bank, br, vol, ma200, k=10, gap=21, min_age=63):
    import numpy as np
    def ret(n):
        out = np.full(len(m), np.nan); out[n:] = m[n:] / m[:-n] - 1; return out
    F = np.column_stack([ret(5), ret(21), ret(63), ret(126), vol, m / ma200 - 1, br])
    t = len(m) - 1
    use = [c for c in range(F.shape[1]) if np.isfinite(F[t, c])]
    X = F[:, use]
    mu, sd = np.nanmean(X, 0), np.nanstd(X, 0)
    Z = (X - mu) / sd
    ok = np.all(np.isfinite(Z), 1)
    d = np.full(len(m), np.inf)
    d[ok] = np.sqrt(((Z[ok] - Z[t]) ** 2).sum(1))
    d[t - min_age + 1:] = np.inf
    chosen = []
    for i in np.argsort(d):
        if not np.isfinite(d[i]):
            break
        if all(abs(i - j) >= gap for j in chosen):
            chosen.append(int(i))
        if len(chosen) == k:
            break
    bk = np.array([bank.get(x, np.nan) for x in dates], float)
    def fwd(series, i, h):
        return series[i + h] / series[i] - 1 if i + h < len(series) and series[i] > 0 and np.isfinite(series[i + h]) else np.nan
    names = ["5-session return", "21-session return", "63-session return", "126-session return", "20-session volatility", "distance from 200-session average", "breadth"]
    res = {"features": [names[c] for c in use],
           "days": [{"date": dates[i], "distance": round(float(d[i]), 2), "n50_21": round(fwd(m, i, 21) * 100, 2), "n50_63": round(fwd(m, i, 63) * 100, 2),
                     "bank_21": None if np.isnan(fwd(bk, i, 21)) else round(fwd(bk, i, 21) * 100, 2)} for i in chosen]}
    allf = lambda h: np.array([fwd(m, i, h) for i in range(len(m) - h)])  # noqa: E731
    for h in (21, 63):
        xs = np.array([x["n50_%d" % h] for x in res["days"] if x["n50_%d" % h] is not None]) / 100
        base = allf(h); base = base[np.isfinite(base)]
        res[f"h{h}"] = {"analog_median_pct": round(float(np.median(xs)) * 100, 2), "analog_up": int((xs > 0).sum()), "analogs": int(len(xs)),
                        "all_days_median_pct": round(float(np.median(base)) * 100, 2), "all_days_up_pct": round(float((base > 0).mean()) * 100, 1)}
    up = res["h21"]["analog_up"]
    res["lean"] = 1 if up >= 8 else -1 if up <= 2 else 0
    return res


# ------------------------------------------------------------------ bots

def _universe():
    e = json.loads((DATA / "aladin_e" / "latest.json").read_text(encoding="utf-8"))
    return sorted(e.get("stocks", {}))


_LOCK = threading.Lock()


def _market(ctx):
    """The prices, built once per run and shared by the three analysts (they run at the same time)."""
    with _LOCK:
        return _market_locked(ctx)


def _market_locked(ctx):
    if "T_market" not in ctx.shared:
        n50, bank = market_series()
        if len(n50) < 1000:
            raise RuntimeError(f"NIFTY 50 history too short on this runner ({len(n50)} days): the price cache or the history branch is missing")
        stocks = {s: stock_series(s) for s in _universe()}
        stocks = {s: v for s, v in stocks.items() if len(v) >= 260}
        dates, m, syms, P = build(n50, stocks)
        st, vol, ma200 = states(m)
        ctx.shared["T_market"] = {"dates": dates, "m": m, "syms": syms, "P": P, "st": st, "vol": vol, "ma200": ma200, "br": breadth(P), "bank": bank}
    return ctx.shared["T_market"]


def t3_regime(ctx):
    M = _market(ctx)
    t = len(M["dates"]) - 1
    from collections import Counter
    c = Counter(s for s in M["st"] if s)
    br = M["br"][t]
    today = M["st"][t]
    breadth_txt = "not measured" if br != br else f"{br * 100:.0f}% of {len(M['syms'])} stocks above their 200-day average"
    return {"items": len(M["dates"]), "as_of": M["dates"][t],
            "detail": f"Today ({M['dates'][t]}): {today or 'not measured'}. NIFTY 50 {M['m'][t]:,.0f} vs its 200-day average {M['ma200'][t]:,.0f}; 20-day volatility "
                      f"{M['vol'][t] * 100:.1f}% a year; breadth {breadth_txt}. "
                      f"Days in each state since {M['dates'][0][:4]}: " + ", ".join(f"{k} {v}" for k, v in c.most_common()),
            "state": today}


def t4_lab(ctx):
    import numpy as np
    M = _market(ctx)
    t = len(M["dates"]) - 1
    today = M["st"][t]
    cache = STORE / "strategy_lab.json"
    from datetime import date
    try:
        old = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    fresh = old.get("to") and (ctx.now.date() - date.fromisoformat(old["created"][:10])).days < LAB_REFRESH_DAYS
    if fresh:
        rec = old["record"]
    else:
        rec = lab(M["dates"], M["P"], M["st"], today)
        STORE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"created": ctx.now.isoformat(), "from": M["dates"][259], "to": M["dates"][-HOLD - 2], "record": rec, "rules": "scripts/blab/technical.py"},
                                    separators=(",", ":")), encoding="utf-8")
    here = rec.get(today or "", {})
    good = [k for k, v in here.items() if v["verdict"].startswith("measurably better")]
    findings = []
    if good:
        sig = signals(M["P"], t); sig.pop("_eligible")
        for k in good:
            v = sig[k]; ok = np.isfinite(v)
            for j in np.argsort(-np.where(ok, v, -np.inf))[:10]:
                if ok[j]:
                    findings.append({"sym": M["syms"][j], "kind": f"strategy: {k}", "direction": 1,
                                     "text": f"Among the strongest current picks of '{k}', which beat the average stock by {here[k]['mean_pct']:+.2f}% per 21 sessions after costs in past '{today}' markets (range {here[k]['ci95_pct'][0]:+.2f} to {here[k]['ci95_pct'][1]:+.2f}%, {here[k]['n']} start days).",
                                     "evidence": [{"src": "B-Lab strategy lab (NSE prices)", "url": "", "quote": f"{k} in {today}"}]})
    lines = [f"{k}: {v['mean_pct']:+.2f}% ({v['verdict']})" for k, v in sorted(here.items(), key=lambda kv: -kv[1]["mean_pct"])]
    stored = json.loads(cache.read_text(encoding="utf-8"))
    return {"items": sum(v["n"] for s in rec.values() for v in s.values()), "as_of": stored["created"], "findings": findings,
            "detail": f"6 strategies tested in every market state on {len(M['syms'])} stocks, {stored['from']} to {stored['to']} (re-tested weekly; companies listed today only). "
                      f"In today's state ({today}): " + ("; ".join(lines) if lines else "not measured") + ". "
                      + (f"{len(findings)} current picks filed from {', '.join(good)}." if good else "No strategy is measurably better in this state, so no picks are filed."),
            "record": rec, "today_state": today}


def t5_analogs(ctx):
    M = _market(ctx)
    a = analogs(M["dates"], M["m"], M["bank"], M["br"], M["vol"], M["ma200"])
    h21, h63 = a["h21"], a["h63"]
    day = M["dates"][-1]
    f = []
    if a["lean"]:
        f.append({"scope": "NIFTY 50", "kind": "analog days", "direction": a["lean"], "event": f"analogs {day}",
                  "text": f"{h21['analog_up']} of the {h21['analogs']} past days most like {day} saw NIFTY 50 higher 21 sessions later (median {h21['analog_median_pct']:+.2f}%; all days: {h21['all_days_up_pct']:.0f}% higher, median {h21['all_days_median_pct']:+.2f}%).",
                  "evidence": [{"src": "B-Lab analog finder (NSE index history)", "url": "", "quote": ", ".join(x["date"] for x in a["days"])}]})
    return {"items": len(a["days"]), "as_of": day, "findings": f, "analogs": a,
            "detail": f"The 10 past days most like {day} ({', '.join(x['date'] for x in a['days'][:5])}, ...): NIFTY 50 21 sessions later median {h21['analog_median_pct']:+.2f}% "
                      f"({h21['analog_up']} of {h21['analogs']} higher) vs all days {h21['all_days_median_pct']:+.2f}% ({h21['all_days_up_pct']:.0f}% higher); 63 sessions later "
                      f"{h63['analog_median_pct']:+.2f}% vs {h63['all_days_median_pct']:+.2f}%. "
                      + ("A lean is filed (8+ of 10 went the same way)." if a["lean"] else "No lean: fewer than 8 of 10 went the same way.")}


def t2_flows(ctx):
    """FII/DII cash flows (the daily job's file) and NSE's bulk, block and short deals for the latest session, kept 400 days."""
    from datetime import timedelta
    from .core import ROOT
    f, _ = ctx.read("data/institutional/fii_dii.json")
    days = f.get("days", [])
    last = days[-1] if days else {}
    path = STORE / "deals.json"
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {"rows": []}
    err = []
    try:
        if getattr(ctx, "nse", None) is None:
            sys.path.insert(0, str(ROOT / "scripts"))
            import aladin_ticker_daemon as d
            ctx.nse = d.NseSession()
        j = ctx.nse.get_json("/api/snapshot-capital-market-largedeal", None, referer="https://www.nseindia.com/market-data/large-deals", max_tries=2)
        have = {tuple(r[:6]) for r in st["rows"]}
        from .fundamental import nse_day
        for kind, k in (("bulk", "BULK_DEALS_DATA"), ("block", "BLOCK_DEALS_DATA"), ("short", "SHORT_DEALS_DATA")):
            for r in j.get(k) or []:
                row = [kind, nse_day(r.get("date")), r.get("symbol"), r.get("buySell"), (r.get("clientName") or "")[:80], _num(r.get("qty")), _num(r.get("watp"))]
                if tuple(row[:6]) not in have and row[1]:
                    st["rows"].append(row); have.add(tuple(row[:6]))
    except Exception as e:  # noqa: BLE001  the flows from the repository still report
        err.append(f"large deals: {e}")
    cut = (ctx.now.date() - timedelta(days=400)).isoformat()
    st["rows"] = [r for r in st["rows"] if r[1] >= cut]
    STORE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    newest = max((r[1] for r in st["rows"]), default=None)
    lastday = [r for r in st["rows"] if r[1] == newest]
    val = sum((r[5] or 0) * (r[6] or 0) for r in lastday if r[0] != "short") / 1e7
    as_of = max(filter(None, [last.get("date"), newest]), default=None)
    return {"items": len(days) + len(st["rows"]), "as_of": as_of, "errors": err,
            "detail": f"FII/DII cash-market flows for {len(days)} sessions to {last.get('date')} (FII net Rs {last.get('fii', {}).get('net_cr', 0):,.0f} Cr, DII net Rs {last.get('dii', {}).get('net_cr', 0):,.0f} Cr). "
                      f"Large deals kept: {len(st['rows'])}; latest session {newest}: {sum(r[0] == 'bulk' for r in lastday)} bulk, {sum(r[0] == 'block' for r in lastday)} block "
                      f"(about Rs {val:,.0f} Cr), {sum(r[0] == 'short' for r in lastday)} short. F&O open interest: not measured yet."}


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None
