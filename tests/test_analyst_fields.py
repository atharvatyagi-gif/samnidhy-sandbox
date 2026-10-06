"""Neutral names for analyst and institutional fields (the banned-word clean-up): conversions are idempotent, every served JSON is clean, no page code uses the old names."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analyst_fields as af  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_consensus_words_are_mapped_and_the_rest_passes_through():
    assert [af.consensus(v) for v in ("strong_buy", "buy", "hold", "underperform", "sell")] == ["strongly_positive", "positive", "neutral", "negative", "strongly_negative"]
    assert af.consensus(None) is None and af.consensus("strongly_positive") == "strongly_positive" and af.consensus("something else") == "something else"


def test_screener_fund_and_flow_documents_convert_and_conversion_is_idempotent():
    s = {"picks": [{"symbol": "A", "recommendation": "buy", "recommendation_mean": 2.2, "target_mean": 10, "target_high": 12, "target_low": 8, "pe": 3}]}
    c = af.screener_doc(s)
    assert c["picks"][0] == {"symbol": "A", "consensus": "positive", "consensus_score": 2.2, "estimate_mean": 10, "estimate_high": 12, "estimate_low": 8, "pe": 3}
    assert af.screener_doc(c) == c and s["picks"][0]["recommendation"] == "buy"                  # the input is not mutated
    f = {"generated_ist": "x", "stocks": {"A": {"tgt": 5, "tgt_hi": 6, "tgt_lo": 4, "rec": "strong_buy", "an": 3}, "B": {"rec": None}}}
    g = af.fund_doc(f)
    assert g["stocks"]["A"] == {"est": 5, "est_hi": 6, "est_lo": 4, "rec": "strongly_positive", "an": 3} and g["stocks"]["B"] == {"rec": None} and af.fund_doc(g) == g
    i = {"days": [{"date": "d", "fii": {"buy_cr": 1.0, "sell_cr": 2.0, "net_cr": -1.0}, "dii": {"buy_cr": 3.0, "sell_cr": 1.0, "net_cr": 2.0}}], "source": "NSE"}
    h = af.flow_doc(i)
    assert h["days"][0]["fii"] == {"in_cr": 1.0, "out_cr": 2.0, "net_cr": -1.0} and af.flow_doc(h) == h
    assert af.screener_doc({}) == {} and af.fund_doc({}) == {} and af.flow_doc({}) == {}               # a missing or empty file stays empty


def test_the_published_json_has_no_banned_key_or_value_and_the_pages_use_the_new_names():
    import build_site  # noqa: F401  (imports analyst_fields the way the publisher does)
    scr = ROOT / "data" / "screener" / "latest.json"
    if scr.exists():
        doc = af.screener_doc(json.loads(scr.read_text(encoding="utf-8")))
        text = json.dumps(doc)
        assert not re.search(r'"(recommendation\w*|target_\w+)"|"(strong_buy|buy|sell|underperform)"', text)
    adv = (ROOT / "advanced.html").read_text(encoding="utf-8")
    js = adv[adv.index("const recoWord"):adv.index("const recoWord") + 200]
    assert "strongly_positive" in js and "strong_buy" not in js
    for name in ("terminal.js", "chart-engine.js", "chart-indicators.js"):
        code = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"\.(tgt|tgt_hi|tgt_lo)\b|\brecommend\(|\.recommended\b|\bbuyHold\b|\bstrong_buy\b|\.sc\.buy|sc\.sell", code), name
    assert "Recommended for" not in (ROOT / "chart-engine.js").read_text(encoding="utf-8")
