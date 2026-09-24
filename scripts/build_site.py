"""
Builds the public website into site/:

  site/index.html          the latest session (same as dashboard.html)
  site/days/<date>.html    one page per saved session, from data/archive/<date>.json

Every page is fully self-contained (data inside the page), so it also works offline.
site/ is a build output: it is not stored in git; GitHub Actions rebuilds and publishes it.

  python scripts/build_site.py
"""

import shutil
from pathlib import Path

from embed_data import DATA, HTML_PATH, embed, read_json, sessions_summary

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def main() -> None:
    template = HTML_PATH.read_text(encoding="utf-8")
    status = read_json(DATA / "status.json")
    sessions = sessions_summary()

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "days").mkdir(parents=True)

    (SITE / "index.html").write_text(embed(template, {
        "dashboard-data": read_json(DATA / "data.json"),
        "dashboard-status": status,
        "dashboard-sessions": sessions,
        "dashboard-meta": {"view": "latest", "days_prefix": "days/", "home": "index.html"},
    }), encoding="utf-8")

    archive = sorted((DATA / "archive").glob("????-??-??.json"))
    for f in archive:
        (SITE / "days" / f.name.replace(".json", ".html")).write_text(embed(template, {
            "dashboard-data": read_json(f),
            "dashboard-status": status,
            "dashboard-sessions": sessions,
            "dashboard-meta": {"view": "archive", "days_prefix": "", "home": "../index.html"},
        }), encoding="utf-8")

    (SITE / ".nojekyll").write_text("", encoding="utf-8")  # tell GitHub Pages to serve files as-is
    print(f"Built site/index.html and {len(archive)} past-session page(s) in site/days/")


if __name__ == "__main__":
    main()
