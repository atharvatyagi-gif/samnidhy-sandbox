"""B-Lab Fundamental division, step 2 (docs/blab/PLAN.md): the ownership and governance scouts collect NSE's own free
disclosures into small rolling stores in the repository; the blind-spot analyst runs red-flag tests on them and on the
annual statements, each finding citing its filing.

Sources (free, no key; checked 2026-11-16):
  /api/corporate-share-holdings-master?index=equities&symbol=X   promoter and public % per quarter (about 26 quarters)
  /api/corporate-sast-reg29?index=equities&from_date&to_date      takeover-code (SAST Reg 29) acquisitions and sales, all companies
  /api/corporate-announcements?index=equities&from_date&to_date   every company announcement, with NSE's category
Not usable (checked the same day): /api/corporates-pit (insider trades) returns nothing for recent dates and only 2019-2023
rows per company; /api/corporate-pledgedata returns nothing. Pledges therefore come from the announcements NSE files under
"Disclosure under SEBI Takeover Regulations"; insider trades are "not measured" until a working free source is found.

THE RED-FLAG RULES (declared 2026-11-16, before any finding was scored; every one leans negative):
  R1 promoter stake down    promoter + promoter group % fell by 2 points or more against the quarter about a year earlier
  R2 promoter selling       a promoter's own open-market sale disclosed under SAST Reg 29 in the last 30 days
  R3 auditor resigned       "Resignation of Statutory Auditor" announced in the last 30 days
  R4 rating downgraded      a credit-rating announcement whose text says downgrade, in the last 30 days
  R5 results delayed        "Reasons for Delayed/Non-submission of Financial Results" in the last 30 days
  R6 insolvency             "Corporate Insolvency Resolution Process" announced in the last 30 days
  R7 pledge or invocation   a takeover-regulation disclosure whose text mentions a pledge or encumbrance being created or
                            invoked (not released), in the last 30 days
  R8 profit without cash    the last 3 years' operating cash flow is under half of their net profit (profit > 0); not
                            applied to banks and other financials, whose cash flow means something else
  R9 debt jump              total debt up 50% or more in a year (and by at least Rs 100 Cr) while revenue grew under 10%;
                            not applied to financials
Refined 2026-11-16 after reading the first run's output and BEFORE any finding was scored (recorded here honestly):
  - R6 does not flag an order that sets aside, dismisses or withdraws an insolvency case (Polycab: NCLAT set aside an NCLT
    order; that is not a red flag), and announcement rules give one finding per stock and rule (the earliest in the window).
  - R4 and R7 cannot be measured from NSE's summaries: rating announcements only say "informed the Exchange about Credit
    Rating" (the direction is in the attached PDF) and pledge disclosures are not filed under that category. They report
    "not measured" until a PDF reader is added; they never fire on a guess.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .core import DATA, ROOT

STORE = DATA / "blab" / "store"
REF = "https://www.nseindia.com/companies-listing/"
SHP_REFRESH_DAYS, SHP_PER_RUN = 7, 120
KEEP_DAYS = 400
WINDOW = 30
GOV = {"Resignation of Statutory Auditor", "Change in Auditors", "Credit Rating", "Credit Rating- Revision", "Credit Rating- Others",
       "Reasons for Delayed/Non-submission of Financial Results", "Corporate Insolvency Resolution Process",
       "Disclosure under SEBI Takeover Regulations", "Resignation of Director/KMP/SMP", "Related Party Transactions",
       "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company", "Action(s) taken or orders passed",
       "Statement of deviation(s) or variation(s) under Reg. 32", "Disclosure of material issue", "Default", "Fraud/Default/Arrest"}
NSE_SHP_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"


def _load(name, default):
    p = STORE / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(name, doc):
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / name).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def _session(ctx):
    """NSE session (cookie warm-up, throttle, back-off): the repository's own, scripts/aladin_ticker_daemon.py. Tests inject ctx.nse."""
    if getattr(ctx, "nse", None) is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import aladin_ticker_daemon as d
        ctx.nse = d.NseSession()
    return ctx.nse


def nse_day(s):
    """'30-SEP-2026', '14-Nov-2026 23:59:39', '15-Nov-2026 10:02' -> 'YYYY-MM-DD' (None if unreadable)."""
    s = (s or "").strip().title()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def universe():
    e = json.loads((DATA / "aladin_e" / "latest.json").read_text(encoding="utf-8"))
    return sorted(e.get("stocks", {}))


