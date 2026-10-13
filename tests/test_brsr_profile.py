import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import brsr_profile as B  # noqa: E402
import dependency_profile as DP  # noqa: E402

XML = """<xbrli:xbrl><in-capmkt:PercentageOfContributionOfExportsInTheTotalTurnoverOfTheEntity contextRef="DCYMain" unitRef="pure" decimals="INF">0.0215</in-capmkt:PercentageOfContributionOfExportsInTheTotalTurnoverOfTheEntity>
<in-capmkt:PercentageOfContributionOfExportsInTheTotalTurnoverOfTheEntity contextRef="DPYMain" unitRef="pure">0.5</in-capmkt:PercentageOfContributionOfExportsInTheTotalTurnoverOfTheEntity>
<in-capmkt:ABriefOnTypesOfCustomersExplanatoryTextBlock contextRef="DCYMain">&lt;p&gt;Retail &amp;amp; online customers&lt;/p&gt;</in-capmkt:ABriefOnTypesOfCustomersExplanatoryTextBlock>
<in-capmkt:DescriptionOfBusinessActivity contextRef="D_BusinessActivities2">Watches</in-capmkt:DescriptionOfBusinessActivity>
<in-capmkt:PercentageOfTotalTurnoverForBusinessActivities contextRef="D_BusinessActivities2" unitRef="pure">0.0668</in-capmkt:PercentageOfTotalTurnoverForBusinessActivities>
<in-capmkt:DescriptionOfBusinessActivity contextRef="D_BusinessActivities1">Jewellery</in-capmkt:DescriptionOfBusinessActivity>
<in-capmkt:PercentageOfTotalTurnoverForBusinessActivities contextRef="D_BusinessActivities1" unitRef="pure">91.52</in-capmkt:PercentageOfTotalTurnoverForBusinessActivities></xbrli:xbrl>"""


def test_the_current_year_export_share_customer_types_and_activity_split_are_read_as_filed():
    p = B.parse(XML)
    assert p["exports"] == 0.0215 and p["exports_note"] is None                      # the current year (DCYMain), not the previous year's 0.5
    assert p["customers"] == "Retail & online customers"
    assert p["activities"] == [{"d": "Jewellery", "share": 0.9152}, {"d": "Watches", "share": 0.0668}]   # 91.52 written as a percentage is read as 91.52%
    assert B.parse(XML.replace(">0.0215<", ">250<"))["exports"] is None


def test_the_segment_note_wins_for_the_share_from_abroad_and_brsr_fills_it_otherwise():
    brsr = {"cos": {"AAA": {"exports": 0.3, "customers": "OEMs", "activities": [{"d": "Parts", "share": 1.0}]}, "BBB": {"exports": 0.1}}}
    prof = {"cos": {"AAA": {"major": {"status": "not_found", "customers": []}, "geo": {"rows": [{"region": "India", "share": 0.6}, {"region": "Outside India", "share": 0.4}]}}}}
    d = DP.build({"cos": {}, "edges": [], "nodes": []}, prof, brsr=brsr)["cos"]
    assert d["AAA"]["abroad"] == 0.4 and d["AAA"]["abroad_src"] == "segment note" and d["AAA"]["brsr"]["exports"] == 0.3 and d["AAA"]["brsr"]["cust"] == "OEMs"
    assert d["BBB"]["abroad"] == 0.1 and d["BBB"]["abroad_src"] == "BRSR exports" and d["BBB"]["lvl"] == "unknown"
