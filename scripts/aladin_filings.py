"""
ALADIN filings NLP and free alternative data.

  python scripts/aladin_filings.py                   score NSE corporate announcements (NIFTY 500, last 90 days) + delivery trend + deals
  python scripts/aladin_filings.py --symbols TCS,INFY --no-transcripts
  python scripts/aladin_filings.py --alt-only        only the delivery / bulk-block part (no NSE announcement calls)

Output: data/aladin_cache/alt_scores.json  ->  {stocks: {SYM: {nlp:{tone,hedge,qa,src,n}, nlp_z, alt:{deliv, bulk_cr}}}}
read by scripts/aladin_model.py (`load_alt`). Every figure is either measured or absent; nothing is filled in.

* Announcements: NSE's own corporate-announcements API (subject + description), through the same cookie-handshake session the tick daemon
  uses, at most 3 requests/s. If NSE is unreachable (it times out from GitHub Actions), the run says so and keeps the previous scores.
  Each announcement is scored once with FinBERT (cached by NSE's sequence id); the 90-day tone uses a 30-day half-life. The hedging ratio is
  hedge words / (hedge + confident words) from data/config/tone_words.json.
* Earnings-call transcripts: when an announcement's text mentions a transcript, the PDF is read and sent to the cloud model through
  aladin_sentiment_engine.score_transcript (Groq or Gemini key, else a local split). At most 40 per night, cached by URL.
* Delivery %: the 20-day average against the 120-day average, from the saved bhavcopy files.
* Bulk / block deals: NSE publishes only the latest day, so each run saves a copy and the 30-day net value (money in minus money out, Rs crore) is
  built from the copies; it grows from the day this first runs.
"""

import argparse
import csv
import gzip
import io
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
TERM = ROOT / "data" / "terminal"
CACHE = ROOT / "data" / "aladin_cache"
OUT = CACHE / "alt_scores.json"
TONE = ROOT / "data" / "config" / "tone_words.json"
WINDOW_DAYS, HALF_LIFE_DAYS, TRANSCRIPT_CAP = 90, 30, 40
SKIP_DESC = re.compile(r"trading window|share certificate|newspaper publication|loss of|duplicate|investor complaints|compliance certificate|reg\.? ?74|reg\.? ?40|"
                       r"intimation of record date|book closure|postal ballot notice|annual general meeting", re.I)
ANN_URL = "/api/corporate-announcements"
ANN_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"


def now_utc():
    return datetime.now(timezone.utc)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------ text measures

def hedging_ratio(text, hedge, confident):
    words = re.findall(r"[a-z][a-z\-']+", text.lower())
    h = sum(w in hedge for w in words)
    c = sum(w in confident for w in words)
    return None if h + c == 0 else round(h / (h + c), 3)


def parse_ts(s):
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def usable(a):
    """An announcement worth scoring: has text, and is not boilerplate (trading-window notices, share-certificate losses, AGM notices...)."""
    text = f"{a.get('desc', '')} {a.get('attchmntText', '')}".strip()
    return bool(text) and not SKIP_DESC.search(a.get("desc") or "")


def filing_nlp(anns, scores, hedge, confident, now=None):
    """anns: NSE announcement dicts for ONE stock; scores: {seq_id: FinBERT score}. 90-day window, 30-day half-life.
    -> {tone, hedge, n} or None. tone = sum(w*s)/(sum(w)+1) (shrunk towards 0 when there is little to go on)."""
    now = now or now_utc()
    num = den = 0.0
    texts, n = [], 0
    for a in anns:
        ts = parse_ts(a.get("an_dt") or a.get("sort_date") or "")
        sid = str(a.get("seq_id"))
        if ts is None or sid not in scores or not usable(a):
            continue
        age = (now - ts).total_seconds() / 86400
        if age < 0 or age > WINDOW_DAYS:
            continue
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        num, den, n = num + w * scores[sid], den + w, n + 1
        texts.append(f"{a.get('desc', '')}. {a.get('attchmntText', '')}")
    if not n:
        return None
    return {"tone": round(num / (den + 1), 3), "hedge": hedging_ratio(" ".join(texts), hedge, confident), "n": n}


def nlp_z(per_stock):
    """Cross-sectional standardisation of the filing tone (and, when present, minus hedging) into the z-like units the F score expects."""
    syms = [s for s, v in per_stock.items() if v and v.get("tone") is not None]
    if len(syms) < 10:
        return {}
    tone = pd.Series({s: per_stock[s]["tone"] for s in syms})
    hedge = pd.Series({s: per_stock[s]["hedge"] for s in syms if per_stock[s].get("hedge") is not None})
    qa = pd.Series({s: per_stock[s]["qa"] for s in syms if per_stock[s].get("qa") is not None})
    def z(sr):
        sd = sr.std()
        return (sr - sr.mean()) / sd if sd and sd > 0 else sr * 0
    parts = [z(tone)]
    out = {}
    zt, zh, zq = z(tone), (-z(hedge) if len(hedge) >= 10 else pd.Series(dtype=float)), (z(qa) if len(qa) >= 10 else pd.Series(dtype=float))
    for s in syms:
        vals = [zt[s]] + ([zh[s]] if s in zh.index else []) + ([zq[s]] if s in zq.index else [])
        out[s] = round(float(np.clip(np.mean(vals), -3, 3)), 3)
    return out


