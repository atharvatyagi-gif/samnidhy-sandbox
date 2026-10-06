"""
NEXUS supply-chain graph builder.

Reads a listed company's latest annual report (and its latest earnings-call transcripts) from NSE's own filing archive, asks a free LLM
(Groq or Gemini) to copy out what the text says about customers, suppliers, plants and capacity, and then DOES NOT TRUST THE ANSWER:

  * every edge must carry a quote that is an exact substring (whitespace-normalised) of the page it names, otherwise the edge is dropped;
  * a share (w) is kept only if that number is written in the quote;
  * the confidence is a fixed rubric (quote verified 0.5, counterparty named 0.2, numeric share stated 0.2, period <= 18 months old 0.1);
    the model's own confidence is never used and nothing comes from the model's general knowledge;
  * a counterparty becomes a listed company only on a unique fuzzy-name match (>= 92); anonymised customers are linked to a ticker only
    with evidence from the counterparty's own filing (and stay "ANON_..." otherwise).

Edge direction: s = supplier, d = customer, always. w_basis "revenue" = share of the SUPPLIER's revenue that this customer is;
"purchases" = share of the CUSTOMER's purchases that this supplier is. The two are never mixed in one number.
`tier` is 1 for edges read from the focal company's own filing; deeper tiers are built by following listed counterparties' own edges (done in the UI).

    python scripts/revenue_graph_builder.py [--symbols A,B] [--limit 40] [--refresh] [--dry-run]

The output data/supply_graph.json is also the store: it remembers which companies were done and when, so every run resumes where the last stopped.
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

TERM = ROOT / "data" / "terminal"
CACHE = ROOT / "data" / "nexus_cache"
OUT = ROOT / "data" / "supply_graph.json"
SRC = ROOT / "data" / "config" / "nexus_sources.json"
CFG = ROOT / "data" / "config" / "aladin_config.json"
UA = "B-Lab-Desk/1.0 (student research; educational use)"
NAME_MIN = 92
MAX_PDF_MB = 60


PACE_S = 1.5                                               # seconds between companies: NSE's site blocks bursts


def now_utc():
    return datetime.now(timezone.utc)


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_cfg():
    base = {"min_conf": 0.5, "anon_resolve_min_conf": 0.75, "max_llm_calls_per_run": 120, "filings_per_run": 40, "max_tier": 3}
    base.update((load_json(CFG, {}) or {}).get("nexus", {}))
    return base


# ------------------------------------------------------------------ text helpers

def norm(s):
    """Whitespace-normalised, Unicode-folded text, used only to compare a quote with its page."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


def pdf_pages(raw):
    """-> [(page_no, text)], 1-based. Pages that cannot be read are skipped."""
    import logging
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    out = []
    for i, pg in enumerate(PdfReader(io.BytesIO(raw)).pages, 1):
        try:
            out.append((i, pg.extract_text() or ""))
        except Exception:  # noqa: BLE001 - one bad page must not lose the filing
            continue
    return out


def select_pages(pages, keywords, min_hits=2, max_pages=24, char_budget=None, bonus=None):
    """Pages that mention at least `min_hits` of the topic keywords. The best-scoring ones are kept first, up to `max_pages` and `char_budget`
    characters in total (what the run can afford to send), and are returned in page order.
    `bonus` = [{"re", "w"}]: pages that state a share of revenue or purchases, name the biggest counterparties or hold a related-party table score higher than pages
    that merely repeat words like plant, raw material or value chain (sustainability chapters), so the few pages that can hold an edge are the ones sent."""
    rx = [(re.compile(b["re"], re.I), b["w"]) for b in (bonus or [])]
    scored = []
    for no, text in pages:
        low = text.lower()
        hits = sum(1 for k in keywords if k in low)
        if hits >= min_hits:
            scored.append((hits + sum(w for r, w in rx if r.search(low)), no, text))
    scored.sort(key=lambda t: (-t[0], t[1]))
    keep, used = [], 0
    for item in scored[:max_pages]:
        if char_budget is not None and keep and used + len(item[2]) > char_budget:
            continue
        keep.append(item)
        used += len(item[2])
    keep.sort(key=lambda t: t[1])
    return [(no, text) for _, no, text in keep]


def chunk_pages(pages, max_chars=18000):
    """Groups consecutive selected pages into prompts of at most max_chars, every page introduced by [[PAGE n]]."""
    chunks, cur, size = [], [], 0
    for no, text in pages:
        block = f"[[PAGE {no}]]\n{text.strip()}\n"
        if cur and size + len(block) > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append((no, text, block[:max_chars]))
        size += len(block)
    if cur:
        chunks.append(cur)
    return [("".join(b for _, _, b in c), {no: t for no, t, _ in c}) for c in chunks]


# ------------------------------------------------------------------ confidence rubric

