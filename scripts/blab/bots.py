"""B-Lab bots: the registry (docs/blab/PLAN.md, section 2). Step 1: scouts that report on the jobs the site already runs, plus
one analyst built on an existing scorer; everything else is listed as planned with the step that builds it.
Files kept in git are read from the repository; files that are not (price caches, the news wire) are read from the live site,
so a run on any computer sees what visitors see.

MECE by source: a bot reads only its own division's kind of source (company/regulator filings; trading data; official
statistics; what people write). Where an existing job mixes sources, the bot takes only its own part and says so."""
from __future__ import annotations

from .core import Bot
from .fundamental import f2_ownership, f3_governance, f5_blind_spots
from .technical import t2_flows, t3_regime, t4_lab, t5_analogs


def _f1_statements(ctx):
    a, where = ctx.read("data/aladin/latest.json")
    fund = {s: x["f"] for s, x in a.get("stocks", {}).items() if isinstance(x.get("f"), dict) and x["f"].get("sc") is not None}
    try:
        tf, _ = ctx.read(site_path="t/fund.json")
        n_tf = len(tf.get("cos") or tf.get("stocks") or tf) if isinstance(tf, dict) else None
    except Exception:  # noqa: BLE001  the second source is optional; its absence is stated
        n_tf = None
    return {"items": len(fund), "as_of": a.get("generated_utc"),
            "detail": f"Fundamental scores for {len(fund)} stocks (value, quality, fundamental momentum, distress band) from the nightly ALADIN fundamentals job"
                      + (f"; company profiles for {n_tf} stocks on the site." if n_tf else "; the site's company-profile file could not be read this run.")}


def _f4_related(ctx):
    g, _ = ctx.read("data/supply_graph.json")
    rp, _ = ctx.read("data/revenue_profile.json")
    bh, _ = ctx.read("data/config/business_houses.json")
    edges, cos = len(g.get("edges", [])), len(g.get("cos", {}))
    return {"items": edges, "as_of": g.get("generated_utc"),
            "detail": f"NEXUS supply graph: {edges:,} links among {cos:,} companies from their own filings; revenue profiles for {len(rp.get('cos', {})):,}; "
                      f"{len(bh.get('houses', []))} business groups. The graph is saved only when its audit passes, so its date shows when it last passed."}


def _t1_prices(ctx):
    q, _ = ctx.read(site_path="t/quotes.json")
    n5, _ = ctx.read(site_path="t/x/d/Nifty_20500.json")
    last = (n5.get("d") or [[None]])[-1][0]
    return {"items": q.get("covered") or len(q.get("quotes", {})), "as_of": last,
            "detail": f"End-of-day prices for {q.get('covered')} of {q.get('main_board')} main-board stocks (session {q.get('session_date')}); NIFTY 500 to {last}."}


def _s1_india_media(ctx):
    w, _ = ctx.read(site_path="news.json")
    srcs = [s for g in w.get("groups", []) for s in g.get("sources", [])]
    items = sum(len(s.get("items", [])) for s in srcs)
    return {"items": items, "as_of": w.get("generated_utc"),
            "detail": f"{items} headlines from {len(srcs)} feeds ({', '.join(s['name'] for s in srcs[:4])}{'…' if len(srcs) > 4 else ''}) by the existing news wire."}


def _s2_global(ctx):
    g, _ = ctx.read("data/globe/latest.json")
    geo, _ = ctx.read("data/aladin/geo.json")
    ev = g.get("events", [])
    return {"items": len(ev), "as_of": g.get("generated_utc"),
            "detail": f"{len(ev)} world events (GDELT) and news around {len(g.get('chokepoints', []))} shipping and oil chokepoints; {len(geo.get('regions', []) if isinstance(geo.get('regions'), list) else geo.get('regions', {}))} regions scored for news attention."}


def _s4_social(ctx):
    s, _ = ctx.read("data/aladin/sentiment.json")
    rn = sum((x.get("rn") or 0) for x in s.get("stocks", {}).values())
    return {"items": rn, "as_of": s.get("generated_utc"),
            "detail": f"Retail chatter: {rn} posts matched to stocks in the latest window, read by the existing sentiment job only when Reddit is reachable. "
                      "Its terms need approval for commercial use; kept as it is until the owner decides (plan, section 7)."}


TONE_MIN, NAMED_MIN = 0.25, 2      # S5's rule, declared before any scoring: average headline tone beyond +/-0.25 over at least 2 headlines that NAME the stock


def _s5_scorer(ctx):
    """Headline scorer: the existing FinBERT scores, NEWS ONLY (the job's combined level also mixes in FII flow, which is
    Technical's source; MECE keeps it out). A finding when the stock's own named headlines lean one way under the rule above."""
    s, _ = ctx.read("data/aladin/sentiment.json")
    found = []
    for sym, x in s.get("stocks", {}).items():
        named = [it for it in x.get("items", []) if len(it) >= 6 and it[5] == "name" and isinstance(it[4], (int, float))]
        if len(named) < NAMED_MIN:
            continue
        tone = sum(it[4] for it in named) / len(named)
        if abs(tone) < TONE_MIN:
            continue
        found.append({"sym": sym, "kind": "headline tone", "direction": 1 if tone > 0 else -1,
                      "text": f"{len(named)} headlines naming {sym} lean {'positive' if tone > 0 else 'negative'} (average tone {tone:+.2f} on -1 to +1).",
                      "evidence": [{"src": it[2], "url": it[1], "quote": it[0][:160]} for it in named[:3]]})
    return {"items": len(s.get("stocks", {})), "as_of": s.get("generated_utc"), "findings": found,
            "detail": f"FinBERT tone of headlines for {len(s.get('stocks', {}))} stocks (existing sentiment job, news part only). "
                      f"Rule: a finding when at least {NAMED_MIN} headlines name the stock and their average tone is beyond ±{TONE_MIN}; {len(found)} this run."}


