"""
Draws the brand images from the site's own marks (three rising bars on the slate canvas) with the browser the tests already use:
  favicon.svg, icon-192.png, icon-512.png, apple-touch-icon.png (180), og.png (1200x630 social preview).
Run once after changing the brand:  python scripts/make_brand_assets.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BARS = '<rect x="{a}" y="{ya}" width="{w}" height="{ha}" rx="{r}" fill="#fafafa"/><rect x="{b}" y="{yb}" width="{w}" height="{hb}" rx="{r}" fill="#fafafa"/><rect x="{c}" y="{yc}" width="{w}" height="{hc}" rx="{r}" fill="#22c55e"/>'


def mark(size: int) -> str:
    u = size / 64
    kw = dict(a=14 * u, b=29 * u, c=44 * u, w=8 * u, r=2 * u, ya=38 * u, ha=14 * u, yb=30 * u, hb=22 * u, yc=20 * u, hc=32 * u)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" rx="{12 * u}" fill="#09090b"/>' + BARS.format(**kw) + "</svg>"


OG = """<html><body style="margin:0;width:1200px;height:630px;background:#09090b;color:#fafafa;font-family:Inter,Segoe UI,system-ui,sans-serif;display:flex;flex-direction:column;justify-content:center;padding:0 90px;box-sizing:border-box;border:1px solid #27272a">
<div style="display:flex;align-items:center;gap:22px">%s<div style="font-size:30px;color:#a1a1aa;letter-spacing:.04em">TAPMI &middot; STUDENT MARKETS LAB</div></div>
<div style="font-size:120px;font-weight:700;letter-spacing:-0.04em;line-height:1.02;margin-top:34px">The B-Lab<br>Cohort:</div>
<div style="font-size:36px;color:#a1a1aa;margin-top:28px">Where the market becomes a classroom.</div>
<div style="position:absolute;right:90px;bottom:60px;font-size:22px;color:#8b8b94">Educational analysis only. Not investment advice.</div></body></html>"""


def main() -> None:
    (ROOT / "favicon.svg").write_text(mark(64), encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
            pg = b.new_page(viewport={"width": size, "height": size})
            pg.set_content(f'<body style="margin:0;background:#09090b">{mark(size)}</body>')
            pg.screenshot(path=str(ROOT / name))
            pg.close()
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        pg.set_content(OG % mark(72))
        pg.screenshot(path=str(ROOT / "og.png"))
        b.close()
    print("wrote favicon.svg, icon-192.png, icon-512.png, apple-touch-icon.png, og.png")


if __name__ == "__main__":
    main()
