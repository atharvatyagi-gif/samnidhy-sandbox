"""
Derived revenue shares from the filing's own numbers.   python scripts/related_party_shares.py [--symbols A,B] [--limit N] [--max-calls N]

Almost no filing writes "X is 24% of our revenue" for a named listed company, so the impact score had no share to work with. But the related-party note (SEBI LODR) of an
annual report lists what the company SOLD to each named related party, and the statement of profit and loss gives its revenue. Dividing one by the other gives a share, and it
is a share the filing's own numbers support. It is always marked DERIVED (edge field `wd` = "derived", with the two numbers, their quotes and pages in `calc`), never shown as
if the company had stated it, and it carries a lower confidence than a stated share.

What is checked, in code, before a share exists:
  * both quotes are found word for word in the filing; each number is written in its own quote;
  * each number has a unit (crore, lakh, million, billion, thousand or plain rupees) that the model copied from the text AND that appears in that page's text;
  * each number has a column heading that appears in the page text, and the two headings are the same year and the same scope (standalone or consolidated);
  * the counterparty is one named listed company (name resolution as for every other edge);
  * 0 < share <= 1 after converting both numbers to rupees.
Revenue basis only (sales to a related party / revenue from operations: the SUPPLIER's dependence on its customer). The purchases basis would need a total of purchases that filings
state in several different ways; it is not derived here. Which column of a table is "this year" is read by the model and verified only through the heading text: the audit sheet
checks it. The group's own related parties (parents, subsidiaries) are included only when they are listed companies resolved by name, like any other counterparty.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import revenue_graph_builder as rb  # noqa: E402

ROOT = rb.ROOT
PROMPT_VERSION = "rp-v1"
MIN_SHARE = 0.0005                                        # below 0.05% of revenue a share is rounding noise: it would print as 0.0% and tell the impact score nothing
SYSTEM = ("You read the related-party transactions note and the statement of profit and loss of an Indian company's annual report. Extract ONLY what the text states; never use outside "
          "knowledge; use null for anything not stated. Copy every quote exactly as written (verbatim, no paraphrase, no ellipses). Reply with ONE JSON object: "
          '{"revenue": null or {"value": number, "unit": string, "scope": "standalone"|"consolidated"|null, "column_heading": string, "page": integer, "quote": string}, '
          '"transactions": [{"related_party_name": string, "kind": "sale_of_goods_or_services"|"other", "value": number, "unit": string, "scope": "standalone"|"consolidated"|null, '
          '"column_heading": string, "page": integer, "quote": string}]}. '
          "'revenue' is the company's revenue from operations for its CURRENT financial year (the first number is usually this year and the second the previous year; use the column whose "
          "heading is the current year). 'unit' is the unit of that table exactly as the text states it (for example 'Rs. in crore', '` in million', 'INR lakhs'); if the text states none, write null. "
          "'column_heading' is the heading of the column you took the number from, copied from the text (for example 'Year ended March 31, 2026'). 'transactions' lists a row only when the company "
          "SOLD goods or services to a NAMED related party (kind sale_of_goods_or_services); put every other kind of row (purchases, loans, interest, dividends, rent, remuneration) as kind 'other' "
          "or leave it out. 'value' is the number for the current year exactly as written, without commas. Each page in the text starts with a line [[PAGE n]]; 'page' is the page the quote came from. "
          "If the text has none of this, return {\"revenue\": null, \"transactions\": []}.")
KEYWORDS = ["related part", "revenue from operations", "statement of profit and loss", "total income", "sale of goods", "sale of products", "sale of services", "nature of transaction",
            "name of the related party", "holding company", "fellow subsidiar", "joint venture", "associate", "in crore", "in million", "in lakh", "in thousand"]
BONUS = [{"re": r"name of (the )?related part(y|ies)|nature of (the )?transaction|sale of (goods|products|services)", "w": 4},
         {"re": r"revenue from operations", "w": 4}, {"re": r"statement of (consolidated |standalone )?profit and loss", "w": 3}, {"re": r"related part(y|ies) (transactions|disclosures)", "w": 3}]
UNITS = [(re.compile(r"\bcrores?\b|\bcrs?\b\.?", re.I), 1e7), (re.compile(r"\blakhs?\b|\blacs?\b", re.I), 1e5), (re.compile(r"\bmillions?\b|\bmn\b|\bmio\b", re.I), 1e6),
         (re.compile(r"\bbillions?\b|\bbn\b", re.I), 1e9), (re.compile(r"\bthousands?\b|'000|\b000s\b", re.I), 1e3), (re.compile(r"(?:\b(?:rupees|inr|absolute|rs\.?)|₹|`)\s*$", re.I), 1.0)]


def unit_factor(unit):
    """'Rs. in crore' -> 1e7, '` in million' -> 1e6, 'INR lakhs' -> 1e5, 'Rs.' -> 1.0; None when no unit is stated."""
    u = (unit or "").strip()
    if not u:
        return None
    for rx, f in UNITS[:-1]:
        if rx.search(u):
            return f
    return 1.0 if UNITS[-1][0].search(u) else None


def _num_in(value, quote):
    return isinstance(value, (int, float)) and any(abs(n - value) < 1e-6 or abs(n - round(value)) < 1e-6 for n in rb.numbers_in(quote))


def _checked(item, pages, norm_pages):
    """-> (value in rupees, calc fragment) or (None, reason) for one revenue or transaction item."""
    q = rb.norm(item.get("quote") or "")
    pg = item.get("page")
    page_text = None
    for no in ([pg] if pg in norm_pages else []) + list(norm_pages):
        if q and q in norm_pages[no]:
            page_text, pg = norm_pages[no], no
            break
    if page_text is None:
        return None, "quote is not in the source text"
    if not _num_in(item.get("value"), q):
        return None, "the number is not written in its quote"
    f = unit_factor(item.get("unit"))
    if f is None:
        return None, "no unit stated"
    unit_l = rb.norm(item["unit"]).lower().strip()
    if unit_l not in page_text.lower():
        return None, "the unit is not on that page"
    head = rb.norm(item.get("column_heading") or "")
    if not head or head.lower() not in page_text.lower():
        return None, "the column heading is not on that page"
    return item["value"] * f, {"v": item["value"], "u": item["unit"].strip(), "h": head, "pg": pg, "q": q, "sc": item.get("scope")}


def _year(heading):
    m = re.search(r"(20\d\d)", heading or "")
    return m.group(1) if m else None


def derive(answers, pages, meta, now, owner, index):
    """answers: the model's JSON objects (one per chunk) for ONE filing. -> (items for to_graph_edges, notes)."""
    norm_pages = {no: rb.norm(t) for no, t in pages.items()}
    notes, rev = [], None
    for a in answers:
        r = (a or {}).get("revenue") if isinstance(a, dict) else None
        if isinstance(r, dict):
            val, info = _checked(r, pages, norm_pages)
            if val and val > 0:
                rev = (val, info)
                break
            notes.append("revenue: " + str(info))
    if rev is None:
        return [], notes + ["no checked revenue figure in this filing: no share can be derived"]
    out = []
    for a in answers:
        for t in ((a or {}).get("transactions") or []) if isinstance(a, dict) else []:
            if not isinstance(t, dict) or t.get("kind") != "sale_of_goods_or_services":
                continue
            name = (t.get("related_party_name") or "").strip()
            sym = index.resolve(name, exclude=owner) if name else None
            if not sym:
                continue                                              # only listed companies matter for the impact score
            val, info = _checked(t, pages, norm_pages)
            if not val:
                notes.append(f"{name}: {info}")
                continue
            if info["sc"] and rev[1]["sc"] and info["sc"] != rev[1]["sc"]:
                notes.append(f"{name}: standalone and consolidated numbers are not comparable")
                continue
            if _year(info["h"]) and _year(rev[1]["h"]) and _year(info["h"]) != _year(rev[1]["h"]):
                notes.append(f"{name}: the two numbers are from different years")
                continue
            r = val / rev[0]
            if not 0 < r <= 1:
                notes.append(f"{name}: derived share {r:.3f} is outside (0, 1]")
                continue
            if r < MIN_SHARE:
                notes.append(f"{name}: derived share {r:.5f} is below {MIN_SHARE:.2%} of revenue (noise), not kept")
                continue
            per = meta.get("period")
            conf = round(rb.edge_conf(True, True, False, per, now) + 0.1, 2)           # quote .5 + named .2 + derived share .1 + recent period .1
            out.append({"name": name, "anon": None, "direction": "customer", "rel": "supplies", "w": round(r, 4), "wb": "revenue", "per": per, "comp": "sale of goods or services (related party)",
                        "pg": info["pg"], "q": info["q"], "conf": conf, "url": meta["url"], "doc": meta["kind"], "wd": "derived",
                        "calc": {"a": info, "t": {**rev[1], "label": "revenue from operations"}, "r": round(r, 4)}})
    return out, notes