def period_end(period):
    """'FY2024-25' / 'FY 2024-25' / 'FY25' / 'year ended March 31, 2025' -> a date, else None."""
    if not period:
        return None
    p = period.upper()
    m = re.search(r"FY\s*(\d{4})\s*[-/]\s*(\d{2,4})", p)
    if m:
        y2 = m.group(2)
        yr = int(y2) if len(y2) == 4 else int(m.group(1)[:2] + y2)
        return datetime(yr, 3, 31, tzinfo=timezone.utc)
    m = re.search(r"FY\s*(\d{2})\b", p)
    if m:
        return datetime(2000 + int(m.group(1)), 3, 31, tzinfo=timezone.utc)
    m = re.search(r"MARCH\s+31,?\s+(\d{4})", p)
    if m:
        return datetime(int(m.group(1)), 3, 31, tzinfo=timezone.utc)
    m = re.search(r"\b(20\d{2})\b", p)
    if m:
        return datetime(int(m.group(1)), 12, 31, tzinfo=timezone.utc)
    return None


def edge_conf(quote_ok, named, share_stated, period, now):
    c = 0.5 if quote_ok else 0.0
    c += 0.2 if named else 0.0
    c += 0.2 if share_stated else 0.0
    pe = period_end(period)
    if pe and (now - pe) <= timedelta(days=548):
        c += 0.1
    return round(c, 2)


def numbers_in(text):
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", text or "") if x.replace(",", "").replace(".", "", 1).isdigit()]


def share_in_quote(w, quote):
    """True when the share, written as a percentage, appears in the quote (24% -> 24 or 24.0)."""
    if w is None:
        return False
    pct = round(w * 100, 2)
    return any(abs(n - pct) <= 0.051 for n in numbers_in(quote))


# ------------------------------------------------------------------ validation of one LLM answer

# A dependency is on ONE company. "key suppliers", "MSMEs / small producers", "supply chain partners", "large mining OEMs" are groups: the share
# they carry is a share of a category, so such edges are rejected (a single anonymised "Customer A" / "a leading semiconductor player" is fine).
GROUP_WORDS = re.compile(r"\b(suppliers|vendors|partners|clients|customers|producers|msmes?|oems|players|sources|distributors|dealers|retailers|farmers|"
                         r"contractors|manufacturers|sellers|companies|firms|brands|institutions|banks|governments|utilities|agencies|operators|"
                         r"tier[- ]?\d|small|key|parent|holding|subsidiar(?:y|ies)|associates?|promoters?|group|affiliates?)\b", re.I)

# What an edge's own quote must NOT be. Three kinds of sentence were being read as supply relationships:
#  * deals that are not supply: an acquisition, merger, stake or joint venture (kept only when the same sentence also says goods or services are sold or bought);
#  * things that are not a transaction or have not happened: an award or recognition, "we are in discussions to supply", "expecting new bids", "plan to", "likely to" (dropped even when the sentence also says supply);
#  * a descriptor instead of a company: "a major customer based in USA", "our largest supplier" (these are ANONYMOUS counterparties, never named ones).
NOT_SUPPLY = re.compile(r"\b(acqui\w+|merger|amalgamat\w+|joint venture|investment in|invested in|stake in|subscri\w+)\b", re.I)
SUPPLY_WORDS = re.compile(r"\b(suppl\w+|purchas\w+|procur\w+|vendors?|customers?|sold|sells?|sales?|revenue|orders?|PPAs?|power purchase)\b", re.I)
NOT_YET = re.compile(r"\b(awards?|awarded|recogni\w+|in discussions?|in talks|expecting|expect to|plan(?:s|ning)? to|proposed|intend(?:s|ed)? to|looking to|aims? to|exploring|likely to|bids?|bidding)\b", re.I)
GENERIC_NAME = re.compile(r"^\s*(?:(?:a|an|one|the|our|its|this|that)\s+)?(?:(?:major|largest|top|key|single|biggest|principal|leading|large|important|main|primary|significant|anchor)\s+)?"
                          r"(?:\w+\s+){0,2}?(customer|client|supplier|vendor|distributor|buyer|counterparty|licensee|licensor)\b", re.I)


def supply_quote_ok(quote):
    """False for a sentence that is not a statement of an existing supply relationship (see NOT_SUPPLY / NOT_YET)."""
    if NOT_YET.search(quote or ""):
        return False
    return not (NOT_SUPPLY.search(quote or "") and not SUPPLY_WORDS.search(quote or ""))


def is_generic_name(name):
    return bool(name) and bool(GENERIC_NAME.match(name.strip())) and not re.search(r"\b(limited|ltd|inc|corp|llc|gmbh|ag|plc|pvt|private)\b", name, re.I)


