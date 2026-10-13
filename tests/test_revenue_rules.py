import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import revenue_profile as RP  # noqa: E402
import revenue_rules as RR  # noqa: E402

TITAN = """e)  Geographical information
` in crore
For the year ended
31st March 2026
For the year ended
31st March 2025
Revenue (including other income)
India  76,408  53,850
Others {refer note (d) below}  1,681  1,485
Total  78,089  55,335
` in crore
Assets
India  53,305  40,918
Others  312  157
Total  53,617  41,075"""


def read(text):
    pages = {7: text}
    return RP.profile([RR.answer(pages)], pages)[0]


def test_the_geography_table_is_read_from_its_lines_and_checked_like_a_model_answer():
    g = read(TITAN)["geo"]
    assert [r["region"] for r in g["rows"]] == ["India", "Others"] and g["total"] == 78089 and g["rows"][0]["share"] == round(76408 / 78089, 4) and g["factor"] == 1e7


def test_the_asset_table_and_a_table_that_does_not_add_up_are_not_taken():
    assets_only = "Geographical information\n` in crore\n2026 2025\nNon-current assets\nIndia 53,305 40,918\nOthers 312 157\nTotal 53,617 41,075"
    assert read(assets_only)["geo"] is None
    assert read(TITAN.replace("Total  78,089", "Total  90,000"))["geo"] is None


def test_when_the_earlier_year_comes_first_the_second_column_is_used():
    t = "Geographical information\n` in crore\n31 March 2025   31 March 2026\nRevenue from operations\nIndia 100 300\nOutside India 50 100\nTotal 150 400"
    assert read(t)["geo"]["total"] == 400


def test_customer_sentences_none_one_with_a_share_one_over_ten_and_several_are_told_apart():
    none = read("Note 43. No customer individually accounted for more than 10% of the revenues in the year ended December 31, 2025 and 2024. 44 RELATED PARTY")
    assert none["major"]["status"] == "none_over_10"
    assert read("No single customer accounted for 10.0% or more of revenue in any of the years presented.")["major"]["status"] == "none_over_10"
    one = read("(d) Major Customer The Company has one customer whose revenue represents 37% (2025: 37%) of the Company's total revenue.")["major"]
    assert one["status"] == "disclosed" and one["customers"][0]["share"] == 0.37
    over = read("d) The overseas sales are primarily made to a single customer based out of Japan which is contributing more than 10% of the Company's total revenue during the year.")["major"]
    assert over["status"] == "disclosed" and over["customers"][0]["share"] is None and over["customers"][0]["min_share"] == 0.10
    assert read("The Group has three customers which contribute 45% of the total revenue of the Group.")["major"]["status"] == "not_found"


class _Fetch:
    def __init__(self, text): self.text = text
    def pages(self, url): return "sha", [(7, self.text)]


class _NoCall:
    def complete(self, *a): raise AssertionError("a model call was made although the code found everything")


def test_extract_skips_the_model_when_the_code_finds_both_and_marks_a_partial_reading_pending_without_a_model(tmp_path):
    both = TITAN + "\nNo single customer accounted for 10% or more of the revenue of the Company during the year."
    prof, notes, n = RP.extract({"url": "u"}, _Fetch(both), _NoCall(), tmp_path)
    assert n == 1 and prof["by"] == {"geo": "code", "major": "code"} and not prof.get("pending")
    prof, notes, n = RP.extract({"url": "u"}, _Fetch(TITAN), None, tmp_path)
    assert prof["pending"] and prof["geo"] and prof["major"]["status"] == "not_found"
    assert RP.extract({"url": "u"}, _Fetch("Nothing useful here at all."), None, tmp_path)[2] == 0          # nothing found and no model: not recorded, retried later


def test_a_geography_total_far_from_reported_revenue_is_dropped_as_a_unit_mistake():
    g = {"total": 78089, "factor": 1e7}
    assert RP.sane_geo(g, 7.6e11)[0] is g                                   # Rs 78,089 crore vs Rs 76,000 crore reported: kept
    assert RP.sane_geo({"total": 78089, "factor": 1e5}, 7.6e11)[0] is None    # read as lakh: 100x off, dropped
    assert RP.sane_geo(g, None)[0] is g                                     # no revenue to compare: kept as checked