# ------------------------------------------------------------------ delivery % and deals

def delivery_trend(series_by_day, short=20, long=120):
    """series_by_day: list of delivery % values oldest -> newest for one stock. -> avg(last 20) / avg(last 120) - 1, or None if < 60 days."""
    v = [x for x in series_by_day if x is not None and x == x]
    if len(v) < 60:
        return None
    s, l = statistics.fmean(v[-short:]), statistics.fmean(v[-long:])
    return round(s / l - 1, 4) if l > 0 else None


def load_delivery(bhav_dir=TERM / "bhav"):
    """{sym: [delivery % per saved day, oldest first]} from the bhavcopy files (EQ series only)."""
    out = {}
    for f in sorted(Path(bhav_dir).glob("*.csv.gz")):
        try:
            df = pd.read_csv(gzip.open(f))
        except (OSError, ValueError):
            continue
        df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
        for sym, d in zip(df["SYMBOL"], pd.to_numeric(df["DELIV_PER"], errors="coerce")):
            out.setdefault(sym, []).append(None if d != d else float(d))
    return out


def parse_deals(text, kind):
    """NSE bulk.csv / block.csv text -> list of (date 'YYYY-MM-DD', symbol, side 'BUY'|'SELL', quantity, price)."""
    rows = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        try:
            d = datetime.strptime(r["Date"], "%d-%b-%Y").strftime("%Y-%m-%d")
            q = float(r["Quantity Traded"].replace(",", ""))
            px = float([v for k, v in r.items() if k.startswith("Trade Price")][0].replace(",", ""))
        except (KeyError, ValueError, IndexError):
            continue
        side = r.get("Buy/Sell", "").upper()
        if side in ("BUY", "SELL") and r.get("Symbol"):
            rows.append((d, r["Symbol"], side, q, px))
    return rows


def save_deals(deals_dir, today_rows):
    """Keep one JSON file per trading day (the NSE files only ever hold the latest day)."""
    deals_dir.mkdir(parents=True, exist_ok=True)
    by = {}
    for d, sym, side, q, px in today_rows:
        by.setdefault(d, []).append([sym, side, q, px])
    for d, rows in by.items():
        (deals_dir / f"{d}.json").write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")


def net_deal_value(deals_dir, days=30, today=None):
    """{sym: net value in Rs crore over the last `days` calendar days} from the saved daily copies (incoming minus outgoing deals)."""
    today = today or now_utc().date()
    out = {}
    for f in Path(deals_dir).glob("*.json"):
        try:
            d = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - d).days > days or d > today:
            continue
        for sym, side, q, px in json.loads(f.read_text(encoding="utf-8")):
            out[sym] = out.get(sym, 0.0) + (1 if side == "BUY" else -1) * q * px / 1e7
    return {s: round(v, 2) for s, v in out.items()}


def fetch_deals(get):
    rows = []
    for kind in ("bulk", "block"):
        raw = get(f"https://archives.nseindia.com/content/equities/{kind}.csv")
        if raw:
            rows += parse_deals(raw, kind)
    return rows


# ------------------------------------------------------------------ NSE announcements and transcripts

def fetch_announcements(session, sym, days=WINDOW_DAYS, today=None):
    today = today or now_utc().date()
    fmt = lambda d: d.strftime("%d-%m-%Y")
    try:
        j = session.get_json(ANN_URL, {"index": "equities", "symbol": sym, "from_date": fmt(today - timedelta(days=days)), "to_date": fmt(today)}, referer=ANN_REFERER, max_tries=2)
    except Exception:
        return None
    return j if isinstance(j, list) else None


def pdf_text(raw):
    try:
        import pypdf
        r = pypdf.PdfReader(io.BytesIO(raw))
        return "\n".join((p.extract_text() or "") for p in r.pages[:60])
    except Exception:
        return None


def find_transcripts(anns):
    return [a for a in anns if a.get("attchmntFile") and re.search(r"transcript", f"{a.get('desc', '')} {a.get('attchmntText', '')}", re.I)]


# ------------------------------------------------------------------ driver

def load_alt():
    return load_json(OUT, {}).get("stocks", {})