def validate_answer(raw, pages_by_no, meta, now, schema):
    """raw: parsed JSON from the model. -> (edges, facilities, dropped: list[str]). Never raises on bad content."""
    import jsonschema
    edges, facs, dropped = [], [], []
    if not isinstance(raw, dict):
        return edges, facs, ["answer is not an object"]
    validator = jsonschema.Draft202012Validator(schema)
    # validate item by item so one bad item cannot cost the others
    for kind, bucket in (("edges", edges), ("facilities", facs)):
        items = raw.get(kind) or []
        sub = schema["properties"][kind]["items"]
        for it in items if isinstance(items, list) else []:
            errs = list(jsonschema.Draft202012Validator(sub).iter_errors(it))
            if errs:
                dropped.append(f"{kind[:-1]} fails schema: {errs[0].message[:80]}")
                continue
            bucket.append(it)
    del validator
    all_text = {no: norm(t) for no, t in pages_by_no.items()}

    def locate(quote, page):
        q = norm(quote)
        if q and page in all_text and q in all_text[page]:
            return page
        for no, t in all_text.items():                    # the page number is the model's claim too: search the chunk
            if q and q in t:
                return no
        return None

    good_e = []
    for e in edges:
        pg = locate(e["quote"], e["page"])
        if pg is None:
            dropped.append("edge quote is not in the source text")
            continue
        w = e.get("w")
        if w is not None and not share_in_quote(w, e["quote"]):
            w = None                                       # a number the text does not show is not kept
        if not supply_quote_ok(e["quote"]):
            dropped.append("quote is not a statement of an existing supply relationship (deal, award or something not yet happened)")
            continue
        if is_generic_name(e.get("counterparty_name")):           # "a major customer based in USA" is an anonymous customer, not a company called that
            e = {**e, "counterparty_anon_label": e.get("counterparty_anon_label") or e["counterparty_name"].strip(), "counterparty_name": None}
        named = bool((e.get("counterparty_name") or "").strip())
        anon = (e.get("counterparty_anon_label") or "").strip()
        if not named and not anon:
            dropped.append("edge names no counterparty")
            continue
        if GROUP_WORDS.search((e.get("counterparty_name") or "") + " " + (e.get("counterparty_anon_label") or "")):
            dropped.append("counterparty is a group, not one company")
            continue
        basis = e.get("w_basis") if w is not None else None
        if w is not None and basis not in ("revenue", "purchases"):
            w, basis = None, None
        good_e.append({
            "name": (e.get("counterparty_name") or "").strip() or None, "anon": anon or None, "direction": e["direction"], "rel": e["rel"],
            "w": round(w, 3) if w is not None else None, "wb": basis, "per": e.get("period") or meta.get("period"),
            "comp": e.get("component"), "pg": pg, "q": norm(e["quote"]),
            "conf": edge_conf(True, named, w is not None, e.get("period") or meta.get("period"), now),
            "url": meta["url"], "doc": meta["kind"],
        })
    good_f = []
    for f in facs:
        pg = locate(f["quote"], f["page"])
        if pg is None:
            dropped.append("facility quote is not in the source text")
            continue
        q = norm(f["quote"])
        cap = f.get("capacity") or {}
        cv = cap.get("value")
        if cv is not None and not any(abs(n - cv) < 1e-6 or abs(n - round(cv)) < 1e-6 for n in numbers_in(q)):
            cap = {"value": None, "unit": None}            # capacity must be written in the quote
        ut = f.get("utilisation_pct")
        if ut is not None and not any(abs(n - ut) <= 0.051 for n in numbers_in(q)):
            ut = None
        eq = [{"item": x["item"], "vendor": x.get("vendor"), "q": norm(x["quote"])} for x in f.get("equipment") or []
              if locate(x["quote"], f["page"]) is not None]
        good_f.append({"name": f["name"].strip(), "kind": f["kind"], "addr": (f.get("address_text") or "").strip() or None,
                       "cap": {"v": cap.get("value"), "u": cap.get("unit"), "q": q if cap.get("value") is not None else None},
                       "util": {"pct": ut, "per": f.get("period") or meta.get("period"), "q": q if ut is not None else None},
                       "prod": [p for p in f.get("products") or [] if isinstance(p, str)][:8], "eq": eq,
                       "url": meta["url"], "pg": pg, "q": q})
    return good_e, good_f, dropped


# ------------------------------------------------------------------ name resolution

_SUFFIX = re.compile(r"\b(limited|ltd|pvt|private|public|inc|corp|corporation|company|co|llp|plc|the)\b\.?", re.I)


def clean_name(s):
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", re.sub(r"[^\w& ]+", " ", s or ""))).strip().lower()


class NameIndex:
    def __init__(self, stocks, aliases=None):
        self.names = {}                                    # cleaned name -> symbol
        for s in stocks:
            if s.get("board") == "SME" or s.get("etf"):
                continue
            self.names.setdefault(clean_name(s.get("n", "")), s["s"])
        for sym, al in (aliases or {}).items():
            for a in al if isinstance(al, list) else []:
                self.names.setdefault(clean_name(a), sym)
        self.keys = [k for k in self.names if k]

    def resolve(self, name, exclude=None):
        """-> symbol of the one security the name matches at >= 92, else None."""
        from rapidfuzz import fuzz, process
        c = clean_name(name)
        if len(c) < 3:
            return None
        hits = process.extract(c, self.keys, scorer=fuzz.token_sort_ratio, limit=4, score_cutoff=NAME_MIN)
        syms = {self.names[h[0]] for h in hits}
        syms.discard(exclude)
        return syms.pop() if len(syms) == 1 else None


# ------------------------------------------------------------------ LLM

class LLMBudget(Exception):
    pass


class LLMBadRequest(Exception):
    """The provider refused this one request (too long, invalid JSON from the model...). Other chunks can still be tried."""


