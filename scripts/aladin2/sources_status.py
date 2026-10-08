"""
ALADIN 2.0 startup table: which inputs are live right now. Printed at the start of the nightly job and runnable alone:

  python -m scripts.aladin2.sources_status [--offline]
For every source in data/config/aladin2_sources.json: local data present or not (and how fresh), reachability from this machine (a short GET, skipped with --offline), and whether the API key
it needs is set (the key's NAME only; a value is never printed). Missing keys and unreachable sources are reported, never fatal: every feature degrades to "not measured".
"""
import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TERM = None
PROBES = {   # source id -> (url, needs key name or None, local file/folder relative to data/terminal/aladin2 or ROOT)
    "india_vix": ("https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX?range=5d&interval=1d", None, "macro/india_vix.json"),
    "usdinr": ("https://query1.finance.yahoo.com/v8/finance/chart/INR%3DX?range=5d&interval=1d", None, "macro/usdinr.json"),
    "us10y": ("https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&file_type=json", "FRED_API_KEY", "macro/us10y.json"),
    "delivery_pct": ("https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_02012020.csv", None, "deliv"),
    "fno_oi": ("https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20260106_F_0000.csv.zip", None, "fno"),
    "wiki_pageviews": ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/Tata_Steel/daily/20260901/20260903", None, None),
}


def env_has(name):
    if os.environ.get(name):
        return True
    for f in (ROOT / ".env", ROOT.parent / "SAMNIDHY_EDUCATIONAL_DASHBOARD" / ".env"):
        if f.exists() and any(l.startswith(name + "=") and l.split("=", 1)[1].strip() for l in f.read_text(encoding="utf-8", errors="ignore").splitlines()):
            return True
    return False


def local_state(rel, base):
    if rel is None:
        return "no local copy needed"
    p = base / rel
    if not p.exists():
        return "no local data"
    files = [x for x in ([p] if p.is_file() else sorted(p.glob("*"))) if x.is_file() and not x.name.startswith("_")]
    if not files:
        return "no local data"
    newest = max(files, key=lambda x: x.stat().st_mtime); age = (time.time() - newest.stat().st_mtime) / 86400
    return f"{len(files)} file(s), newest {newest.name[:10]} ({age:.0f} d old)"


def table(offline=False, timeout=6):
    import requests
    from . import data_lake as L
    base = Path(L.TERM) / "aladin2"; rows = []; src = json.loads((ROOT / "data" / "config" / "aladin2_sources.json").read_text(encoding="utf-8"))["sources"]
    for s in src:
        sid = s["id"]; url, key, rel = PROBES.get(sid, (None, None, None)); reach = "not probed"; keyst = "-"
        if key:
            keyst = f"{key}: {'set' if env_has(key) else 'MISSING'}"
        if url and not offline:
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}, timeout=timeout); reach = f"HTTP {r.status_code}"
            except Exception as e:                                         # noqa: BLE001
                reach = f"unreachable ({type(e).__name__})"
        rows.append((sid, local_state(rel, base) if rel else s["status"][:60], reach, keyst))
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--offline", action="store_true"); a = ap.parse_args()
    print(f"{'source':<18}{'local data':<46}{'reachable':<22}{'key'}")
    for r in table(a.offline):
        print(f"{r[0]:<18}{r[1][:44]:<46}{r[2]:<22}{r[3]}")


if __name__ == "__main__":
    main()
