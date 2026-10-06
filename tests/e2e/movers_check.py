"""
Browser checks for the extended Movers, Sectors and Houses views (needs `python scripts/dev_preview.py --no-browser` running, and data/aladin/moves.json built by
python scripts/aladin_moves.py):

  python tests/e2e/movers_check.py

The real supply graph has no dependency between two listed companies with a stated share, so one test injects a clearly labelled TEST-ONLY graph and shock into the
served files to prove the shock rows render. Nothing is written to disk.
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import BASE, check, ok, page_for  # noqa: E402

FRONTS = {"Technical", "Fundamental", "Supply-chain impact", "Sentiment"}


def fake_graph(route):                                                         # TEST-ONLY: a supplier link between two listed companies with a stated share
    r = route.fetch()
    g = r.json()
    g["edges"].append({"id": "t1", "s": "INFY", "d": "TCS", "rel": "supplies", "w": 0.24, "wb": "purchases", "per": "FY2025-26", "tier": 1, "comp": None, "conf": 0.9,
                       "kind": "disclosed", "url": "https://example.test/ar.pdf", "pg": 7, "q": "TEST ONLY quote about a supplier", "vq": True, "doc": "annual", "own": "TCS", "cpn": "INFY"})
    route.fulfill(response=r, body=json.dumps(g))


def fake_shocks(route):
    r = route.fetch()
    s = r.json()
    s["shocks"] = [{"focal": "TCS", "cp": "INFY", "rel": "supplies", "w": 0.24, "conf": 0.9, "z": -2.2, "edge": "t1", "cp_ret": -0.05, "focal_ret": -0.01}]
    route.fulfill(response=r, body=json.dumps(s))


def tab(pg, name, wait=900):
    pg.dispatch_event(f'#tabs [data-go="{name}"]', "click")
    pg.wait_for_timeout(wait)


def fresh(pw, **kw):
    b, pg, errs, reqs = page_for(pw, **kw)
    pg._bad = []
    pg.on("response", lambda r: pg._bad.append((r.status, r.url)) if r.status >= 400 else None)
    pg.goto(BASE)
    pg.wait_for_timeout(5500)
    return b, pg, errs, reqs


def run():
    with sync_playwright() as pw:
        # ---------- price & volume (the existing table, extended) ----------
        b, pg, errs, reqs = fresh(pw)
        tab(pg, "movers", 1500)
        heads = pg.inner_text("#mov-table thead").lower()
        check("Price & volume: the table keeps its columns and gains Rel vol and Sweep", "rel vol" in heads and "sweep" in heads and "delivery" in heads and "52-week" in heads)
        row = pg.locator("#mov-table tbody tr[data-s]").first
        cells = row.locator("td")
        rv, sw = cells.nth(7).inner_text(), cells.nth(8).inner_text()
        check("a row's Rel vol is a ratio (or a dash) and its Sweep cell explains itself", (rv.endswith("×") or rv == "—") and sw == "—" and "tick program" in (cells.nth(8).get_attribute("title") or ""), [rv, sw])
        check("the three views are offered, Price & volume is on", pg.locator("#mov-kind button").count() == 3 and pg.get_attribute('#mov-kind [data-k="price"]', "aria-pressed") == "true")
        check("the supply-chain file and the comparison file are not requested yet", not any(("supply_graph.json" in u or "aladin_moves.json" in u) for u, _ in reqs))

        sym = row.get_attribute("data-s")
        row.locator(".mv-tg").click()
        pg.wait_for_timeout(2500)
        exp = pg.locator(f'tr.mv-x[data-for="{sym}"]')
        t = exp.inner_text().lower() if exp.count() else ""
        check("the expander opens a row below it, without leaving Movers", exp.count() == 1 and pg.evaluate("document.querySelector('#v-movers').classList.contains('on')"))
        check("the expansion has supply lineage, quant drivers, sentiment & sweeps, each ending in Open in NEXUS",
              "supply lineage" in t and "quant drivers" in t and "sentiment & sweeps" in t and t.count("open in nexus") == 3, t[:200])
        check("the supply-chain file is fetched only now", any("supply_graph.json" in u for u, _ in reqs))
        check("a company with no disclosed links says 'Not measured' and why", "not measured" in t or "none disclosed" in t, t[:160])

        pg.evaluate("document.querySelectorAll('#mov-table tbody tr[data-s]').forEach(r => r._mark = 1)")
        pg.evaluate("document.querySelector('#mov-filter').dispatchEvent(new Event('input'))")           # same filter: a refresh, not a new list
        pg.wait_for_timeout(500)
        check("a refresh with the same rows patches cells in place: the rows are the same elements and the expansion stays open",
              pg.evaluate("[...document.querySelectorAll('#mov-table tbody tr[data-s]')].every(r => r._mark === 1)") and pg.locator(f'tr.mv-x[data-for="{sym}"]').count() == 1)
        pg.fill("#mov-filter", sym[:3])
        pg.wait_for_timeout(500)
        pg.fill("#mov-filter", "")
        pg.wait_for_timeout(500)
        check("after the list is rebuilt, open expansions come back", pg.locator(f'tr.mv-x[data-for="{sym}"]').count() == 1 and pg.get_attribute(f'tr[data-s="{sym}"] .mv-tg', "aria-expanded") == "true")
        pg.locator(f'tr[data-s="{sym}"] .mv-tg').click()
        pg.wait_for_timeout(300)
        check("the expander closes it again", pg.locator(f'tr.mv-x[data-for="{sym}"]').count() == 0)

        b.close()
        b, pg, errs, reqs = fresh(pw)
        tab(pg, "movers", 1200)
        pg.fill("#mov-filter", "RELIANCE")
        pg.wait_for_timeout(600)
        pg.locator("#mov-table tbody tr[data-s] td.co").first.click()
        pg.wait_for_timeout(1200)
        check("clicking the rest of a row still opens the chart", pg.evaluate("document.querySelector('#v-terminal').classList.contains('on')"))
        b.close()

        # ---------- ALADIN probability ----------
        b, pg, errs, reqs = fresh(pw)
        tab(pg, "movers", 1500)
        tab(pg, "movers", 600)
        pg.click('#mov-kind [data-k="aladin"]')
        pg.wait_for_timeout(2500)
        check("ALADIN probability: the comparison file is fetched now, the price table hides, the horizon switch shows",
              any("aladin_moves.json" in u for u, _ in reqs) and pg.evaluate("document.querySelector('#mov-price').hidden && !document.querySelector('#mov-alt').hidden && !document.querySelector('#mov-h').hidden"))
        t = pg.inner_text("#mov-alt")
        check("it says whose nights are compared and that it is not live", "compared with" in t and "not live" in t.lower(), t[:160])
        up, dn = pg.locator("#mov-alt .tablecard").nth(0).locator("tbody tr.mv-r"), pg.locator("#mov-alt .tablecard").nth(1).locator("tbody tr.mv-r")
        check("15 or fewer rises and falls are listed", 0 < up.count() <= 15 and 0 < dn.count() <= 15, [up.count(), dn.count()])
        fr = {x.strip() for x in pg.eval_on_selector_all("#mov-alt tr.mv-r td:last-child", "els => els.map(e => e.textContent)")}
        check("'Moved by' names one of the four fronts", fr <= FRONTS and len(fr) >= 1, fr)
        ups = pg.eval_on_selector_all("#mov-alt .tablecard:nth-child(1) tr.mv-r td:nth-child(5)", "els => els.map(e => e.textContent)")
        dns = pg.eval_on_selector_all("#mov-alt .tablecard:nth-child(2) tr.mv-r td:nth-child(5)", "els => els.map(e => e.textContent)")
        check("rises are marked ▲ and falls ▼, biggest first", all("▲ +" in x for x in ups) and all("▼" in x for x in dns), [ups[:2], dns[:2]])
        before = pg.inner_text("#mov-alt")
        pg.click('#mov-h [data-h="5"]')
        pg.wait_for_timeout(900)
        check("the horizon switch changes the list", pg.inner_text("#mov-alt") != before and "at 5 days" in pg.inner_text("#mov-alt"))
        s0 = pg.locator("#mov-alt tr.mv-r").first.get_attribute("data-s")
        pg.locator("#mov-alt tr.mv-r").first.click()
        pg.wait_for_timeout(2000)
        check("a row of this table expands into the same three blocks", "supply lineage" in pg.inner_text(f'#mov-alt tr.mv-x[data-for="{s0}"]').lower())

        # ---------- supply-chain shocks, real data: an honest empty state ----------
        pg.click('#mov-kind [data-k="shock"]')
        pg.wait_for_timeout(2500)
        t = pg.inner_text("#mov-alt")
        check("Supply-chain shocks with the real graph: says why there is nothing to rank, with the counts", "No supply-chain shock to show" in t and re.search(r"\d+ of \d+ companies read so far have a disclosed dependency on another listed company", t) is not None, t[:200])
        tab(pg, "movers", 300)
        check("the empty state is not an error", not errs, [errs[:3], pg._bad])
        b.close()

        # ---------- supply-chain shocks, injected TEST-ONLY data ----------
        b, pg, errs, reqs = fresh(pw, routes={"**/supply_graph.json*": fake_graph, "**/shocks.json*": fake_shocks})
        tab(pg, "movers", 1200)
        pg.click('#mov-kind [data-k="shock"]')
        pg.wait_for_timeout(3000)
        t = pg.inner_text("#mov-alt")
        check("a shock row renders: counterparty, stock affected, share and the honest sentence",
              "INFY" in t and "TCS" in t and "Supplier INFY" in t and "INFY is 24% of TCS's purchases" in t and "association, not proof of cause" in t, t[:300])
        check("the share is worded as the customer's purchases and the filing is named", "24% of the customer's purchases" in t and "FY2025-26 annual report" in t)
        pg.locator('#mov-alt [data-nexus="edge:t1"]').first.click()
        pg.wait_for_timeout(1500)
        check("clicking the link opens the NEXUS dependency panel with the quote", "TEST ONLY quote" in pg.inner_text("#nx-body") and "not proof of cause" in pg.inner_text("#nx-body").lower())
        pg.keyboard.press("Escape")
        check("shock rows: 0 console errors", not errs, errs[:3])
        b.close()

        # ---------- sectors ----------
        b, pg, errs, reqs = fresh(pw)
        tab(pg, "sectors", 1500)
        check("Sectors: the dependency map is closed and the graph is not fetched yet", pg.locator("details.sec-dep").count() == 1 and not pg.evaluate("document.querySelector('details.sec-dep').open") and not any("supply_graph.json" in u for u, _ in reqs))
        pg.locator('#heat button', has_text="Automobile").first.click()
        pg.wait_for_timeout(600)
        pg.click("details.sec-dep > summary")
        pg.wait_for_timeout(2500)
        body = pg.inner_text("#sec-dep-body")
        check("opening it loads the graph and shows an honest coverage line", any("supply_graph.json" in u for u, _ in reqs) and "Disclosed links for" in body and " of " in body and "filings read" in body, body[:200])
        check("it lists counterparty sectors and groups unlisted parties", "linked to other sectors" in body.lower() and "Unlisted or unnamed" in body, body[:400])
        check("an 'Open the graph' button names the company with the most links", pg.locator('#sec-dep-body [data-nexus^="company:"]').count() >= 1 and "open the graph for" in body.lower())
        pg.locator('#sec-dep-body button.btn-line').click()
        pg.wait_for_timeout(1500)
        check("that button opens the NEXUS supply-chain panel", "company" in pg.inner_text("#nx-kind").lower())
        pg.keyboard.press("Escape")
        check("sectors: 0 console errors", not errs, errs[:3])
        b.close()

        # ---------- houses ----------
        b, pg, errs, reqs = fresh(pw)
        tab(pg, "houses", 2500)
        check("Houses: the supply-chain file is not fetched until a group is opened", not any("supply_graph.json" in u for u, _ in reqs))
        pg.locator("tr.hh-row .hh-tg").first.click()
        pg.wait_for_timeout(3000)
        t = pg.inner_text("tr.hh-detail")
        d = pg.inner_text(".hh-deps")
        check("a group's expansion has a Group dependencies block with an honest coverage line", "group dependencies" in t.lower() and "Graph covers" in t and "members (filings read)" in t, t[-500:])
        check("it says no related-party rows exist yet, and shows both external concentration lists", "Related-party transactions" in t and "largest customers" in t.lower() and "largest suppliers" in t.lower())
        check("rupee amounts are only claimed for shares of the member's own revenue", ("≈ ₹" not in d or "sum of share × the member's revenue" in d) and ("no share stated" in d or "no rupee amount can be worked out" in d or "no external" in d.lower() or "sum of share" in d), d[-300:])
        check("houses: 0 console errors", not errs, errs[:3])
        b.close()

        # ---------- commands ----------
        b, pg, errs, _ = fresh(pw)
        for text, want in (("MOVERS ALADIN", "aladin"), ("MOVERS SHOCK", "shock"), ("MOVERS", "price")):
            pg.fill("#cmd", text)
            pg.press("#cmd", "Enter")
            pg.wait_for_timeout(1800)
            on = pg.eval_on_selector('#mov-kind button[aria-pressed="true"]', "e => e.dataset.k")
            check(f"command {text}: opens Movers on the {want} view", pg.evaluate("document.querySelector('#v-movers').classList.contains('on')") and on == want, on)
        check("commands: no 'not built yet' message any more", "not built yet" not in pg.inner_text("#toast"))
        check("commands: 0 console errors", not errs, errs[:3])
        b.close()

        # ---------- accessibility and phone ----------
        b, pg, errs, _ = fresh(pw)
        tab(pg, "movers", 1500)
        pg.locator("#mov-table tbody tr[data-s] .mv-tg").first.click()
        pg.wait_for_timeout(2000)
        pg.click('#mov-kind [data-k="aladin"]')
        pg.wait_for_timeout(2500)
        pg.add_script_tag(url="https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js")
        res = pg.evaluate("axe.run('#v-movers').then(r => r.violations.map(v => [v.id, v.impact, v.nodes.length]))")
        bad = [v for v in res if v[1] in ("serious", "critical")]
        check("Movers (ALADIN view with an open expansion): no serious or critical axe violations", not bad, res)
        pg.keyboard.press("Tab")
        check("the expander is a real button reachable by keyboard", pg.locator("#mov-alt .mv-tg").first.evaluate("e => e.tagName") == "BUTTON")
        b.close()
        b, pg, errs, _ = fresh(pw, size=(390, 844))
        tab(pg, "movers", 1500)
        pg.click('#mov-kind [data-k="aladin"]')
        pg.wait_for_timeout(2500)
        check("phone: the ALADIN movers view does not scroll the whole page sideways", pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
        check("phone: 0 console errors", not errs, errs[:3])
        b.close()
    print("ALL OK" if all(ok) else f"{ok.count(False)} FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(run())
