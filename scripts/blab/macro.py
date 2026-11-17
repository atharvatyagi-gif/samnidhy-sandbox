"""B-Lab Macro division, step 4 (docs/blab/PLAN.md): official statistics and market-priced macro, Indian and US, used ONLY for
what they meant for Indian markets (owner, 2026-11-16: findings about Indian stocks only; US and Indian inputs allowed).

Sources (free; checked 2026-11-16/17):
  RBI home page (rbi.org.in)            today's repo, SDF, MSF, bank rate, CRR, SLR, INR reference rate; saved each run
  FRED (free key: the GitHub secret FRED_API_KEY in the environment; the bots never open the local key file)
    India: INDIRLTLT01STM 10-year yield (monthly), IRSTCI01INM156N call-money rate (monthly)
    US:    FEDFUNDS, CPIAUCSL, UMCSENT (monthly)
    Market-priced: DEXINUS rupee per dollar, DCOILBRENTEU Brent, DTWEXBGS broad dollar, VIXCLS US VIX, DGS10 US 10-year (daily)
  MOSPI API (api.mospi.gov.in)          India CPI. It stops at December 2025 (CPI moved to a 2024 base in January 2026 and the
                                        API has no rows for it yet), so CPI is shown as late, with that reason; never filled in.
  NSE index files (published site)      India VIX, Nifty 10-year benchmark G-Sec index.
  NIFTY 50 / Bank Nifty history          the daily job's "history" branch + NSE index files (as the Technical division).
Not usable (stale on FRED): India CPI (to 2025-03), industrial production (to 2023), leading indicator (to 2024).

THE FACTOR RULES (declared 2026-11-17 before any result was looked at). Each value counts from the day it was PUBLISHED:
monthly FRED values 45 days after their month starts, daily values 2 days after their date (no look-ahead).
  india rates  India 10-year yield change over 3 months: up 0.25 points or more "rising", down 0.25 or more "falling", else "flat"
  rupee        rupee per dollar change over 63 sessions: +2% or more "weakening", -2% or more "strengthening", else "stable"
  oil          Brent change over 63 sessions: +15% or more "up sharply", -15% or more "down sharply", else "flat"
  fed          fed funds change over 6 months: +0.5 points or more "hiking", -0.5 or more "cutting", else "on hold"
  us fear      US VIX 20-day average: 25 or more "stressed", 15 or less "calm", else "normal"
  dollar       broad dollar change over 63 sessions: +3% or more "strong", -3% or more "weak", else "steady"
Outcome, every 5th session since 2007: NIFTY 50 and Bank Nifty change over the next 21 and 63 sessions, and the Technical
division's six strategies (their start-day values in data/blab/store/strategy_lab.json), grouped by each factor's level that
day. A level is "measurably" different when its mean minus the all-days mean has a 95% range clear of zero (start-day
values, widened by sqrt(horizon/5) for overlap) with at least 30 start days. Findings: for each factor whose TODAY level is
measurably different for NIFTY 50 over 63 sessions, one finding about NIFTY 50 (once per factor, level and month).
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from .core import DATA, NoKey, SITE_URL, fetch_json

STORE = DATA / "blab" / "store"
FRED_START = "2005-01-01"
FRED = {
    "INDIRLTLT01STM": ("India 10-year government bond yield", "%", "M", "india"),
    "IRSTCI01INM156N": ("India call-money rate", "%", "M", "india"),
    "FEDFUNDS": ("US fed funds rate", "%", "M", "us"),
    "CPIAUCSL": ("US consumer prices (index)", "", "M", "us"),
    "UMCSENT": ("US consumer sentiment", "", "M", "us"),
    "DEXINUS": ("Rupees per US dollar", "Rs", "D", "market"),
    "DCOILBRENTEU": ("Brent crude", "$", "D", "market"),
    "DTWEXBGS": ("Broad dollar index", "", "D", "market"),
    "VIXCLS": ("US VIX (fear gauge)", "", "D", "market"),
    "DGS10": ("US 10-year Treasury yield", "%", "D", "market"),
}
LATE_DAYS = {"M": 100, "D": 10}              # a monthly value dated the 1st is usually published 2-7 weeks later
PUB_LAG = {"M": 45, "D": 2}
FACTORS = ["india rates", "rupee", "oil", "fed", "us fear", "dollar"]


def _load(name, default):
    try:
        return json.loads((STORE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(name, doc):
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / name).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (B-Lab research desk, educational)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ------------------------------------------------------------------ sources

_FRED_LOCK = threading.Lock()


def fred_series(ctx, sids):
    """Thread-safe: the three scouts and the analyst share one store."""
    with _FRED_LOCK:
        return _fred_series(ctx, sids)


def _fred_series(ctx, sids):
    """Keep each FRED series in data/blab/store/fred.json, refreshed each run from 60 days before its last value. The key comes
    only from the environment (the GitHub secret); without it -> NoKey. -> ({sid: [[date, value], ...]}, errors)"""
    key = os.environ.get("FRED_API_KEY", "").strip()
    st = _load("fred.json", {})
    if not key:
        if all(st.get(s, {}).get("obs") for s in sids):
            return {s: st[s]["obs"] for s in sids}, ["FRED: no key on this runner; showing the saved values"]
        raise NoKey("FRED needs its free key (GitHub secret FRED_API_KEY).")
    fetch = getattr(ctx, "fred_fetch", None) or (lambda url: json.loads(_get(url)))
    errors = []
    for s in sids:
        have = st.get(s, {}).get("obs") or []
        start = (date.fromisoformat(have[-1][0]) - timedelta(days=60)).isoformat() if have else FRED_START
        q = urllib.parse.urlencode({"series_id": s, "api_key": key, "file_type": "json", "observation_start": start})
        try:
            obs = fetch("https://api.stlouisfed.org/fred/series/observations?" + q).get("observations", [])
        except Exception as e:  # noqa: BLE001  never let the key reach a message
            errors.append(f"{s}: {str(e).replace(key, '***')[:120]}"); continue
        new = {o["date"]: float(o["value"]) for o in obs if o.get("value") not in (None, ".", "")}
        merged = {d: v for d, v in have if d < start}
        merged.update(new)
        st[s] = {"fetched": ctx.now.isoformat(), "obs": sorted([d, v] for d, v in merged.items())}
    _save("fred.json", st)
    return {s: st.get(s, {}).get("obs", []) for s in sids}, errors


RBI_KEYS = [("repo", r"Policy Repo Rate\s*:\s*([\d.]+)"), ("sdf", r"Standing Deposit Facility Rate\s*:\s*([\d.]+)"),
            ("msf", r"Marginal Standing Facility Rate\s*:\s*([\d.]+)"), ("bank_rate", r"Bank Rate\s*:\s*([\d.]+)"),
            ("crr", r"CRR\s*:\s*([\d.]+)"), ("slr", r"SLR\s*:\s*([\d.]+)"), ("inr_usd", r"INR\s*/\s*1\s*USD\s*:\s*([\d.]+)")]


def parse_rbi(html_text):
    import html as H
    t = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", html_text)))
    out = {}
    for k, pat in RBI_KEYS:
        m = re.search(pat, t)
        out[k] = float(m.group(1)) if m else None
    return out


def rbi_snapshot(ctx):
    st = _load("rbi.json", {"rows": []})
    page = (getattr(ctx, "rbi_fetch", None) or _get)("https://www.rbi.org.in/")
    v = parse_rbi(page)
    if v.get("repo") is None:
        raise RuntimeError("the RBI page no longer shows 'Policy Repo Rate' where expected")
    day = ctx.now.date().isoformat()
    st["rows"] = [r for r in st["rows"] if r["date"] != day] + [{"date": day, **v}]
    _save("rbi.json", st)
    return st["rows"]


def mospi_cpi(ctx):
    """All-India Combined General CPI, latest month the MOSPI API serves. -> (row or None, note)"""
    fetch = getattr(ctx, "mospi_fetch", None) or (lambda url: json.loads(_get(url)))
    for y in (ctx.now.year, ctx.now.year - 1):
        try:
            # state_code 99 = All India, sector_code 3 = Combined, group_code 0 = General (checked 2026-11-17); newest month first
            rows = fetch(f"https://api.mospi.gov.in/api/cpi/getCPIIndex?year={y}&state_code=99&sector_code=3&group_code=0").get("data") or []
        except Exception as e:  # noqa: BLE001
            return None, f"MOSPI API failed ({type(e).__name__})"
        gen = [r for r in rows if r.get("state") == "All India" and r.get("sector") == "Combined" and "General" in (r.get("group") or "")]
        if gen:
            r = gen[0]
            return {"year": r["year"], "month": r["month"], "index": r.get("index"), "inflation": r.get("inflation"), "base": r.get("baseyear")}, ""
    return None, "MOSPI API returned no CPI rows"


def site_index(name):
    return {r[0]: r[4] for r in fetch_json(SITE_URL + f"t/x/d/{name}.json").get("d", []) if r[4]}


# ------------------------------------------------------------------ the factors

def published(obs, freq):
    """[[obs_date, value]] -> [[date it became public, value]] (no look-ahead)."""
    lag = PUB_LAG[freq]
    return [[(date.fromisoformat(d) + timedelta(days=lag)).isoformat(), v] for d, v in obs]


def asof_series(pub, days):
    """Value known on each day (the latest published on or before it); None before the first."""
    out, i, cur = [], 0, None
    for d in days:
        while i < len(pub) and pub[i][0] <= d:
            cur = pub[i][1]; i += 1
        out.append(cur)
    return out


def levels(days, fred):
    """Each factor's level on each trading day, from values public by then. -> {factor: [level or None]}"""
    def known(sid):
        return asof_series(published(fred.get(sid, []), FRED[sid][2]), days)
    def change(vals, n, ratio):
        out = [None] * len(vals)
        for i in range(n, len(vals)):
            a, b = vals[i - n], vals[i]
            if a is not None and b is not None and (not ratio or a):
                out[i] = (b / a - 1) if ratio else (b - a)
        return out
    def months_back(vals, months):
        out, back = [None] * len(vals), {}
        for i, d in enumerate(days):
            back[d] = vals[i]
        keys = days
        for i, d in enumerate(keys):
            target = (date.fromisoformat(d) - timedelta(days=int(30.44 * months))).isoformat()
            j = _bisect_left(keys, target)
            if 0 <= j < len(keys) and vals[i] is not None and vals[j] is not None:
                out[i] = vals[i] - vals[j]
        return out
    lv = {}
    ind10 = months_back(known("INDIRLTLT01STM"), 3)
    lv["india rates"] = [None if x is None else "rising" if x >= 0.25 else "falling" if x <= -0.25 else "flat" for x in ind10]
    rup = change(known("DEXINUS"), 63, True)
    lv["rupee"] = [None if x is None else "weakening" if x >= 0.02 else "strengthening" if x <= -0.02 else "stable" for x in rup]
    oil = change(known("DCOILBRENTEU"), 63, True)
    lv["oil"] = [None if x is None else "up sharply" if x >= 0.15 else "down sharply" if x <= -0.15 else "flat" for x in oil]
    fed = months_back(known("FEDFUNDS"), 6)
    lv["fed"] = [None if x is None else "hiking" if x >= 0.5 else "cutting" if x <= -0.5 else "on hold" for x in fed]
    vix = known("VIXCLS")
    avg = [None] * len(vix)
    for i in range(19, len(vix)):
        w = [x for x in vix[i - 19:i + 1] if x is not None]
        avg[i] = sum(w) / len(w) if len(w) >= 15 else None
    lv["us fear"] = [None if x is None else "stressed" if x >= 25 else "calm" if x <= 15 else "normal" for x in avg]
    dol = change(known("DTWEXBGS"), 63, True)
    lv["dollar"] = [None if x is None else "strong" if x >= 0.03 else "weak" if x <= -0.03 else "steady" for x in dol]
    return lv


