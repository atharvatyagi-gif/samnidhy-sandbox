"""
Financial news wire for the Expert terminal's News tab -> data/news/wire.json

Global business news comes from brutalist.report (a plain-text headline aggregator; robots.txt allows all):
  - its Business topic page (CNBC, MarketWatch, Fortune, Business Insider, Zero Hedge, FastCompany, HBR,
    Yahoo Finance), and
  - its WSJ, Quartz and Coindesk source pages.
Indian market news comes straight from the publishers' own RSS feeds (brutalist.report has no Indian sources):
  Economic Times Markets, Business Standard Markets, Mint Markets.

Headlines and links only (every link goes to the original article). An article's age is what the source
says: brutalist.report's "[35m]" label, or the RSS pubDate. A source that fails keeps its last good
headlines from the previous file; nothing is made up.

  python scripts/news_wire.py
"""

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "news" / "wire.json"
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Samnidhy B-Lab news wire; educational)"}
BR = "https://brutalist.report"
BR_SOURCES = [("wsj", "The Wall Street Journal"), ("quartz", "Quartz"), ("coindesk", "Coindesk")]
RSS = [
    ("Economic Times · Markets", "https://economictimes.indiatimes.com/markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Business Standard · Markets", "https://www.business-standard.com/markets", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Mint · Markets", "https://www.livemint.com/market", "https://www.livemint.com/rss/markets"),
]
MAX_ITEMS = 40
ITEM = re.compile(r'<li><a href="([^"]+)">(.*?)</a>\s*\[([^\]]+)\]', re.S)
BLOCK = re.compile(r'<h3><a href="(/source/[^"]+)">([^<]+)</a></h3>\s*<ul>(.*?)</ul>', re.S)


def age_minutes(label):
    """'35m' -> 35, '2h' -> 120, '1d' -> 1440 (brutalist.report's own label)."""
    m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", label)
    return None if not m else int(m.group(1)) * {"m": 1, "h": 60, "d": 1440}[m.group(2)]


def clean(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()


def br_items(body):
    out = []
    for url, title, age in ITEM.findall(body):
        t = clean(title)
        if t and url.startswith("http"):
            out.append({"t": t, "u": url, "age": age.strip(), "age_min": age_minutes(age)})
    return out[:MAX_ITEMS]


def get(url):
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
    return r.text


def brutalist():
    """[{name, home, via, items}] for the Business topic's sources plus WSJ, Quartz, Coindesk."""
    out = []
    page = get(f"{BR}/topic/business?limit=50")
    for href, name, body in BLOCK.findall(page):
        out.append({"name": clean(name), "home": BR + href, "via": "brutalist.report", "items": br_items(body)})
    for slug, name in BR_SOURCES:
        try:
            page = get(f"{BR}/source/{slug}?limit={MAX_ITEMS}")
            items = [i for _, _, body in BLOCK.findall(page) for i in br_items(body)] or br_items(page)
            out.append({"name": name, "home": f"{BR}/source/{slug}", "via": "brutalist.report", "items": items})
        except Exception as exc:
            print(f"  brutalist.report/{slug}: {exc}")
            out.append({"name": name, "home": f"{BR}/source/{slug}", "via": "brutalist.report", "items": None})
    return out


def rss(name, home, url, now):
    root = ET.fromstring(requests.get(url, headers=UA, timeout=25).content)
    items = []
    for it in root.iter("item"):
        t, link = clean(it.findtext("title") or ""), (it.findtext("link") or "").strip()
        if not t or not link.startswith("http"):
            continue
        age_min, label = None, ""
        pub = it.findtext("pubDate")
        if pub:
            try:
                age_min = max(0, int((now - parsedate_to_datetime(pub.strip())).total_seconds() // 60))
                label = f"{age_min}m" if age_min < 60 else f"{age_min // 60}h" if age_min < 1440 else f"{age_min // 1440}d"
            except (TypeError, ValueError):
                pass
        items.append({"t": t, "u": link, "age": label, "age_min": age_min})
    items.sort(key=lambda i: i["age_min"] if i["age_min"] is not None else 10 ** 9)
    return {"name": name, "home": home, "via": "RSS", "items": items[:MAX_ITEMS]}


def main():
    now = datetime.now(timezone.utc)
    prev = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
            prev = {s["name"]: s for g in old.get("groups", []) for s in g["sources"]}
        except Exception:
            prev = {}

    def keep(src):
        """A source that failed this time keeps its last good headlines (their ages then grow)."""
        if src["items"] is None:
            old = prev.get(src["name"])
            src["items"] = old["items"] if old else []
            src["stale"] = bool(old)
        return src

    india = []
    for name, home, url in RSS:
        try:
            india.append(rss(name, home, url, now))
        except Exception as exc:
            print(f"  {name}: {exc}")
            india.append(keep({"name": name, "home": home, "via": "RSS", "items": None}))
    try:
        world = brutalist()
    except Exception as exc:
        print(f"  brutalist.report: {exc}")
        world = [keep(dict(s, items=None)) for s in prev.values() if s.get("via") == "brutalist.report"]
    world = [keep(s) for s in world]
    crypto = [s for s in world if s["name"] == "Coindesk"]
    world = [s for s in world if s["name"] != "Coindesk"]
    res = {
        "generated_utc": now.isoformat(timespec="seconds"),
        "generated_ist": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "groups": [
            {"id": "india", "name": "India markets", "sources": india},
            {"id": "global", "name": "Global business · via brutalist.report", "sources": world},
            {"id": "crypto", "name": "Crypto · via brutalist.report", "sources": crypto},
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for g in res["groups"]:
        for s in g["sources"]:
            print(f"  {g['id']:7} {s['name']:32} {len(s['items']):3} headlines{' (kept from last run)' if s.get('stale') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
