"""The ALADIN 2.0 methodology text: README block equals the tab's text word for word; mandatory disclaimer; neutral wording; every 'not measured' item the brief promises is listed."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import make_aladin2_readme as mr  # noqa: E402

METHOD = json.loads((ROOT / "data" / "config" / "aladin2_method.json").read_text(encoding="utf-8"))
CFG = json.loads((ROOT / "data" / "config" / "aladin2.json").read_text(encoding="utf-8"))


def test_readme_block_equals_the_tab_text_word_for_word():
    text = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n"); cur = mr.current_block(text)
    assert cur is not None and cur == mr.block(METHOD) and mr.main(["--check"]) == 0


def test_disclaimer_neutral_wording_and_required_content():
    assert METHOD["disclaimer"] == CFG["disclaimer"]
    t = json.dumps(METHOD)
    assert not re.search(r"buy|sell|target|recommend|guaranteed", t, re.I)
    for must in ("survivorship", "Survivorship", "append-only", "NO EDGE", "not investment advice", "Cash-equity delivery cannot be shorted", "false-discovery", "Suspended"):
        assert must in t, must
    names = " ".join(n for n, _ in METHOD["not_measured"]).lower()
    for need in ("dividend", "fundamental", "delisted", "market capitalisation", "paper-portfolio", "median", "github"):
        assert need in names, need


def test_numbers_quoted_in_the_text_match_the_measured_reports():
    p3 = json.loads((ROOT / "data" / "aladin2" / "phase3_report.json").read_text(encoding="utf-8")); t = json.dumps(METHOD)
    assert p3["horizons"]["20"]["coverage_80_by_year"]["2020"] == 0.7049 and "70% for the 80% range at 20 days" in t
    assert round(p3["horizons"]["60"]["coverage_80_by_year"]["2020"] * 100) == 58 and "58% at 60 days" in t
    assert 0.029 <= p3["horizons"]["1"]["p_up"]["ece_after_isotonic"] <= 0.03 and "0.03 and 0.04" in t
    assert all(0.47 < p3["horizons"][h]["p_up"]["auc"] < 0.51 for h in p3["horizons"])