def _bisect_left(a, x):
    lo, hi = 0, len(a)
    while lo < hi:
        m = (lo + hi) // 2
        if a[m] < x:
            lo = m + 1
        else:
            hi = m
    return lo


def outcome(days, series, lv, h, step=5, first=None):
    """{factor: {level: {n, mean_pct, diff_pct, ci95_pct (of the difference), verdict}}, plus all-days mean} for one series."""
    idx = [i for i in range(0, len(days) - h, step) if (first is None or days[i] >= first) and series[i] and series[i + h]]
    fwd = {i: series[i + h] / series[i] - 1 for i in idx}
    if not fwd:
        return {}, None
    allm = sum(fwd.values()) / len(fwd)
    out = {}
    for f, L in lv.items():
        out[f] = {}
        for lev in sorted({L[i] for i in idx if L[i]}):
            xs = [fwd[i] - allm for i in idx if L[i] == lev]
            n = len(xs)
            mu = sum(xs) / n
            sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
            half = 1.96 * sd / math.sqrt(n) * math.sqrt(h / step) if n > 1 else None
            lo, hi = (None, None) if half is None else (mu - half, mu + half)
            v = "too few start days" if n < 30 else "measurably better than usual" if lo > 0 else "measurably worse than usual" if hi < 0 else "no measurable difference"
            out[f][lev] = {"n": n, "mean_pct": round((mu + allm) * 100, 2), "diff_pct": round(mu * 100, 2),
                           "ci95_pct": None if lo is None else [round(lo * 100, 2), round(hi * 100, 2)], "verdict": v}
    return out, round(allm * 100, 2)


