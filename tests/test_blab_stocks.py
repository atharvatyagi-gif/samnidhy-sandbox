"""B-Lab per-stock cards (scripts/blab/stocks.py), on made-up stores. No network."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from blab import stocks as K  # noqa: E402

TODAY = date(2026, 11, 17)


def test_every_main_board_stock_is_searchable_and_every_covered_one_has_a_card():
    uni = [{"s": "TCS", "n": "Tata Consultancy Services Limited", "board": "Main"}, {"s": "SMEX", "n": "Sme Co", "board": "SME"},
           {"s": "NIFTYBEES", "n": "Nifty ETF", "etf": True}, {"s": "20MICRONS", "n": "20 Microns Limited", "board": "Main"}]
    stores = {"shp": {"TCS": {"q": [["2026-09-30", 71.77, 28.2, None, "1"], ["2025-09-30", 72.07, 27.9, None, "2"]]}},
              "ann": [["9", "TCS", "Change in Auditors", "2026-11-01", "t", "u"], ["8", "TCS", "Change in Auditors", "2026-05-01", "t", "u"]],
              "sast": [], "deals": [["bulk", "2026-11-13", "TCS", "BUY", "A FUND", 1000.0, 3000.0], ["short", "2026-11-13", "TCS", None, "", 1.0, None]],
              "ai": [{"analysed": "2026-11-16T10:00:00Z", "title": "TCS wins", "url": "u", "effect": "positive", "confidence": "high", "syms": ["TCS"]}],
              "hist": [["5", "TCS", "Press Release", "2026-11-12"]]}
    ledger = [{"bot": "T4", "division": "technical", "sym": "TCS", "kind": "strategy: momentum", "direction": 1, "seen": "2026-11-16", "text": "pick"},
              {"bot": "F5", "division": "fundamental", "sym": "TCS", "kind": "debt jump", "direction": -1, "seen": "2026-11-15", "text": "debt"}]
    study = {"Press Release": {"21": {"n": 112, "mean_pct": 3.09, "verdict": "too few months (4 of 12)"}}}
    doc = K.build(uni, {"TCS", "LISTEDLATER"}, stores, ledger, study, TODAY)
    assert [n[0] for n in doc["names"]] == ["20MICRONS", "TCS", "LISTEDLATER"]               # SME and ETFs left out; a covered stock is always searchable
    assert dict((n[0], n[2]) for n in doc["names"]) == {"20MICRONS": False, "TCS": True, "LISTEDLATER": True}
    c = doc["cards"]["TCS"]
    assert c["fundamental"]["promoter"] == {"quarter": "2026-09-30", "pct": 71.77, "chg_1y": -0.3, "public": 28.2}
    assert c["fundamental"]["governance_n"] == 1                                               # only the last 90 days
    assert c["fundamental"]["findings"][0]["kind"] == "debt jump"
    assert c["technical"]["picks"] == ["momentum"] and c["technical"]["deals_n"] == 1           # short deals are not shown as deals
    assert c["sentiment"]["ai"][0]["title"] == "TCS wins" and c["sentiment"]["announcements"][0][2]["mean_pct"] == 3.09
    assert doc["cards"]["LISTEDLATER"]["fundamental"]["promoter"] is None                        # nothing collected: left empty, never filled in
    assert "20MICRONS" not in doc["cards"]