B = Bot
BOTS = [
    # Fundamental: what the company or a regulator files
    B("F1", "fundamental", "Statements scout", "scout", "Collects results and statements and the fundamental scores built from them.", ["Yahoo Finance statements", "NSE results"], 60, _f1_statements, 1, "scripts/aladin_fund.py, scripts/terminal_fund.py"),
    B("F2", "fundamental", "Ownership scout", "scout", "Promoter and public shareholding each quarter; takeover-code (SAST Reg 29) acquisitions and sales by large holders and promoters.", ["NSE shareholding pattern", "NSE SAST Reg 29 disclosures"], 100, f2_ownership, 2),
    B("F3", "fundamental", "Governance scout", "scout", "Collects governance announcements: auditors, ratings, delayed results, insolvency, pledges, related-party deals, litigation, regulator actions.", ["NSE corporate announcements"], 100, f3_governance, 2, "also reports the tone reading of scripts/aladin_filings.py"),
    B("F4", "fundamental", "Related-party scout", "scout", "Related-party deals, group companies and who depends on whom, from the companies' own filings.", ["Annual-report segment notes", "BRSR", "Business-group list"], 24 * 8, _f4_related, 1, "NEXUS (scripts/supply_graph build, revenue_profile.py, brsr_profile.py)"),
    B("F5", "fundamental", "Blind-spot analyst", "analyst", "Nine red-flag tests on ownership, governance and the annual statements, each finding citing its filing.", ["F2", "F3", "annual statements"], 100, f5_blind_spots, 2),
    # Technical: what trading produces
    B("T1", "technical", "Price scout", "scout", "End-of-day prices, volume and every NSE index.", ["NSE end-of-day files", "Yahoo Finance"], 100, _t1_prices, 1, "scripts/nse_eod.py, scripts/terminal_hist.py, scripts/indices_eod.py"),
    B("T2", "technical", "Flows scout", "scout", "FII/DII flows and NSE's bulk, block and short deals; F&O open interest not measured yet.", ["NSE FII/DII report", "NSE large deals"], 100, t2_flows, 3, "also the daily update's FII/DII step"),
    B("T3", "technical", "Regime bot", "analyst", "Today's market state (trend x volatility) from NIFTY 50 history since 2007, with breadth.", ["NSE index history", "history branch"], 100, t3_regime, 3),
    B("T4", "technical", "Strategy lab", "analyst", "Six fixed strategies tested in every past market state after costs; files the picks of those measurably better in today's.", ["NSE prices of the 500 stocks since 1996"], 24 * 8, t4_lab, 3),
    B("T5", "technical", "Analog finder", "analyst", "The 10 past days most like today and what NIFTY 50 and Bank Nifty did next.", ["NSE index history"], 100, t5_analogs, 3),
    # Macro: official statistics
    B("M1", "macro", "India scout", "scout", "RBI (repo, liquidity, credit, reserves) and MOSPI (CPI, IIP, GDP).", ["RBI DBIE", "MOSPI"], 24 * 45, None, 4),
    B("M2", "macro", "Global scout", "scout", "US and global rates, inflation, dollar, and India series, from FRED and the World Bank.", ["FRED (free key)", "World Bank API"], 24 * 45, None, 4),
    B("M3", "macro", "Market-macro scout", "scout", "Crude, gold, USD/INR and the US 10-year yield, daily.", ["Yahoo Finance"], 100, None, 4),
    B("M4", "macro", "Macro analyst", "analyst", "Today's macro state and its tested outcome for the NIFTY 500, sectors and strategies.", ["M1-M3", "T4"], 100, None, 4),
    # Sentiment: what other people write or say
    B("S1", "sentiment", "India media scraper", "scout", "Indian business media headlines.", ["Economic Times, Mint, Business Standard RSS", "Google News"], 6, _s1_india_media, 1, "scripts/news_wire.py"),
    B("S2", "sentiment", "Global & macro scraper", "scout", "World events and news around shipping and oil chokepoints.", ["GDELT", "global wires"], 6, _s2_global, 1, "scripts/globe_data.py"),
    B("S3", "sentiment", "Sector scraper", "scout", "Industry and regulator news per sector.", ["sector RSS feeds"], 24, None, 5),
    B("S4", "sentiment", "Social scraper", "scout", "Retail chatter, only where the source's terms allow.", ["Reddit (existing job, when reachable)"], 6, _s4_social, 1, "scripts/aladin_sentiment_engine.py"),
    B("S5", "sentiment", "Headline scorer", "analyst", "Scores the tone of headlines that name a stock (FinBERT, news only).", ["S1"], 6, _s5_scorer, 1, "scripts/aladin_sentiment_engine.py (news part)"),
    B("S6", "sentiment", "News analyst (AI)", "analyst", "Reads the day's key news: event, who is named, and which stocks are exposed without being named.", ["S1-S4", "NEXUS graph", "GitHub Models (free)"], 24, None, 5),
    B("S7", "sentiment", "Event historian", "analyst", "Which stocks moved after similar events in the past.", ["GDELT history", "T1"], 24, None, 5),
]