def strategy_by_factor(lab_daily, lv_by_day):
    """The Technical division's per-start-day strategy values grouped by each factor's level that day."""
    if not lab_daily:
        return {}
    out = {}
    for f in FACTORS:
        out[f] = {}
        for k, vals in lab_daily["values"].items():
            groups = {}
            for d, v in zip(lab_daily["dates"], vals):
                lev = (lv_by_day.get(d) or {}).get(f)
                if lev and v is not None:
                    groups.setdefault(lev, []).append(v)
            for lev, xs in groups.items():
                n = len(xs); mu = sum(xs) / n
                sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else 0
                half = 1.96 * sd / math.sqrt(n) * math.sqrt(21 / 5) if n > 1 else None
                lo, hi = (None, None) if half is None else (mu - half, mu + half)
                v = "too few start days" if n < 30 else "measurably better than the average stock" if lo > 0 else "measurably worse than the average stock" if hi < 0 else "no measurable difference"
                out[f].setdefault(lev, {})[k] = {"n": n, "mean_pct": round(mu * 100, 2), "ci95_pct": None if lo is None else [round(lo * 100, 2), round(hi * 100, 2)], "verdict": v}
    return out


# ------------------------------------------------------------------ bots

def _late(d, freq, today):
    return d is None or (today - date.fromisoformat(d)).days > LATE_DAYS[freq]


