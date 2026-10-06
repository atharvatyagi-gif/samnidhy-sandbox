"""
Neutral names for the analyst and institutional fields we pass through from Yahoo Finance and NSE.

The sources call them recommendationKey ("strong_buy", "buy", "hold", "underperform", "sell"), targetMeanPrice / targetHighPrice / targetLowPrice, and the FII/DII report's
buyValue / sellValue. Our pages and served JSON use neutral words instead (consensus: strongly_positive ... strongly_negative; price estimates; money in / money out), so no
file we serve, and no label a student reads, tells anyone to buy or sell. The conversions are idempotent (already-converted data passes through unchanged), so older saved files and
new ones can be mixed freely. Used by the producers (screener.py, terminal_fund.py, institutional.py) and by build_site.py / embed_data.py when they publish.
"""
POSITIVE = {"strong_buy": "strongly_positive", "buy": "positive", "hold": "neutral", "underperform": "negative", "sell": "strongly_negative"}
SCREENER_KEYS = {"recommendation": "consensus", "recommendation_mean": "consensus_score", "target_mean": "estimate_mean", "target_high": "estimate_high", "target_low": "estimate_low"}
FUND_KEYS = {"tgt": "est", "tgt_hi": "est_hi", "tgt_lo": "est_lo"}
FLOW_KEYS = {"buy_cr": "in_cr", "sell_cr": "out_cr"}


def consensus(v):
    """Yahoo's recommendationKey -> our neutral word (anything else, including None, passes through)."""
    return POSITIVE.get(v, v)


def _rename(row, keys):
    return {keys.get(k, k): v for k, v in row.items()}


def screener_row(row):
    r = _rename(row, SCREENER_KEYS)
    if "consensus" in r:
        r["consensus"] = consensus(r["consensus"])
    return r


def fund_row(row):
    r = _rename(row, FUND_KEYS)
    if "rec" in r:
        r["rec"] = consensus(r["rec"])
    return r


def screener_doc(doc):
    if not isinstance(doc, dict) or "picks" not in doc:
        return doc
    return {**doc, "picks": [screener_row(p) for p in doc["picks"]]}


def fund_doc(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("stocks"), dict):
        return doc
    return {**doc, "stocks": {s: fund_row(r) for s, r in doc["stocks"].items()}}


def flow_doc(doc):
    if not isinstance(doc, dict) or "days" not in doc:
        return doc
    return {**doc, "days": [{**d, **{side: _rename(d[side], FLOW_KEYS) for side in ("fii", "dii") if isinstance(d.get(side), dict)}} for d in doc["days"]]}
