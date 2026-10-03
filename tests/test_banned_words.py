"""
Banned words (acceptance check 2): case-insensitive buy|sell|target|recommendation|guaranteed must not appear in anything NEW that the user can read:
the new JavaScript modules, the new HTML blocks, the new config JSON strings, the methodology text in the README, and the strings in the generated
aladin.json. Existing code is excluded (override 8).

Not counted, because they are not wording: the DOM property `event.target` and the HTML attribute `target="_blank"` in JavaScript, stock symbols that
happen to contain the letters (a company called BEARDSELL), and third-party headlines (sentiment.json / geo.json items are quoted from publishers).
Python modules are checked for user-facing strings only through the JSON and the tab; their identifiers and NSE's own "BUY"/"SELL" deal-side codes are data-format constants.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"buy|sell|target|recommendation|guaranteed", re.I)


def strip_js_tokens(src):
    src = re.sub(r"\.target\b", ".X", src)                        # event.target
    src = re.sub(r'target="_blank"', 'X="_blank"', src)             # link attribute
    return src


def hits(text):
    return sorted({m.group(0).lower() for m in BANNED.finditer(text)})


def test_new_javascript_modules():
    for name in ("desk-houses.js", "desk-map.js", "desk-aladin.js", "desk-ticks.js", "desk-nexus.js"):
        assert hits(strip_js_tokens((ROOT / name).read_text(encoding="utf-8"))) == [], name


def test_new_html_blocks():
    html = (ROOT / "expert-terminal.html").read_text(encoding="utf-8")
    for pat in (r'<section class="view" id="v-houses">.*?</section>', r'<section class="view" id="v-lab">.*?</section>', r'<div class="geo-desk" id="geo-desk"></div>'):
        m = re.search(pat, html, re.S)
        assert m and hits(m.group(0)) == [], pat


def test_new_config_json_strings():
    for name in ("business_houses.json", "geo_exposure.json", "aladin_method.json", "news_aliases.json", "tone_words.json", "aladin_config.json"):
        assert hits((ROOT / "data" / "config" / name).read_text(encoding="utf-8")) == [], name


def test_readme_methodology_block():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    a, b = text.index("<!-- ALADIN-METHOD:START"), text.index("<!-- ALADIN-METHOD:END -->")
    assert hits(text[a:b]) == []


def test_generated_aladin_json_strings():
    p = ROOT / "data" / "aladin" / "latest.json"
    if not p.exists():
        return
    d = json.loads(p.read_text(encoding="utf-8"))
    d = {**d, "stocks": {}}                                                                  # symbols are data; the per-stock strings are driver names and the like
    assert hits(json.dumps(d)) == []
    for e in json.loads(p.read_text(encoding="utf-8"))["stocks"].values():
        assert hits(json.dumps(e)) == []


def test_paper_trader_caption_and_disclaimer_wording():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import paper_trader
    assert hits(paper_trader.CAPTION) == [] and paper_trader.CAPTION.startswith("Simulated. Not real trades.")