def _series_rows(obs_by_sid, sids, today):
    rows = []
    for s in sids:
        o = obs_by_sid.get(s) or []
        last = o[-1] if o else None
        name, unit, freq, _ = FRED[s]
        rows.append({"id": s, "name": name, "unit": unit, "freq": "monthly" if freq == "M" else "daily", "date": last[0] if last else None,
                     "value": last[1] if last else None, "late": _late(last[0] if last else None, freq, today), "source": "FRED"})
    return rows


def m1_india(ctx):
    today = ctx.now.date()
    rows, errs = [], []
    try:
        rbi = rbi_snapshot(ctx)[-1]
        for k, label in (("repo", "RBI policy repo rate"), ("sdf", "Standing deposit facility rate"), ("msf", "Marginal standing facility rate"),
                         ("crr", "Cash reserve ratio (CRR)"), ("slr", "Statutory liquidity ratio (SLR)"), ("inr_usd", "RBI reference rate, rupees per dollar")):
            rows.append({"id": k, "name": label, "unit": "%" if k != "inr_usd" else "Rs", "freq": "daily snapshot", "date": rbi["date"], "value": rbi.get(k), "late": False, "source": "RBI"})
    except Exception as e:  # noqa: BLE001
        errs.append(f"RBI: {e}")
    try:
        obs, e2 = fred_series(ctx, ["INDIRLTLT01STM", "IRSTCI01INM156N"])
        errs += e2
        rows += _series_rows(obs, ["INDIRLTLT01STM", "IRSTCI01INM156N"], today)
    except NoKey as e:
        errs.append(str(e))
    cpi, note = mospi_cpi(ctx)
    if cpi:
        mdate = datetime.strptime(f"{cpi['month']} {cpi['year']}", "%B %Y").date().isoformat()
        rows.append({"id": "cpi", "name": f"India CPI, All-India combined (base {cpi['base']})", "unit": "", "freq": "monthly", "date": mdate,
                     "value": float(cpi["index"]) if cpi.get("index") else None, "extra": f"inflation {cpi['inflation']}% a year" if cpi.get("inflation") else "",
                     "late": _late(mdate, "M", today), "source": "MOSPI",
                     "why_late": "the MOSPI API stops at December 2025: CPI moved to a 2024 base in January 2026 and the API has no rows for it yet" if _late(mdate, "M", today) else ""})
    else:
        errs.append(f"MOSPI CPI: {note}")
    ctx.shared["M_rows_india"] = rows
    if not rows:
        raise RuntimeError("; ".join(errs[:3]) or "no Indian macro source answered")
    late = [r["name"] for r in rows if r["late"]]
    return {"items": len(rows), "as_of": max(r["date"] for r in rows if r["date"]), "errors": errs, "series": rows,
            "detail": f"{len(rows)} Indian series: repo {next((r['value'] for r in rows if r['id'] == 'repo'), 'n/a')}%, India 10-year "
                      f"{next((r['value'] for r in rows if r['id'] == 'INDIRLTLT01STM'), 'n/a')}% ({next((r['date'] for r in rows if r['id'] == 'INDIRLTLT01STM'), '')}), "
                      f"rupee {next((r['value'] for r in rows if r['id'] == 'inr_usd'), 'n/a')} per dollar. "
                      + (f"Late: {', '.join(late)}." if late else "Nothing late.")}