# ------------------------------------------------------------------ scouts

def collect_shareholding(ctx, syms, today):
    st = _load("shareholding.json", {})
    due = sorted((s for s in syms if (st.get(s) or {}).get("fetched", "") < (today - timedelta(days=SHP_REFRESH_DAYS)).isoformat()),
                 key=lambda s: (st.get(s) or {}).get("fetched", ""))[:SHP_PER_RUN]
    nse, errors = _session(ctx), []
    for s in due:
        try:
            rows = nse.get_json("/api/corporate-share-holdings-master", {"index": "equities", "symbol": s}, referer=REF + "corporate-filings-shareholding-pattern", max_tries=2)
        except Exception as e:  # noqa: BLE001  one stock's failure is counted, the rest go on
            errors.append(f"{s}: {e}"); continue
        q = []
        for r in rows if isinstance(rows, list) else []:
            d0, pr = nse_day(r.get("date")), r.get("pr_and_prgrp")
            try:
                pr = float(pr)
            except (TypeError, ValueError):
                continue
            if d0:
                q.append([d0, pr, _f(r.get("public_val")), nse_day(r.get("broadcastDate")), r.get("recordId")])
        st[s] = {"fetched": today.isoformat(), "q": sorted(q, reverse=True)}
    _save("shareholding.json", st)
    return st, len(due), errors


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def collect_range(ctx, name, path, page, today, first_days, chunk_days, keep, compact):
    """Rolling store of an all-company NSE list fetched by date range. -> (rows, newest_day, errors)."""
    st = _load(name, {"to": None, "rows": []})
    start = (date.fromisoformat(st["to"]) - timedelta(days=2)) if st.get("to") else today - timedelta(days=first_days)
    have = {r[0] for r in st["rows"]}
    nse, errors, d = _session(ctx), [], start
    ok_to = st.get("to")
    while d <= today:
        e = min(today, d + timedelta(days=chunk_days - 1))
        try:
            j = nse.get_json(path, {"index": "equities", "from_date": d.strftime("%d-%m-%Y"), "to_date": e.strftime("%d-%m-%Y")}, referer=REF + page, max_tries=2)
            rows = j.get("data", []) if isinstance(j, dict) else j
            for r in rows or []:
                if keep(r):
                    c = compact(r)
                    if c[0] not in have:
                        st["rows"].append(c); have.add(c[0])
            ok_to = e.isoformat()
        except Exception as ex:  # noqa: BLE001
            errors.append(f"{d}..{e}: {ex}"); break
        d = e + timedelta(days=1)
    cut = (today - timedelta(days=KEEP_DAYS)).isoformat()
    st["rows"] = [r for r in st["rows"] if (r[3] or "") >= cut]
    st["to"] = ok_to
    _save(name, st)
    return st["rows"], ok_to, errors


def f2_ownership(ctx):
    today = ctx.now.date()
    syms = universe()
    shp, n, err1 = collect_shareholding(ctx, syms, today)
    # SAST Reg 29 row: [application_no, symbol, kind, day, promoter, mode, shares_sold, holding_after_pct, acquirer, attachment]
    sast, to, err2 = collect_range(ctx, "sast29.json", "/api/corporate-sast-reg29", "corporate-filings-regulation-29", today, 90, 31,
                                   keep=lambda r: True,
                                   compact=lambda r: [str(r.get("application_no")), r.get("symbol"), r.get("acqSaleType"), nse_day(r.get("timestamp") or r.get("sysTime")),
                                                      r.get("promoterType") == "Y", r.get("acquisitionMode"), _f(r.get("noOfShareSale")), _f(r.get("totAftShare")),
                                                      (r.get("acquirerName") or "")[:80], r.get("attachement")])
    ctx.shared["F2"] = {"shp": shp, "sast": sast}
    covered = sum(1 for s in syms if (shp.get(s) or {}).get("q"))
    errs = err1[:5] + err2[:3]
    if not covered and not sast:
        raise RuntimeError("no shareholding and no SAST data: " + "; ".join(errs[:3]))
    stamp = ctx.now.isoformat() if to == today.isoformat() else to       # fetched up to today: as fresh as this run; else the last day reached
    return {"items": covered + len(sast), "as_of": stamp, "errors": errs,
            "detail": f"Shareholding history for {covered} of {len(syms)} stocks ({n} refreshed this run, each at most weekly); {len(sast)} takeover-code (SAST Reg 29) "
                      f"disclosures kept, to {to}. Insider (PIT) trades: not measured (NSE's feed returns no recent rows). "
                      + (f"{len(err1)} stock(s) failed this run." if err1 else "")}


