"""
ALADIN Module B: stock sentiment from news, retail chatter and institutional flow. Low frequency (every 15-60 min).

  python scripts/aladin_sentiment_engine.py --once          one cycle (GitHub Actions)
  python scripts/aladin_sentiment_engine.py --loop 900      every 15 minutes (your PC)
  options: --no-google (skip per-stock Google News queries)  --no-reddit  --dry (print, write nothing)

Output: data/aladin/sentiment.json  (build_site.py copies it to site/sentiment.json)

What it does and does not do (all of it visible in the output's `method` / `notes` fields and the UI):
* Headlines come from Mint's RSS, the site's own news wire (ET, Business Standard, Mint), and Google News RSS queries
  per company (Moneycontrol headlines come through Google News: Moneycontrol itself is not scraped).
* Each headline is scored once by FinBERT (P(positive) - P(negative)); if torch/transformers can't load, a word-list
  fallback is used and `method` says "lexicon".
* A headline counts as evidence for a stock only if it names the stock (symbol, company name or alias) or, when it
  names no stock at all, its business group. Sector and market-wide headlines add low-weight context but are NEVER on
  their own evidence: a stock with nothing specific in the last 72 h is "NO NEWS" with no score (not neutral).
* Retail sentiment (Reddit) needs >= 5 distinct authors in 24 h per stock, otherwise it is null. Reddit's RSS answers
  HTTP 429 after the first request from many networks; PRAW with keys is used when REDDIT_CLIENT_ID/SECRET exist.
* Institutional flow is market-wide (FII/DII net, 5-day) with weight 0.15 on every scored stock.
"""

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
CFG = ROOT / "data" / "config" / "aladin_config.json"
ALIASES = ROOT / "data" / "config" / "news_aliases.json"
TONE = ROOT / "data" / "config" / "tone_words.json"
HOUSES = ROOT / "data" / "config" / "business_houses.json"
UNIVERSE = ROOT / "data" / "terminal" / "universe.json"
WIRE = ROOT / "data" / "news" / "wire.json"
FIIDII = ROOT / "data" / "institutional" / "fii_dii.json"
GEO = ROOT / "data" / "aladin" / "geo.json"
OUT = ROOT / "data" / "aladin" / "sentiment.json"
CACHE = ROOT / "data" / "aladin_cache"
UA = {"User-Agent": "samnidhy-blab-sentiment/1.0 (educational; contact github.com/atharvatyagi-gif)"}
RETENTION_DAYS, EVIDENCE_H = 7, 72
LEVELS = [(-60, "BAD"), (-20, "POOR"), (20, "NEUTRAL"), (60, "GOOD")]
MINT_FEEDS = ["https://www.livemint.com/rss/companies", "https://www.livemint.com/rss/markets"]
LEGAL = re.compile(r"\b(limited|ltd|corporation|corp|company|co|incorporated|inc|plc|pvt|private|of india|india)\b\.?", re.I)


def now_utc():
    return datetime.now(timezone.utc)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def level(sc):
    """S <= -60 BAD; -60 < S <= -20 POOR; -20 < S < 20 NEUTRAL; 20 <= S < 60 GOOD; S >= 60 EXCELLENT."""
    if sc <= -60:
        return "BAD"
    if sc <= -20:
        return "POOR"
    if sc < 20:
        return "NEUTRAL"
    return "GOOD" if sc < 60 else "EXCELLENT"


# ------------------------------------------------------------------ items

@dataclass
class Item:
    title: str
    url: str
    source: str
    ts: datetime | None
    kind: str = "media"            # media | google | reddit
    hint: str | None = None        # symbol this item was fetched for (Google per-company queries)
    author: str | None = None
    text: str = ""                 # extra body text (Reddit self-text)
    votes: int = 0
    comments: int = 0

    def age_h(self, now):
        return max(0.0, (now - self.ts).total_seconds() / 3600) if self.ts else 24.0


