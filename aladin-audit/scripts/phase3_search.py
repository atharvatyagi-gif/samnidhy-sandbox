"""
ALADIN audit, phase 3: find published evidence on Indian equities through OpenAlex (the free, open scholarly database, official API).
  python aladin-audit/scripts/phase3_search.py   -> aladin-audit/phase3/search.json (every record found, with its abstract)
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "phase3"
QUERIES = {
    "A momentum": ["momentum profits Indian stock market", "momentum anomaly India equity", "momentum crash India"],
    "A quality": ["quality factor Indian stocks profitability", "Fama French five factor India", "four factor model Indian equities"],
    "B PEAD": ["post earnings announcement drift India", "earnings surprise stock returns India", "earnings announcement efficiency Indian market"],
    "C machine learning": ["machine learning cross section stock returns India", "gradient boosting stock return prediction India", "machine learning Indian stock market prediction out of sample"],
    "D regime / multi-factor": ["factor timing India regime", "multifactor portfolio India", "market regime switching Indian stock returns"],
    "E risk / volatility": ["low volatility anomaly India", "volatility forecasting India VIX", "volatility managed portfolio India"],
    "F pairs": ["pairs trading India", "statistical arbitrage Indian stock market", "cointegration pairs trading NSE"],
    "G other": ["short term reversal Indian stocks", "news sentiment stock returns India", "investor sentiment Indian stock market returns", "transaction costs anomalies India"],
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "aladin-audit/1.0 (research; mailto not given)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def abstract(inv):
    if not inv:
        return None
    pos = {}
    for w, idxs in inv.items():
        for i in idxs:
            pos[i] = w
    return " ".join(pos[i] for i in sorted(pos))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seen, out = set(), {}
    fields = "id,display_name,publication_year,cited_by_count,doi,primary_location,open_access,abstract_inverted_index,type"
    for group, qs in QUERIES.items():
        out[group] = []
        for q in qs:
            url = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": q, "per-page": 12, "select": fields})
            try:
                d = get(url)
            except Exception as e:  # noqa: BLE001
                print("failed", q, e)
                continue
            for w in d.get("results", []):
                if w["id"] in seen:
                    continue
                seen.add(w["id"])
                src = ((w.get("primary_location") or {}).get("source") or {})
                out[group].append({"query": q, "id": w["id"], "title": w["display_name"], "year": w["publication_year"], "cited": w["cited_by_count"],
                                   "doi": w.get("doi"), "venue": src.get("display_name"), "oa_url": (w.get("open_access") or {}).get("oa_url"),
                                   "abstract": abstract(w.get("abstract_inverted_index"))})
            time.sleep(0.3)
    (OUT / "search.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for g, rows in out.items():
        print(g, len(rows), "records,", sum(1 for r in rows if r["abstract"]), "with abstracts")


if __name__ == "__main__":
    main()
