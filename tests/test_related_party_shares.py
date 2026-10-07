"""Derived revenue shares (option 2): sales to a named listed related party divided by revenue, from the same filing; every check that must hold before a share exists."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_graph as cg  # noqa: E402
import related_party_shares as rps  # noqa: E402
import revenue_graph_builder as rb  # noqa: E402

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
STOCKS = [{"s": "SUPPLIER", "n": "Supplier Industries Limited", "board": "Main"}, {"s": "BIGCO", "n": "Bigco Motors Limited", "board": "Main"}, {"s": "OTHERCO", "n": "Otherco Steel Limited", "board": "Main"}]
INDEX = rb.NameIndex(STOCKS)
META = {"url": "https://nsearchives.nseindia.com/annual_reports/AR_x.pdf", "kind": "annual", "period": "FY2025-26"}
PAGES = {
    10: "Statement of Standalone Profit and Loss (Rs. in crore) Particulars Year ended March 31, 2026 Year ended March 31, 2025 Revenue from operations 5,000.00 4,200.00",
    40: "Related party transactions (Rs. in crore) Name of the related party Nature of transaction Year ended March 31, 2026 Year ended March 31, 2025 "
        "Bigco Motors Limited Sale of goods 1,250.50 980.00 Otherco Steel Limited Sale of goods 6,000.00 10.00 Unlisted Widgets Pvt Ltd Sale of goods 12.00 9.00",
}
REV = {"value": 5000, "unit": "Rs. in crore", "scope": "standalone", "column_heading": "Year ended March 31, 2026", "page": 10,
       "quote": "Revenue from operations 5,000.00 4,200.00"}


def tx(name="Bigco Motors Limited", value=1250.5, quote=None, **kw):
    t = {"related_party_name": name, "kind": "sale_of_goods_or_services", "value": value, "unit": "Rs. in crore", "scope": "standalone",
         "column_heading": "Year ended March 31, 2026", "page": 40, "quote": quote or f"{name} Sale of goods {value:,.2f} 980.00"}
    t.update(kw)
    return t


def run(rev=REV, txs=None, pages=PAGES):
    return rps.derive([{"revenue": rev, "transactions": txs if txs is not None else [tx()]}], pages, META, NOW, "SUPPLIER", INDEX)


def test_unit_factors():
    f = rps.unit_factor
    assert f("Rs. in crore") == 1e7 and f("INR crores") == 1e7 and f("` in million") == 1e6 and f("Rs. in lakhs") == 1e5 and f("USD billion") == 1e9 and f("in thousands") == 1e3
    assert f("Rs.") == 1.0 and f("₹") == 1.0 and f(None) is None and f("") is None and f("percent") is None


def test_the_share_is_the_sale_to_the_listed_related_party_over_revenue_and_says_it_is_derived():
    items, notes = run()
    assert len(items) == 1
    e = items[0]
    assert e["name"] == "Bigco Motors Limited" and e["direction"] == "customer" and e["rel"] == "supplies" and e["wb"] == "revenue" and e["wd"] == "derived"
    assert e["w"] == pytest.approx(1250.5 / 5000, abs=1e-4) and e["calc"]["r"] == e["w"] and e["calc"]["t"]["label"] == "revenue from operations"
    assert e["conf"] == 0.9                                                      # quote .5 + named .2 + derived share .1 + recent period .1 (a stated share is 1.0)
    assert e["calc"]["a"]["pg"] == 40 and e["calc"]["t"]["pg"] == 10 and "Year ended March 31, 2026" in e["calc"]["a"]["h"]


def test_units_may_differ_between_the_two_tables_and_are_converted():
    pages = {**PAGES, 10: PAGES[10].replace("Rs. in crore", "Rs. in million").replace("5,000.00 4,200.00", "50,000.00 42,000.00")}
    rev = {**REV, "unit": "Rs. in million", "value": 50000.0, "quote": "Revenue from operations 50,000.00 42,000.00"}
    items, _ = run(rev=rev, pages=pages)
    assert items[0]["w"] == pytest.approx(1250.5 * 1e7 / (50000 * 1e6), abs=1e-4) == pytest.approx(0.25, abs=1e-3)


@pytest.mark.parametrize("change, why", [
    ({"quote": "Bigco Motors Limited Sale of goods 1,250.50 and a sentence that is not in the filing"}, "quote is not in the source text"),
    ({"value": 999.0, "quote": "Bigco Motors Limited Sale of goods 1,250.50 980.00"}, "the number is not written in its quote"),
    ({"unit": None}, "no unit stated"),
    ({"unit": "Rs. in million"}, "the unit is not on that page"),
    ({"column_heading": "Year ended March 31, 2031"}, "the column heading is not on that page"),
    ({"column_heading": None}, "the column heading is not on that page"),
    ({"scope": "consolidated"}, "not comparable"),
])
def test_every_check_stops_a_share_with_a_stated_reason(change, why):
    items, notes = run(txs=[tx(**change)])
    assert items == [] and any(why in n for n in notes), notes


def test_different_years_a_share_above_one_other_kinds_and_unlisted_parties_give_nothing():
    items, notes = run(txs=[tx(column_heading="Year ended March 31, 2025", quote="Bigco Motors Limited Sale of goods 1,250.50 980.00")])
    assert items == [] and any("different years" in n for n in notes)
    items, notes = run(txs=[tx(name="Otherco Steel Limited", value=6000.0, quote="Otherco Steel Limited Sale of goods 6,000.00 10.00")])
    assert items == [] and any("outside (0, 1]" in n for n in notes)                       # 6,000 of 5,000 revenue: impossible
    assert run(txs=[tx(kind="other")])[0] == []                                              # purchases, loans, interest and the rest are never turned into shares
    assert run(txs=[tx(name="Unlisted Widgets Pvt Ltd", value=12.0, quote="Unlisted Widgets Pvt Ltd Sale of goods 12.00 9.00")])[0] == []     # only listed companies matter here


def test_without_a_checked_revenue_figure_nothing_is_derived():
    items, notes = run(rev={**REV, "unit": None})
    assert items == [] and any("no checked revenue figure" in n for n in notes)
    items, notes = run(rev=None)
    assert items == []


def graph_with(rows):
    return {"v": 1, "cos": {"SUPPLIER": {"at": "2026-10-01T00:00:00Z", "edges": 0, "fac": 0, "notes": []}}, "edges": rows, "nodes": [], "anon": {}, "fac": {}}


def test_a_derived_edge_goes_into_the_graph_passes_the_audit_and_a_rerun_replaces_it():
    items, _ = run()
    rows = rb.to_graph_edges("SUPPLIER", items, INDEX)
    assert rows[0]["wd"] == "derived" and rows[0]["calc"]["r"] == rows[0]["w"] and rows[0]["s"] == "SUPPLIER" and rows[0]["d"] == "BIGCO"
    g = rb.assemble(rps.merge(graph_with([]), "SUPPLIER", rows, {"at": "2026-10-01T00:00:00Z", "derived": 1, "notes": []}), {}, STOCKS, [], 0.75, NOW)
    assert cg.audit(g) == [] and g["cos"]["SUPPLIER"]["rp"]["derived"] == 1 and sum(1 for e in g["edges"] if e.get("wd") == "derived") == 1
    g2 = rb.assemble(rps.merge(g, "SUPPLIER", [], {"at": "2026-10-02T00:00:00Z", "derived": 0, "notes": []}), {}, STOCKS, [], 0.75, NOW)
    assert not [e for e in g2["edges"] if e.get("wd") == "derived"]                       # a re-run with a different answer leaves no stale share behind


def test_the_audit_rejects_a_derived_share_whose_arithmetic_or_labels_do_not_hold():
    items, _ = run()
    row = rb.to_graph_edges("SUPPLIER", items, INDEX)[0]
    g = rb.assemble(rps.merge(graph_with([]), "SUPPLIER", [row], {"at": "x", "derived": 1, "notes": []}), {}, STOCKS, [], 0.75, NOW)
    for mutate, fragment in [(lambda x: x.update(w=0.9), "does not equal"), (lambda x: x.update(wd=None), "without wd=derived"), (lambda x: x["calc"]["a"].update(q=""), "missing q"),
                             (lambda x: x["calc"]["t"].update(u="percent"), "units cannot be read"), (lambda x: x.update(wb="purchases"), "revenue-basis"), (lambda x: x.update(conf=0.95), "0.9")]:
        bad = json.loads(json.dumps(g))
        mutate(bad["edges"][0])
        assert any(fragment in p for p in cg.audit(bad)), (fragment, cg.audit(bad))
    assert cg.audit(g) == []


def test_the_impact_score_can_use_a_derived_share():
    import graph_impact as gi
    items, _ = run()
    rows = rb.to_graph_edges("SUPPLIER", items, INDEX)
    g = rb.assemble(rps.merge(graph_with([]), "SUPPLIER", rows, {"at": "x", "derived": 1, "notes": []}), {}, STOCKS, [], 0.75, NOW)
    ex = gi.exposures(g, {"SUPPLIER", "BIGCO"}, 0.5)
    assert [(i["cp"], i["w"]) for i in ex["SUPPLIER"]] == [("BIGCO", 0.2501)]


def test_a_share_below_005_percent_is_noise_and_is_not_kept_even_if_saved_earlier():
    pages = {**PAGES, 40: PAGES[40] + " Bigco Motors Limited Sale of goods 0.50 980.00"}
    items, notes = run(txs=[tx(value=0.5, quote="Bigco Motors Limited Sale of goods 0.50 980.00")], pages=pages)            # 0.5 / 5,000 = 0.01%
    assert items == [] and any("noise" in n for n in notes)
    tiny = {"own": "SUPPLIER", "s": "SUPPLIER", "d": "BIGCO", "rel": "supplies", "w": 0.0, "wb": "revenue", "wd": "derived", "q": "Bigco Motors Limited Sale of goods 0.50 980.00", "conf": 0.9}
    assert rb.clean_saved_edge(tiny) is None
    assert rb.clean_saved_edge({**tiny, "w": 0.0034}) is not None


def test_a_number_written_as_text_is_accepted_only_when_the_quote_shows_it():
    assert rps.as_number("15,21,486") == 1521486.0 and rps.as_number(12) == 12.0 and rps.as_number("n/a") is None and rps.as_number(None) is None and rps.as_number(True) is None
    items, _ = run(rev={**REV, "value": "5,000.00"}, txs=[tx(value="1,250.50", quote="Bigco Motors Limited Sale of goods 1,250.50 980.00")])                     # text numbers: the same share as with real numbers
    assert items and items[0]["w"] == pytest.approx(0.2501, abs=1e-4) and items[0]["calc"]["a"]["v"] == 1250.5
    items, notes = run(rev={**REV, "value": "500000"})                                              # a text number that is NOT in the quote (the model moved the decimal point)
    assert items == []                                                                              # no checked revenue figure, so nothing is derived
    items, notes = run(txs=[tx(value="125050", quote="Bigco Motors Limited Sale of goods 1,250.50 980.00")])
    assert items == [] and any("the number is not written in its quote" in n for n in notes)


def test_a_derived_row_must_be_shown_to_be_a_sale_by_the_filings_own_words():
    page = "Related party transactions (Rs. in crore) Sale of goods Bigco Motors Limited 120.00 90.00 Purchase of goods Otherco Steel Limited 50.00 40.00 Year ended March 31, 2026"
    assert rps.sale_nature(page, "Bigco Motors Limited 120.00 90.00")                                           # a plain row under a sale heading
    assert not rps.sale_nature(page, "Otherco Steel Limited 50.00 40.00")                                       # under a purchase heading
    assert rps.sale_nature(page, "Bigco Motors Limited Sale of goods 120.00 90.00")                             # the row itself says so
    assert not rps.sale_nature(page, "Bigco Motors Limited - - - - 120.00 - -")                                 # a matrix row: which column holds the 120 is not in the text
    assert not rps.sale_nature("Name of party 1.00 2.00", "Name of party 1.00 2.00")                           # nothing says what the row is
    pages = {10: PAGES[10], 40: PAGES[40].replace("Sale of goods", "Amount")}                                    # the same table with the word sale taken out
    items, notes = run(txs=[tx(quote="Bigco Motors Limited Amount 1,250.50 980.00")], pages=pages)
    assert items == [] and any("do not show that this row is a sale" in n for n in notes)
