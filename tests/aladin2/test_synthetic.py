import numpy as np

from scripts.aladin2 import synthetic as S


def test_reproducible_and_valid_bars():
    a, b = S.make("noise", seed=5), S.make("noise", seed=5)
    assert a.equals(b) and not S.make("noise", seed=6).equals(a)
    assert (a["h"] >= a[["o", "c"]].max(axis=1)).all() and (a["l"] <= a[["o", "c"]].min(axis=1)).all() and (a["v"] > 0).all()
    r = np.log(a["c"] / a["c"].shift()).dropna(); assert 0.15 < r.std() * np.sqrt(250) < 0.6


def test_planted_momentum_is_visible_and_noise_is_not():
    def ac(df):
        r = np.log(df["c"] / df["c"].shift()).dropna().values; m20 = np.convolve(r, np.ones(20), "valid")
        return np.corrcoef(m20[:-20], m20[20:])[0, 1]
    mom = np.mean([ac(S.make("momentum", n=5000, seed=s, strength=20)) for s in range(10)])
    noi = np.mean([ac(S.make("noise", n=5000, seed=s)) for s in range(10)])
    assert mom > 0.05 and abs(noi) < 0.05


def test_vanishing_edge_truth_and_regime_flag():
    d = S.make("vanishing", seed=1, frac=0.4); assert d.attrs["truth"]["vanishes_at_index"] == 1000
    assert S.make("regime", seed=1).attrs["truth"]["family"] == "trend"