def run(symbols, use_nse=True, transcripts=True, now=None, session=None, scorer=None, http_get=None):
    """-> alt_scores document. `scorer(list[str]) -> list[float]` defaults to FinBERT; session defaults to the daemon's NseSession."""
    now = now or now_utc()
    tone = load_json(TONE, {"hedge": [], "confident": []})
    hedge, confident = set(tone.get("hedge", [])), set(tone.get("confident", []))
    old = load_alt()
    prev = {s: v for s, v in old.items()}
    notes, per = [], {}
    cache_p = CACHE / "filings_scores.json"
    scache = load_json(cache_p, {})
    tcache = load_json(CACHE / "transcripts.json", {})
    if use_nse:
        if session is None:
            import aladin_ticker_daemon as d
            session = d.NseSession()
        if scorer is None:
            import aladin_sentiment_engine as se
            scorer = se.Finbert.get().score
        fails = 0
        done_transcripts = 0
        for i, sym in enumerate(symbols):
            anns = fetch_announcements(session, sym, today=now.date())
            if anns is None:
                fails += 1
                if fails >= 10 and fails == i + 1:
                    notes.append("NSE corporate announcements were unreachable from here (the first 10 requests failed): filing text is not measured this run.")
                    break
                continue
            fails = 0
            new = [a for a in anns if usable(a) and str(a.get("seq_id")) not in scache and parse_ts(a.get("an_dt") or "") and (now - parse_ts(a["an_dt"])).days <= WINDOW_DAYS]
            if new:
                for a, s in zip(new, scorer([f"{a.get('desc', '')}. {a.get('attchmntText', '')}"[:600] for a in new])):
                    scache[str(a["seq_id"])] = s
            r = filing_nlp(anns, scache, hedge, confident, now)
            if r:
                per[sym] = r
            if transcripts and done_transcripts < TRANSCRIPT_CAP:
                for t in find_transcripts(anns)[:1]:
                    url = t["attchmntFile"]
                    if url in tcache:
                        res = tcache[url]
                    else:
                        raw = (http_get or _download)(url)
                        txt = pdf_text(raw) if raw else None
                        import aladin_sentiment_engine as se
                        res = se.score_transcript(txt, sym, cache=tcache, key=url) if txt else None
                        done_transcripts += 1
                    if res and res.get("qa_gap") is not None and sym in per:
                        per[sym]["qa"], per[sym]["src"] = res["qa_gap"], url
        scache = {k: v for k, v in scache.items()}
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps(scache, separators=(",", ":")), encoding="utf-8")
        (CACHE / "transcripts.json").write_text(json.dumps(tcache, separators=(",", ":")), encoding="utf-8")
        for s, r in list(per.items()):
            prev_s = prev.get(s, {})
            prev_s["nlp"] = r
            prev[s] = prev_s
        zs = nlp_z({s: v.get("nlp") for s, v in prev.items()})
        for s in prev:
            if s in zs:
                prev[s]["nlp_z"] = zs[s]
    # alt data
    deliv = load_delivery()
    for s, series in deliv.items():
        tr = delivery_trend(series)
        if tr is not None:
            prev.setdefault(s, {}).setdefault("alt", {})["deliv"] = tr
    deals_dir = CACHE / "deals"
    get = http_get or _download_text
    rows = fetch_deals(get) if use_nse else []
    if rows:
        save_deals(deals_dir, rows)
    elif use_nse:
        notes.append("Bulk/block deal files could not be fetched today.")
    nets = net_deal_value(deals_dir, 30, now.date())
    for s, v in nets.items():
        prev.setdefault(s, {}).setdefault("alt", {})["bulk_cr"] = v
    notes.append(f"Bulk/block history: {len(list(deals_dir.glob('*.json'))) if deals_dir.exists() else 0} day(s) saved so far; the 30-day net value builds up from the first run.")
    return {"generated_utc": now.isoformat(timespec="seconds"), "notes": notes, "stocks": prev}


def _download(url):
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
        return r.content if r.status_code == 200 else None
    except requests.RequestException:
        return None


def _download_text(url):
    raw = _download(url)
    return raw.decode("utf-8", "replace") if raw else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--alt-only", action="store_true")
    ap.add_argument("--no-transcripts", action="store_true")
    a = ap.parse_args(argv)
    import aladin_env
    aladin_env.announce("aladin_filings")
    uni = json.loads((TERM / "universe.json").read_text(encoding="utf-8"))["stocks"]
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()] or [s["s"] for s in sorted((x for x in uni if x.get("n500")), key=lambda x: -(x.get("avgv20") or 0) * (x.get("c") or 0))]
    doc = run(syms, use_nse=not a.alt_only, transcripts=not a.no_transcripts)
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    nn = sum(1 for v in doc["stocks"].values() if v.get("nlp"))
    nd = sum(1 for v in doc["stocks"].values() if (v.get("alt") or {}).get("deliv") is not None)
    print(f"filings: {nn} stocks with filing text scored, {nd} with a delivery trend; notes: {doc['notes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
