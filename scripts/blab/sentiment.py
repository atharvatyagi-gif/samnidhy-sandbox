"""B-Lab Sentiment division, step 5 (docs/blab/PLAN.md): what people write, Indian and US (owner, 2026-11-16: US and Indian
sentiment are inputs; findings are about Indian stocks only).

Sources (free, no key unless stated; checked 2026-11-17):
  Google News RSS, India edition: one search per NSE sector; US edition: Wall Street / stock market
  CNBC RSS (top news, markets); Economic Times industry, Business Standard companies, Mint companies RSS
  AI analyst: the repository's free-tier client (scripts/revenue_graph_builder.py LLM): Groq and Gemini free tiers (keys
  already GitHub secrets) and GitHub Models with the workflow's own token. When every free quota is used up the bot says
  "free limit reached"; it never switches to a paid service.
  Event history: NSE corporate announcements by date (the same free API as the governance scout), up to 3 years back.

THE RULES (declared 2026-11-17, before any result was looked at)
  S6 AI analyst  up to 30 new headlines a run (10 a request), newest first, at most 10 of them US. The model returns for each:
                 event type (fixed list), effect on Indian stocks (positive / negative / none), confidence (high / medium /
                 low), Indian listed companies named, Indian sectors affected, a one-line reason. Code, not the model, maps
                 names to NSE symbols (fuzzy match >= 92, the repository's NameIndex). A finding only when confidence is
                 "high" and the effect is not "none": one per named company in the 500 most-traded (direction = the effect),
                 and, for each named company, up to 5 companies linked to it in the NEXUS supply graph that were NOT named
                 ("exposed via supply chain", same direction).
  S7 historian   each NSE announcement category (company events) in the last 3 years, for stocks in the 500 most-traded:
                 reaction = close before the announcement day to the first close after it; drift = that close to 5 and 21
                 sessions later; both minus NIFTY 500 over the same days. "Measurable" = 95% range clear of zero with at
                 least 30 events. Finding: a new announcement (last 3 days) in a category whose 21-session drift is
                 measurable, direction = its sign, once per announcement.
  Refined 2026-11-17 after reading the first run and BEFORE any finding was scored (recorded honestly): with only 3 months
                 of history, three categories looked "measurable" because announcements from the same weeks move together.
                 The 95% range is now built from MONTHLY averages (events in one month are not independent), a category
                 needs events in at least 12 different months, and no finding is filed until the history spans 2 years.
                 One finding per stock, category and day.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .core import DATA, ROOT, Limit, NoKey, SITE_URL, fetch_json

STORE = DATA / "blab" / "store"
KEEP_NEWS_DAYS = 14
GN_IN = "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
GN_US = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
SECTORS = {"Banking": "bank stocks India", "IT": "IT stocks India Infosys TCS", "Pharma": "pharma stocks India", "Auto": "auto stocks India",
           "FMCG": "FMCG stocks India", "Metals": "metal stocks India", "Oil & gas": "oil gas stocks India", "Power": "power stocks India",
           "Realty": "realty stocks India", "Telecom": "telecom stocks India", "Capital goods": "capital goods stocks India",
           "Chemicals": "chemical stocks India", "Cement": "cement stocks India", "NBFC": "NBFC stocks India"}
COMPANY_FEEDS = [("Economic Times · Industry", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"),
                 ("Business Standard · Companies", "https://www.business-standard.com/rss/companies-101.rss"),
                 ("Mint · Companies", "https://www.livemint.com/rss/companies")]
US_FEEDS = [("CNBC · Top news", "https://www.cnbc.com/id/100003114/device/rss/rss.html"), ("CNBC · Markets", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
            ("Google News US · Wall Street", GN_US + urllib.parse.quote("stock market Wall Street when:1d"))]
EVENT_TYPES = ["earnings", "order or contract win", "merger or acquisition", "management change", "regulatory or legal action", "rating change",
               "fundraise or dilution", "capex or expansion", "default or distress", "policy or tax change", "interest rates or central bank",
               "commodity price move", "currency move", "geopolitics or war", "trade or tariffs", "global markets move", "other"]
MAX_ITEMS, BATCH, MAX_US = 30, 10, 10
EVENT_CATS = {"Bagging/Receiving of orders/contracts", "Acquisition", "Integrated Filing- Financial", "Credit Rating", "Credit Rating- Revision",
              "Resignation of Statutory Auditor", "Change in Auditors", "Resignation of Director/KMP/SMP", "Change in Management", "Spurt in Volume",
              "Dividend", "Allotment of Securities", "Related Party Transactions", "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company",
              "Action(s) taken or orders passed", "Disclosure of material issue", "Corporate Insolvency Resolution Process",
              "Reasons for Delayed/Non-submission of Financial Results", "Capacity addition", "Agreements", "Buyback", "Investor Presentation",
              "Analysts/Institutional Investor Meet/Con. Call Updates", "Press Release", "Statement of deviation(s) or variation(s) under Reg. 32"}
HIST_YEARS, BACK_DAYS_PER_RUN = 3, 45
MIN_MONTHS, MIN_SPAN_DAYS = 12, 730


def _load(name, default):
    try:
        return json.loads((STORE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(name, doc):
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / name).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (B-Lab research desk, educational)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_rss(raw, src_default):
    """RSS bytes -> [{t, u, src, pub}] (pub ISO UTC or None)."""
    out = []
    root = ET.fromstring(raw)
    for it in root.iter("item"):
        t = re.sub(r"\s+", " ", (it.findtext("title") or "")).strip()
        u = (it.findtext("link") or "").strip()
        if not t or not u.startswith("http"):
            continue
        src = (it.findtext("source") or "").strip() or src_default
        if src and t.endswith(" - " + src):
            t = t[: -len(src) - 3]
        pub = None
        try:
            pub = parsedate_to_datetime((it.findtext("pubDate") or "").strip()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, IndexError):
            pass
        out.append({"t": t, "u": u, "src": src, "pub": pub})
    return out


def _nid(title):
    return hashlib.sha1(re.sub(r"\W+", " ", title.lower()).strip().encode()).hexdigest()[:12]


def collect_news(ctx, feeds, name):
    """feeds: [(region, scope, source label, url)] -> rolling store `name` of [id, region, scope, title, url, src, pub, first_seen]."""
    st = _load(name, {"rows": []})
    have = {r[0] for r in st["rows"]}
    get = getattr(ctx, "rss_fetch", None) or _get
    now, errs, n_new = ctx.now, [], 0
    for region, scope, label, url in feeds:
        try:
            for it in parse_rss(get(url), label):
                i = _nid(it["t"])
                if i not in have:
                    st["rows"].append([i, region, scope, it["t"], it["u"], it["src"], it["pub"], now.strftime("%Y-%m-%dT%H:%M:%SZ")]); have.add(i); n_new += 1
        except Exception as e:  # noqa: BLE001  one feed failing never stops the others
            errs.append(f"{label}: {type(e).__name__}")
    cut = (now - timedelta(days=KEEP_NEWS_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st["rows"] = [r for r in st["rows"] if (r[6] or r[7]) >= cut]
    _save(name, st)
    return st["rows"], n_new, errs


# ------------------------------------------------------------------ scouts

def s2_us_news(ctx):
    rows, n, errs = collect_news(ctx, [("US", "US markets", lab, u) for lab, u in US_FEEDS], "news_us.json")
    ctx.shared["S2_us"] = rows
    if not rows and errs:
        raise RuntimeError("; ".join(errs))
    return rows, n, errs


def s3_sectors(ctx):
    feeds = [("IN", sec, f"Google News · {sec}", GN_IN + urllib.parse.quote(q + " when:2d")) for sec, q in SECTORS.items()]
    feeds += [("IN", "Companies", lab, u) for lab, u in COMPANY_FEEDS]
    rows, n, errs = collect_news(ctx, feeds, "news_sectors.json")
    ctx.shared["S3"] = rows
    if not rows and errs:
        raise RuntimeError("; ".join(errs[:3]))
    newest = max((r[6] or r[7] for r in rows), default=None)
    from collections import Counter
    c = Counter(r[2] for r in rows)
    return {"items": len(rows), "as_of": newest, "errors": errs[:5],
            "detail": f"{len(rows)} Indian sector and company headlines kept ({n} new this run) from {len(feeds)} free feeds: "
                      + ", ".join(f"{k} {v}" for k, v in c.most_common(8)) + ("" if not errs else f". {len(errs)} feed(s) failed this run.")}


# ------------------------------------------------------------------ AI analyst

SYSTEM = ("You read financial news headlines and judge their effect on Indian listed stocks only. Answer in JSON: "
          '{"items": [{"i": <the headline number>, "event": <one of: ' + ", ".join(EVENT_TYPES) + '>, '
          '"india_effect": "positive" | "negative" | "none", "confidence": "high" | "medium" | "low", '
          '"companies": [Indian listed companies the effect applies to; NOT the other side of a deal, e.g. the customer that gives an order], '
          '"sectors": [Indian sectors affected, from: ' + ", ".join(SECTORS) + '], '
          '"why": "<= 20 words"}]}. Use "none" when the effect on Indian stocks is unclear. Use "high" confidence only when the headline itself '
          "states a concrete event with a clear direction. Do not invent companies; a US company is not an Indian listed company.")


def _name_index():
    sys.path.insert(0, str(ROOT / "scripts"))
    import revenue_graph_builder as rb
    uni = fetch_json(SITE_URL + "t/universe.json")
    stocks = uni.get("stocks", uni) if isinstance(uni, dict) else uni
    try:
        aliases = json.loads((DATA / "config" / "news_aliases.json").read_text(encoding="utf-8")).get("manual", {})   # {symbol: [names]}
    except (OSError, ValueError):
        aliases = {}
    return rb.NameIndex(stocks, aliases)


def _llm():
    sys.path.insert(0, str(ROOT / "scripts"))
    import revenue_graph_builder as rb
    llm = rb.LLM(provider="auto", max_calls=math.ceil(MAX_ITEMS / BATCH))     # "auto": any free model; a stray LLM_PROVIDER setting must not switch it off
    if not llm.cands:
        raise NoKey("no free AI model key on this runner (GROQ_API_KEY, GEMINI_API_KEY or the workflow's GitHub Models token)")
    return llm, rb


def neighbours(sym, graph, k=5):
    """Companies linked to `sym` in the NEXUS supply graph (either direction), strongest first."""
    out = []
    for e in graph.get("edges", []):
        a, b = e.get("s"), e.get("d")                       # NEXUS edge: s = from, d = to
        other = b if a == sym else a if b == sym else None
        if other and other != sym:
            out.append((float(e.get("conf") or e.get("confidence") or 0), other))
    seen, res = set(), []
    for _, o in sorted(out, reverse=True):
        if o not in seen:
            seen.add(o); res.append(o)
        if len(res) == k:
            break
    return res


def pick_items(india, us, done, n=MAX_ITEMS, max_us=MAX_US):
    """Newest unanalysed headlines, at most max_us from the US. Rows: [id, region, scope, title, url, src, pub, first_seen]."""
    key = lambda r: r[6] or r[7] or ""  # noqa: E731
    us_new = [r for r in sorted(us, key=key, reverse=True) if r[0] not in done][:max_us]
    in_new = [r for r in sorted(india, key=key, reverse=True) if r[0] not in done][: n - len(us_new)]
    return in_new + us_new


def interpret(results, items, resolve, universe, graph):
    """Model answers -> findings, by the declared rule. resolve(name) -> symbol or None."""
    found = []
    for res in results:
        try:
            it = items[int(res.get("i")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        eff, conf = res.get("india_effect"), res.get("confidence")
        if conf != "high" or eff not in ("positive", "negative"):
            continue
        d = 1 if eff == "positive" else -1
        ev_type = res.get("event") if res.get("event") in EVENT_TYPES else "other"          # the fixed list only: anything else is "other"
        named = []
        for nm in res.get("companies") or []:
            s = resolve(str(nm))
            if s and s in universe and s not in named:
                named.append(s)
        ev = {"src": it[5], "url": it[4], "quote": it[3][:160]}
        for s in named:
            found.append({"sym": s, "kind": f"news: {ev_type}", "direction": d, "event": f"ai {it[0]} {s}",
                          "text": f"AI reading ({'US' if it[1] == 'US' else 'Indian'} news): {eff} for {s}. {str(res.get('why') or '')[:140]}", "evidence": [ev]})
            for o in neighbours(s, graph):
                if o in universe and o not in named:
                    found.append({"sym": o, "kind": "exposed via supply chain", "direction": d, "event": f"ai {it[0]} {o} via {s}",
                                  "text": f"Not named, but linked to {s} in the NEXUS supply graph; the news reads {eff} for {s}. {str(res.get('why') or '')[:100]}", "evidence": [ev]})
    return found


def s6_ai_analyst(ctx):
    india = (ctx.shared.get("S3") or []) + (ctx.shared.get("S1_rows") or [])
    us = ctx.shared.get("S2_us") or []
    if not india and not us:
        raise RuntimeError("no headlines from the scrapers this run")
    st = _load("ai_news.json", {"rows": []})
    done = {r["id"] for r in st["rows"]}
    items = pick_items(india, us, done)
    llm, rb = (ctx.llm, None) if getattr(ctx, "llm", None) else _llm()
    parse = rb.parse_json_text if rb else (lambda s: json.loads(s))
    resolve = getattr(ctx, "resolve", None) or _name_index().resolve
    uni = set(json.loads((DATA / "aladin_e" / "latest.json").read_text(encoding="utf-8")).get("stocks", {}))
    try:
        graph = json.loads((DATA / "supply_graph.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        graph = {"edges": []}
    found, analysed, limit_hit = [], 0, None
    for k in range(0, len(items), BATCH):
        batch = items[k:k + BATCH]
        user = "\n".join(f"{j + 1}. [{'US' if r[1] == 'US' else 'India'}] {r[3]}" for j, r in enumerate(batch))
        try:
            ans = parse(llm.complete(SYSTEM, user)) or {}
        except Exception as e:  # noqa: BLE001
            if "quota" in str(e).lower() or "limit" in str(e).lower() or type(e).__name__ == "LLMBudget":
                limit_hit = str(e); break
            raise
        res = ans.get("items") or []
        found += interpret(res, batch, resolve, uni, graph)
        model = getattr(llm, "model", None) or "test"
        for r in res:
            try:
                it = batch[int(r.get("i")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            st["rows"].append({"id": it[0], "region": it[1], "title": it[3], "url": it[4], "src": it[5], "pub": it[6], "analysed": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "model": model, "event": r.get("event") if r.get("event") in EVENT_TYPES else "other", "effect": r.get("india_effect"), "confidence": r.get("confidence"),
                               "companies": r.get("companies") or [], "sectors": r.get("sectors") or [], "why": str(r.get("why") or "")[:160],
                               "syms": sorted({x for x in (resolve(str(n)) for n in (r.get("companies") or [])) if x})})
            analysed += 1
    cut = (ctx.now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st["rows"] = [r for r in st["rows"] if r["analysed"] >= cut]
    _save("ai_news.json", st)
    if limit_hit and not analysed:
        raise Limit(f"every free AI quota is used up for today ({limit_hit[:120]}); the next run continues")
    from collections import Counter
    recent = [r for r in st["rows"] if r["analysed"] >= (ctx.now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")]
    eff = Counter(r["effect"] for r in recent)
    secs = Counter(s for r in recent if r["effect"] != "none" for s in r["sectors"])
    return {"items": analysed, "as_of": ctx.now.isoformat(), "findings": found,
            "recent": sorted(recent, key=lambda r: r["analysed"], reverse=True)[:40],
            "detail": f"{analysed} new headlines read this run ({len(items)} picked, at most {MAX_US} US) by {getattr(llm, 'model', 'a free model')}; last 24 h: "
                      f"{eff.get('positive', 0)} positive, {eff.get('negative', 0)} negative, {eff.get('none', 0)} no clear effect for Indian stocks. "
                      + (f"Sectors most mentioned: {', '.join(f'{k} {v}' for k, v in secs.most_common(5))}. " if secs else "")
                      + f"{len(found)} findings (high confidence only: named companies and their supply-chain neighbours)."
                      + (f" Stopped early: {limit_hit[:80]}." if limit_hit else "")}


# ------------------------------------------------------------------ event historian

def collect_events(ctx, today, universe):
    """Rolling store of NSE announcements (EVENT_CATS, the 500 stocks) up to HIST_YEARS back: forward to today, then up to
    BACK_DAYS_PER_RUN further back each run. Rows: [seq_id, symbol, category, day]."""
    from .fundamental import _session, nse_day, REF
    st = _load("events_hist.json", {"from": None, "to": None, "rows": []})
    have = {r[0] for r in st["rows"]}
    nse, errs = _session(ctx), []
    def grab(a, b):
        j = nse.get_json("/api/corporate-announcements", {"index": "equities", "from_date": a.strftime("%d-%m-%Y"), "to_date": b.strftime("%d-%m-%Y")},
                         referer=REF + "corporate-filings-announcements", max_tries=2)
        for r in (j if isinstance(j, list) else j.get("data", [])) or []:
            if r.get("desc") in EVENT_CATS and r.get("symbol") in universe:
                row = [str(r.get("seq_id")), r.get("symbol"), r.get("desc"), nse_day(r.get("an_dt") or r.get("sort_date"))]
                if row[0] not in have and row[3]:
                    st["rows"].append(row); have.add(row[0])
    windows = []
    start_fwd = date.fromisoformat(st["to"]) - timedelta(days=2) if st.get("to") else today - timedelta(days=BACK_DAYS_PER_RUN)
    d = start_fwd
    while d <= today:
        windows.append((d, min(today, d + timedelta(days=2)), "fwd")); d += timedelta(days=3)
    oldest = date.fromisoformat(st["from"]) if st.get("from") else start_fwd
    limit = today - timedelta(days=365 * HIST_YEARS)
    if oldest > limit:
        d = oldest - timedelta(days=1)
        stop = max(limit, oldest - timedelta(days=BACK_DAYS_PER_RUN))
        while d > stop:
            windows.append((max(stop, d - timedelta(days=2)), d, "back")); d -= timedelta(days=3)
    new_to, new_from = st.get("to"), st.get("from") or start_fwd.isoformat()
    for a, b, kind in windows:
        try:
            grab(a, b)
            if kind == "fwd":
                new_to = b.isoformat()
            else:
                new_from = min(new_from, a.isoformat())
        except Exception as e:  # noqa: BLE001
            errs.append(f"{a}..{b}: {e}"); break
    st["to"], st["from"] = new_to, new_from
    _save("events_hist.json", st)
    return st, errs


def event_study(events, closes, index, hs=(5, 21)):
    """events: [(sym, day, category)]; closes: {sym: (dates, values)}; index: (dates, values) of NIFTY 500.
    -> {category: {"reaction": stat, "5": stat, "21": stat}}"""
    import bisect
    idd, idv = index
    ipos = {d: i for i, d in enumerate(idd)}
    acc = {}
    for sym, day, cat in events:
        if sym not in closes:
            continue
        sd, sv = closes[sym]
        spos = {d: i for i, d in enumerate(sd)}
        j = bisect.bisect_left(idd, day)                       # first session on or after the announcement day
        if j <= 0 or j + 1 >= len(idd):
            continue
        before, first_after = idd[j - 1], idd[j + 1] if idd[j] == day else idd[j]
        def r(a, b):
            if a in spos and b in spos and a in ipos and b in ipos and sv[spos[a]] and idv[ipos[a]]:
                return (sv[spos[b]] / sv[spos[a]] - 1) - (idv[ipos[b]] / idv[ipos[a]] - 1)
            return None
        k = ipos[first_after]
        vals = {"reaction": r(before, first_after)}
        for h in hs:
            vals[str(h)] = r(first_after, idd[k + h]) if k + h < len(idd) else None
        for key, v in vals.items():
            if v is not None and abs(v) < 2:
                acc.setdefault(cat, {}).setdefault(key, []).append((day[:7], v))
    out = {}
    for cat, by in acc.items():
        out[cat] = {}
        for key, pairs in by.items():
            xs = [v for _, v in pairs]
            n = len(xs); mu = sum(xs) / n
            months = {}
            for m, v in pairs:
                months.setdefault(m, []).append(v)
            mm = [sum(v) / len(v) for v in months.values()]                 # one value per month: events in one month move together
            k = len(mm)
            sd = math.sqrt(sum((x - sum(mm) / k) ** 2 for x in mm) / (k - 1)) if k > 1 else None
            half = 1.96 * sd / math.sqrt(k) if sd is not None else None
            lo, hi = (None, None) if half is None else (mu - half, mu + half)
            v = ("too few events" if n < 30 else f"too few months ({k} of {MIN_MONTHS})" if k < MIN_MONTHS
                 else "measurably above the market" if lo > 0 else "measurably below the market" if hi < 0 else "no measurable difference")
            out[cat][key] = {"n": n, "months": k, "mean_pct": round(mu * 100, 2), "ci95_pct": None if lo is None else [round(lo * 100, 2), round(hi * 100, 2)], "verdict": v}
    return out


def _closes(syms):
    from .technical import _rows, TERM, key
    out = {}
    for s in syms:
        rows = _rows(TERM / "daily" / f"{key(s)}.json")
        if rows:
            out[s] = ([r[0] for r in rows], [r[4] for r in rows])
    return out


def s7_historian(ctx):
    today = ctx.now.date()
    uni = set(json.loads((DATA / "aladin_e" / "latest.json").read_text(encoding="utf-8")).get("stocks", {}))
    st, errs = collect_events(ctx, today, uni)
    from .technical import _rows, TERM
    n5 = _rows(TERM / "idx" / "out" / "d" / "Nifty_20500.json")
    if len(n5) < 250:
        raise RuntimeError("NIFTY 500 prices are missing on this runner (the price cache was not restored)")
    index = ([r[0] for r in n5], [r[4] for r in n5])
    closes = _closes({r[1] for r in st["rows"]})
    events = [(r[1], r[3], r[2]) for r in st["rows"]]
    study = event_study(events, closes, index)
    ai = _load("ai_news.json", {"rows": []})["rows"]
    found, seen = [], set()
    recent = (today - timedelta(days=3)).isoformat()
    span = (date.fromisoformat(st["to"]) - date.fromisoformat(st["from"])).days if st.get("from") and st.get("to") else 0
    for r in st["rows"] if span >= MIN_SPAN_DAYS else []:
        c = (study.get(r[2]) or {}).get("21")
        if (r[1], r[2], r[3]) in seen:
            continue
        if r[3] >= recent and c and c["verdict"].startswith("measurably"):
            seen.add((r[1], r[2], r[3]))
            found.append({"sym": r[1], "kind": f"event: {r[2]}", "direction": 1 if "above" in c["verdict"] else -1, "event": f"hist {r[0]}",
                          "text": f"'{r[2]}' announced {r[3]}. In the last {HIST_YEARS} years, the 500 stocks' next 21 sessions after this kind of announcement averaged "
                                  f"{c['mean_pct']:+.2f}% against NIFTY 500 (range {c['ci95_pct'][0]:+.2f} to {c['ci95_pct'][1]:+.2f}%, {c['n']} events).",
                          "evidence": [{"src": "NSE announcement + B-Lab event study", "url": "", "quote": r[2]}]})
    meas = sorted(((k, v["21"]) for k, v in study.items() if "21" in v and v["21"]["verdict"].startswith("measurably")), key=lambda kv: -abs(kv[1]["mean_pct"]))
    ai_days = len({r["analysed"][:10] for r in ai})
    return {"items": len(st["rows"]), "as_of": ctx.now.isoformat(), "errors": errs[:3], "findings": found, "study": study,
            "history": {"from": st.get("from"), "to": st.get("to"), "events": len(st["rows"])},
            "detail": (f"History spans {span} days; findings start once it spans {MIN_SPAN_DAYS} (about {math.ceil((MIN_SPAN_DAYS - span) / BACK_DAYS_PER_RUN / 2)} more days of runs). " if span < MIN_SPAN_DAYS else "")
                      + f"{len(st['rows']):,} company announcements of the 500 stocks kept, {st.get('from')} to {st.get('to')} (filling back to {HIST_YEARS} years, "
                      f"{BACK_DAYS_PER_RUN} days a run). Categories with a measurable 21-session drift: "
                      + ("; ".join(f"{k} {v['mean_pct']:+.2f}% ({v['n']})" for k, v in meas[:6]) or "none yet")
                      + f". {len(found)} new announcements filed. The AI analyst's event types get the same study once 60 days of readings exist ({ai_days} so far)."}