def _entry_ts(e):
    t = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def collect_media(now=None, fetch=None):
    """Mint RSS (feedparser) plus the news wire the site already builds (ET, Business Standard, Mint)."""
    import feedparser
    now, items, fetch = now or now_utc(), [], fetch or _http
    for url in MINT_FEEDS:
        raw = fetch(url)
        if raw:
            for e in feedparser.parse(raw).entries:
                if e.get("title") and e.get("link"):
                    items.append(Item(e.title.strip(), e.link, "Mint", _entry_ts(e)))
    for g in load_json(WIRE, {}).get("groups", []):
        for s in g.get("sources", []):
            if g.get("id") != "india":
                continue
            for it in s.get("items", []):
                m = it.get("age_min")
                if it.get("t") and it.get("u"):
                    items.append(Item(it["t"].strip(), it["u"], s.get("name", "wire").split(" · ")[0], None if m is None else now - timedelta(minutes=m)))
    return items


def _http(url, params=None):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=25)
        return r.content if r.status_code == 200 else None
    except requests.RequestException:
        return None


def collect_google_news(symbols, names, per_cycle=25, now=None, fetch=None, sleep=time.sleep, gap=3.0):
    """Google News RSS per company, restricted to Moneycontrol headlines. 3 s between requests; the caller chooses the
    symbols (sweeps today, top 40 by traded value, a rotating batch of 25 others)."""
    import feedparser
    now, items, fetch = now or now_utc(), [], fetch or _http
    for i, sym in enumerate(symbols):
        raw = fetch("https://news.google.com/rss/search", {"q": f"{names.get(sym, sym)} NSE site:moneycontrol.com", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        if raw:
            for e in feedparser.parse(raw).entries[:8]:
                if e.get("title") and e.get("link"):
                    src = (e.get("source") or {}).get("title") if isinstance(e.get("source"), dict) else None
                    items.append(Item(re.sub(r"\s+-\s+[^-]+$", "", e.title.strip()), e.link, src or "Moneycontrol", _entry_ts(e), "google", sym))
        if i < len(symbols) - 1:
            sleep(gap)
    return items


def collect_reddit(subs, now=None, fetch=None, sleep=time.sleep):
    """PRAW if keys exist, else the subreddit .rss (posts only: no scores or comment counts), else []. Never raises."""
    now, items = now or now_utc(), []
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if cid and sec:
        try:
            import praw
            r = praw.Reddit(client_id=cid, client_secret=sec, user_agent=UA["User-Agent"], check_for_async=False)
            for sub in subs:
                try:
                    for p in list(r.subreddit(sub).new(limit=100)) + list(r.subreddit(sub).hot(limit=50)):
                        ts = datetime.fromtimestamp(p.created_utc, timezone.utc)
                        if (now - ts) <= timedelta(hours=24):
                            items.append(Item(p.title, "https://reddit.com" + p.permalink, f"r/{sub}", ts, "reddit", None, str(p.author), p.selftext or "", int(p.score), int(p.num_comments)))
                except Exception:
                    continue
            return items
        except Exception:
            items = []
    import feedparser
    fetch = fetch or _http
    for sub in subs:
        raw = fetch(f"https://www.reddit.com/r/{sub}/new/.rss")
        if raw:
            for e in feedparser.parse(raw).entries:
                items.append(Item(e.get("title", ""), e.get("link", ""), f"r/{sub}", _entry_ts(e), "reddit", None, e.get("author", None), re.sub(r"<[^>]+>", " ", e.get("summary", ""))))
        sleep(5)
    return items


# ------------------------------------------------------------------ scoring

class Finbert:
    """ProsusAI/finbert, lazy, batched; score = P(positive) - P(negative). If it can't load, `method` is 'lexicon'."""
    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self):
        self.ok, self.method = False, "lexicon"
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
            self.torch = torch
            self.tok = AutoTokenizer.from_pretrained("ProsusAI/finbert")
            self.model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert").eval()
            self.labels = {int(k): v.lower() for k, v in self.model.config.id2label.items()}
            self.ok, self.method = True, "finbert"
        except Exception:
            pass
        self.neg, self.pos = _lexicon()
        self.cache = {}

    def score(self, texts):
        out, todo = [None] * len(texts), []
        for i, t in enumerate(texts):
            k = hashlib.sha1((self.method + t).encode()).hexdigest()
            if k in self.cache:
                out[i] = self.cache[k]
            else:
                todo.append((i, t, k))
        if todo and self.ok:
            for b in range(0, len(todo), 16):
                chunk = todo[b:b + 16]
                with self.torch.inference_mode():
                    enc = self.tok([t for _, t, _ in chunk], return_tensors="pt", padding=True, truncation=True, max_length=128)
                    prob = self.torch.softmax(self.model(**enc).logits, -1)
                for (i, _, k), row in zip(chunk, prob):
                    d = {self.labels[j]: float(row[j]) for j in range(len(row))}
                    out[i] = self.cache[k] = round(d.get("positive", 0.0) - d.get("negative", 0.0), 4)
        elif todo:
            for i, t, k in todo:
                out[i] = self.cache[k] = lexicon_score(t, self.neg, self.pos)
        return out


def _lexicon():
    j = load_json(TONE, {"negative": [], "positive": []})
    return set(j["negative"]), set(j["positive"])


def lexicon_score(text, neg, pos):
    words = re.findall(r"[a-z][a-z\-']+", re.sub(r"\s+-\s+[^-]+$", "", text.lower()))
    n, p = sum(w in neg for w in words), sum(w in pos for w in words)
    return round((p - n) / (p + n + 1), 4)


# ------------------------------------------------------------------ matching headlines to stocks

def norm(text):
    return re.findall(r"[a-z0-9&]+", text.lower().replace("'", "").replace("’", ""))


class Matcher:
    def __init__(self, stocks, aliases, houses):
        self.stoplist = set(aliases["symbol_stoplist"])
        self.symbols = {s["s"] for s in stocks if s.get("series") == "EQ" and not s.get("etf")}
        self.industry = {s["s"]: s.get("ind") for s in stocks}
        self.name_index = {}                               # phrase -> {symbols}
        for s in stocks:
            if s["s"] not in self.symbols or s.get("board") != "Main":
                continue
            base = " ".join(norm(LEGAL.sub(" ", s["n"])))
            if len(base) >= 6 and base not in {"india", "global", "power", "energy", "industries", "enterprises", "infra", "tech", "international"}:
                self.name_index.setdefault(base, set()).add(s["s"])
        for sym, al in aliases["manual"].items():
            for a in al:
                self.name_index.setdefault(" ".join(norm(a)), set()).add(sym)
        self.name_index = {k: v for k, v in self.name_index.items() if len(v) == 1 or k in {" ".join(norm(a)) for al in aliases["manual"].values() for a in al}}
        self.max_words = max((len(k.split()) for k in self.name_index), default=1)
        self.groups = {}
        gmem = {h["id"]: h["symbols"] for h in houses.get("houses", [])}
        for gid, phrases in aliases.get("groups", {}).items():
            for p in phrases:
                self.groups[" ".join(norm(p))] = gmem.get(gid, [])
        self.sector_kw = {" ".join(norm(k)): ind for ind, ks in aliases["sector_keywords"].items() for k in ks}
        self.market_terms = {" ".join(norm(t)) for t in aliases["market_terms"]}

    def _phrases(self, words, maxn):
        for n in range(1, maxn + 1):
            for i in range(len(words) - n + 1):
                yield " ".join(words[i:i + n])

    def match(self, title, text="", hint=None):
        """-> (stock_matches {sym: (weight, type)}, sectors {industry}, market bool)"""
        words = norm(title + " " + text)
        out = {}

        def put(sym, w, t):
            if sym in self.symbols and (sym not in out or w > out[sym][0]):
                out[sym] = (w, t)
        letters = [c for c in title if c.isalpha()]
        shouty = letters and sum(c.isupper() for c in letters) / len(letters) > 0.6
        if shouty:                                         # an all-caps headline is a ticker list or a shout, not a story about one company
            return {}, set(), False
        for m in re.finditer(r"\$([A-Z][A-Z0-9&\-]{1,15})|(?<![A-Za-z0-9&])([A-Z][A-Z0-9&\-]{2,15})(?![A-Za-z0-9&])", title + " " + text):
            sym, cash = m.group(1) or m.group(2), m.group(1) is not None
            if sym in self.symbols and (cash or sym not in self.stoplist):
                put(sym, 1.0, "symbol")
        phrases = set(self._phrases(words, self.max_words))
        for ph in phrases:
            for sym in self.name_index.get(ph, ()):
                put(sym, 0.9, "name")
        if hint and hint not in out and any(ph in self.name_index and hint in self.name_index[ph] for ph in phrases):
            put(hint, 0.9, "name")
        if not out:                                        # a story about a group in general (not about one named company)
            for ph in phrases:
                for sym in self.groups.get(ph, ()):
                    put(sym, 0.5, "group")
        sectors = {ind for ph, ind in self.sector_kw.items() if ph in phrases or (" " + ph + " ") in (" " + " ".join(words) + " ")}
        market = any(t in phrases for t in self.market_terms)
        return out, sectors, market


def source_weight(source, url, publishers):
    s = f"{source or ''} {url or ''}".lower()
    return 1.0 if any(p in s for p in publishers) else 0.7


# ------------------------------------------------------------------ the three parts

def flow_score(fiidii=None):
    j = fiidii if fiidii is not None else load_json(FIIDII, {})
    days = [d for d in j.get("days", []) if d.get("fii") and d.get("dii")]
    if not days:
        return None, {"reason": "FII/DII file missing or empty"}
    last = days[-5:]
    fii5 = statistics.fmean(d["fii"]["net_cr"] for d in last)
    dii5 = statistics.fmean(d["dii"]["net_cr"] for d in last)
    series = [0.7 * d["fii"]["net_cr"] + 0.3 * d["dii"]["net_cr"] for d in days[-60:]]
    scale = statistics.pstdev(series) if len(days) >= 20 and statistics.pstdev(series) > 0 else 4000.0
    v = math.tanh((0.7 * fii5 + 0.3 * dii5) / scale)
    return round(v, 4), {"days": len(days), "fii5_cr": round(fii5), "dii5_cr": round(dii5), "scale": round(scale), "scale_kind": "60-day std" if len(days) >= 20 else "fixed 4000 (fewer than 20 days saved)"}


def retail_scores(scored_reddit, matcher, now):
    """scored_reddit = [(Item, s)]. Returns {sym: (S_retail|None, n_mentions)}. One author counts once per stock per day."""
    per = {}
    for it, s in scored_reddit:
        stocks, _, _ = matcher.match(it.title, it.text)
        age = it.age_h(now)
        if age > 24:
            continue
        w = (1 + math.log(1 + max(it.votes, 0)) + 0.5 * math.log(1 + it.comments)) * math.exp(-age / 8)
        for sym, (_, typ) in stocks.items():
            if typ not in ("symbol", "name"):
                continue
            key = (it.author or it.url, sym)
            if key not in per or w > per[key][0]:
                per[key] = (w, s, sym)
    by = {}
    for (_, sym), (w, s, _) in per.items():
        by.setdefault(sym, []).append((w, s))
    return {sym: ((sum(w * s for w, s in v) / (sum(w for w, _ in v) + 3)) if len(v) >= 5 else None, len(v)) for sym, v in by.items()}


def geo_adjust(sym, ind, geo):
    adj = 0.0
    for r in (geo or {}).get("regions", []):
        if r.get("score") is None:
            continue
        for e in r.get("exposure", []):
            if e.get("sym") == sym or (e.get("ind") and e["ind"] == ind):
                adj += (1 if e["dir"] == "+" else -1) * (r["score"] - 50) / 50 * 0.2
    return max(-0.2, min(0.2, adj))


def build_sentiment(scored, matcher, flow, flow_info, geo, retail=None, publishers=(), now=None, method="finbert", notes=()):
    """scored = [(Item, s)] for media/google items. -> the sentiment.json document."""
    now, retail = now or now_utc(), retail or {}
    num, den, evid = {}, {}, {}
    mnum = mden = 0.0
    snum, sden, scount = {}, {}, {}
    for it, s in scored:
        age = it.age_h(now)
        if age > EVIDENCE_H:
            continue
        decay = math.exp(-age / 24) * source_weight(it.source, it.url, publishers)
        stocks, sectors, market = matcher.match(it.title, it.text, it.hint)
        for sym, (mw, typ) in stocks.items():
            w = mw * decay
            num[sym], den[sym] = num.get(sym, 0.0) + w * s, den.get(sym, 0.0) + w
            evid.setdefault(sym, []).append((it, s, typ, round(age * 60)))
        for ind in sectors:
            w = 0.3 * decay
            snum[ind], sden[ind], scount[ind] = snum.get(ind, 0.0) + w * s, sden.get(ind, 0.0) + w, scount.get(ind, 0) + 1
        if market:
            mnum += 0.1 * decay * s
            mden += 0.1 * decay
    stocks_out = {}
    for sym in set(evid) | set(retail):
        ind = matcher.industry.get(sym)
        parts = {}
        if sym in evid:
            n = len(evid[sym])
            parts["news"] = (num[sym] + snum.get(ind, 0.0) + mnum) / (den[sym] + sden.get(ind, 0.0) + mden + 1)
        if retail.get(sym, (None, 0))[0] is not None:
            parts["retail"] = retail[sym][0]
        if flow is not None:
            parts["flow"] = flow
        if not ({"news", "retail"} & set(parts)):
            continue
        base = {"news": 0.60, "retail": 0.15, "flow": 0.15}
        tot = sum(base[k] for k in parts)
        raw = sum(base[k] / tot * v for k, v in parts.items())
        g = geo_adjust(sym, ind, geo)
        sc = round(100 * max(-1.0, min(1.0, raw + g)), 1)
        ev = sorted(evid.get(sym, []), key=lambda e: e[3])[:8]
        stocks_out[sym] = {"sc": sc, "lvl": level(sc), "n": len(evid.get(sym, [])), "geo": round(g, 3),
                           "parts": {k: round(v, 3) for k, v in parts.items()}, "rn": retail.get(sym, (None, 0))[1],
                           "items": [[it.title[:140], it.url, it.source, age, round(s, 3), typ] for it, s, typ, age in ev]}
    return {"generated_utc": now.isoformat(timespec="seconds"), "version": 1, "method": method, "evidence_window_h": EVIDENCE_H,
            "market": {"sc": None if mden == 0 else round(100 * mnum / (mden + 1), 1), "n_weight": round(mden, 2), "flow": flow, "flow_info": flow_info},
            "sectors": {k: {"sc": round(100 * snum[k] / (sden[k] + 1), 1), "n": scount[k]} for k in snum if scount[k] >= 3},
            "notes": list(notes), "scored": len(stocks_out), "stocks": stocks_out}


# ------------------------------------------------------------------ transcripts (cloud LLM, used by the filings step)

QA_MARK = re.compile(r"question[- ]and[- ]answer|Q\s*&\s*A|first question", re.I)
LLM_PROMPT = ("You are analysing an earnings-call transcript. Reply with STRICT JSON only, keys: tone (-1..1), hedging_ratio (0..1), "
              "prepared_tone (-1..1), qa_tone (-1..1), qa_gap (qa_tone - prepared_tone), evidence (up to 3 quotes of at most 25 words each, "
              "copied from the text), confidence (0..1). No commentary.")


def _llm_cfg():
    return load_json(CFG, {}).get("llm", {"groq_model": "llama-3.3-70b-versatile", "gemini_model": "gemini-1.5-flash"})


def call_llm(text, post=None, env=None, sleep=time.sleep):
    """Groq if GROQ_API_KEY else Gemini if GEMINI_API_KEY; JSON dict or None. Retries 429 with backoff. Never raises."""
    env, post, cfg = env if env is not None else os.environ, post or requests.post, _llm_cfg()
    for attempt in range(3):
        try:
            if env.get("GROQ_API_KEY"):
                r = post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": "Bearer " + env["GROQ_API_KEY"]}, timeout=60,
                         json={"model": cfg["groq_model"], "temperature": 0, "response_format": {"type": "json_object"},
                               "messages": [{"role": "system", "content": LLM_PROMPT}, {"role": "user", "content": text}]})
                if r.status_code == 429:
                    sleep(2 ** attempt * 2); continue
                return json.loads(r.json()["choices"][0]["message"]["content"]) if r.status_code == 200 else None
            if env.get("GEMINI_API_KEY"):
                r = post(f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['gemini_model']}:generateContent", params={"key": env["GEMINI_API_KEY"]}, timeout=60,
                         json={"contents": [{"parts": [{"text": LLM_PROMPT + "\n\n" + text}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}})
                if r.status_code == 429:
                    sleep(2 ** attempt * 2); continue
                return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"]) if r.status_code == 200 else None
            return None
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
            return None
    return None


def local_transcript(text, scorer=None):
    """No key or rate-limited: split at the Q&A marker, score each half with FinBERT (or the lexicon)."""
    scorer = scorer or Finbert.get().score
    m = QA_MARK.search(text)
    prep, qa = (text[:m.start()], text[m.end():]) if m else (text, "")
    def half(t):
        chunks = [t[i:i + 600] for i in range(0, min(len(t), 24000), 600)]
        s = scorer(chunks) if chunks else []
        return round(statistics.fmean(s), 3) if s else None
    p, q = half(prep), half(qa)
    return {"tone": round(statistics.fmean([x for x in (p, q) if x is not None]), 3) if (p is not None or q is not None) else None,
            "prepared_tone": p, "qa_tone": q, "qa_gap": None if p is None or q is None else round(q - p, 3), "hedging_ratio": None, "evidence": [], "confidence": 0.3, "method": "local"}


def score_transcript(pdf_text, symbol, cache=None, key=None, post=None, env=None, scorer=None, sleep=time.sleep):
    """Cloud LLM when a key exists, else the local split. Cached by `key` (the PDF's URL). Short quotes only."""
    cache = cache if cache is not None else {}
    if key and key in cache:
        return cache[key]
    if not pdf_text or len(pdf_text) < 500:
        return None
    res = call_llm(pdf_text[:60000], post, env, sleep)
    if isinstance(res, dict) and isinstance(res.get("tone"), (int, float)):
        res = {**res, "method": "llm", "evidence": [" ".join(str(q).split()[:25]) for q in (res.get("evidence") or [])[:3]]}
    else:
        res = local_transcript(pdf_text, scorer)
    res["symbol"] = symbol
    if key:
        cache[key] = res
    return res


# ------------------------------------------------------------------ one cycle

def choose_symbols(stocks, sweep_syms, state, top_n=40, rotate=25):
    liquid = sorted((s for s in stocks if s.get("series") == "EQ" and s.get("board") == "Main" and not s.get("etf")), key=lambda s: -(s.get("val_cr") or 0))
    first = list(dict.fromkeys(list(sweep_syms) + [s["s"] for s in liquid[:top_n]]))
    rest = [s["s"] for s in liquid[top_n:top_n + 800] if s["s"] not in first]
    start = state.get("rot", 0) % max(1, len(rest))
    batch = (rest[start:] + rest[:start])[:rotate]
    state["rot"] = (start + rotate) % max(1, len(rest))
    return first + batch


def run_cycle(args=None, now=None, scorer=None, fetch=None, sleep=time.sleep):
    now = now or now_utc()
    stocks = load_json(UNIVERSE, {}).get("stocks", [])
    if not stocks:
        raise SystemExit("data/terminal/universe.json is missing: run scripts/nse_eod.py first")
    aliases, houses = load_json(ALIASES, {}), load_json(HOUSES, {})
    matcher = Matcher(stocks, aliases, houses)
    names = {s["s"]: LEGAL.sub(" ", s["n"]).strip() for s in stocks}
    fb = scorer or Finbert.get()
    state = load_json(CACHE / "sentiment_state.json", {})
    store = load_json(CACHE / "news_store.json", {})
    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
    store = {u: v for u, v in store.items() if v["ts"] >= cutoff}
    notes = []
    items = collect_media(now, fetch)
    if not (args and args.no_google):
        today = now.strftime("%Y-%m-%d")
        sweeps = {json.loads(l)["sym"] for l in (CACHE / "sweep_log" / f"{today}.jsonl").read_text(encoding="utf-8").splitlines()} if (CACHE / "sweep_log" / f"{today}.jsonl").exists() else set()
        items += collect_google_news(choose_symbols(stocks, sweeps, state), names, now=now, fetch=fetch, sleep=sleep)
    else:
        notes.append("Per-company Google News queries were skipped in this run.")
    seen, uniq = set(), []
    for it in items:
        if it.url and it.url not in seen:
            seen.add(it.url); uniq.append(it)
    todo = [it for it in uniq if it.url not in store]
    method = fb.method if hasattr(fb, "method") else "finbert"
    if todo:
        for it, s in zip(todo, fb.score([it.title for it in todo])):
            store[it.url] = {"ts": (it.ts or now).isoformat(), "s": s, "m": method}
    scored = [(it, store[it.url]["s"]) for it in uniq]
    retail = {}
    if not (args and args.no_reddit):
        rd = collect_reddit(aliases.get("reddit_subs", []), now, fetch, sleep)
        if rd:
            retail = retail_scores(list(zip(rd, fb.score([r.title + " " + r.text[:300] for r in rd]))), matcher, now)
        else:
            notes.append("Reddit returned nothing (rate-limited or blocked): retail sentiment is not measured this cycle.")
    flow, finfo = flow_score()
    if flow is None:
        notes.append("Institutional flow not measured: " + finfo.get("reason", ""))
    doc = build_sentiment(scored, matcher, flow, finfo, load_json(GEO, None), retail, aliases.get("indian_publishers", []), now, method, notes)
    doc["headlines_scored"] = len(scored)
    if method == "lexicon":
        doc["notes"].append("FinBERT could not load here; headlines were scored with a word list, which is cruder.")
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "news_store.json").write_text(json.dumps(store, separators=(",", ":")), encoding="utf-8")
    (CACHE / "sentiment_state.json").write_text(json.dumps(state), encoding="utf-8")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, default=0)
    ap.add_argument("--no-google", action="store_true")
    ap.add_argument("--no-reddit", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    while True:
        doc = run_cycle(a)
        txt = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
        if a.dry:
            print(txt[:2000])
        else:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(txt, encoding="utf-8")
            print(f"sentiment: {doc['headlines_scored']} headlines scored ({doc['method']}), {doc['scored']} stocks with a score, {len(txt) / 1024:.0f} KB")
            branch = os.environ.get("ALADIN_GIT_BRANCH")
            if os.environ.get("ALADIN_GIT_PUSH") == "1":
                if branch:
                    import gitops
                    gitops.commit_and_push(["data/aladin/sentiment.json"], "ALADIN sentiment refresh [skip ci]", branch=branch)
                else:
                    print("ALADIN_GIT_PUSH=1 but ALADIN_GIT_BRANCH is not set: not pushing (the loop never assumes 'main').")
        if not a.loop:
            return 0
        time.sleep(a.loop)


if __name__ == "__main__":
    sys.exit(main())
