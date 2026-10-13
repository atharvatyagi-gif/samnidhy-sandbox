"""
Export share and customer types from each company's BRSR (Business Responsibility and Sustainability Report), the machine-readable XBRL file the company
itself files with NSE. No language model, no quota.

  python scripts/brsr_profile.py [--limit N] [--symbols A,B]      -> data/brsr_profile.json  (resumes: a filing already read is not read again)

From the current-year context of the XBRL (contextRef "DCYMain" and the business-activity contexts), exactly as filed:
  exports      PercentageOfContributionOfExportsInTheTotalTurnoverOfTheEntity (a fraction; a value written as 0-100 is kept only when it is clearly a percentage,
               i.e. above 1 and at most 100, and marked "pct_written")
  customers    ABriefOnTypesOfCustomersExplanatoryTextBlock (plain text, shortened)
  activities   DescriptionOfMainActivity / DescriptionOfBusinessActivity with PercentageOfTotalTurnoverForBusinessActivities (the turnover split by activity)
The list of filings comes from one NSE call (the latest BRSR of every company that filed one, about 1,260). BRSR is required of the top 1,000 listed companies.
"""
import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "brsr_profile.json"
LIST = "/api/corporate-bussiness-sustainabilitiy?index=equities"            # NSE's own spelling
TAG = r"<(?:[a-z-]+:)?{name}\b[^>]*contextRef=\"{ctx}\"[^>]*>(.*?)</(?:[a-z-]+:)?{name}>"


def _val(xml, name, ctx="DCYMain"):
    m = re.search(TAG.format(name=name, ctx=re.escape(ctx)), xml, re.S)
    return html.unescape(m.group(1)).strip() if m else None


def _text(s, n=400):
    if not s:
        return None
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s))).strip()
    return (t[:n].rsplit(" ", 1)[0] + "…") if len(t) > n else t or None


def parse(xml):
    """XBRL text -> {exports, exports_note, customers, activities}. Pure (tests/test_brsr_profile.py)."""
    out = {"exports": None, "exports_note": None, "customers": _text(_val(xml, "ABriefOnTypesOfCustomersExplanatoryTextBlock")), "activities": []}
    raw = _val(xml, "PercentageOfContributionOfExportsInTheTotalTurnoverOfTheEntity")
    try:
        v = float(raw) if raw not in (None, "") else None
    except ValueError:
        v = None
    if v is not None and 0 <= v <= 1:
        out["exports"] = round(v, 4)
    elif v is not None and 1 < v <= 100:
        out["exports"], out["exports_note"] = round(v / 100, 4), "pct_written"
    elif v is not None:
        out["exports_note"] = f"not kept: {raw}"
    for ctx in sorted(set(re.findall(r'contextRef="(D_BusinessActivities\d+)"', xml)), key=lambda c: int(re.sub(r"\D", "", c))):
        share = _val(xml, "PercentageOfTotalTurnoverForBusinessActivities", ctx)
        try:
            share = float(share)
        except (TypeError, ValueError):
            share = None
        if share is not None and 1 < share <= 100:
            share /= 100
        name = _val(xml, "DescriptionOfBusinessActivity", ctx) or _val(xml, "DescriptionOfMainActivity", ctx)
        if name and share is not None and 0 <= share <= 1:
            out["activities"].append({"d": _text(name, 90), "share": round(share, 4)})
    return out


def run(session, fetch, limit=2000, symbols=None, out=None, log=print, now=None):
    out = Path(out or OUT)
    doc = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"v": 1, "cos": {}}
    rows = (session.get_json(LIST) or {}).get("data") or []
    latest = {}
    for r in rows:                                                          # the latest filing per company (highest fiscal year, then the latest submission)
        x = r.get("xbrlFile")
        if not r.get("symbol") or not x or x == "-":
            continue
        k = (r.get("fyTo") or 0, r.get("fyFrom") or 0)
        if r["symbol"] not in latest or k > latest[r["symbol"]][0]:
            latest[r["symbol"]] = (k, r)
    todo = [s for s in (symbols or sorted(latest)) if s in latest and (doc["cos"].get(s) or {}).get("xbrl") != latest[s][1]["xbrlFile"]][:limit]
    log(f"BRSR filings listed: {len(latest)}; to read now: {len(todo)}")
    done = 0
    for sym in todo:
        r = latest[sym][1]
        try:
            xml = fetch(r["xbrlFile"])
        except Exception as e:  # noqa: BLE001
            log(f"  {sym}: download failed ({type(e).__name__}), retried next run"); continue
        rec = {"fy": f"{r.get('fyFrom')}-{str(r.get('fyTo'))[-2:]}", "filed": r.get("submissionDate"), "xbrl": r["xbrlFile"], "pdf": r.get("attachmentFile"), **parse(xml)}
        doc["cos"][sym] = rec; done += 1
        if done % 25 == 0:
            out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        time.sleep(0.3)
    doc["generated_utc"] = (now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n_exp = sum(1 for v in doc["cos"].values() if v.get("exports") is not None)
    log(f"BRSR profile: {len(doc['cos'])} companies, export share for {n_exp}; read {done} this run")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=2000); ap.add_argument("--symbols", default=""); a = ap.parse_args(argv)
    import requests
    from aladin_ticker_daemon import NseSession
    s = NseSession(); http = requests.Session(); http.headers["User-Agent"] = "Mozilla/5.0 (research; B-Lab)"

    def fetch(url):
        r = http.get(url, timeout=60); r.raise_for_status()
        if len(r.content) > 15_000_000:
            raise ValueError("file too large")
        return r.text
    run(s, fetch, a.limit, [x.strip().upper() for x in a.symbols.split(",") if x.strip()] or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
