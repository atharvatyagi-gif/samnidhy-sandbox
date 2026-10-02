"""The per-stock record written to aladin.json (build_stock_entries) and the driver filter, with small synthetic inputs."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_model as am  # noqa: E402

CFG = {"weights": {"wF": 0.20, "wS": 0.12, "wSweep": 0.18}, "primary_horizon": 10}


def frame():
    return pd.DataFrame({"sym": ["AAA", "BBB", "CCC"], "tr": [True, True, False], "pca_z": [1.2, np.nan, -0.5], "coint_z": [0.8, np.nan, np.nan]})


def test_entry_structure_coverage_and_combination():
    L = frame()
    per = {5: np.array([0.55, 0.45, 0.50]), 10: np.array([0.60, 0.40, 0.52])}
    drv = [[["x", 0.1]], [["y", -0.2]], [["z", 0.0]]]
    fund = {"AAA": {"v": 1.0, "q": 1.0, "m": 0.5, "dist": {"band": "Low"}, "fin": False, "raw": {"roe": 0.2}}}
    sent = {"stocks": {"AAA": {"sc": 40.0}, "BBB": {"sc": -30.0}}}
    pairs = {"AAA": {"peer": "BBB", "hl": 9.0, "beta": 0.8}}
    jumps = {"AAA": {"lam": 3.0, "mj": -0.04, "sj": 0.03, "last": 5, "bv": 0.1}}
    alt = {"AAA": {"nlp": {"tone": 0.2, "hedge": 0.3, "n": 5}, "nlp_z": 0.5, "alt": {"deliv": 0.05, "bulk_cr": 12.5}}}
    e = am.build_stock_entries(L, per, drv, fund, sent, CFG, 0.12, jumps, pairs, alt)
    a, b, c = e["AAA"], e["BBB"], e["CCC"]
    assert a["cov"] == {"f": 1.0, "t": 1, "s": 1} and b["cov"] == {"f": None, "t": 1, "s": 1} and c["cov"] == {"f": None, "t": 1, "s": None}
    assert a["t"]["p"] == {"5": 0.55, "10": 0.6} and a["t"]["sc"] == 20.0 and b["t"]["sc"] == -20.0
    assert a["t"]["coint"] == {"peer": "BBB", "z": 0.8, "hl": 9.0, "beta": 0.8} and "coint" not in b["t"] and a["t"]["pca_z"] == 1.2 and "pca_z" not in b["t"]
    assert a["t"]["jump"]["last"] == 5 and a["t"]["hmm"] == 0.12
    assert "f" in a and "f" not in b and a["f"]["alt"] == {"deliv": 0.05, "bulk_cr": 12.5} and a["f"]["nlp"]["tone"] == 0.2 and a["f"]["raw"] == {"roe": 0.2}
    assert c["t"]["sc"] == 4.0
    # deciles are 1..10 across the scored stocks; the best p is in the top decile, the worst in the bottom
    assert a["dec"]["10"] == 10 and b["dec"]["10"] == 1
    # the nightly combined view uses F and S the same way the browser does
    expect = am.combine_py(0.60, a["f"]["sc"], 40.0, None, CFG["weights"])
    assert a["comb"]["10"] == [expect["p"], expect["conf"], expect["agree"]]
    assert b["comb"]["10"][2] in ("0/2", "1/2", "2/2")                         # no F for BBB: only T and S are available fronts


def test_fundamental_part_changes_the_combined_probability_only_when_present():
    L = frame().iloc[:1]
    per = {10: np.array([0.60])}
    base = am.build_stock_entries(L, per, [[]], {}, {}, CFG, 0.0, {}, {}, {})["AAA"]["comb"]["10"][0]
    with_f = am.build_stock_entries(L, per, [[]], {"AAA": {"v": 2.0, "q": 2.0, "m": 2.0, "dist": None}}, {}, CFG, 0.0, {}, {}, {})["AAA"]["comb"]["10"][0]
    assert base == pytest.approx(0.6, abs=1e-3) and with_f > base


def test_drivers_leave_out_market_wide_inputs():
    class Stub:
        def predict(self, X, pred_contrib=True):
            return np.array([[5.0, 0.1, -0.4, 2.0, 0.0]])                      # last column is the bias term
    feats = ["m_disp", "r5", "hmm_p_highvol", "vol20"]
    D = pd.DataFrame([[0, 0, 0, 0]], columns=feats)
    out = am.drivers(Stub(), D, feats, k=5)[0]
    names = [n for n, _ in out]
    assert "market dispersion" not in names and "market turbulence probability" not in names and names[0] == "3-month volatility" or names[0] == "1-month volatility"
    assert out[0][1] == 2.0
