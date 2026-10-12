import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import revenue_profile as P  # noqa: E402

GEO_PAGE = ("e) Geographical information ` in crore For the year ended 31st March 2026 For the year ended 31st March 2025 Revenue (including other income) "
            "India 76,408 53,850 Others 1,681 1,485 Total 78,089 55,335")
MAJOR_PAGE = ("Information about major customers During the year ended March 31, 2026, revenue arising from one customer in India amounting to ` 5,579.68 crore is "
              "contributing to more than 10% of the Group's revenue. (2025 : 4,105.50 crore)")
NONE_PAGE = "c) Information about major customer: Revenue from any single customer is not equal to or exceeds 10% of the company's total revenue."


def test_geography_rows_add_up_and_become_shares():
    ans = {"geography": {"unit": "` in crore", "column_heading": "For the year ended 31st March 2026", "page": 3,
                         "quote": "India 76,408 53,850 Others 1,681 1,485 Total 78,089", "rows": [{"region": "India", "amount": 76408}, {"region": "Others", "amount": 1681}], "total": 78089},
           "major_customers": [], "no_major_customer": None}
    prof, notes = P.profile([ans], {3: GEO_PAGE})
    g = prof["geo"]
    assert [r["region"] for r in g["rows"]] == ["India", "Others"] and abs(g["rows"][0]["share"] - 0.9785) < 1e-3 and g["factor"] == 1e7
    assert prof["major"]["status"] == "not_found"


def test_geography_that_does_not_add_up_or_is_invented_is_dropped():
    bad = {"geography": {"unit": "` in crore", "column_heading": "x", "page": 3, "quote": "India 76,408 53,850 Others 1,681 1,485 Total 78,089",
                         "rows": [{"region": "India", "amount": 76408}, {"region": "Others", "amount": 1681}], "total": 99999}}
    assert P.profile([bad], {3: GEO_PAGE})[0]["geo"] is None
    made_up = {"geography": {"unit": "` in crore", "column_heading": "x", "page": 3, "quote": "India 76,408 53,850 Others 1,681", "rows": [{"region": "India", "amount": 76408}, {"region": "USA", "amount": 1681}]}}
    assert P.profile([made_up], {3: GEO_PAGE})[0]["geo"] is None


def test_a_major_customer_amount_becomes_a_share_of_the_checked_geography_total():
    ans = {"geography": {"unit": "` in crore", "column_heading": "For the year ended 31st March 2026", "page": 3, "quote": "India 76,408 53,850 Others 1,681 1,485 Total 78,089",
                         "rows": [{"region": "India", "amount": 76408}, {"region": "Others", "amount": 1681}], "total": 78089},
           "major_customers": [{"name": None, "amount": 5579.68, "unit": "crore", "share_pct": None, "where": "India", "page": 4,
                                "quote": "revenue arising from one customer in India amounting to ` 5,579.68 crore is contributing to more than 10% of the Group's revenue"}]}
    prof, _ = P.profile([ans], {3: GEO_PAGE, 4: MAJOR_PAGE})
    c = prof["major"]["customers"][0]
    assert prof["major"]["status"] == "disclosed" and c["where"] == "India" and c["amount_cr"] == 5579.68 and c["share"] is None and c["min_share"] == 0.10   # 7.1% of the total: outside 10-100%, so only "10% or more" is kept


def test_a_stated_percentage_is_kept_and_a_previous_year_number_cannot_sneak_in():
    page = "One customer accounted for 37% (2025: 33%) of the Company's total revenue from operations."
    ok = {"major_customers": [{"share_pct": 37, "page": 1, "quote": "One customer accounted for 37% (2025: 33%) of the Company's total revenue from operations."}]}
    assert P.profile([ok], {1: page})[0]["major"]["customers"][0]["share"] == 0.37
    wrong = {"major_customers": [{"share_pct": 41, "page": 1, "quote": "One customer accounted for 37% (2025: 33%) of the Company's total revenue from operations."}]}
    assert P.profile([wrong], {1: page})[0]["major"]["status"] == "not_found"


def test_none_over_ten_needs_the_words_and_a_customer():
    ok = {"no_major_customer": {"page": 2, "quote": "Revenue from any single customer is not equal to or exceeds 10% of the company's total revenue."}}
    prof, _ = P.profile([ok], {2: NONE_PAGE})
    assert prof["major"]["status"] == "none_over_10"
    vague = {"no_major_customer": {"page": 2, "quote": "c) Information about major customer: Revenue from any"}}
    assert P.profile([vague], {2: NONE_PAGE})[0]["major"]["status"] == "not_found"