def f3_governance(ctx):
    today = ctx.now.date()
    # announcement row: [seq_id, symbol, category, day, text, attachment]
    rows, to, err = collect_range(ctx, "announcements.json", "/api/corporate-announcements", "corporate-filings-announcements", today, 30, 3,
                                  keep=lambda r: r.get("desc") in GOV,
                                  compact=lambda r: [str(r.get("seq_id")), r.get("symbol"), r.get("desc"), nse_day(r.get("an_dt") or r.get("sort_date")),
                                                     (r.get("attchmntText") or "")[:400], r.get("attchmntFile")])
    ctx.shared["F3"] = {"ann": rows}
    a, _ = ctx.read("data/aladin/latest.json")
    nlp = [x["f"]["nlp"] for x in a.get("stocks", {}).values() if isinstance(x.get("f"), dict) and isinstance(x["f"].get("nlp"), dict)]
    if not rows and err:
        raise RuntimeError("announcements could not be read: " + err[0])
    newest = max((r[3] for r in rows if r[3]), default=to)
    return {"items": len(rows), "as_of": newest, "errors": err[:3],
            "detail": f"{len(rows)} governance announcements kept (auditors, ratings, delayed results, insolvency, pledges and encumbrances, related-party, "
                      f"litigation, regulator actions), newest {newest}. Also: the existing filings job's tone reading for {len(nlp)} stocks."}


# ------------------------------------------------------------------ analyst

def _statements(sym):
    p = DATA / "aladin_cache" / "statements" / f"{sym}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _series(doc, part, table, field):
    rows = ((doc or {}).get(part, {}).get(table, {}) or {}).get(field) or []
    return sorted(((d, v) for d, v in rows if v is not None), reverse=True)


