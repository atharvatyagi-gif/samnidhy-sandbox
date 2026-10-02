"""The methodology drawer text (aladin_method.json) and the README block must match word for word; compliance wording."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import make_aladin_readme as mr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
METHOD = json.loads((ROOT / "data" / "config" / "aladin_method.json").read_text(encoding="utf-8"))
DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice."
BANNED = re.compile(r"buy|sell|target|recommend|guaranteed", re.I)


def test_readme_block_equals_the_drawer_text_word_for_word():
    text = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    cur = mr.current_block(text)
    assert cur is not None, "README.md has no ALADIN methodology block: run python scripts/make_aladin_readme.py"
    assert cur == mr.block(METHOD)
    assert mr.main(["--check"]) == 0


def test_mandatory_disclaimer_and_required_sections():
    assert METHOD["disclaimer"] == DISCLAIMER
    heads = [s["h"] for s in METHOD["sections"]]
    for needed in ("Technical view", "Fundamental view", "Sentiment view", "Liquidity sweeps", "How the views are combined", "How it was tested", "Not measured, and why", "Paper trading", "Limits"):
        assert needed in heads
    assert "Simulated. Not real trades." in json.dumps(METHOD)


def test_every_not_measured_row_has_a_reason_and_the_text_names_them():
    text = json.dumps(METHOD)
    for name, why in METHOD["not_measured"]:
        assert why and name.lower().split()[0] in text.lower()
    for item in ("Satellite imagery", "Card-spend", "Job postings", "ESG", "order-book", "Heston", "LSTM"):
        assert item.lower() in text.lower()


def test_no_banned_words_in_the_methodology():
    assert not BANNED.search(json.dumps(METHOD))