def m2_us(ctx):
    sids = ["FEDFUNDS", "CPIAUCSL", "UMCSENT"]
    obs, errs = fred_series(ctx, sids)
    rows = _series_rows(obs, sids, ctx.now.date())
    ctx.shared["M_rows_us"] = rows
    late = [r["name"] for r in rows if r["late"]]
    return {"items": len(rows), "as_of": max((r["date"] for r in rows if r["date"]), default=None), "errors": errs, "series": rows,
            "detail": "US official statistics, used only for their effect on Indian markets: " + "; ".join(f"{r['name']} {r['value']} ({r['date']})" for r in rows)
                      + (f". Late: {', '.join(late)}." if late else ".")}


def m3_market(ctx):
    sids = ["DEXINUS", "DCOILBRENTEU", "DTWEXBGS", "VIXCLS", "DGS10"]
    obs, errs = fred_series(ctx, sids)
    today = ctx.now.date()
    rows = _series_rows(obs, sids, today)
    for name, file in (("India VIX", "India_20VIX"), ("Nifty 10-year benchmark G-Sec index", "Nifty_2010_20yr_20Benchmark_20G_2dSec")):
        try:
            s = site_index(file)
            d = max(s)
            rows.append({"id": file, "name": name, "unit": "", "freq": "daily", "date": d, "value": round(s[d], 2), "late": _late(d, "D", today), "source": "NSE"})
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}: {type(e).__name__}")
    ctx.shared["M_rows_market"] = rows
    late = [r["name"] for r in rows if r["late"]]
    return {"items": len(rows), "as_of": max((r["date"] for r in rows if r["date"]), default=None), "errors": errs, "series": rows,
            "detail": "; ".join(f"{r['name']} {r['value']} ({r['date']})" for r in rows) + (f". Late: {', '.join(late)}." if late else ".")}