def pages_for(pages):
    return rb.select_pages(pages, KEYWORDS, 2, 14, 3 * 10000, BONUS)


def extract(doc, fetcher, llm, now, cache_dir, owner, index, log=print):
    sh, pages = fetcher.pages(doc["url"])
    if not pages:
        return [], ["annual: no readable text"], 0
    sel = pages_for(pages)
    chunks = rb.chunk_pages(sel, 10000)[:3]
    answers, notes, answered = [], [f"rp: {len(pages)} pages, {len(sel)} relevant, {len(chunks)} sent"], 0
    pmap_all = {}
    for text, pmap in chunks:
        pmap_all.update(pmap)
        key = rb.sha(f"{sh}|{rb.sha(text)}|{PROMPT_VERSION}")
        cp = cache_dir / f"{key}.json"
        ans = rb.load_json(cp) if cp.exists() else None
        if ans is None:
            try:
                raw = llm.complete(SYSTEM, f"Filing text follows.\n\n{text}")
            except rb.LLMBadRequest as ex:
                notes.append(f"chunk refused by the model API ({str(ex)[:80]})")
                continue
            ans = rb.parse_json_text(raw)
            if ans is None:
                notes.append("model answer was not JSON")
                continue
            cp.write_text(json.dumps(ans), encoding="utf-8")
        answers.append(ans)
        answered += 1
    items, dn = derive(answers, pmap_all, {"url": doc["url"], "kind": doc["kind"], "period": doc.get("period")}, now, owner, index)
    return items, notes + dn, answered


