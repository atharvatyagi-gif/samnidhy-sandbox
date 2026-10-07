"""
The compliance wording check:   python scripts/check_banned.py [--existing]

1. NEW wording: the words buy / sell / target / recommendation / guaranteed (any case) must not appear in anything new the user can read: the new JavaScript modules, the new
   HTML blocks, the strings of our own config JSON, the README methodology block, and every KEY (at any depth) of every JSON file the site serves, plus the strings of the
   generated model file. Not counted, because it is not wording: the DOM property `event.target`, the link attribute target="_blank", stock symbols that contain the letters
   (BEARDSELL), and third-party headlines or filing quotes (they are quoted, not ours).
2. The mandatory disclaimer must be present, word for word, on the ALADIN view, the NEXUS panel and the Globe tab.
3. --existing lists the same words in the desk's OLDER code (terminal.js, terminal.css, expert-terminal.html outside the new blocks): analyst labels such as "Strong buy" and
   price-target figures that were there before the ALADIN work. They are reported, never silently changed; the owner decides whether to rename them.
Exit code 1 when 1 or 2 finds a problem. The report of 3 never fails the run.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"buy|sell|target|recommendation|guaranteed", re.I)
DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice."
NEW_JS = ["terminal-guide.js", "desk-houses.js", "desk-map.js", "desk-aladin.js", "desk-ticks.js", "desk-nexus.js", "desk-cmd.js", "desk-lanes.js", "desk-globe.js", "desk-deps.js", "desk-movers.js", "desk-sectors.js", "desk-kin.js", "desk-kin-live.js", "desk-globe3d.js"]
NEW_HTML = [r'<section class="view" id="v-houses">.*?</section>', r'<section class="view" id="v-lab">.*?</section>', r'<div class="geo-desk" id="geo-desk"></div>', r'<section class="view" id="v-map">.*?</section>']
CONFIG_JSON = ["business_houses.json", "geo_exposure.json", "aladin_method.json", "news_aliases.json", "tone_words.json", "aladin_config.json", "trade_lanes.json", "cargo_carriers.json"]            # nexus_sources.json is instructions to a model, not served and not shown
SERVED_JSON = ["aladin/latest.json", "aladin/sentiment.json", "aladin/geo.json", "aladin/moves.json", "aladin/shocks.json", "aladin/impact.json", "supply_graph.json",
               "config/business_houses.json", "config/aladin_method.json", "config/trade_lanes.json", "paper_trades/portfolio.json", "live_extra/aladin_telemetry.json"]
SYMBOL = re.compile(r"^[A-Z0-9&.\-]{1,24}$")                           # a key that is a stock symbol is data, not wording
THIRD_PARTY = {"title", "heads", "items", "q", "quote", "n", "name", "cpn", "desc", "headline"}      # text quoted from publishers, filings or the exchange


def strip_tokens(src):
    src = re.sub(r"\.target\b", ".X", src)
    return re.sub(r'target="_blank"', 'X="_blank"', src)


def hits(text):
    return sorted({m.group(0).lower() for m in BANNED.finditer(text)})


def keys_of(node, path=""):
    """Yield (path, key) for every dict key that is wording (not a symbol), at any depth."""
    if isinstance(node, dict):
        for k, v in node.items():
            if not SYMBOL.match(str(k)):
                yield path, str(k)
            if k not in THIRD_PARTY:
                yield from keys_of(v, f"{path}/{k}")
    elif isinstance(node, list):
        for v in node[:200]:
            yield from keys_of(v, path)


def strings_of(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in THIRD_PARTY:
                yield from strings_of(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings_of(v)


def check(root=ROOT):
    problems = []
    for name in NEW_JS:
        p = root / name
        if p.exists() and (h := hits(strip_tokens(p.read_text(encoding="utf-8")))):
            problems.append(f"{name}: {h}")
    html = (root / "expert-terminal.html").read_text(encoding="utf-8")
    for pat in NEW_HTML:
        m = re.search(pat, html, re.S)
        if not m:
            problems.append(f"HTML block not found: {pat[:40]}")
        elif h := hits(m.group(0)):
            problems.append(f"HTML {pat[:40]}: {h}")
    for name in CONFIG_JSON:
        p = root / "data" / "config" / name
        if p.exists() and (h := hits(" ".join(strings_of(json.loads(p.read_text(encoding="utf-8")))))):
            problems.append(f"data/config/{name} strings: {h}")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if "<!-- ALADIN-METHOD:START" in readme and (h := hits(readme[readme.index("<!-- ALADIN-METHOD:START"):readme.index("<!-- ALADIN-METHOD:END -->")])):
        problems.append(f"README methodology block: {h}")
    for rel in SERVED_JSON:
        p = root / "data" / rel
        if not p.exists():
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        bad = sorted({k for _, k in keys_of(doc) if hits(k)})
        if bad:
            problems.append(f"data/{rel} keys: {bad}")
        if rel == "aladin/latest.json":
            own = {k: v for k, v in doc.items() if k != "stocks"}
            if h := hits(" ".join(strings_of(own))):
                problems.append(f"data/{rel} strings: {h}")
    # the mandatory disclaimer, word for word
    for name, where in (("desk-aladin.js", "the ALADIN view"), ("desk-nexus.js", "the NEXUS panel")):
        if DISCLAIMER not in (root / name).read_text(encoding="utf-8"):
            problems.append(f"the disclaimer is missing from {where} ({name})")
    g = re.search(r'<section class="view" id="v-map">.*?</section>', html, re.S)
    if not g or DISCLAIMER not in g.group(0):
        problems.append("the disclaimer is missing from the Globe tab (expert-terminal.html)")
    return problems


def existing(root=ROOT):
    """Banned words in the desk's older code, one line each: (file, line number, the line, trimmed)."""
    out = []
    for name in ("terminal.js", "terminal.css", "expert-terminal.html"):
        p = root / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        if name == "expert-terminal.html":                           # the blocks that are new are checked above
            for pat in NEW_HTML:
                text = re.sub(pat, "", text, flags=re.S)
        for i, line in enumerate(text.splitlines(), 1):
            clean = strip_tokens(line)
            if hits(clean) and not clean.lstrip().startswith(("//", "/*", "*")):
                out.append((name, i, line.strip()[:170], hits(clean)))
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    problems = check()
    for p in problems:
        print("PROBLEM", p)
    print("banned-word and disclaimer check:", "FAILED" if problems else "ok")
    if "--existing" in argv:
        found = existing()
        print(f"\nOlder code (reported, not changed): {len(found)} line(s) with a banned word")
        for f, i, line, h in found:
            print(f"  {f}:{i}  [{', '.join(h)}]  {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