def m4_analyst(ctx):
    from .technical import joined
    obs, errs = fred_series(ctx, ["INDIRLTLT01STM", "DEXINUS", "DCOILBRENTEU", "FEDFUNDS", "VIXCLS", "DTWEXBGS"])
    site_rows = lambda name: [[d, 0, 0, 0, v] for d, v in sorted(site_index(name).items())]   # noqa: E731  recent years: the live site's NSE files
    n50 = joined("_5eNSEI.json", site_rows("Nifty_2050"))                                     # older years: the history branch
    bank = joined("_5eNSEBANK.json", site_rows("Nifty_20Bank"))
    days = sorted(n50)
    if len(days) < 1000 or days[0] > "2008-01-01" or (ctx.now.date() - date.fromisoformat(days[-1])).days > 10:
        raise RuntimeError(f"NIFTY 50 history incomplete on this runner ({len(days)} days, {days[0] if days else '-'} to {days[-1] if days else '-'}): the history branch or the site is missing")
    lv = levels(days, obs)
    today = {f: lv[f][-1] for f in FACTORS}
    n = [n50[d] for d in days]
    b = [bank.get(d) for d in days]
    res = {}
    for name, ser in (("NIFTY 50", n), ("Bank Nifty", b)):
        for h in (21, 63):
            res[f"{name} {h}"] = outcome(days, ser, lv, h, first="2007-01-01")
    lab_doc = _load("strategy_lab.json", {})
    by_day = {d: {f: lv[f][i] for f in FACTORS} for i, d in enumerate(days)}
    strat = strategy_by_factor(lab_doc.get("daily"), by_day)
    found = []
    o63, all63 = res["NIFTY 50 63"]
    month = days[-1][:7]
    for f in FACTORS:
        lev = today[f]
        c = (o63.get(f) or {}).get(lev) if lev else None
        if c and c["verdict"].startswith("measurably"):
            found.append({"scope": "NIFTY 50", "kind": f"macro: {f}", "direction": 1 if "better" in c["verdict"] else -1, "event": f"{f} {lev} {month}",
                          "text": f"Today the {f} factor reads '{lev}'. Since 2007, NIFTY 50's next 63 sessions on such days averaged {c['mean_pct']:+.2f}% against "
                                  f"{all63:+.2f}% on all days (difference {c['diff_pct']:+.2f}%, range {c['ci95_pct'][0]:+.2f} to {c['ci95_pct'][1]:+.2f}%, {c['n']} start days).",
                          "evidence": [{"src": "B-Lab macro analyst (FRED, NSE)", "url": "", "quote": f"{f}: {lev}"}]})
    pack = {k: {"by": v[0], "all_pct": v[1]} for k, v in res.items()}
    meas = [f"{f} '{today[f]}' ({(o63.get(f) or {}).get(today[f], {}).get('verdict', 'not measured')})" for f in FACTORS if today[f]]
    return {"items": len(days), "as_of": ctx.now.isoformat(), "errors": errs, "findings": found,
            "today": today, "outcomes": pack, "strategies": strat, "strategy_dates": [lab_doc.get("from"), lab_doc.get("to")],
            "detail": f"Six factors on NIFTY 50 history since {days[0][:4]} (each value counted from its publication). Today: " + "; ".join(meas)
                      + f". {len(found)} finding(s) filed." + ("" if lab_doc.get("daily") else " Strategies by factor: waiting for the Technical division's start-day values.")}