def merge(graph, owner, edge_rows, rp_info):
    """Replaces the owner's previously derived edges with the new ones and records the pass in cos[owner]['rp']."""
    keep = [e for e in graph.get("edges", []) if not (e["own"] == owner and e.get("wd") == "derived")]
    g = {**graph, "edges": keep + edge_rows, "cos": {**graph.get("cos", {})}}
    c = dict(g["cos"].get(owner) or {"at": rp_info["at"], "edges": 0, "fac": 0, "notes": []})
    c["rp"] = rp_info
    g["cos"][owner] = c
    return g


def run(symbols, limit, session, llm, fetcher, now=None, log=print, out=None):
    now = now or rb.now_utc()
    out = out or rb.OUT
    src = rb.load_json(rb.SRC)
    stocks = rb.load_universe()
    houses = (rb.load_json(ROOT / "data" / "config" / "business_houses.json", {}) or {}).get("houses", [])
    index = rb.NameIndex(stocks, rb.load_json(ROOT / "data" / "config" / "news_aliases.json", {}))
    graph = rb.load_json(out, {"cos": {}, "edges": []})
    todo = [s for s in (symbols or sorted(graph.get("cos", {}))) if "rp" not in (graph.get("cos", {}).get(s) or {})][:limit]
    cache = rb.CACHE / "llm"
    cache.mkdir(parents=True, exist_ok=True)
    report = []
    for sym in todo:
        try:
            docs = [d for d in rb.discover(session, sym, {**src, "transcript_candidates": 0}, now) if d["kind"] == "annual"]
        except Exception as e:  # noqa: BLE001
            report.append((sym, f"filings could not be listed (will be retried): {e}"))
            log("  %-12s %s" % report[-1])
            continue
        time.sleep(rb.PACE_S)
        if not docs:
            report.append((sym, "no annual report found"))
            g = merge(graph, sym, [], {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "derived": 0, "notes": ["no annual report found"]})
        else:
            try:
                items, notes, answered = extract(docs[0], fetcher, llm, now, cache, sym, index, log)
            except rb.LLMBudget as b:
                report.append((sym, "stopped: " + str(b)))
                log("  " + report[-1][1])
                break
            except Exception as ex:  # noqa: BLE001
                report.append((sym, f"failed: {str(ex)[:80]}"))
                continue
            if answered == 0:
                report.append((sym, "NOT recorded, will be retried: " + "; ".join(notes[:2])))
                continue
            rows = rb.to_graph_edges(sym, items, index)
            g = merge(graph, sym, rows, {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "derived": len(rows), "notes": notes[:6]})
            report.append((sym, f"{len(rows)} derived shares; " + "; ".join(notes[:2])))
        graph = rb.assemble(g, {}, stocks, houses, rb.load_cfg()["anon_resolve_min_conf"], now)
        out.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        log("  %-12s %s" % report[-1])
    return graph, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--max-calls", type=int, default=400)
    a = ap.parse_args(argv)
    try:
        from aladin_env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    llm = rb.LLM(max_calls=a.max_calls)
    if llm.provider is None:
        print("No GROQ_API_KEY or GEMINI_API_KEY set: nothing to extract with.")
        return 0
    from aladin_ticker_daemon import NseSession
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    try:
        run(syms, a.limit, NseSession(), llm, rb.Fetcher())
    except rb.NoUniverse as e:
        print(e)
    print(f"model calls this run: {llm.calls}; tokens reported by the providers: {sum(llm.tokens.values()):,} {llm.tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
