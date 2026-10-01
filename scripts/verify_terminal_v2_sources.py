"""
One-off verification for the terminal-v2 plan (docs/TERMINAL_PLAN.md): actually calls every data source listed
in that plan FROM WHEREVER THIS SCRIPT RUNS, and records the real HTTP status + a short real sample (or the
real error) for each. Written to run on a GitHub Actions runner specifically, because this project has already
seen one real case (OpenSky, 30 Sep 2026) where a source worked from a developer's machine but failed from
GitHub's shared runner IPs - sandbox/local results are not trusted as a stand-in for this.

Never invents a result: a source that errors is recorded as failed with the real exception text, not skipped
or guessed. Secrets-gated sources (AISSTREAM_KEY, ACLED_KEY/ACLED_EMAIL, FRED_KEY) are marked "needs key" and
only actually called if the secret is present in the environment.

Output: data/terminal_v2/source_verification.json (machine-readable) and .md (for docs/TERMINAL_PLAN.md).

  python scripts/verify_terminal_v2_sources.py
"""
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "data" / "terminal_v2" / "source_verification.json"
UA = {"User-Agent": "Mozilla/5.0 (Samnidhy B-Lab terminal-v2 source check; educational; github.com/atharvatyagi-gif)"}
results = []


def record(category, name, url, status, detail, needs_key=False, sample=None):
    results.append({
        "category": category, "name": name, "url": url, "status": status,
        "detail": detail[:500] if isinstance(detail, str) else detail,
        "sample": (json.dumps(sample)[:400] if sample is not None else None),
        "needs_key": needs_key,
    })
    print(f"[{status:4}] {category} / {name}: {detail[:160] if isinstance(detail, str) else detail}")


def check_get(category, name, url, params=None, headers=None, timeout=20, sample_fn=None):
    try:
        r = requests.get(url, params=params, headers=headers or UA, timeout=timeout)
        ok = r.ok
        sample = None
        if ok and sample_fn:
            try:
                sample = sample_fn(r)
            except Exception as exc:
                sample = f"(sample extraction failed: {type(exc).__name__} {exc})"
        record(category, name, r.url, "OK" if ok else "FAIL", f"HTTP {r.status_code}", sample=sample)
        return r if ok else None
    except Exception as exc:
        record(category, name, url, "FAIL", f"{type(exc).__name__}: {exc}")
        return None


