"""
Revenue profile from the annual report's own segment note:   python scripts/revenue_profile.py [--symbols A,B] [--limit N] [--max-calls N] [--redo]

Ind AS 108 (Operating Segments, paragraphs 33-34) makes every listed Indian company disclose, in its annual report:
  * reliance on major customers: every single customer that brings 10% or more of revenue (the amount, usually without the name), or a statement that none does;
  * revenue by geography: at least the company's home country (India) against all other countries.
So, unlike named customers with a share (rare), these two facts are available for most companies and are comparable. This pass reads them, once per company,
from the same cached annual report the supply-chain builder already downloaded, with a free language model, and checks everything in code:

  * every quote is found word for word on its page; every number is written in its own quote;
  * a major customer is kept only if its quote speaks of a customer and of revenue; its share is the stated percentage, or its amount divided by a checked revenue
    figure in the same unit and year (geography total, or revenue from operations); a share outside 10-100% is not kept (the rule is "10% or more");
  * "no single customer is 10% or more" is kept only if the quote says so in words (no / not / none / any single ... 10%);
  * geography rows are kept only if every amount is in the quote, there are at least two rows, and the rows add up to the stated total (within 3%) when one is stated;
  * nothing is estimated: a company whose filing does not say it is "not found", never "low".
Output: data/revenue_profile.json  {cos: {SYM: {at, url, per, major: {status, customers: [...]}, geo: {rows: [...], total, unit, q, pg}, notes}}}
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import revenue_graph_builder as rb  # noqa: E402
import related_party_shares as rp  # noqa: E402

ROOT = rb.ROOT
OUT = ROOT / "data" / "revenue_profile.json"
PROMPT_VERSION = "prof-v1"
SYSTEM = ("You read the operating-segment note (Ind AS 108) of an Indian company's annual report: 'Information about major customers' and 'Geographical information'. "
          "Extract ONLY what the text states; never use outside knowledge; use null for anything not stated. Copy every quote exactly as written (verbatim, no paraphrase, no ellipses). "
          "Reply with ONE JSON object: "
          '{"no_major_customer": null or {"page": integer, "quote": string}, '
          '"major_customers": [{"name": string or null, "share_pct": number or null, "amount": number or null, "unit": string or null, "where": "India"|"outside India"|null, '
          '"column_heading": string or null, "page": integer, "quote": string}], '
          '"geography": null or {"unit": string or null, "column_heading": string, "scope": "standalone"|"consolidated"|null, "page": integer, "quote": string, '
          '"rows": [{"region": string, "amount": number}], "total": number or null}}. '
          "'no_major_customer' is the sentence saying that NO single customer accounts for 10% or more of revenue. 'major_customers' lists each customer that the text says brings 10% "
          "or more of revenue, for the CURRENT financial year only (not the previous year): share_pct if a percentage is written, amount and unit if an amount is written. "
          "'geography' is revenue (from external customers) by region for the CURRENT year: the region names and amounts as written, the unit of the table as written "
          "(for example 'Rs. in crore', '` in million'), the column heading you took the numbers from, and the total if written. Use the current-year column only. "
          "Each page starts with a line [[PAGE n]]; 'page' is the page the quote came from. If the text has none of this, return "
          '{"no_major_customer": null, "major_customers": [], "geography": null}.')
KEYWORDS = ["major customer", "single customer", "10%", "10 %", "ten per", "geographical", "geographic", "outside india", "within india", "domestic", "export",
            "entity-wide", "entity wide", "segment information", "operating segment", "ind as 108", "revenue from external customers"]
BONUS = [{"re": r"information (about|on|regarding) (major|key|significant) customers?|single (external )?customer|10\s?%\s*(or more|of the (company|group)|of (total )?revenue)", "w": 6},
         {"re": r"geographical (information|areas?|segment)|revenue from external customers|outside india", "w": 5},
         {"re": r"ind as 108|operating segments?|entity[- ]wide", "w": 3}]
NO_MAJOR_RX = re.compile(r"\b(no|not|none|neither|nil|any single|did not|does not|do not)\b.{0,140}(10\s?%|ten per ?cent)|(10\s?%|ten per ?cent).{0,140}\b(no|not|none|nil)\b", re.I)
CUSTOMER_RX = re.compile(r"customer|client|buyer|party", re.I)
REVENUE_RX = re.compile(r"revenue|sales|turnover|income", re.I)


def pages_for(pages):
    return rb.select_pages(pages, KEYWORDS, 2, 10, 2 * 10000, BONUS)


def _find(q, pg, norm_pages):
    """(page number, page text) where the normalised quote is found word for word, preferring the page the model named; else (None, None)."""
    q = rb.norm(q or "")
    if len(q) < 12:
        return None, None
    for no in ([pg] if pg in norm_pages else []) + list(norm_pages):
        if q in norm_pages[no]:
            return no, norm_pages[no]
    return None, None


def _unit_ok(unit, page_text):
    f = rp.unit_factor(unit)
    return f if f is not None and rb.norm(unit).lower().strip() in page_text.lower() else None


def check_geo(g, norm_pages):
    """-> (geo dict or None, note)."""
    if not isinstance(g, dict):
        return None, None
    pg, page = _find(g.get("quote"), g.get("page"), norm_pages)
    if page is None:
        return None, "geography: quote is not in the source text"
    q = rb.norm(g["quote"]); f = _unit_ok(g.get("unit"), page)
    rows = []
    for r in g.get("rows") or []:
        if not isinstance(r, dict):
            continue
        reg, amt = (r.get("region") or "").strip(), rp.as_number(r.get("amount"))
        if not reg or amt is None or amt < 0:
            continue
        if reg.lower() not in q.lower() or not rp._num_in(amt, q):
            return None, f"geography: '{reg}' or its amount is not in the quote"
        rows.append({"region": reg, "amount": amt})
    if len(rows) < 2:
        return None, "geography: fewer than two regions"
    s = sum(r["amount"] for r in rows); tot = rp.as_number(g.get("total"))
    if tot is not None:
        if not rp._num_in(tot, q):
            return None, "geography: the total is not in the quote"
        if not (0.97 <= s / tot <= 1.03 if tot else False):
            return None, f"geography: regions add up to {s:g}, not the stated total {tot:g}"
    total = tot or s
    if total <= 0:
        return None, "geography: total is zero"
    out = {"rows": [{"region": r["region"], "amount": r["amount"], "share": round(r["amount"] / total, 4)} for r in rows], "total": total,
           "unit": g.get("unit") if f else None, "factor": f, "h": rb.norm(g.get("column_heading") or "") or None, "sc": g.get("scope"), "pg": pg, "q": q}
    return out, None


def check_major(answers, norm_pages, geo, rev):
    """-> (major dict, notes). rev: (rupees, info) or None; geo: checked geography (its total, in rupees when the unit is known, is a revenue figure)."""
    notes, customers, none_q = [], [], None
    base = rev[0] if rev else (geo["total"] * geo["factor"] if geo and geo.get("factor") else None)
    for a in answers:
        nm = (a or {}).get("no_major_customer") if isinstance(a, dict) else None
        if isinstance(nm, dict) and none_q is None:
            pg, page = _find(nm.get("quote"), nm.get("page"), norm_pages)
            q = rb.norm(nm.get("quote") or "")
            if page is not None and NO_MAJOR_RX.search(q) and CUSTOMER_RX.search(q):
                none_q = {"q": q, "pg": pg}
            else:
                notes.append("no-major statement not confirmed by its own words")
        for c in ((a or {}).get("major_customers") or []) if isinstance(a, dict) else []:
            if not isinstance(c, dict):
                continue
            pg, page = _find(c.get("quote"), c.get("page"), norm_pages)
            if page is None:
                notes.append("major customer: quote is not in the source text"); continue
            q = rb.norm(c["quote"])
            if not (CUSTOMER_RX.search(q) and REVENUE_RX.search(q)):
                notes.append("major customer: the quote does not speak of a customer and revenue"); continue
            share, amt_rs = None, None
            sp = rp.as_number(c.get("share_pct"))
            if sp is not None:
                if not rp._num_in(sp, q):
                    notes.append("major customer: the percentage is not in the quote"); continue
                share = sp / 100.0
            amt = rp.as_number(c.get("amount"))
            if amt is not None:
                f = _unit_ok(c.get("unit"), page)
                if not rp._num_in(amt, q):
                    notes.append("major customer: the amount is not in the quote"); continue
                if f:
                    amt_rs = amt * f
                    if share is None and base:
                        share = amt_rs / base
            min10 = bool(re.search(r"10\s?%|ten per ?cent", q, re.I))
            if share is not None and not (0.0999 <= share <= 1.0):
                notes.append(f"major customer: share {share:.3f} is outside 10-100% (likely a unit or year mismatch), not kept"); share = None
            if share is None and not min10:
                notes.append("major customer: neither a share nor the 10% threshold is written"); continue
            customers.append({"name": (c.get("name") or None), "share": round(share, 4) if share is not None else None, "min_share": 0.10 if share is None else None,
                              "amount_cr": round(amt_rs / 1e7, 2) if amt_rs else None, "where": c.get("where") if c.get("where") in ("India", "outside India") else None, "pg": pg, "q": q})
    if customers:
        return {"status": "disclosed", "customers": customers}, notes
    if none_q:
        return {"status": "none_over_10", "customers": [], **none_q}, notes
    return {"status": "not_found", "customers": []}, notes


def profile(answers, pages):
    """answers: the model's JSON objects for ONE filing; pages: {page no: text}. -> (profile fragment, notes). Pure (tests/test_revenue_profile.py)."""
    norm_pages = {no: rb.norm(t) for no, t in pages.items()}
    geo, notes = None, []
    for a in answers:
        g, n = check_geo((a or {}).get("geography") if isinstance(a, dict) else None, norm_pages)
        if g:
            geo = g; break
        if n:
            notes.append(n)
    major, mn = check_major(answers, norm_pages, geo, None)
    return {"major": major, "geo": geo}, notes + mn


