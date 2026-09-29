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

import shutil
from pathlib import Path

from embed_data import ADVANCED_PATH, DATA, HTML_PATH, SCREENER, advanced_blocks, embed, read_json, sessions_summary

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
STATIC = ["index.html", "landing.css", "landing.js", "auth.html", "auth-check.js", "config.js",
          "expert-terminal.html", "terminal.css", "terminal.js", "reload-home.js"]
TERMINAL = ROOT / "data" / "terminal"


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
        }), encoding="utf-8")

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
    for sub, dst in (("hist", "h"), ("intra", "i")):
        if (TERMINAL / sub).exists():
            shutil.copytree(TERMINAL / sub, SITE / "t" / dst)
    if (DATA / "institutional" / "fii_dii.json").exists():   # the Advanced page refreshes FII/DII from this
        shutil.copyfile(DATA / "institutional" / "fii_dii.json", SITE / "institutional.json")
    if (SCREENER / "latest.json").exists():   # the terminal reads the screen as a separate file
        (SITE / "screener.json").write_text((SCREENER / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")

    (SITE / ".nojekyll").write_text("", encoding="utf-8")  # tell GitHub Pages to serve files as-is
    print(f"Built site/ (landing, sandbox, advanced, expert access) and {len(archive)} past-session page(s) in site/days/")


if __name__ == "__main__":
    main()