def main():
    # ---- MAP layers ----
    check_get("map", "OpenSky /states/all (Hormuz bbox)", "https://opensky-network.org/api/states/all",
              params={"lamin": 25.3, "lamax": 27.9, "lomin": 55.0, "lomax": 57.6},
              sample_fn=lambda r: {"count": len(r.json().get("states") or [])})

    PW = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
    check_get("map", "IMF PortWatch: chokepoints_database", f"{PW}/PortWatch_chokepoints_database/FeatureServer/0/query",
              params={"where": "1=1", "outFields": "*", "f": "json", "resultRecordCount": 2},
              sample_fn=lambda r: {"n_features": len(r.json().get("features", [])), "first": (r.json().get("features") or [{}])[0].get("attributes", {}).get("fullname")})
    check_get("map", "IMF PortWatch: Daily_Chokepoints_Data", f"{PW}/Daily_Chokepoints_Data/FeatureServer/0/query",
              params={"where": "1=1", "outFields": "*", "f": "json", "resultRecordCount": 1, "orderByFields": "date DESC"},
              sample_fn=lambda r: (r.json().get("features") or [{}])[0].get("attributes", {}))
    check_get("map", "IMF PortWatch: portwatch_disruptions_database", f"{PW}/portwatch_disruptions_database/FeatureServer/0/query",
              params={"where": "1=1", "outFields": "*", "f": "json", "resultRecordCount": 2},
              sample_fn=lambda r: {"n_features": len(r.json().get("features", []))})
    check_get("map", "IMF PortWatch: PortWatch_ports_database (India)", f"{PW}/PortWatch_ports_database/FeatureServer/0/query",
              params={"where": "ISO3='IND'", "outFields": "*", "f": "json"},
              sample_fn=lambda r: {"n_india_ports": len(r.json().get("features", []))})
    check_get("map", "IMF PortWatch: Daily_Ports_Data", f"{PW}/Daily_Ports_Data/FeatureServer/0/query",
              params={"where": "ISO3='IND'", "outFields": "*", "f": "json", "resultRecordCount": 1, "orderByFields": "date DESC"},
              sample_fn=lambda r: (r.json().get("features") or [{}])[0].get("attributes", {}))

    check_get("map", "Shipping lanes (newzealandpaul/Shipping-Lanes, CC BY 4.0)",
              "https://raw.githubusercontent.com/newzealandpaul/Shipping-Lanes/main/data/Shipping_Lanes_v1.geojson",
              sample_fn=lambda r: {"n_features": len(r.json().get("features", [])), "bytes": len(r.content)})

    check_get("map", "TeleGeography submarine cables", "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json",
              sample_fn=lambda r: {"n_cables": len(r.json().get("features", []))})
    check_get("map", "TeleGeography landing points", "https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json",
              sample_fn=lambda r: {"n_points": len(r.json().get("features", []))})

    check_get("map", "WRI Global Power Plant Database (CSV)",
              "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv",
              sample_fn=lambda r: {"n_rows_india": sum(1 for row in csv.DictReader(io.StringIO(r.text)) if row.get("country") == "IND"), "bytes": len(r.content)})

    check_get("map", "USGS earthquakes M4.5+ (7 days)", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
              sample_fn=lambda r: {"n_events": len(r.json().get("features", []))})
    check_get("map", "NASA EONET v3 (open events)", "https://eonet.gsfc.nasa.gov/api/v3/events", params={"status": "open"},
              sample_fn=lambda r: {"n_events": len(r.json().get("events", []))})
    check_get("map", "GDACS event list", "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
              sample_fn=lambda r: {"n_events": len(r.json().get("features", r.json()) if isinstance(r.json(), dict) else r.json())})

    wikidata_query = """
      SELECT ?company ?companyLabel ?facility ?facilityLabel ?coord WHERE {
        ?company wdt:P414 ?exchange . ?company rdfs:label "Reliance Industries"@en .
        ?facility wdt:P127 ?company . ?facility wdt:P625 ?coord .
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
      } LIMIT 5"""
    check_get("map", "Wikidata SPARQL (company facilities, Reliance test query)", "https://query.wikidata.org/sparql",
              params={"query": wikidata_query, "format": "json"}, headers={**UA, "Accept": "application/sparql-results+json"},
              sample_fn=lambda r: {"n_bindings": len(r.json().get("results", {}).get("bindings", []))})

    check_get("map", "GDELT DOC 2.0 (claimed failing from Actions - testing live)", "https://api.gdeltproject.org/api/v2/doc/doc",
              params={"query": '"Strait of Hormuz"', "mode": "artlist", "maxrecords": 3, "format": "json", "sort": "datedesc"}, headers=UA,
              sample_fn=lambda r: {"n_articles": len((r.json() or {}).get("articles", []))} if r.headers.get("content-type", "").startswith("application/json") else {"non_json_body_head": r.text[:150]})
    check_get("map", "Google News RSS (GDELT fallback)", "https://news.google.com/rss/search",
              params={"q": "Strait of Hormuz", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
              sample_fn=lambda r: {"bytes": len(r.content), "looks_like_rss": r.text.strip().startswith("<?xml")})

    # Secret-gated: only call if the secret is actually present (never fabricate a key or a result)
    if os.environ.get("AISSTREAM_KEY"):
        record("map", "aisstream.io (ship AIS)", "wss://stream.aisstream.io/v0/stream", "SKIPPED",
               "Key present but this script doesn't open websockets; verify manually.", needs_key=True)
    else:
        record("map", "aisstream.io (ship AIS)", "wss://stream.aisstream.io/v0/stream", "NEEDS_KEY",
               "AISSTREAM_KEY not set - user must register a free account and provide it as a GitHub secret.", needs_key=True)
    if os.environ.get("ACLED_KEY") and os.environ.get("ACLED_EMAIL"):
        check_get("map", "ACLED API", "https://api.acleddata.com/acled/read",
                  params={"key": os.environ["ACLED_KEY"], "email": os.environ["ACLED_EMAIL"], "limit": 1})
    else:
        record("map", "ACLED API (conflict events)", "https://api.acleddata.com/acled/read", "NEEDS_KEY",
               "ACLED_KEY/ACLED_EMAIL not set - user must register a free account and provide both as GitHub secrets.", needs_key=True)

    # ---- Section 5: other free data ----
    try:
        import yfinance as yf
        tickers = {"USDINR=X": "USDINR", "BZ=F": "Brent", "GC=F": "Gold", "SI=F": "Silver", "HG=F": "Copper", "NG=F": "Nat gas"}
        data = yf.download(list(tickers.keys()), period="5d", progress=False, threads=True)
        last = data["Close"].iloc[-1].to_dict() if not data.empty else {}
        record("macro", "Yahoo Finance (yfinance) FX & commodities", "yfinance", "OK" if last else "FAIL",
               "fetched" if last else "empty result", sample=last)
    except Exception as exc:
        record("macro", "Yahoo Finance (yfinance) FX & commodities", "yfinance", "FAIL", f"{type(exc).__name__}: {exc}")

    check_get("macro", "RBI reference rate page", "https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx")
    check_get("macro", "RBI current rates page", "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx")
    check_get("macro", "MOSPI release calendar", "https://www.mospi.gov.in/release-calendar")
    check_get("macro", "World Bank API (India GDP)", "https://api.worldbank.org/v2/country/IN/indicator/NY.GDP.MKTP.CD",
              params={"format": "json", "per_page": 1}, sample_fn=lambda r: r.json()[1] if isinstance(r.json(), list) and len(r.json()) > 1 else r.json())
    check_get("macro", "IMF DataMapper API (India real GDP growth)", "https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH/IND",
              sample_fn=lambda r: r.json())
    if os.environ.get("FRED_KEY"):
        check_get("macro", "FRED API", "https://api.stlouisfed.org/fred/series/observations",
                  params={"series_id": "DGS10", "api_key": os.environ["FRED_KEY"], "file_type": "json", "limit": 1})
    else:
        record("macro", "FRED API", "https://api.stlouisfed.org/fred/series/observations", "NEEDS_KEY",
               "FRED_KEY not set (optional) - free to register at fred.stlouisfed.org.", needs_key=True)

    # NSE corporate announcements: needs the session-cookie dance this repo already uses (scripts/nse_live_poll.py)
    try:
        s = requests.Session(); s.headers.update(UA); s.headers["Referer"] = "https://www.nseindia.com/"
        s.get("https://www.nseindia.com/", timeout=20)
        r = s.get("https://www.nseindia.com/api/corporate-announcements", params={"index": "equities"}, timeout=20)
        r.raise_for_status()
        j = r.json()
        record("macro", "NSE corporate announcements", r.url, "OK", f"HTTP {r.status_code}", sample={"n": len(j) if isinstance(j, list) else "?"})
    except Exception as exc:
        record("macro", "NSE corporate announcements", "https://www.nseindia.com/api/corporate-announcements", "FAIL", f"{type(exc).__name__}: {exc}")

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_context": "GitHub Actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local/other",
        "runner_ip_note": "See each source's real status below; do not assume local results transfer to Actions runners.",
        "results": results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    md = OUT_JSON.with_suffix(".md")
    lines = [f"# terminal-v2 source verification — {out['generated_utc']} ({out['run_context']})", ""]
    lines.append("| Category | Source | Status | Detail |")
    lines.append("|---|---|---|---|")
    for r in results:
        lines.append(f"| {r['category']} | {r['name']} | **{r['status']}** | {r['detail']} |")
    md.write_text("\n".join(lines), encoding="utf-8")
    n_ok = sum(1 for r in results if r["status"] == "OK")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_key = sum(1 for r in results if r["needs_key"])
    print(f"\n{n_ok} OK, {n_fail} FAIL, {n_key} need a key, out of {len(results)} sources checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
