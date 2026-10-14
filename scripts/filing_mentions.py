"""
Which listed companies each company's own filings NAME, read by code (no language model, so it is not limited by free quota).
One input of the NEXUS link-prediction model (scripts/nexus_predict.py); a mention is evidence of some relationship, never
proof of a revenue link, and the page shows it as "named on page N of <company>'s annual report", with the sentence.

  1. every filing already downloaded by the graph builder (data/nexus_cache/text) is scanned;
  2. then the latest annual report of companies not read yet is downloaded from NSE (<= --limit per run, resumes),
     scanned in memory and thrown away: only the mentions are kept, so the Actions cache does not grow by gigabytes.

Name matching (precision first): a company's cleaned name (no "Limited", "Ltd"...) of two or more words, longest match
first so "Bank of India" is not found inside "State Bank of India"; a one-word name only when written "<Name> Limited/Ltd".
SME-board names and ETFs are not matched; a name shared by two securities is dropped.

  python scripts/filing_mentions.py [--limit 150] [--no-download]   -> data/nexus_predict/mentions.json
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "data" / "terminal" / "universe.json"
CACHE = ROOT / "data" / "nexus_cache"
GRAPH = ROOT / "data" / "supply_graph.json"
OUT = ROOT / "data" / "nexus_predict" / "mentions.json"
SRC = ROOT / "data" / "config" / "nexus_sources.json"
SUFFIX = {"limited", "ltd", "pvt", "private", "public", "inc", "corp", "corporation", "company", "co", "llp", "plc", "the"}
LTD = {"limited", "ltd"}
MAX_N, SNIP = 7, 220
SUPPLY = re.compile(r"\b(suppl\w*|purchas\w*|procur\w*|sourc\w*|vendors?|customers?|clients?|buyers?|sold|sells?|sales?|orders?|"
                    r"contracts?|offtake|power purchase|deliver\w*|distribut\w*|dealers?|raw material)\b", re.I)
AR_SYM = re.compile(r"/AR_\d+_([A-Z0-9&-]+?)_\d{4}_\d{4}_")
CODE_SYM = re.compile(r"(?:NSE\s*(?:Code|Symbol|Scrip(?:\s*Code)?)|Trading\s*Symbol|Symbol)\s*[:\-–]?\s*([A-Z][A-Z0-9&-]{1,19})\b")
TOK = re.compile(r"[a-z0-9]+|&")
RAW = re.compile(r"[A-Za-z0-9]+|&")
SMALL = {"of", "and", "the", "for", "in", "&"}
# institutions whose names contain a listed company's name ("Reserve Bank of India" is not Bank of India): consumed, never matched
STOP = ["reserve bank of india", "small industries development bank of india", "export import bank of india", "exim bank of india",
        "national stock exchange of india", "securities and exchange board of india", "insurance regulatory and development authority of india",
        "national housing bank", "national bank for agriculture and rural development", "state bank of india"]
# pages about directors and governance name other companies because of shared directors, not business
BOARD_PAGE = re.compile(r"(?-i:\bDIN\b)|directorships?|independent director|listed entities from which|chairperson of the committee|membership of the committee|"
                        r"registrar and (?:share )?transfer agent|names? of (?:the )?(?:other )?(?:listed )?(?:companies|entities)", re.I)
UBIQUITOUS = 0.15        # a company named in more than this share of the filings read (depositories, registrars, exchanges) is service boilerplate


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def toks(s):
    return TOK.findall((s or "").lower())


class Matcher:
    """Cleaned company names -> symbol, matched on the token stream of a page."""

    def __init__(self, stocks):
        seen = {}
        for s in stocks:
            if s.get("etf") or s.get("board") == "SME" or s.get("series") in ("SM", "ST"):
                continue
            t = [w for w in toks(s.get("n")) if w not in SUFFIX]
            if not t:
                continue
            keys = [tuple(t)] if len(t) >= 2 else [(t[0], "limited"), (t[0], "ltd")] if len(t[0]) >= 4 else []
            for k in keys:
                seen.setdefault(k, set()).add(s["s"])
        self.names = {k: v.pop() for k, v in seen.items() if len(v) == 1}
        sbin = self.names.get(tuple(toks("state bank of india")))
        for p in STOP:
            self.names[tuple(toks(p))] = sbin if p == "state bank of india" else None
        self.first = {}
        for k in self.names:
            self.first.setdefault(k[0], set()).add(len(k))

    def find(self, text):
        """-> {symbol: count} for one page; longest name wins at each position, matched tokens are not reused."""
        raw = RAW.findall(text or "")
        t, out, i = [w.lower() for w in raw], {}, 0
        while i < len(t):
            hit = None
            for n in sorted(self.first.get(t[i], ()), reverse=True):
                k = tuple(t[i:i + n])
                if k in self.names and all(w[0].isupper() or w[0].isdigit() or w.lower() in SMALL for w in raw[i:i + n]):
                    hit = (self.names[k], n)          # written as a name ("Prime Focus"), not as words ("a prime focus")
                    break
            if hit:
                if hit[0]:
                    out[hit[0]] = out.get(hit[0], 0) + 1
                i += hit[1]
            else:
                i += 1
        return out


def snippet(text, name):
    """The sentence of `text` that names the company (by the words of its name), trimmed; prefers one with supply words."""
    words = [w for w in toks(name) if w not in SUFFIX] or toks(name)
    rx = re.compile(r"\b" + r"\W+".join(re.escape(w) for w in words) + r"\b", re.I)
    best = None
    for m in rx.finditer(text or ""):
        a = max(text.rfind(".", 0, m.start()), text.rfind("\n\n", 0, m.start())) + 1
        b = text.find(".", m.end())
        s = re.sub(r"\s+", " ", text[a:b + 1 if b > 0 else len(text)]).strip()
        if len(s) > SNIP:
            c = max(0, m.start() - a - SNIP // 2)
            s = "…" + re.sub(r"\s+", " ", text[a:][c:c + SNIP]).strip() + "…"
        if SUPPLY.search(s):
            return s, True
        best = best or s
    return best, False


def scan(owner, pages, matcher, names, doc):
    """-> {other: {n, sup, pg, q, url, kind, per}} for one filing of `owner`."""
    found = {}
    for pg, text in pages:
        if BOARD_PAGE.search(text or ""):
            continue
        for sym, n in matcher.find(text).items():
            if sym == owner:
                continue
            r = found.setdefault(sym, {"n": 0, "sup": 0, "pg": [], "q": None, **doc})
            r["n"] += n
            if len(r["pg"]) < 3:
                r["pg"].append(pg)
            q, sup = snippet(text, names.get(sym, sym))
            r["sup"] += int(sup)
            if q and (r["q"] is None or (sup and not r.get("_qs"))):
                r["q"], r["_qs"] = q, sup
    for r in found.values():
        r.pop("_qs", None)
    return found


def owner_of(url, pages, by_url, symbols):
    m = AR_SYM.search(url)
    if m and m.group(1) in symbols:
        return m.group(1)
    if url in by_url:
        return by_url[url]
    for _, text in pages[:2]:
        for m in CODE_SYM.finditer(text or ""):
            if m.group(1) in symbols:
                return m.group(1)
    return None


def merge(out, owner, found):
    dst = out.setdefault(owner, {})
    for sym, r in found.items():
        old = dst.get(sym)
        if not old:
            dst[sym] = r
            continue
        old["n"] += r["n"]
        old["sup"] += r["sup"]
        if r["sup"] and not SUPPLY.search(old.get("q") or ""):
            old.update(q=r["q"], pg=r["pg"], url=r["url"], kind=r["kind"], per=r["per"])


def scan_cached(matcher, names, symbols, log=print):
    """Filings the graph builder already downloaded."""
    urls = load(CACHE / "urls.json", {})
    g = load(GRAPH, {})
    by_url = {e["url"]: e["own"] for e in g.get("edges", []) if e.get("url") and e.get("own")}
    m, docs = {}, {}
    for url, sh in urls.items():
        pages = [tuple(x) for x in load(CACHE / "text" / f"{sh}.json", [])]
        own = owner_of(url, pages, by_url, symbols)
        if not own or not pages:
            continue
        kind = "annual" if "/annual_reports/" in url else "call or filing"
        merge(m, own, scan(own, pages, matcher, names, {"url": url, "kind": kind, "per": None}))
        docs.setdefault(own, []).append({"url": url, "kind": kind, "pages": len(pages)})
    log(f"cached filings: {len(urls)} read, {sum(len(v) for v in docs.values())} with a known owner, {len(docs)} companies")
    return m, docs


def download_new(todo, matcher, names, state, limit, log=print, session=None, get_pdf=None):
    """Latest annual report of companies not read yet; text is kept in memory only."""
    from revenue_graph_builder import MAX_PDF_MB, UA, pdf_pages
    src = load(SRC, {})
    ep = src["endpoints"]["annual_reports"]
    if session is None:
        from aladin_ticker_daemon import NseSession
        session = NseSession(rate_per_s=1.0)
    if get_pdf is None:
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/pdf,*/*"})

        def get_pdf(url):
            r = s.get(url, timeout=90, stream=True)
            r.raise_for_status()
            raw = b""
            for part in r.iter_content(1 << 16):
                raw += part
                if len(raw) > MAX_PDF_MB << 20:
                    return None
            return raw
    done = 0
    for sym in todo:
        if done >= limit:
            break
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            js = session.get_json(ep["path"], {**ep["params"], "symbol": sym}, referer="https://www.nseindia.com" + ep["referer"])
            rows = [r for r in (js.get("data") if isinstance(js, dict) else js) or [] if str(r.get("fileName", "")).lower().endswith(".pdf")]
        except Exception as e:  # noqa: BLE001 - a failed call is retried next run, never recorded as "no report"
            log(f"  {sym}: list failed ({str(e)[:60]}); retried next run")
            continue
        done += 1
        if not rows:
            state["done"][sym] = {"at": today, "none": "NSE lists no annual report"}
            continue
        rows.sort(key=lambda r: str(r.get("toYr", "")), reverse=True)
        r = rows[0]
        url, per = r["fileName"], f"FY{r['fromYr']}-{str(r['toYr'])[-2:]}"
        try:
            raw = get_pdf(url)
            pages = pdf_pages(raw) if raw else []
        except Exception as e:  # noqa: BLE001
            log(f"  {sym}: download failed ({str(e)[:60]}); retried next run")
            continue
        if not pages:
            state["done"][sym] = {"at": today, "url": url, "none": "report too large or unreadable"}
            continue
        merge(state["m"], sym, scan(sym, pages, matcher, names, {"url": url, "kind": "annual", "per": per}))
        state["done"][sym] = {"at": today, "url": url, "per": per, "pages": len(pages)}
        log(f"  {sym}: {per}, {len(pages)} pages, names {len(state['m'].get(sym, {}))} listed companies")
        time.sleep(1.0)
    return done


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=150)
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args(argv)
    stocks = load(UNIVERSE, {}).get("stocks", [])
    if not stocks:
        print("mentions: no universe; nothing done")
        return 0
    matcher = Matcher(stocks)
    names = {s["s"]: s.get("n") or s["s"] for s in stocks}
    symbols = set(names)
    prev = load(OUT, {})
    state = {"m": {}, "done": prev.get("done", {})}
    # downloaded-only results are kept between runs; cached filings are re-scanned in full every run
    for own, rows in prev.get("m", {}).items():
        if own in state["done"] and state["done"][own].get("url"):
            keep = {k: v for k, v in rows.items() if v.get("url") == state["done"][own]["url"]}
            if keep:
                state["m"][own] = keep
    cm, docs = scan_cached(matcher, names, symbols)
    for own, rows in cm.items():
        merge(state["m"], own, rows)
    if not a.no_download:
        companies = [s["s"] for s in stocks if not s.get("etf") and s.get("series") in ("EQ", "BE", "BZ")]
        todo = [s for s in companies if s not in docs and s not in state["done"]]
        print(f"downloading: {len(todo)} companies not read yet; up to {a.limit} this run")
        download_new(todo, matcher, names, state, a.limit)
    read = set(docs) | {s for s, d in state["done"].items() if d.get("url") and not d.get("none")}
    named_by = {}
    for own, rows in state["m"].items():
        for sym in rows:
            named_by[sym] = named_by.get(sym, 0) + 1
    common = sorted(s for s, n in named_by.items() if len(read) >= 20 and n > UBIQUITOUS * len(read))
    for rows in state["m"].values():
        for sym in common:
            rows.pop(sym, None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"v": 1, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "read": sorted(read), "ubiquitous": common, "done": state["done"], "m": state["m"]},
                              separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    pairs = sum(len(v) for v in state["m"].values())
    print(f"mentions: {len(read)} companies' filings read; {pairs} company-names-company pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
