"""
Builds the public website into site/:

  site/index.html          The B-Lab Cohort: landing page (index.html + landing.css/js)
  site/sandbox.html        the daily movers dashboard, latest session (same as dashboard.html)
  site/days/<date>.html    one page per saved session, from data/archive/<date>.json
  site/advanced.html       the Advanced page (daily screen + live technicals)
  site/live.json           latest live prices, polled by the Advanced page between rebuilds

Every page is fully self-contained (data inside the page), so it also works offline.
site/ is a build output: it is not stored in git; GitHub Actions rebuilds and publishes it.

  python scripts/build_site.py
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

from embed_data import ADVANCED_PATH, DATA, HTML_PATH, SCREENER, advanced_blocks, embed, read_json, sessions_summary

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
STATIC = ["index.html", "landing.css", "landing.js", "auth.html", "auth-check.js", "config.js",
          "expert-terminal.html", "terminal.css", "terminal.js", "reload-home.js",
          "chart-engine.js", "chart-indicators.js", "mode-dock.js", "globe-map.js",
          "desk-houses.js", "desk-map.js", "desk-aladin.js", "desk-ticks.js", "desk-nexus.js", "desk-cmd.js", "desk-lanes.js", "desk-globe.js", "desk-deps.js", "desk-movers.js", "desk-sectors.js"]
TERMINAL = ROOT / "data" / "terminal"
# Scripts/styles that pages load. Browsers keep these for a while (GitHub Pages: 10 min, some longer), so an
# update could mix a new page with an old script. Every reference gets ?v=<hash of the file>, which changes
# only when the file does. Leaves first: auth-check.js imports config.js, so its own hash covers that version.
# ORDER MATTERS: a file must come AFTER every file it imports (desk-map imports desk-aladin, which imports desk-ticks), because each file is stamped with
# the hashes of the files before it. Out of order, an import keeps its plain address while the page loads the hashed one, and the browser runs the file
# twice as two separate modules (one of them never initialised). tests/test_build_assets.py checks this.
ASSETS = ["config.js", "reload-home.js", "mode-dock.js", "landing.css", "landing.js", "terminal.css", "chart-indicators.js", "chart-engine.js", "globe-map.js", "desk-ticks.js", "desk-lanes.js", "desk-deps.js", "desk-nexus.js", "desk-cmd.js", "desk-aladin.js", "desk-movers.js", "desk-sectors.js", "desk-globe.js", "desk-map.js", "desk-houses.js", "terminal.js", "auth-check.js"]


def geo_summary(g: dict) -> dict:
    """A few hundred bytes for the regime strip and the Brief, so geo.json itself can stay lazy: the highest-scoring region (if any region has a score yet)."""
    scored = [r for r in g.get("regions", []) if r.get("score") is not None]
    top = max(scored, key=lambda r: r["score"]) if scored else None
    first = (g.get("regions") or [{}])[0].get("baseline", {})
    return {"generated_utc": g.get("generated_utc"), "baseline": {k: first.get(k) for k in ("n", "need", "days", "need_days")},
            "top": None if top is None else {"id": top["id"], "name": top["name"], "level": top["level"], "score": top["score"], "head": ((top.get("heads") or [{}])[0]).get("title")}}


def version_assets() -> None:
    names = "|".join(re.escape(a) for a in ASSETS)
    ref = re.compile(r'((?:src|href)="(?:\.\./)?|from "\./)(' + names + r')(?=")')
    ver = {}
    def stamp(path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        new = ref.sub(lambda m: f"{m.group(1)}{m.group(2)}?v={ver[m.group(2)]}" if m.group(2) in ver else m.group(0), text)
        if new != text:
            path.write_text(new, encoding="utf-8")
    for a in ASSETS:
        if (SITE / a).exists():
            stamp(SITE / a)
            ver[a] = hashlib.sha256((SITE / a).read_bytes()).hexdigest()[:10]
    for page in list(SITE.glob("*.html")) + list((SITE / "days").glob("*.html")):
        stamp(page)


def main() -> None:
    template = HTML_PATH.read_text(encoding="utf-8")
    status = read_json(DATA / "status.json")
    sessions = sessions_summary()

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "days").mkdir(parents=True)

    (SITE / "sandbox.html").write_text(embed(template, {
        "dashboard-data": read_json(DATA / "data.json"),
        "dashboard-status": status,
        "dashboard-sessions": sessions,
        "dashboard-meta": {"view": "latest", "days_prefix": "days/", "home": "sandbox.html"},
    }), encoding="utf-8")

    archive = sorted((DATA / "archive").glob("????-??-??.json"))
    for f in archive:
        (SITE / "days" / f.name.replace(".json", ".html")).write_text(embed(template, {
            "dashboard-data": read_json(f),
            "dashboard-status": status,
            "dashboard-sessions": sessions,
            "dashboard-meta": {"view": "archive", "days_prefix": "", "home": "../sandbox.html"},
        }).replace('src="mode-dock.js"', 'src="../mode-dock.js"'), encoding="utf-8")

    (SITE / "advanced.html").write_text(embed(ADVANCED_PATH.read_text(encoding="utf-8"), advanced_blocks()), encoding="utf-8")
    if (SCREENER / "live.json").exists():
        (SITE / "live.json").write_text((SCREENER / "live.json").read_text(encoding="utf-8"), encoding="utf-8")

    # The B-Lab Cohort: landing page, Expert access and the terminal are static files, copied as they are.
    for name in STATIC:
        shutil.copyfile(ROOT / name, SITE / name)
    # all-NSE data for the terminal: t/universe.json, t/quotes.json, t/fund.json, t/h/*.json, t/i/*.json
    (SITE / "t").mkdir()
    for name in ("universe.json", "quotes.json", "fund.json"):
        if (TERMINAL / name).exists():
            shutil.copyfile(TERMINAL / name, SITE / "t" / name)
    for sub, dst in (("hist", "h"), ("intra", "i"), ("daily", "d"), ("replay", "r")):
        if (TERMINAL / sub).exists():
            shutil.copytree(TERMINAL / sub, SITE / "t" / dst, ignore=shutil.ignore_patterns("_meta.json"))
    if (DATA / "institutional" / "fii_dii.json").exists():   # the Advanced page refreshes FII/DII from this
        shutil.copyfile(DATA / "institutional" / "fii_dii.json", SITE / "institutional.json")
    if (DATA / "predict" / "latest.json").exists():   # the terminal's Outlook tab (scripts/predict_model.py)
        shutil.copyfile(DATA / "predict" / "latest.json", SITE / "predict.json")
    if (DATA / "nse_live" / "latest.json").exists():   # NSE's own live indices/movers (scripts/nse_live_poll.py)
        shutil.copyfile(DATA / "nse_live" / "latest.json", SITE / "nse_live.json")
    if (DATA / "globe" / "latest.json").exists():   # live flights + real geopolitical news (scripts/globe_data.py)
        shutil.copyfile(DATA / "globe" / "latest.json", SITE / "globe.json")
    if (DATA / "globe" / "layers").exists():   # slow-changing map layers, regenerated weekly (scripts/globe_layers.py)
        shutil.copytree(DATA / "globe" / "layers", SITE / "globe" / "layers", dirs_exist_ok=True)
    if (DATA / "status.json").exists():   # the main page checks this to load a newer session by itself
        shutil.copyfile(DATA / "status.json", SITE / "status.json")
    if (DATA / "news" / "wire.json").exists():   # the terminal's News tab (scripts/news_wire.py)
        shutil.copyfile(DATA / "news" / "wire.json", SITE / "news.json")
    # ALADIN / Houses / geo tension / paper trades: each file is copied only if it exists, and desk_data.json lists
    # which ones do, so the page requests only those (no console 404s while a file hasn't been produced yet).
    # data/live_extra/ticks.json is deliberately NEVER copied: it's the operator's own live feed (NSE's website
    # terms restrict redistributing it) and must not be published.
    desk = {"aladin": DATA / "aladin" / "latest.json", "sentiment": DATA / "aladin" / "sentiment.json", "geo": DATA / "aladin" / "geo.json",
            "houses": DATA / "config" / "business_houses.json", "paper": DATA / "paper_trades" / "portfolio.json", "method": DATA / "config" / "aladin_method.json",
            "graph": DATA / "supply_graph.json", "shocks": DATA / "aladin" / "shocks.json",
            "lanes": DATA / "config" / "trade_lanes.json", "moves": DATA / "aladin" / "moves.json",
            "transport": DATA / "live_extra" / "transport.json"}                 # the ONE file from live_extra that is published: positions from OpenSky / AISstream, never the tick feed
    present = {}
    for key, src in desk.items():
        present[key] = src.exists()
        if src.exists():
            shutil.copyfile(src, SITE / {"aladin": "aladin.json", "sentiment": "sentiment.json", "geo": "geo.json", "houses": "houses.json", "paper": "paper.json", "method": "aladin_method.json", "graph": "supply_graph.json", "shocks": "shocks.json", "lanes": "trade_lanes.json", "transport": "transport.json", "moves": "aladin_moves.json"}[key])
    # geo.json itself loads only when the Globe tab is opened; this tiny summary (a few hundred bytes) is what the regime strip and the Brief read.
    present["geo_summary"] = False
    if present.get("geo"):
        try:
            g = json.loads((SITE / "geo.json").read_text(encoding="utf-8"))
            (SITE / "geo_summary.json").write_text(json.dumps(geo_summary(g), ensure_ascii=False), encoding="utf-8")
            present["geo_summary"] = True
        except (OSError, ValueError, KeyError):
            pass
    (SITE / "desk_data.json").write_text(json.dumps(present), encoding="utf-8")
    if (SCREENER / "latest.json").exists():   # the terminal reads the screen as a separate file
        (SITE / "screener.json").write_text((SCREENER / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")

    version_assets()
    (SITE / ".nojekyll").write_text("", encoding="utf-8")  # tell GitHub Pages to serve files as-is
    print(f"Built site/ (landing, sandbox, advanced, expert access) and {len(archive)} past-session page(s) in site/days/")


if __name__ == "__main__":
    main()