def extract(doc, fetcher, llm, cache_dir):
    sh, pages = fetcher.pages(doc["url"])
    if not pages:
        return None, ["annual: no readable text"], 0
    sel = pages_for(pages)
    chunks = rb.chunk_pages(sel, 10000)[:2]
    answers, notes, answered, pmap_all = [], [f"profile: {len(pages)} pages, {len(sel)} relevant, {len(chunks)} sent"], 0, {}
    for text, pmap in chunks:
        pmap_all.update(pmap)
        cp = cache_dir / f"{rb.sha(f'{sh}|{rb.sha(text)}|{PROMPT_VERSION}')}.json"
        ans = rb.load_json(cp) if cp.exists() else None
        if ans is None:
            try:
                raw = llm.complete(SYSTEM, f"Filing text follows.\n\n{text}")
            except rb.LLMBadRequest as ex:
                notes.append(f"chunk refused by the model API ({str(ex)[:80]})"); continue
            ans = rb.parse_json_text(raw)
            if ans is None:
                notes.append("model answer was not JSON"); continue
            cp.write_text(json.dumps(ans), encoding="utf-8")
        answers.append(ans); answered += 1
    prof, pn = profile(answers, pmap_all)
    return prof, notes + pn, answered


def run(symbols, limit, session, llm, fetcher, now=None, log=print, out=None, redo=False):
    now = now or rb.now_utc(); out = Path(out or OUT)
    src = rb.load_json(rb.SRC); doc = rb.load_json(out, {"v": 1, "cos": {}}) or {"v": 1, "cos": {}}
    graph = rb.load_json(rb.OUT, {"cos": {}})
    pool = symbols or sorted(graph.get("cos", {}))                                  # companies whose filings the supply-chain builder already found
    todo = [s for s in pool if redo or s not in doc["cos"]][:limit]
    cache = rb.CACHE / "llm"; cache.mkdir(parents=True, exist_ok=True); report = []
    for sym in todo:
        try:
            docs = [d for d in rb.discover(session, sym, {**src, "transcript_candidates": 0}, now) if d["kind"] == "annual"]
        except Exception as e:  # noqa: BLE001
            report.append((sym, f"filings could not be listed (will be retried): {e}")); log("  %-12s %s" % report[-1]); continue
        time.sleep(rb.PACE_S)
        rec = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if not docs:
            rec.update({"major": {"status": "not_found", "customers": []}, "geo": None, "notes": ["no annual report found"]})
        else:
            try:
                prof, notes, answered = extract(docs[0], fetcher, llm, cache)
            except rb.LLMBudget as b:
                report.append((sym, "stopped: " + str(b))); log("  " + report[-1][1]); break
            except Exception as ex:  # noqa: BLE001
                report.append((sym, f"failed: {str(ex)[:80]}")); continue
            if answered == 0:
                report.append((sym, "NOT recorded, will be retried: " + "; ".join(notes[:2]))); continue
            rec.update({"url": docs[0]["url"], "per": docs[0].get("period"), **prof, "notes": notes[:6]})
        doc["cos"][sym] = rec; doc["generated_utc"] = rec["at"]
        out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        m = rec["major"]; g = rec.get("geo")
        report.append((sym, f"major: {m['status']} ({len(m['customers'])}), geography: {len(g['rows']) if g else 0} regions"))
        log("  %-12s %s" % report[-1])
    return doc, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=""); ap.add_argument("--limit", type=int, default=200); ap.add_argument("--max-calls", type=int, default=200)
    ap.add_argument("--redo", action="store_true", help="check again for companies already done, from the cached model answers")
    a = ap.parse_args(argv)
    try:
        from aladin_env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    llm = rb.LLM(max_calls=a.max_calls)
    if llm.provider is None:
        print("No GROQ_API_KEY or GEMINI_API_KEY set: nothing to extract with."); return 0
    from aladin_ticker_daemon import NseSession
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    try:
        run(syms, a.limit, NseSession(), llm, rb.Fetcher(), redo=a.redo)
    except rb.NoUniverse as e:
        print(e)
    print(f"model calls this run: {llm.calls}; tokens reported by the providers: {sum(llm.tokens.values()):,} {llm.tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
