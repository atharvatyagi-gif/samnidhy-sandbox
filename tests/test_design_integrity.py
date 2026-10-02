"""Design integrity (acceptance check 8) for the NEW code only: no colour literals outside :root, only existing CSS variables, wording rules."""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "terminal.css").read_text(encoding="utf-8")
LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\bhwb\(|\blab\(|\boklch\(")


def new_css():
    start = CSS.index("/* ---------- HOUSES ---------- */")
    return CSS[start:]


def root_vars():
    m = re.search(r":root\s*\{(.*?)\}", CSS, re.S)
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", m.group(1)))


def test_new_css_has_no_colour_literals():
    hits = [l for l in new_css().splitlines() if LITERAL.search(re.sub(r"/\*.*?\*/", "", l))]
    assert hits == [], hits[:5]


def test_new_css_uses_only_variables_that_exist():
    defined = root_vars() | {"--r"}
    used = set(re.findall(r"var\((--[a-z0-9-]+)", new_css()))
    assert used <= defined, sorted(used - defined)


def test_tab_overflow_rule_is_variable_only():
    m = re.search(r"@media \(max-width: 1280px\)\s*\{\s*\.tabs[^}]*\}", CSS)
    assert m is not None and not LITERAL.search(m.group(0))


def test_new_javascript_has_no_colour_literals():
    for name in ("desk-houses.js", "desk-map.js", "desk-aladin.js", "desk-ticks.js"):
        src = (ROOT / name).read_text(encoding="utf-8")
        body = re.sub(r"//.*|/\*.*?\*/", "", src, flags=re.S)
        # style="..." attributes may only reference variables; look for literal hex / rgb colours anywhere
        assert not re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![\w-])|\brgba?\(|\bhsla?\(", body), name


def test_new_html_blocks_have_no_colour_literals():
    html = (ROOT / "expert-terminal.html").read_text(encoding="utf-8")
    for block_id in ("v-houses", "v-lab"):
        m = re.search(rf'<section class="view" id="{block_id}">.*?</section>', html, re.S)
        assert m and not LITERAL.search(m.group(0)), block_id
    m = re.search(r'<div class="geo-desk" id="geo-desk"></div>', html)
    assert m


def test_existing_classes_are_reused_for_the_new_views():
    html = (ROOT / "expert-terminal.html").read_text(encoding="utf-8")
    for needed in ("page-head", "kick", "acc", "asof"):
        assert needed in re.search(r'id="v-houses">.*?</section>', html, re.S).group(0)
    js = (ROOT / "desk-aladin.js").read_text(encoding="utf-8") + (ROOT / "desk-houses.js").read_text(encoding="utf-8")
    for cls in ("ol-grid", "ol-stat", "ol-more", "tablecard", "tbl", "seg", "tag", "more-row", "sec-t", "tg-bar", "tg-top", "tg-n", "btn-line", "controls"):
        assert cls in js, cls


def test_all_workflows_parse_and_new_ones_never_deploy():
    for f in (ROOT / ".github" / "workflows").glob("*.yml"):
        yaml.safe_load(f.read_text(encoding="utf-8"))
    for name in ("aladin.yml", "aladin-sentiment.yml"):
        text = "\n".join(l for l in (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))      # comments may mention them
        assert "deploy-pages" not in text and "upload-pages-artifact" not in text and "build_site.py" not in text


def test_geo_summary_for_the_brief_is_tiny_and_honest():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site
    regions = [{"id": "a", "name": "A", "level": "High", "score": 71, "heads": [{"title": "t"}], "baseline": {"n": 120, "need": 48, "days": 6, "need_days": 3}},
               {"id": "b", "name": "B", "level": "Low", "score": 12, "heads": [], "baseline": {}}, {"id": "c", "name": "C", "level": "Building baseline", "score": None, "heads": []}]
    s = build_site.geo_summary({"generated_utc": "x", "regions": regions})
    assert s["top"] == {"id": "a", "name": "A", "level": "High", "score": 71, "head": "t"} and len(json.dumps(s)) < 500
    none = build_site.geo_summary({"regions": [{"id": "c", "score": None, "baseline": {"n": 5, "need": 48, "days": 1, "need_days": 3}}]})
    assert none["top"] is None and none["baseline"]["n"] == 5