class LLM:
    """Free-tier models through their plain REST APIs (no SDK). `complete(system, user) -> str` is the only thing the builder uses.

    Candidates are tried in order and a model whose DAILY quota is used up is skipped for the rest of the run: Groq's free models each have their own
    daily token allowance (openai/gpt-oss-120b, then openai/gpt-oss-20b, then qwen), and Gemini is added when GEMINI_API_KEY is set. Override the
    first Groq model with GROQ_MODEL, the Gemini one with GEMINI_MODEL, the whole Groq list with GROQ_FALLBACK_MODELS (comma separated)."""

    def __init__(self, provider=None, max_calls=120, sleep=time.sleep, clock=time.monotonic):
        env = os.environ
        want = (provider or env.get("LLM_PROVIDER") or "auto").lower()
        self.cands = []
        # A second key (GROQ_API_KEY_1, GEMINI_API_KEY_1) has its OWN daily allowance, so its models are added after the first key's: candidate model "name#1" means "name, second key".
        for prov, base in (("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY")):
            keys = [("", base)] + [(f"#{i}", f"{base}_{i}") for i in (1, 2)]
            have = [(tag, name) for tag, name in keys if env.get(name)]
            if not (want in ("auto", prov) and have):
                continue
            if prov == "groq":
                first = env.get("GROQ_MODEL") or "openai/gpt-oss-120b"
                models = list(dict.fromkeys([first] + [m.strip() for m in (env.get("GROQ_FALLBACK_MODELS") or "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]))
            else:
                models = [env["GEMINI_MODEL"]] if env.get("GEMINI_MODEL") else ["gemini-flash-latest", "gemini-flash-lite-latest"]   # aliases: Google retires fixed names
            self.cands += [(prov, m + tag) for tag, _ in have for m in models]
        self.provider = self.cands[0][0] if self.cands else None
        self.model = self.cands[0][1] if self.cands else None
        self.calls, self.max_calls, self.sleep, self.clock = 0, max_calls, sleep, clock
        self.tokens = {}                                   # tokens the providers reported per model, for the run's cost report
        self.dead = set()                                  # candidates whose daily quota is used up (or that keep failing)
        self.fails = {}
        self._ready = {}                                   # per-candidate earliest next call (free-tier pacing: ~7,000 tokens a minute on Groq)

    @property
    def tag(self):
        live = [c for c in self.cands if c not in self.dead]
        return "%s:%s" % (live[0] if live else self.cands[0])

    def _call(self, cand, system, user):
        import requests
        prov, model = cand
        model, _, idx = model.partition("#")                           # "name#1" = the model on the second key
        keyname = ("GROQ_API_KEY" if prov == "groq" else "GEMINI_API_KEY") + (f"_{idx}" if idx else "")
        if prov == "groq":
            body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "max_completion_tokens": 3500,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"
            return requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=90, json=body,
                                 headers={"Authorization": "Bearer " + os.environ[keyname], "User-Agent": UA})
        return requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", timeout=90,
                             headers={"x-goog-api-key": os.environ[keyname], "User-Agent": UA},
                             json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
                                   "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})

    def complete(self, system, user):
        import requests
        if self.calls >= self.max_calls:
            raise LLMBudget(f"the run's limit of {self.max_calls} model calls is used up")
        for attempt in range(8):
            live = [c for c in self.cands if c not in self.dead]
            if not live:
                raise LLMBudget("the free daily quota is used up on every configured model; the run resumes tomorrow from where it stopped")
            cand = live[0]
            wait = self._ready.get(cand, 0.0) - self.clock()
            if wait > 0:
                self.sleep(wait)
            try:
                r = self._call(cand, system, user)
            except (requests.ConnectionError, requests.Timeout):          # a network blip: wait and try again
                self.sleep(min(60, 5 * 2 ** min(attempt, 4)))
                continue
            if r.status_code == 429:
                if "per day" in r.text.lower() or "(tpd)" in r.text.lower() or "daily" in r.text.lower():
                    self.dead.add(cand)                                    # this model's day is over: use the next one
                    continue
                self.sleep(min(90, float(r.headers.get("retry-after", 2 ** (attempt + 1)))))
                continue
            if r.status_code >= 500:
                self.fails[cand] = self.fails.get(cand, 0) + 1
                if self.fails[cand] >= 3:                                  # persistently overloaded: use the next model
                    self.dead.add(cand)
                self.sleep(min(30, 2 ** (attempt + 1)))
                continue
            if r.status_code in (400, 413):
                raise LLMBadRequest(f"{r.status_code}: {r.text[:160]}")
            r.raise_for_status()
            self.calls += 1                                   # only answered requests use up the budget; retries do not
            self.fails[cand] = 0
            js = r.json()
            used = (js.get("usage") or {}).get("total_tokens") or (js.get("usageMetadata") or {}).get("totalTokenCount") or 0
            self.tokens[cand[1]] = self.tokens.get(cand[1], 0) + used
            tpm, gap = (7000, 1.0) if cand[0] == "groq" else (200000, 6.5)
            self._ready[cand] = self.clock() + max(gap, used / tpm * 60.0)
            self.provider, self.model = cand
            if cand[0] == "groq":
                return js["choices"][0]["message"]["content"]
            return js["candidates"][0]["content"]["parts"][0]["text"]
        raise RuntimeError("model API unreachable or rate-limited after several tries; stopping this filing")


def parse_json_text(s):
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    try:
        return json.loads(s)
    except ValueError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


# ------------------------------------------------------------------ filings

class Fetcher:
    """Downloads filing PDFs politely (<= 1 request/s, timeout, size cap) and caches the extracted pages by content hash."""

    def __init__(self, cache=CACHE, sleep=time.sleep, clock=time.monotonic):
        import requests
        self.s, self.cache, self.sleep, self.clock, self._last = requests.Session(), Path(cache), sleep, clock, 0.0
        self.s.headers.update({"User-Agent": UA, "Accept": "application/pdf,*/*"})
        (self.cache / "text").mkdir(parents=True, exist_ok=True)
        self.urls = load_json(self.cache / "urls.json", {})

    def pages(self, url):
        """-> (sha, [(page, text)]) or (None, [])."""
        sh = self.urls.get(url)
        if sh and (self.cache / "text" / f"{sh}.json").exists():
            return sh, [tuple(x) for x in load_json(self.cache / "text" / f"{sh}.json", [])]
        gap = 1.0 - (self.clock() - self._last)
        if gap > 0:
            self.sleep(gap)
        self._last = self.clock()
        r = self.s.get(url, timeout=60, stream=True)
        r.raise_for_status()
        raw = b""
        for part in r.iter_content(1 << 16):
            raw += part
            if len(raw) > MAX_PDF_MB << 20:
                return None, []
        sh = sha(raw)
        pg = pdf_pages(raw)
        (self.cache / "text" / f"{sh}.json").write_text(json.dumps(pg), encoding="utf-8")
        self.urls[url] = sh
        (self.cache / "urls.json").write_text(json.dumps(self.urls), encoding="utf-8")
        return sh, pg


def discover(session, sym, src, now=None, get=None):
    """Latest annual report + latest earnings-call transcripts from NSE's own APIs -> [{kind,url,period,asof}]. Nothing is assumed: absent -> []."""
    now = now or now_utc()
    ep = src["endpoints"]
    base = "https://www.nseindia.com"
    docs = []
    try:
        js = (get or session.get_json)(ep["annual_reports"]["path"], {**ep["annual_reports"]["params"], "symbol": sym}, referer=base + ep["annual_reports"]["referer"])
        rows = [r for r in (js.get("data") if isinstance(js, dict) else js) or [] if str(r.get("fileName", "")).lower().endswith(".pdf")]
        rows.sort(key=lambda r: str(r.get("toYr", "")), reverse=True)
        if rows:
            r = rows[0]
            docs.append({"kind": "annual", "url": r["fileName"], "period": f"FY{r['fromYr']}-{str(r['toYr'])[-2:]}", "asof": f"{r['toYr']}-03-31"})
    except Exception as e:  # noqa: BLE001
        raise DiscoverError(f"annual-report list failed: {str(e)[:100]}") from e      # a failed call is NOT "no filing": the company must be retried, never recorded as empty
    try:
        frm = (now - timedelta(days=src["transcript_lookback_days"])).strftime("%d-%m-%Y")
        js = (get or session.get_json)(ep["announcements"]["path"], {**ep["announcements"]["params"], "symbol": sym, "from_date": frm, "to_date": now.strftime("%d-%m-%Y")},
                                       referer=base + ep["announcements"]["referer"])
        pat = re.compile(src["transcript_pattern"], re.I)
        notice = re.compile(src.get("transcript_notice_pattern", "intimation|schedule of|invitation"), re.I)
        cands = []
        for a in js if isinstance(js, list) else (js or {}).get("data", []):
            url = a.get("attchmntFile") or ""
            text = f"{a.get('desc', '')} {a.get('attchmntText', '')}"
            if url.lower().endswith(".pdf") and pat.search(text):
                try:
                    d = datetime.strptime(a.get("an_dt", "")[:11], "%d-%b-%Y").date().isoformat()
                except ValueError:
                    d = None
                rank = 2 if re.search("transcript", text, re.I) else 0 if notice.search(text) else 1      # a filing called a transcript first; scheduling notices last (they are only notices)
                cands.append((-rank, -(int(d.replace("-", "")) if d else 0), url, d))
        for _, _, url, d in sorted(cands)[: src.get("transcript_candidates", 5)]:
            docs.append({"kind": "transcript", "url": url, "period": f"call {d}" if d else None, "asof": d})
    except Exception:  # noqa: BLE001
        pass
    return docs


# ------------------------------------------------------------------ one company

def extract_filing(doc, fetcher, llm, src, now, llm_cache, log=print):
    """-> (edges, facilities, notes, answered). `answered` = number of chunks the model actually answered (0 means nothing was learned from this
    filing, so the company must not be recorded as done). LLM answers are cached per (filing hash, chunk hash, prompt version)."""
    sh, pages = fetcher.pages(doc["url"])
    if not pages:
        return [], [], [f"{doc['kind']}: no readable text"], 0
    if doc["kind"] == "transcript" and sum(len(t) for _, t in pages) < src.get("min_transcript_chars", 6000):
        return [], [], ["transcript: too short to be a transcript (a notice); skipped"], 0
    sel = select_pages(pages, src["keywords"], src["min_keyword_hits"], src["max_pages_per_filing"], src["max_chunks_per_filing"] * src["max_chunk_chars"], src.get("page_bonus"))
    chunks = chunk_pages(sel, src["max_chunk_chars"])[: src["max_chunks_per_filing"]]
    edges, facs, notes = [], [], [f"{doc['kind']}: {len(pages)} pages, {len(sel)} relevant, {len(chunks)} sent"]
    answered = 0
    for text, pmap in chunks:
        key = sha(f"{sh}|{sha(text)}|{src['prompt_version']}")
        cp = llm_cache / f"{key}.json"
        ans = load_json(cp) if cp.exists() else None
        if ans is None:
            try:
                raw = llm.complete(src["system_prompt"], f"Filing text follows.\n\n{text}")
            except LLMBadRequest as ex:
                notes.append(f"chunk refused by the model API ({str(ex)[:90]})")
                continue
            ans = parse_json_text(raw)
            if ans is None:
                notes.append("model answer was not JSON")
                continue
            cp.write_text(json.dumps(ans), encoding="utf-8")
        answered += 1
        e, f, dr = validate_answer(ans, pmap, {**doc, "period": doc.get("period")}, now, src["schema"])
        edges += e
        facs += f
        notes += dr
    return edges, facs, notes, answered


def to_graph_edges(owner, items, index):
    """Turns validated edges of company `owner` into (s, d, ...) rows with resolved or external/anon node ids."""
    out = []
    for e in items:
        sym = index.resolve(e["name"], exclude=owner) if e["name"] else None
        if e["name"]:
            cp = sym or "EXT_" + re.sub(r"[^A-Z0-9]+", "_", clean_name(e["name"]).upper()).strip("_")
        else:
            cp = "ANON_%s_%s" % (owner, re.sub(r"[^A-Z0-9]+", "_", e["anon"].upper()).strip("_"))
        s, d = (owner, cp) if e["direction"] == "customer" else (cp, owner)
        out.append({"own": owner, "s": s, "d": d, "rel": e["rel"], "w": e["w"], "wb": e["wb"], "per": e["per"], "tier": 1, "comp": e["comp"],
                    "conf": e["conf"], "kind": "disclosed", "url": e["url"], "pg": e["pg"], "q": e["q"], "vq": True, "doc": e["doc"],
                    "cpn": e["name"] or e["anon"], **({"wd": e["wd"], "calc": e["calc"]} if e.get("wd") else {})})       # a derived share carries its two numbers (related_party_shares.py)
    return out


def resolve_anon(edges, min_conf=0.75):
    """Links ANON_<owner>_<label> to a listed company only with evidence: that company's own filing names <owner> as its supplier
    in the same period, and exactly one company does. Anything else stays unresolved. -> {anon_id: {resolved_to, conf, evidence}}."""
    res = {}
    anons = {}
    for e in edges:
        for end in (e["s"], e["d"]):
            if end.startswith("ANON_"):
                anons.setdefault(end, e)
    for aid, e in anons.items():
        owner = e["own"]
        cands = {}
        for x in edges:
            if x["s"] == owner and x["own"] != owner and x["own"] == x["d"] and x["per"] == e["per"] and x["conf"] >= 0.7 and not x["d"].startswith(("ANON_", "EXT_")):
                cands.setdefault(x["d"], x)
        if len(cands) == 1:
            sym, ev = next(iter(cands.items()))
            conf = 0.8
            res[aid] = {"resolved_to": sym if conf >= min_conf else None, "conf": conf, "evidence": [{"url": ev["url"], "pg": ev["pg"], "q": ev["q"]}]}
        else:
            res[aid] = {"resolved_to": None, "conf": 0.0, "evidence": []}
    return res


# ------------------------------------------------------------------ assembling the document

def clean_saved_edge(e):
    """The checks of validate_answer applied to an edge that is already in the graph: None = drop it; a descriptor saved as an external company becomes an anonymous customer."""
    if not supply_quote_ok(e.get("q", "")):
        return None
    if e.get("wd") == "derived" and (e.get("w") or 0) < 0.0005:           # rounding noise (related_party_shares.MIN_SHARE)
        return None
    if e.get("cpn") and is_generic_name(e["cpn"]) and not e["s"].startswith("ANON_") and not e["d"].startswith("ANON_"):
        cp = e["d"] if e["own"] == e["s"] else e["s"]
        if cp.startswith("EXT_"):
            aid = "ANON_%s_%s" % (e["own"], re.sub(r"[^A-Z0-9]+", "_", e["cpn"].upper()).strip("_"))
            e = {**e, "s": aid if e["s"] == cp else e["s"], "d": aid if e["d"] == cp else e["d"]}
    return e


def assemble(old, owner_results, stocks, houses, anon_min=0.75, now=None):
    """old: previous document; owner_results: {sym: {"edges":[...], "fac":[...], "at": iso, "notes": [...]}} replaces those owners' records."""
    now = now or now_utc()
    edges = [e for e in (old or {}).get("edges", []) if e["own"] not in owner_results]
    facs = {k: v for k, v in (old or {}).get("fac", {}).items() if v["co"] not in owner_results}
    cos = dict((old or {}).get("cos", {}))
    for sym, r in owner_results.items():
        edges += r["edges"]
        for f in r["fac"]:
            fid = "FAC_%s_%s" % (sym, sha(f["name"].lower())[:8])
            facs[fid] = {"co": sym, "n": f["name"], "kind": f["kind"], "addr": f["addr"], "cap": f["cap"], "util": f["util"], "prod": f["prod"], "eq": f["eq"],
                         "url": f["url"], "pg": f["pg"], "q": f["q"], "lat": None, "lon": None, "geo_prec": None}
        cos[sym] = {"at": r["at"], "edges": len(r["edges"]), "fac": len(r["fac"]), "notes": r["notes"][:6]}
    edges = [x for x in (clean_saved_edge(e) for e in edges) if x is not None]
    # dedupe: same pair/relation/period/component keeps the stronger record
    best = {}
    for e in edges:
        k = (e["s"], e["d"], e["rel"], e["per"], e["comp"], e["own"])
        if k not in best or e["conf"] > best[k]["conf"]:
            best[k] = e
    edges = sorted(best.values(), key=lambda e: (e["own"], e["s"], e["d"], e["rel"], str(e["per"])))
    anon = resolve_anon(edges, anon_min)
    for i, e in enumerate(edges, 1):
        e["id"] = f"e{i}"
    by_sym = {s["s"]: s for s in stocks}
    house_of = {}
    for h in houses:
        for sym in h.get("symbols", []):
            house_of.setdefault(sym, h["id"])
    nodes = {}
    for e in edges:
        for nid in (e["s"], e["d"]):
            if nid in nodes:
                continue
            if nid in by_sym:
                u = by_sym[nid]
                nodes[nid] = {"id": nid, "k": "co", "n": u.get("n"), "sym": nid, "ind": u.get("ind"), "house": house_of.get(nid), "lat": None, "lon": None, "geo_prec": None}
            elif nid.startswith("ANON_"):
                nodes[nid] = {"id": nid, "k": "anon", "n": "Unnamed customer", "sym": None, "ind": None, "house": None, "lat": None, "lon": None, "geo_prec": None}
            else:
                nodes[nid] = {"id": nid, "k": "ext", "n": e["cpn"], "sym": None, "ind": None, "house": None, "lat": None, "lon": None, "geo_prec": None}
    for fid, f in facs.items():
        nodes[fid] = {"id": fid, "k": "fac", "n": f["n"], "sym": f["co"], "ind": None, "house": house_of.get(f["co"]), "lat": f["lat"], "lon": f["lon"], "geo_prec": f["geo_prec"]}
    anon_doc = {}
    for aid, r in anon.items():
        own = next(e for e in edges if aid in (e["s"], e["d"]))
        anon_doc[aid] = {"owner": own["own"], "share": own["w"], "per": own["per"], **r}
        if r["resolved_to"]:                               # the edge is rewritten to the resolved company, marked as resolved
            for e in edges:
                if e["s"] == aid:
                    e["s"], e["kind"], e["conf"] = r["resolved_to"], "resolved", round(min(e["conf"], r["conf"]), 2)
                if e["d"] == aid:
                    e["d"], e["kind"], e["conf"] = r["resolved_to"], "resolved", round(min(e["conf"], r["conf"]), 2)
            nodes.pop(aid, None)
    return {"v": 1, "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "coverage": {"companies_done": len(cos), "companies_total": len(by_sym), "edges": len(edges), "facilities": len(facs)},
            "cos": cos, "nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": edges, "anon": anon_doc, "fac": facs}


# ------------------------------------------------------------------ driver

class DiscoverError(Exception):
    """NSE did not answer the filing list (blocked, paused, timed out). Different from an answer with no filings."""


class NoUniverse(Exception):
    """data/terminal/universe.json is missing or empty. Without it no company can be recognised as listed, so every owner would be saved as an unnamed external
    node (this is what damaged the graph committed on 2026-10-05): refuse to write anything."""


def load_universe():
    stocks = load_json(TERM / "universe.json", {"stocks": []}).get("stocks", [])
    if not stocks:
        raise NoUniverse("data/terminal/universe.json is missing or empty (run scripts/nse_eod.py first): the graph is left untouched")
    return stocks


def reassemble(log=print, now=None):
    """Rebuild nodes, ids and coverage from the edges already in data/supply_graph.json using the current universe. No network, no language model."""
    now = now or now_utc()
    stocks = load_universe()
    houses = (load_json(ROOT / "data" / "config" / "business_houses.json", {}) or {}).get("houses", [])
    old = load_json(OUT, {"cos": {}})
    doc = assemble(old, {}, stocks, houses, load_cfg()["anon_resolve_min_conf"], now)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"reassembled {OUT.name}: {doc['coverage']}")
    return doc


def run(symbols, limit, refresh, dry, session, llm, fetcher, now=None, log=print):
    now = now or now_utc()
    cfg, src = load_cfg(), load_json(SRC)
    stocks = load_universe()
    houses = (load_json(ROOT / "data" / "config" / "business_houses.json", {}) or {}).get("houses", [])
    index = NameIndex(stocks, load_json(ROOT / "data" / "config" / "news_aliases.json", {}))
    old = load_json(OUT, {"cos": {}})
    done = old.get("cos", {})
    if not symbols:
        main = [s for s in stocks if s.get("board") == "Main" and s.get("series") == "EQ" and not s.get("etf")]
        main.sort(key=lambda s: (not s.get("n500"), -((s.get("avgv20") or 0) * (s.get("c") or 0))))
        symbols = [s["s"] for s in main]
        symbols.sort(key=lambda s: done.get(s, {}).get("at", ""))   # oldest-refreshed (never-done first), stable on the n500/liquidity order
        prio = [r["sym"] for r in (load_json(ROOT / "data" / "config" / "nexus_priority.json", {}) or {}).get("rows", [])]
        first = [x for x in prio if x not in done and any(x == m["s"] for m in main)]       # the companies most likely to give listed-to-listed edges go first (scripts/nexus_priority.py)
        symbols = first + [x for x in symbols if x not in set(first)]
    todo = [s for s in symbols if refresh or s not in done][: limit]
    llm_cache = CACHE / "llm"
    llm_cache.mkdir(parents=True, exist_ok=True)
    results, report = {}, []
    for sym in todo:
        try:
            docs = discover(session, sym, src, now)
        except Exception as e:  # noqa: BLE001
            report.append((sym, f"filings could not be listed (will be retried): {e}"))
            log("  %-12s %s" % report[-1])
            if "paused" in str(e).lower() or sum(1 for r in report[-3:] if "could not be listed" in r[1]) >= 3:
                report.append((sym, "stopped: NSE is not answering (three failures in a row); the run resumes from here next time"))
                log("  " + report[-1][1])
                break
            continue
        time.sleep(PACE_S)
        if not docs:
            results[sym] = {"edges": [], "fac": [], "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "notes": ["no filing found"]}
            report.append((sym, "no filing found"))
            continue
        edges, facs, notes, stop, got_tr, answered = [], [], [], False, 0, 0
        for doc in docs:
            if doc["kind"] == "transcript" and got_tr >= src["transcripts_per_company"]:
                continue
            try:
                e, f, n, a = extract_filing(doc, fetcher, llm, src, now, llm_cache, log)
            except LLMBudget as b:
                notes.append(str(b))
                stop = True
                break
            except Exception as ex:  # noqa: BLE001 - one filing failing must not stop the run
                notes.append(f"{doc['kind']} failed: {str(ex)[:80]}")
                continue
            edges += e
            facs += f
            notes += n
            answered += a
            if doc["kind"] == "transcript" and not any("skipped" in x or "no readable" in x for x in n):
                got_tr += 1
        if stop and not edges:
            report.append((sym, "stopped: " + notes[-1]))
            break
        if answered == 0:                                  # nothing learned (rate limits, refusals): leave the company for the next run
            report.append((sym, "NOT recorded, will be retried: " + "; ".join(notes[:3])))
            continue
        results[sym] = {"edges": to_graph_edges(sym, edges, index), "fac": facs, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "notes": notes}
        report.append((sym, f"{len(edges)} edges, {len(facs)} facilities; " + "; ".join(notes[:2])))
        log("  %-12s %s" % report[-1])
        if not dry:                                        # saved after every company: a stopped or crashed run loses nothing
            OUT.write_text(json.dumps(assemble(old, results, stocks, houses, cfg["anon_resolve_min_conf"], now), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if stop:
            break
    doc = assemble(old, results, stocks, houses, load_cfg()["anon_resolve_min_conf"], now)
    if not dry:
        OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        log(f"wrote {OUT.name}: {doc['coverage']}")
    return doc, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-calls", type=int, default=None, help="model calls allowed in this run (default: nexus.max_llm_calls_per_run)")
    ap.add_argument("--reassemble", action="store_true", help="rebuild nodes and coverage from the saved edges (no network, no model)")
    a = ap.parse_args(argv)
    try:
        from aladin_env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    if a.reassemble:
        try:
            reassemble()
        except NoUniverse as e:
            print(e)
        return 0
    cfg = load_cfg()
    llm = LLM(max_calls=a.max_calls or cfg["max_llm_calls_per_run"])
    if llm.provider is None:
        print("No GROQ_API_KEY or GEMINI_API_KEY set: nothing to extract with. Add a free key to .env (see .env.example).")
        return 0
    from aladin_ticker_daemon import NseSession
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    try:
        run(syms, a.limit or cfg["filings_per_run"], a.refresh, a.dry_run, NseSession(), llm, Fetcher())
    except NoUniverse as e:
        print(e)
    print(f"model calls this run: {llm.calls}; tokens reported by the providers: {sum(llm.tokens.values()):,} {llm.tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
