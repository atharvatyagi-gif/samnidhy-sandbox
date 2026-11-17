"""Browser checks for the B-Lab research desk dashboard (lab.html). Not collected by pytest (it needs a running preview):
  python scripts/dev_preview.py --no-browser
  python tests/e2e/lab_check.py
The page is checked against the status file it is served (blab/status.json): every division and bot shown, the filters work,
no console errors, no sideways scroll on a phone, no serious or critical axe violations."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import AXE, check, ok, page_for  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

URL = "http://127.0.0.1:8765/lab.html"


def run():
    with sync_playwright() as pw:
        b, pg, errs, reqs = page_for(pw)
        pg.goto(URL); pg.wait_for_selector(".lab-org", timeout=30000)
        doc = pg.evaluate("fetch('blab/status.json').then(r => r.json())")
        check("lab: the page is not linked for search engines (noindex)", "noindex" in (pg.get_attribute("meta[name=robots]", "content") or ""))
        check("lab: all four divisions are shown", pg.locator(".lab-org").first.locator(".lab-div").count() == 4)
        check("lab: one card per bot in the status file", pg.locator(".lab-bot").count() == len(doc["bots"]), [pg.locator(".lab-bot").count(), len(doc["bots"])])
        check("lab: every card shows its state", all(pg.locator(f'.lab-bot[data-bot="{x["id"]}"] .lab-pill').count() == 1 for x in doc["bots"]))
        t = pg.inner_text("#lab")
        check("lab: says experimental and not investment advice", "experimental" in t.lower() and "not investment advice" in t.lower())
        n = len(doc.get("findings_recent", []))
        rows = pg.locator("#lab-feed tbody tr").count()
        check("lab: the findings feed lists the recent findings", rows == min(n, 300) if n else "No findings match" in pg.inner_text("#lab-feed"), [rows, n])
        if n:
            sym = doc["findings_recent"][0]["sym"]
            pg.fill("#lab-sym", sym); pg.wait_for_timeout(300)
            check("lab: the stock filter narrows the feed", 0 < pg.locator("#lab-feed tbody tr").count() <= rows)
            pg.fill("#lab-one", sym); pg.wait_for_timeout(300)
            check("lab: one stock, every division", pg.locator("#lab-stock .lab-div").count() == 4 and sym in pg.inner_text("#lab-stock"))
        sx = pg.evaluate("fetch('blab/stocks.json').then(r => r.ok ? r.json() : null)")
        if sx:
            have = {f["sym"] for f in doc.get("findings_recent", []) if f.get("sym")}
            quiet = next((s for s in sx["cards"] if s not in have), None)
            pg.fill("#lab-one", quiet); pg.wait_for_timeout(600)
            t1 = pg.inner_text("#lab-stock")
            check("lab: a covered stock with no findings still gets all four divisions", pg.locator("#lab-stock .lab-div").count() == 4 and quiet in t1, quiet)
            outside = next((n[0] for n in sx["names"] if not n[2]), None)
            if outside:
                pg.fill("#lab-one", outside); pg.wait_for_timeout(400)
                check("lab: a listed stock outside the 500 says it is not covered", "outside the 500" in pg.inner_text("#lab-stock"), outside)
            check("lab: the search suggests every searchable stock", pg.locator("#lab-stocks option").count() == len(sx["names"]), [pg.locator("#lab-stocks option").count(), len(sx["names"])])
        check("lab: the scorecard section explains how findings are scored", "next close" in pg.inner_text("#lab"))
        pg.add_script_tag(url=AXE)
        res = pg.evaluate("async () => { const r = await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'best-practice'] }); return r.violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length })); }")
        serious = [v for v in res if v["impact"] in ("serious", "critical")]
        print("   axe lab", [(v["id"], v["impact"], v["n"]) for v in res])
        check("lab: no serious or critical axe violations", not serious, [(v["id"], v["n"]) for v in serious])
        check("lab: 0 console errors", not errs, errs[:3])
        b.close()
        b, pg, errs, _ = page_for(pw, size=(390, 844))
        pg.goto(URL); pg.wait_for_selector(".lab-org", timeout=30000)
        check("lab phone: the page does not scroll sideways", pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0)
        b.close()
    print(f"\n{sum(ok)}/{len(ok)} checks passed")
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    run()
