import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import indices_eod as I  # noqa: E402


def test_groups_follow_nse_families():
    assert I.group_of("Nifty 50") == "Broad market" and I.group_of("Nifty Bank") == "Sectoral" and I.group_of("Nifty200 Momentum 30") == "Strategy"
    assert I.group_of("India VIX") == "Bonds, VIX and others" and I.group_of("Nifty 10 yr Benchmark G-Sec") == "Bonds, VIX and others" and I.group_of("Nifty India Defence") == "Thematic"


def test_key_matches_the_terminal_rule():
    assert I.key("Nifty 50") == "Nifty_2050" and I.key("S&P BSE SENSEX") == "S_26P_20BSE_20SENSEX" and I.key("Bitcoin (INR)") == "Bitcoin_20_28INR_29"


def test_summary_returns_and_52_week_range_from_real_rows():
    dates = pd.bdate_range("2025-10-01", "2026-10-09"); c = [100.0 + i * 0.1 for i in range(len(dates))]
    df = pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in dates], "o": c, "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c, "pe": 20.5, "pb": 3.1, "dy": float("nan")})
    r = I.summary("Nifty Test", "Thematic", "NSE end-of-day file", df)
    assert r["as_of"] == "2026-10-09" and r["last"] == round(c[-1], 2) and r["pct"] == round((c[-1] / c[-2] - 1) * 100, 2)
    assert r["hi52"] == round(c[-1] + 1, 2) and r["pe"] == 20.5 and r["dy"] is None and r["r1y"] is not None and r["r1m"] > 0


def test_discontinued_index_is_not_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "OUT", tmp_path)
    mk = lambda end: pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=end, periods=30)], "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "pe": None, "pb": None, "dy": None})
    doc = I.build({"Nifty 50": mk("2026-10-09"), "Nifty Tata Group": mk("2024-04-26")}, {})
    names = [r["name"] for r in doc["indices"] if r.get("key")]
    assert names == ["Nifty 50"] and doc["discontinued"][0]["name"] == "Nifty Tata Group" and (tmp_path / "d" / "Nifty_2050.json").exists()
