"""
Before/after image diff of the existing views (acceptance check 8). Needs both servers:
  python tests/e2e/baseline_site.py && python -m http.server 8766 --directory site_old --bind 127.0.0.1     (page code before ALADIN, same data)
  python scripts/dev_preview.py --no-browser                                                                (page code now)
  python tests/e2e/before_after.py [outdir]

Moving things (clocks, tickers, "checked N s ago", toasts) are hidden in both so only real layout / colour changes show. Prints, per view, the share of
pixels that differ and the rectangles where they do, and saves old / new / diff images.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

OLD, NEW = "http://127.0.0.1:8766/expert-dev.html", "http://127.0.0.1:8765/expert-dev.html"
VIEWS = [("brief", "Brief"), ("terminal", "Terminal"), ("movers", "Movers"), ("sectors", "Sectors"), ("world", "World"), ("outlook", "Outlook"), ("news", "News")]
HIDE = """
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
#clock, #tape, .tape, .crawl, #crawl, #st-data, #sys-fresh, .fresh, .toast, #toasts, #livechip, .livechip, #live-txt, [data-asof], .asof, .mstats, #st-auto, .auto, #ticker, .marquee { visibility: hidden !important; }
"""


def shoot(pw, url, view, out):
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.add_init_script("localStorage.setItem('blab-onboarded','true')")
    pg.goto(url)
    pg.wait_for_timeout(9000)                                                  # past the 5 s ALADIN preload: the Brief's ALADIN card and the Details block are in
    pg.add_style_tag(content=HIDE)
    pg.dispatch_event(f'#tabs [data-go="{view}"]', "click")
    pg.wait_for_timeout(1800)
    pg.screenshot(path=str(out))
    b.close()


def regions(mask, cell=40):
    h, w = mask.shape
    boxes = []
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if mask[y:y + cell, x:x + cell].any():
                boxes.append((x, y))
    if not boxes:
        return []
    ys = sorted({y for _, y in boxes})
    bands, cur = [], [ys[0]]
    for y in ys[1:]:
        if y - cur[-1] <= cell:
            cur.append(y)
        else:
            bands.append((cur[0], cur[-1] + cell)); cur = [y]
    bands.append((cur[0], cur[-1] + cell))
    out = []
    for y0, y1 in bands:
        xs = [x for x, y in boxes if y0 <= y < y1]
        out.append((min(xs), y0, max(xs) + cell, y1))
    return out


def main(outdir="."):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        for view, label in VIEWS:
            po, pn = out / f"ba_{view}_old.png", out / f"ba_{view}_new.png"
            shoot(pw, OLD, view, po)
            shoot(pw, NEW, view, pn)
            a, b = Image.open(po).convert("RGB"), Image.open(pn).convert("RGB")
            diff = ImageChops.difference(a, b)
            mask = np.array(diff).sum(axis=2) > 24
            share = mask.mean() * 100
            Image.fromarray((mask * 255).astype("uint8")).save(out / f"ba_{view}_diff.png")
            print(f"{label:9s} {share:5.2f}% of pixels differ; regions (x0,y0,x1,y1): {regions(mask)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
