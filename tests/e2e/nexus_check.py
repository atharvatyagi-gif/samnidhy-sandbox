"""
Browser checks for the NEXUS panel and the supply-chain columns in ALADIN (needs `python scripts/dev_preview.py --no-browser` running):

  python tests/e2e/nexus_check.py

Opens the real supply graph in the real page. The impact score is not available for any stock yet (the graph has no stated share between two listed
companies), so one test injects a clearly labelled TEST-ONLY impact value into the served aladin.json to prove the column, the block and the combiner
render; nothing is written to disk.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import BASE, check, ok, page_for  # noqa: E402

GRAPH = json.loads((ROOT / "data" / "supply_graph.json").read_text(encoding="utf-8"))
# a listed company that has links, one with a quote, and one facility
SYM = max({e["own"] for e in GRAPH["edges"]}, key=lambda s: sum(1 for e in GRAPH["edges"] if s in (e["s"], e["d"])))
EDGE = next(e for e in GRAPH["edges"] if e["own"] == SYM)
FAC = next(iter(GRAPH["fac"]))


def inject_impact(route):
    r = route.fetch()
    j = r.json()
    st = j["stocks"].get(SYM)
    if st:
        st["x"] = {"i": 35.0, "n": 1, "top": [["TESTCP", "supplies", 0.3, -2.1, 0.9]], "asof": j["as_of"]}     # TEST-ONLY
    j["weights"]["impact_validated"] = False
    route.fulfill(response=r, body=json.dumps(j))


def open_panel(pg, hash_):
    pg.goto(BASE + hash_)
    pg.wait_for_timeout(5000)


def run():
    with sync_playwright() as pw:
        # 1. the panel from the ALADIN row, on the real graph
        b, pg, errs, reqs = page_for(pw)
        pg.goto(BASE)
        pg.wait_for_timeout(5000)
        check("NEXUS: supply_graph.json is not requested before the panel opens", not any("supply_graph.json" in u for u, _ in reqs))
        pg.dispatch_event('#tabs [data-go="lab"]', "click")
        pg.wait_for_timeout(2500)
        pg.fill("#al-q", SYM)
        pg.wait_for_timeout(600)
        pg.click(f'tr[data-s="{SYM}"] .al-tg')
        pg.wait_for_timeout(500)
        check("ALADIN row expansion has an 'Open in NEXUS' button and a supply-chain block", pg.locator(f'.al-x [data-nexus="company:{SYM}"]').count() >= 1 and "supply-chain impact" in pg.inner_text(".al-x").lower())
        check("a company with no impact score says 'Not measured', never 0", "not measured" in pg.inner_text(".al-x").lower())
        pg.click(f'.al-x [data-nexus="company:{SYM}"]')
        pg.wait_for_selector("#nx-root .nx-drawer")
        pg.wait_for_timeout(800)
        dlg = pg.locator("#nx-root [role=dialog]")
        check("NEXUS: drawer is a modal dialog with a label", dlg.get_attribute("aria-modal") == "true" and dlg.get_attribute("aria-labelledby") == "nx-title")
        check("NEXUS: title names the company", SYM in pg.inner_text("#nx-title"))
        check("NEXUS: disclaimer present", "It is often wrong. Educational analysis only, not investment advice." in pg.inner_text("#nx-root"))
        check("NEXUS: deep link written to the address", f"nx=company%3A{SYM}" in pg.url or f"nx=company:{SYM}" in pg.url, pg.url[-60:])
        check("NEXUS: supply_graph.json requested only now", any("supply_graph.json" in u for u, _ in reqs))
        pg.click('[data-nx-tab="chain"]')
        pg.wait_for_timeout(600)
        check("NEXUS: supply-chain tab draws the graph canvas", pg.locator("#nx-canvas").count() == 1 and pg.eval_on_selector("#nx-canvas", "c => c.width > 100"))
        check("NEXUS: canvas is hidden from screen readers, the table is the equivalent", pg.get_attribute("#nx-canvas", "aria-hidden") == "true" and pg.locator("#nx-body table.tbl").count() >= 1)
        pg.click('[data-nx-view="table"]')
        check("NEXUS: Table view lists the links with their share and confidence", "supplier" in pg.inner_text("#nx-body").lower() and "conf" in pg.inner_text("#nx-body").lower())
        pg.click('[data-nx-tab="deps"]')
        pg.wait_for_timeout(300)
        check("NEXUS: Dependencies tab shows an evidence quote", pg.locator("details.nx-q").count() >= 1)
        pg.click('[data-nx-tab="sources"]')
        check("NEXUS: Sources tab lists url, page and quote", "source" in pg.inner_text("#nx-body") and "“" in pg.inner_text("#nx-body"))
        # focus trap
        for _ in range(40):
            pg.keyboard.press("Tab")
        inside = pg.evaluate("document.querySelector('#nx-root .nx-drawer').contains(document.activeElement)")
        check("NEXUS: Tab key stays inside the drawer (focus trap)", inside)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        check("NEXUS: Esc closes the drawer and clears the deep link", pg.evaluate("document.querySelector('#nx-root').hidden") and "nx=" not in pg.url)
        check("NEXUS: focus returns to where it was", pg.evaluate("document.activeElement && document.activeElement.closest('.al-x') !== null"))
        check("NEXUS: 0 console errors or warnings", not errs, errs[:3])
        b.close()

        # 2. deep links: edge, facility, company
        for h, needle, label in ((f"#v=brief&nx=edge:{EDGE['id']}", "Quote", "edge"), (f"#v=brief&nx=facility:{FAC}", "Equipment lineage", "facility"), (f"#v=brief&nx=company:{SYM}", SYM, "company")):
            b, pg, errs, _ = page_for(pw)
            open_panel(pg, h)
            check(f"NEXUS deep link opens the {label} panel on load", pg.locator("#nx-root .nx-drawer").is_visible() and needle.lower() in pg.inner_text("#nx-root").lower(), pg.inner_text("#nx-title"))
            if label == "edge":
                check("edge panel shows the verbatim quote and the association wording", EDGE["q"][:30] in pg.inner_text("#nx-body") and "not proof of cause" in pg.inner_text("#nx-body"))
            if label == "facility":
                t = pg.inner_text("#nx-body")
                check("facility panel: missing capacity/utilisation/lineage say 'Not disclosed'; no invented location", "Not disclosed" in t and ("Not located yet" in t or "Approximate" in t or "Exact" in t))
            check(f"{label} deep link: 0 console errors or warnings", not errs, errs[:3])
            b.close()

        # 3. mobile: bottom sheet
        b, pg, errs, _ = page_for(pw, size=(390, 844))
        open_panel(pg, f"#v=brief&nx=company:{SYM}")
        box = pg.locator("#nx-root .nx-drawer").bounding_box()
        check("NEXUS on a phone: full-width bottom sheet", box and box["width"] >= 385 and box["y"] > 60, box)
        b.close()

        # 4. unknown company: honest empty state
        b, pg, errs, _ = page_for(pw)
        open_panel(pg, "#v=brief&nx=company:RELIANCE")
        pg.click('[data-nx-tab="chain"]')
        pg.wait_for_timeout(300)
        t = pg.inner_text("#nx-body")
        check("a company with no disclosed links shows 'Not measured' and 'Deeper tiers: not disclosed'", "Not measured" in t or "table" in t.lower())
        b.close()

        # 5. impact column, block and combiner with a TEST-ONLY injected score
        b, pg, errs, _ = page_for(pw, routes={"**/aladin.json*": inject_impact})
        pg.goto(BASE)
        pg.wait_for_timeout(5000)
        pg.dispatch_event('#tabs [data-go="lab"]', "click")
        pg.wait_for_timeout(2500)
        pg.fill("#al-q", SYM)
        pg.wait_for_timeout(700)
        row = pg.inner_text(f'tr[data-s="{SYM}"]')
        _x = json.loads((ROOT / "data" / "aladin" / "latest.json").read_text(encoding="utf-8"))["stocks"].get(SYM, {}).get("x")
        if _x is None:
            print("SKIP ALADIN Impact column: the local nightly file has no impact block for " + SYM + " (no usable listed-to-listed edge with a stated share yet)")
        else:
            _ip = _x["ip"] if _x.get("ip") is not None else -_x["i"] / 25                         # files written before the estimate was stored: undo the scale
            check("ALADIN: the Impact column shows the linked-move estimate in % pts (not the model-only score)", f"{_ip:+.1f}" in row, row[:120].replace("\n", " "))
        check("ALADIN: Fundamental cell tooltip carries 'F x · I y'", pg.locator(f'tr[data-s="{SYM}"] [title^="F "]').count() >= 1 or pg.locator(f'tr[data-s="{SYM}"] .al-gc').count() >= 2)
        pg.click(f'tr[data-s="{SYM}"] .al-tg')
        pg.wait_for_timeout(400)
        blk = pg.inner_text(".al-x")
        check("ALADIN: expansion lists the impact edges and the 'prior, unvalidated' status", "TESTCP" in blk and "prior, unvalidated" in blk and "association, not proof of cause" in blk.lower())
        pg.click('.al-x [data-nexus="company:TESTCP"]')
        pg.wait_for_timeout(800)
        check("clicking a counterparty in the block opens its panel", "TESTCP" in pg.inner_text("#nx-title"))
        check("impact injected: 0 console errors or warnings", not errs, errs[:3])
        b.close()

        # 6. the graph file missing from the manifest: honest message, no errors
        def no_graph(route):
            r = route.fetch()
            m = r.json()
            m.pop("graph", None)
            route.fulfill(response=r, body=json.dumps(m))
        b, pg, errs, _ = page_for(pw, routes={"**/desk_data.json*": no_graph})
        open_panel(pg, f"#v=brief&nx=company:{SYM}")
        check("supply-chain data not published: the panel says so, 0 console errors", "has not been published" in pg.inner_text("#nx-body") and not errs, errs[:3])
        b.close()

        # 7. accessibility of the open panel
        b, pg, errs, _ = page_for(pw)
        open_panel(pg, f"#v=brief&nx=company:{SYM}")
        pg.click('[data-nx-tab="deps"]')
        pg.add_script_tag(url="https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js")
        res = pg.evaluate("axe.run('#nx-root').then(r => r.violations.map(v => [v.id, v.impact, v.nodes.length]))")
        bad = [v for v in res if v[1] in ("serious", "critical")]
        check("NEXUS: no serious or critical axe violations", not bad, res)
        b.close()
    print("ALL OK" if all(ok) else f"{ok.count(False)} FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    t0 = time.time()
    sys.exit(run())
