"""Browser checks for the public ALADIN tab (model E) and the ALADIN BOT lock over the earlier models (aladin-audit Phase 6).
Not collected by pytest (it needs a running preview and Chromium):
  ALADIN_BOT_CODE=<made-up test code> python scripts/dev_preview.py --no-browser
  E2E_BOT_CODE=<the same test code> python tests/e2e/aladin_e_check.py
Never use the real access code. Without E2E_BOT_CODE the unlocked checks print SKIP."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bot import OPEN, skip, unlock  # noqa: E402
from acceptance import BASE, check, ok, page_for  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

BANNED = re.compile(r"\b(target|recommendation|guaranteed)\b", re.I)      # buy and sell are allowed on this tab (owner, 2026-11-13: public signals)


def legacy_visible(pg):
    return pg.evaluate("[...document.querySelectorAll('[data-legacy]')].filter(e => e.offsetParent !== null).length")


def run():
    with sync_playwright() as pw:
        # 1. locked (every visitor): model E only, no earlier-model file requested
        b, pg, errs, reqs = page_for(pw)
        pg.goto(BASE + "#v=signals"); pg.reload(); pg.wait_for_selector("#ae-list tr.ae-r", timeout=30000)
        t = pg.inner_text("#signals")
        check("E: the ALADIN tab lists ranked stocks", pg.locator("#ae-list tr.ae-r").count() >= 10)
        check("E: the market strip shows the NIFTY 500 risk check", "NIFTY 500" in t and "200-day" in t)
        check("E: the student-model disclaimer is on the page", "It is often wrong" in t)
        check("E: no banned word on the page", not BANNED.search(t), (BANNED.search(t) or [None])[0])
        sg = pg.evaluate("fetch('aladin_e.json').then(r => r.json()).then(d => ({sg: d.signals, hold: (d.holdings || []).map(h => [h.sym, h.entry_px])}))")
        st = pg.inner_text(".ae-signals") if pg.locator(".ae-signals").count() else ""
        check("signals: the panel is shown with the SEBI / not-advice note, the exits and the stop-loss result", all(w in st.lower() for w in ("buy and sell signals", "sebi", "not investment advice", "kill switch", "stop-loss")), st[:120])     # inner_text follows CSS capitals
        rows = pg.locator(".ae-signals tbody tr").count()
        want = len((sg["sg"] or {}).get("buy", [])) + len((sg["sg"] or {}).get("sell", []))
        check("signals: one row per buy, holding and sell signal in the data", rows == want, [rows, want])
        held = {b["sym"]: b["ref_price"] for b in (sg["sg"] or {}).get("buy", []) if b["state"] == "held"}
        check("signals: the holdings are exactly the paper account's positions, at the price it paid", held == {s: p for s, p in sg["hold"]}, [len(held), len(sg["hold"])])
        check("signals: each buy or holding has an expected range (low, typical, high)", all(b.get("range") for b in (sg["sg"] or {}).get("buy", [])))
        pg.locator("#ae-list tr.ae-r").first.click(); pg.wait_for_timeout(500)
        check("E: a row opens 3 to 5 plain reasons", 3 <= pg.locator("#ae-list .ae-why li").count() <= 5)
        pg.fill("#ae-q", "TCS"); pg.wait_for_timeout(500)
        check("E: the search finds a stock by symbol", "TCS" in pg.inner_text("#ae-list"))
        if OPEN:                                                         # owner, 2026-11-13: ALADIN BOT without any code
            check("open: the earlier-model tabs are shown to every visitor, with no code", legacy_visible(pg) >= 4, legacy_visible(pg))
            check("open: aladin.json is published readable", pg.evaluate("fetch('aladin.json').then(r => r.status)") == 200)
            pg.goto(BASE + "#v=lab"); pg.reload(); pg.wait_for_timeout(5000)
            check("open: a link to the Tools tab opens Tools", pg.evaluate("location.hash").startswith("#v=lab"))
            pg.goto(BASE + "#v=a2bot"); pg.reload(); pg.wait_for_timeout(6000)
            check("open: ALADIN BOT shows the console with no code form and no lock button", pg.locator("#botcode").count() == 0 and pg.locator("#a2l-lockbtn").count() == 0 and pg.locator(".a2b-earlier-lock").count() == 0 and "ALADIN" in pg.inner_text("#a2bot"))
        else:
            check("lock: no earlier-model tab or button is shown", legacy_visible(pg) == 0)
            check("lock: no earlier-model file is requested", not any("/legacy/" in u and not u.split("?")[0].endswith("meta.json") for u, _ in reqs))
            check("lock: aladin.json is not published readable", pg.evaluate("fetch('aladin.json').then(r => r.status)") == 404)
            pg.goto(BASE + "#v=lab"); pg.reload(); pg.wait_for_timeout(5000)
            check("lock: a link to the Tools tab opens ALADIN BOT instead", pg.evaluate("location.hash").startswith("#v=a2bot"))
        check("E: 0 console errors", not [e for e in errs if "404" not in e], errs[:3])
        b.close()

        # 2. phone width: no sideways scroll of the page
        b, pg, errs, _ = page_for(pw, size=(390, 844))
        pg.goto(BASE + "#v=signals"); pg.reload(); pg.wait_for_selector("#ae-list tr.ae-r", timeout=30000)
        check("E phone: the page does not scroll sideways", pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0)
        b.close()

        # 3. unlocked with the TEST code, then locked again
        b, pg, errs, reqs = page_for(pw)
        if not unlock(pg, BASE):
            skip("unlock: earlier models inside ALADIN BOT"); b.close(); return
        check("unlock: the earlier models appear (Outlook, Tools, Old weekly signal, ALADIN 2.0)", legacy_visible(pg) >= 4, legacy_visible(pg))
        for v, sel, want in (("sigold", "#signals-old", "Weekly view"), ("lab", "#v-lab", "ALADIN"), ("outlook", "#v-outlook", "20 trading days"), ("a2", "#v-a2", "ALADIN 2.0")):
            pg.evaluate(f"document.querySelector('.a2b-earlier [data-go={v}]').click()"); pg.wait_for_timeout(5000)
            txt = pg.inner_text(sel)
            check(f"unlock: {v} opens and shows its data", want in txt and "not been published" not in txt and "Loading" not in txt[:300], txt[:80].replace("\n", " "))
            pg.evaluate("document.querySelector('[data-go=a2bot]').click()"); pg.wait_for_timeout(800)
        if not OPEN:
            pg.click(".a2b-earlier-lock"); pg.wait_for_timeout(800)
            check("lock again: the earlier models are hidden and the code is forgotten", legacy_visible(pg) == 0 and pg.evaluate("sessionStorage.getItem('aladin2.bot.code')") is None)
        check("unlocked: 0 console errors", not [e for e in errs if "404" not in e], errs[:3])
        b.close()
    print(f"\n{sum(ok)}/{len(ok)} checks passed")
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    run()
