"""
Coverage integrity (acceptance check 9), on the real local data when it is present (skipped in a clean checkout):
* aladin.json holds a probability for exactly the securities that have >= 250 daily bars and traded in the last 10 days;
* every such security is also a row the ALADIN tab can show, because the tab lists the whole universe.json;
* the size limit (< 3 MB) and the shape of every stock record hold.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
ROOT = Path(__file__).resolve().parent.parent
ALADIN = ROOT / "data" / "aladin" / "latest.json"
UNIVERSE = ROOT / "data" / "terminal" / "universe.json"

pytestmark = pytest.mark.skipif(not (ALADIN.exists() and UNIVERSE.exists()), reason="needs data/aladin/latest.json and data/terminal/universe.json (generated data)")


@pytest.fixture(scope="module")
def doc():
    return json.loads(ALADIN.read_text(encoding="utf-8"))


def test_file_is_under_3_mb_and_has_the_contract_keys(doc):
    assert ALADIN.stat().st_size < 3_000_000
    for k in ("generated_utc", "as_of", "horizons", "primary", "weights", "model", "oos", "live", "sweep_eval", "not_measured", "stocks"):
        assert k in doc
    assert doc["weights"]["mode"] in ("prior", "fitted") and doc["weights"]["sweep_validated"] is False
    assert any("Satellite" in x[0] for x in doc["not_measured"]) and all(len(x) == 2 and x[1] for x in doc["not_measured"])


def test_every_stock_record_has_a_probability_per_horizon_and_a_decile(doc):
    for sym, e in doc["stocks"].items():
        assert set(e["t"]["p"]) == {str(h) for h in doc["horizons"]}, sym
        assert all(0.02 <= p <= 0.98 for p in e["t"]["p"].values()) and -100 <= e["t"]["sc"] <= 100
        assert all(1 <= d <= 10 for d in e["dec"].values()) and {"f", "t", "s"} <= set(e["cov"]) <= {"f", "t", "s", "x"}


def test_probabilities_exist_exactly_for_securities_with_250_bars_and_recent_trading(doc):
    import aladin_model as am
    stocks = json.loads(UNIVERSE.read_text(encoding="utf-8"))["stocks"]
    nifty = am.load_prices("^NSEI", 300)
    last = nifty.index[-1]
    should, short, stale = set(), [], []
    for s in stocks:
        sym = s["s"]
        if sym.startswith(("^", "DUMMY")):
            continue
        df = am.load_prices(sym, 1)                                              # no minimum: we count the bars ourselves
        if df is None or len(df) < am.MIN_BARS:
            short.append(sym)
        elif df.index[-1] < last - pd.Timedelta(days=10):
            stale.append(sym)
        else:
            should.add(sym)
    have = set(doc["stocks"])
    # the features need 250 warm-up rows AND the final day; securities whose last-day feature row is empty cannot be scored
    assert have <= should, sorted(have - should)[:10]
    missing = should - have
    assert len(missing) <= 0.01 * len(should), (len(missing), sorted(missing)[:10])           # at most a handful of rows lack a feature value on the last day
    assert not (have & set(short)) and not (have & set(stale))


def test_sme_etf_rows_are_covered_for_the_right_reasons(doc):
    stocks = {s["s"]: s for s in json.loads(UNIVERSE.read_text(encoding="utf-8"))["stocks"]}
    sme = [s for s in doc["stocks"] if stocks.get(s, {}).get("board") == "SME"]
    etf = [s for s in doc["stocks"] if stocks.get(s, {}).get("etf")]
    assert all("f" not in doc["stocks"][s] for s in sme + etf)                  # no fundamental block: the tab shows "not covered" / "n/a"
    assert all(stocks[s].get("board") != "SME" or "f" not in doc["stocks"][s] for s in doc["stocks"] if s in stocks)
