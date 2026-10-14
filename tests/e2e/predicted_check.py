"""
Browser checks for the NEXUS predicted links on the terminal's stock details and the home search's stock page (needs
`python scripts/dev_preview.py --no-browser` running, and data/nexus_predict built by python scripts/nexus_predict.py):

  python tests/e2e/predicted_check.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import BASE, check, ok, page_for  # noqa: E402

HOME = BASE.replace("expert-dev.html", "index.html")
SYM = "MARUTI"


def run():
    with sync_playwright() as pw:
        b, pg, errs, _ = page_for(pw)
        pg.goto(f"{BASE}#v=terminal&s={SYM}")
        pg.wait_for_timeout(3000)
        pg.evaluate("document.querySelector('[data-side=details]') && document.querySelector('[data-side=details]').click()")
        pg.wait_for_selector(".pl-list > li", timeout=30000)
        rows = pg.locator(".pl-list > li")
        check("terminal: predicted links are listed under the revenue dependency", rows.count() >= 3, rows.count())
        check("terminal: the section says Predicted, not confirmed", "predicted, not confirmed" in pg.inner_text("#details").lower())
        check("terminal: the fair test result is shown", "fair test" in pg.inner_text("#details"))
        pg.locator(".pl-list summary").first.click()
        check("terminal: opening a row shows its reasons", pg.locator(".pl-list details[open] .pl-why li").count() >= 1)
        check("terminal: 0 console errors", not errs, errs[:3])
        first = pg.locator(".pl-list [data-pl]").first.get_attribute("data-pl")
        pg.locator(".pl-list [data-pl]").first.click()
        pg.wait_for_timeout(1500)
        check("terminal: a predicted company opens in the terminal", first in pg.evaluate("location.hash"), first)
        # (opening a stock without an ALADIN 2.0 shard logs a 404 for aladin2/stock/<SYM>.json: older behaviour of the terminal, not of this section)
        b.close()

        b, pg, errs, _ = page_for(pw, size=(390, 844))
        pg.goto(f"{HOME}?home#s={SYM}&tab=revenue")
        pg.wait_for_selector("#st-pred details", timeout=30000)
        check("stock page: the predicted links card is on the revenue tab", pg.locator("#st-pred details").count() >= 3)
        check("stock page: the card says Predicted, not confirmed", "Predicted, not confirmed" in pg.inner_text("#st-pred"))
        pg.locator("#st-pred summary").first.click()
        check("stock page: tapping a row shows its reasons", pg.locator("#st-pred details[open] ul li").count() >= 1)
        check("phone: the stock page does not scroll sideways", pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
        check("stock page: 0 console errors", not errs, errs[:3])
        b.close()
    print("ALL OK" if all(ok) else f"{ok.count(False)} FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(run())
