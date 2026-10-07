"""The screener publishes how many stocks scored 0..9 on the F-Score, so the landing page's "Try the screen" slider can use real counts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import screener  # noqa: E402


def test_counts_cover_every_score_and_skip_rows_without_data():
    rows = [{"fscore": 9}, {"fscore": 6}, {"fscore": 6}, {"fscore": 0}, {"skip": "no data"}, {"fscore": None}]
    c = screener.fscore_counts(rows)
    assert list(c) == [str(i) for i in range(10)]
    assert (c["9"], c["6"], c["0"], c["3"]) == (1, 2, 1, 0)
    assert sum(c.values()) == 4


def test_the_published_document_carries_the_counts():
    src = (ROOT / "scripts" / "screener.py").read_text(encoding="utf-8")
    assert '"fscore_counts": fscore_counts(good)' in src