def flags(sym, shp, sast, ann, stmt, financial, today):
    """Every red flag for one stock. Pure: tests drive it. -> list of findings (direction -1)."""
    out, recent = [], (today - timedelta(days=WINDOW)).isoformat()
    q = (shp or {}).get("q") or []
    if q:
        d1, p1 = q[0][0], q[0][1]
        old = [x for x in q if (date.fromisoformat(d1) - date.fromisoformat(x[0])).days >= 330]
        if old and p1 - old[0][1] <= -2.0:
            out.append({"kind": "promoter stake down", "event": f"shp {d1}", "text": f"Promoters hold {p1:.2f}% at {d1}, down {old[0][1] - p1:.2f} points from {old[0][1]:.2f}% at {old[0][0]}.",
                        "evidence": [{"src": "NSE shareholding pattern", "url": NSE_SHP_PAGE, "quote": f"{old[0][0]} {old[0][1]}% -> {d1} {p1}%"}]})
    for r in sast:
        if r[1] == sym and r[4] and r[2] in ("Sale", "Both") and (r[6] or 0) > 0 and r[5] == "Open Market" and (r[3] or "") >= recent:
            out.append({"kind": "promoter selling", "event": f"sast {r[0]}", "text": f"Promoter {r[8]} sold {int(r[6]):,} shares in the open market (disclosed {r[3]}); holds {r[7]}% after.",
                        "evidence": [{"src": "NSE SAST Reg 29 disclosure", "url": r[9], "quote": f"{r[8]}: sale of {int(r[6]):,} shares"}]})
    for r in sorted(ann, key=lambda r: (r[3] or "", r[0])):          # oldest first: the earliest announcement in the window is the one kept
        if r[1] != sym or (r[3] or "") < recent:
            continue
        cat, txt, low = r[2], r[4] or "", (r[4] or "").lower()
        kind = None
        if cat == "Resignation of Statutory Auditor":
            kind = "auditor resigned"
        elif cat.startswith("Credit Rating") and re.search(r"downgrad", low):
            kind = "rating downgraded"
        elif cat == "Reasons for Delayed/Non-submission of Financial Results":
            kind = "results delayed"
        elif cat == "Corporate Insolvency Resolution Process" and not re.search(r"set(ting)? aside|dismiss|withdr|quash|closure of", low):
            kind = "insolvency"
        elif cat == "Disclosure under SEBI Takeover Regulations" and re.search(r"pledg|encumb", low) and (re.search(r"invo|creat", low) or not re.search(r"releas|revo", low)):
            kind = "pledge or invocation"
        if kind and not any(f["kind"] == kind for f in out):     # one finding per stock and rule in the window
            out.append({"kind": kind, "event": f"ann {r[0]}", "text": f"{cat} ({r[3]}): {txt[:180]}", "evidence": [{"src": "NSE announcement", "url": r[5], "quote": txt[:160]}]})
    if stmt and not financial:
        ni, ocf = _series(stmt, "ann", "inc", "Net Income")[:3], _series(stmt, "ann", "cf", "Operating Cash Flow")[:3]
        if len(ni) == 3 and len(ocf) == 3 and {d for d, _ in ni} == {d for d, _ in ocf}:
            sni, socf = sum(v for _, v in ni), sum(v for _, v in ocf)
            if sni > 0 and socf < 0.5 * sni:
                out.append({"kind": "profit without cash", "event": f"stmt {ni[0][0]}",
                            "text": f"Over the 3 years to {ni[0][0]}, operating cash flow was Rs {socf / 1e7:,.0f} Cr against net profit of Rs {sni / 1e7:,.0f} Cr ({socf / sni:.0%}). "
                                    "A lending or leasing arm, land bought for projects or a stock build-up can cause this without wrongdoing; the filing shows which.",
                            "evidence": [{"src": "Annual statements (Yahoo Finance)", "url": f"https://finance.yahoo.com/quote/{sym}.NS/cash-flow", "quote": f"OCF {socf / 1e7:,.0f} Cr vs profit {sni / 1e7:,.0f} Cr"}]})
        debt, rev = _series(stmt, "ann", "bal", "Total Debt")[:2], _series(stmt, "ann", "inc", "Total Revenue")[:2]
        if len(debt) == 2 and len(rev) == 2 and debt[1][1] > 0 and rev[1][1] > 0 and debt[0][0] == rev[0][0]:
            g_d, g_r, inc = debt[0][1] / debt[1][1] - 1, rev[0][1] / rev[1][1] - 1, debt[0][1] - debt[1][1]
            if g_d >= 0.5 and inc >= 100e7 and g_r < 0.10:
                out.append({"kind": "debt jump", "event": f"debt {debt[0][0]}",
                            "text": f"Total debt rose {g_d:.0%} (Rs {inc / 1e7:,.0f} Cr) in the year to {debt[0][0]} while revenue changed {g_r:+.0%}.",
                            "evidence": [{"src": "Annual statements (Yahoo Finance)", "url": f"https://finance.yahoo.com/quote/{sym}.NS/balance-sheet", "quote": f"debt {debt[1][1] / 1e7:,.0f} -> {debt[0][1] / 1e7:,.0f} Cr"}]})
    for f in out:
        f.update({"sym": sym, "direction": -1})
    return out


def f5_blind_spots(ctx):
    f2, f3 = ctx.shared.get("F2"), ctx.shared.get("F3")
    if not f2 and not f3:
        raise RuntimeError("neither the ownership scout (F2) nor the governance scout (F3) delivered data this run")
    today = ctx.now.date()
    a, _ = ctx.read("data/aladin/latest.json")
    fin = {s for s, x in a.get("stocks", {}).items() if isinstance(x.get("f"), dict) and x["f"].get("fin")}
    shp, sast, ann = (f2 or {}).get("shp", {}), (f2 or {}).get("sast", []), (f3 or {}).get("ann", [])
    found, with_stmt = [], 0
    for s in universe():
        st = _statements(s)
        with_stmt += st is not None
        found += flags(s, shp.get(s), sast, ann, st, s in fin, today)
    from collections import Counter
    c = Counter(f["kind"] for f in found)
    missing = [n for n, ok in (("ownership (F2)", f2), ("governance (F3)", f3)) if not ok]
    return {"items": len(universe()), "as_of": ctx.now.isoformat(), "findings": found,
            "detail": f"Red-flag rules R1-R9 (declared before scoring) on {len(universe())} stocks; statements available for {with_stmt}. "
                      "R4 rating downgrades and R7 pledges: not measured (NSE's summaries do not say which way; the PDFs do). "
                      + (", ".join(f"{k}: {v}" for k, v in c.most_common()) or "No red flag this run.")
                      + (f" Missing this run: {', '.join(missing)}." if missing else "")}
