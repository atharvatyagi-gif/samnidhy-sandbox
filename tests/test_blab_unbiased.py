"""Survivorship-free market (scripts/blab/unbiased.py, scripts/corp_actions.py), on made-up NSE daily files. No network."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bhav_history as B  # noqa: E402
from corp_actions import factor  # noqa: E402
from blab import evolve as V  # noqa: E402
from blab.unbiased import BhavMarket  # noqa: E402

CFG = json.loads((ROOT / "data" / "config" / "aladin_e.json").read_text(encoding="utf-8"))


def test_split_and_bonus_wordings():
    assert factor("Fv Split Rs.10/- To Rs.2/") == 0.2
    assert factor("Agm/Div-Rs.2/Fv Rs10tors5") == 0.5
    assert factor("Fv Split Rs.10/- To Rs.2/- And Bonus 1:1") == 0.1
    assert factor("Bonus 3:2") == 0.4
    assert factor("Interim Dividend - Rs 5 Per Share") is None and factor("Rights 1:5 @ Premium Rs 20/-") is None


def build(tmp_path, n=320):
    """Five companies: SPL splits 10 -> 2 on day 300 (recorded), CRSH collapses 80% on day 300 (no record), OLDN renamed to
    NEWN (same ISIN) on day 200, GONE stops trading on day 290, LCK is circuit-locked on day 305."""
    d0 = date(2010, 1, 4)
    days = [d0 + timedelta(days=i) for i in range(n)]
    prev = {}
    for t, d in enumerate(days):
        rows = []
        for sym, isin in (("SPL", "I1"), ("CRSH", "I2"), ("OLDN" if t < 200 else "NEWN", "I3"), ("GONE", "I4"), ("LCK", "I5")):
            if sym == "GONE" and t >= 290:
                continue
            base = {"SPL": 500.0, "CRSH": 300.0, "OLDN": 100.0, "NEWN": 100.0, "GONE": 50.0, "LCK": 80.0}[sym] * (1.001 ** t)
            if sym == "SPL" and t >= 300:
                base /= 5
            if sym == "CRSH" and t >= 300:
                base *= 0.2
            o = h = lo = c = round(base, 2)
            if not (sym == "LCK" and t == 305):
                h, lo = round(base * 1.01, 2), round(base * 0.99, 2)
            pc = prev.get(isin, c)
            rows.append([d.isoformat(), sym, "EQ", o, h, lo, c, pc, 100000, c * 100000 * 10, isin])
            prev[isin] = c
        B.save_day(tmp_path, d, rows)
    (tmp_path / "corporate_actions.json").write_text(json.dumps({"months_done": [], "events": [["SPL", days[300].isoformat(), 0.2, "Fv Split Rs.10/- To Rs.2/"]]}))
    return days


def test_bias_free_market(tmp_path):
    days = build(tmp_path)
    M = BhavMarket(tmp_path, start="2010-01-01", index_series={d.isoformat(): 1000 * 1.0005 ** i for i, d in enumerate(days)})
    j = M.syms.index("SPL")
    assert abs(M.C[300, j] / M.C[299, j] - 1) < 0.01                                  # the recorded split is not a crash
    k = M.syms.index("CRSH")
    assert M.C[300, k] / M.C[299, k] - 1 < -0.75                                       # an unrecorded collapse stays a real loss
    assert ("CRSH", days[300].isoformat()) in [(u[0], u[1]) for u in M.unexplained]
    assert "NEWN" not in M.syms and np.isfinite(M.C[250, M.syms.index("OLDN")])        # renamed: one company, one history
    assert M.locked[305, M.syms.index("LCK")] and not M.locked[304, M.syms.index("LCK")]
    assert np.isnan(M.C[295, M.syms.index("GONE")])


def test_vanished_holdings_base_and_stress(tmp_path):
    days = build(tmp_path)
    M = BhavMarket(tmp_path, start="2010-01-01", index_series={d.isoformat(): 1000.0 for d in days})
    M.elig[:] = False
    M.elig[:, M.syms.index("GONE")] = True                                              # only GONE can be held
    cand = {"id": "t", "fam": "trend", "p": {"n": 100}}
    base = V.simulate(M, cand, CFG, start="2010-01-04", vanish="base")
    stress = V.simulate(M, cand, CFG, start="2010-01-04", vanish="stress")
    gb = [t for t in base["trades"] if len(t) > 7]
    gs = [t for t in stress["trades"] if len(t) > 7]
    assert gb and gs and gb[0][3] > 0 and gs[0][3] == 0.0                               # base: last close; stress: nothing
    assert stress["eq"][-1] < base["eq"][-1]
