"""
No look-ahead (acceptance check 3): every price after date D is multiplied by 1.5. Anything computed "as of" a date <= D must not change.
Covers the technical features, the PCA residual features, the Kalman spread and cointegration-pair features, the jump features, the HMM
filtered probabilities, the walk-forward splitter's purge gap, and the paper trader's entry price (next session's open).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_model as am  # noqa: E402
import aladin_quant as aq  # noqa: E402
import paper_trader as pt  # noqa: E402
import predict_model as pm  # noqa: E402

N = 700
IDX = pd.bdate_range("2021-01-04", periods=N)
D = IDX[500]                                                         # the cut date
AFTER = IDX > D


def make_prices(seed, base=100.0):
    rng = np.random.default_rng(seed)
    return pd.Series(base * np.exp(np.cumsum(rng.normal(0.0003, 0.015, N))), index=IDX)


def tamper(s):
    t = s.copy()
    t[AFTER] = t[AFTER] * 1.5                                        # +50% from the day after D onwards
    return t


def ohlcv(close, seed):
    rng = np.random.default_rng(seed)
    o = close.shift(1).fillna(close.iloc[0]) * (1 + rng.normal(0, 0.002, N))
    h = pd.concat([o, close], axis=1).max(axis=1) * (1 + abs(rng.normal(0, 0.003, N)))
    l = pd.concat([o, close], axis=1).min(axis=1) * (1 - abs(rng.normal(0, 0.003, N)))
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": close, "v": rng.integers(1e5, 1e6, N).astype(float)}, index=IDX)


def same_up_to_D(a, b, cols=None):
    a, b = a.loc[:D], b.loc[:D]
    if cols is not None:
        a, b = a[cols], b[cols]
    return np.allclose(a.values.astype(float), b.values.astype(float), equal_nan=True, rtol=1e-9, atol=1e-12)


def test_technical_features_up_to_D_do_not_change():
    close, nclose = make_prices(1), make_prices(2, 18000)
    df1, df2 = ohlcv(close, 3), ohlcv(tamper(close), 3)
    # the second frame must really differ after D, or the test proves nothing
    assert not np.allclose(df1.loc[IDX[600], "c"], df2.loc[IDX[600], "c"])
    f1, _ = pm.features(df1, np.log(nclose).diff())
    f2, _ = pm.features(df2, np.log(tamper(nclose)).diff())
    assert same_up_to_D(f1, f2), [c for c in f1.columns if not same_up_to_D(f1[[c]], f2[[c]])]
    assert not np.allclose(f1.loc[IDX[501]:IDX[515], "d_sma20"].values, f2.loc[IDX[501]:IDX[515], "d_sma20"].values)    # after D the features DO see the change


def test_jump_features_up_to_D_do_not_change():
    c = make_prices(4)
    f1 = aq.jump_features(np.log(c).diff())
    f2 = aq.jump_features(np.log(tamper(c)).diff())
    assert same_up_to_D(f1, f2)
    assert f2["jump_recent"].loc[IDX[510]] == 1.0 and f1["jump_recent"].loc[IDX[510]] == 0.0                         # the +50% day after D is a jump, and only in the tampered series


def test_pca_residual_features_up_to_D_do_not_change():
    px = pd.DataFrame({f"S{i}": make_prices(10 + i) for i in range(40)})
    r1, r2 = np.log(px).diff(), np.log(px.apply(tamper)).diff()
    res1, _ = aq.pca_residuals(r1)
    res2, _ = aq.pca_residuals(r2)
    assert same_up_to_D(res1, res2)
    z1, q1 = aq.pca_features(r1, res1)
    z2, q2 = aq.pca_features(r2, res2)
    assert same_up_to_D(z1, z2) and same_up_to_D(q1, q2)


def test_kalman_spread_up_to_D_does_not_change():
    x, y = make_prices(20), make_prices(21)
    a1, b1, s1, _ = aq.kalman_spread(np.log(y).values, np.log(x).values)
    a2, b2, s2, _ = aq.kalman_spread(np.log(tamper(y)).values, np.log(tamper(x)).values)
    k = IDX.get_loc(D) + 1
    assert np.allclose(s1[:k], s2[:k]) and np.allclose(b1[:k], b2[:k]) and not np.allclose(s1[k + 5:], s2[k + 5:])


def test_pair_features_up_to_D_do_not_change():
    rng = np.random.default_rng(5)
    base = np.cumsum(rng.normal(0, 0.01, N))
    cols = {"A": base + 4, "B": 0.9 * base + 3 + rng.normal(0, 0.004, N), "C": np.cumsum(rng.normal(0, 0.01, N)) + 4, "D": np.cumsum(rng.normal(0, 0.01, N)) + 4}
    prices = pd.DataFrame({k: np.exp(v) for k, v in cols.items()}, index=IDX)
    ind = {"A": "x", "B": "x", "C": "y", "D": "y"}
    p1 = am.pair_features(prices.to_dict("series"), ind, {}, workers=0, log=lambda *a: None)
    p2 = am.pair_features(prices.apply(tamper).to_dict("series"), ind, {}, workers=0, log=lambda *a: None)
    key = ["date", "sym"]
    a = p1[p1["date"] <= D].set_index(key)[["coint_z", "coint_hl", "coint_p"]]
    b = p2[p2["date"] <= D].set_index(key)[["coint_z", "coint_hl", "coint_p"]]
    assert len(a) > 50 and a.index.equals(b.index) and np.allclose(a.values, b.values, equal_nan=True)


def test_hmm_filtered_probabilities_up_to_D_do_not_change():
    rng = np.random.default_rng(6)
    r = pd.Series(np.where(rng.random(N) < 0.15, rng.normal(0, 0.03, N), rng.normal(0.0004, 0.007, N)), index=IDX)
    def obs(x):
        return pd.DataFrame({"r": x, "rv5": x.rolling(5).std()}).dropna()
    o1 = obs(r)
    r2 = r.copy(); r2[AFTER] = r2[AFTER] * 4 + 0.02                                    # a very different future
    o2 = obs(r2)
    cal = IDX
    cut = IDX[400]                                                                      # the HMM is fitted only on rows before `cut` (<= D)
    p1, p2 = am.hmm_series(o1, cal, cut), am.hmm_series(o2, cal, cut)
    assert np.allclose(p1.loc[:D].values, p2.loc[:D].values) and not np.allclose(p1.loc[IDX[560]:].values, p2.loc[IDX[560]:].values)


# ---------------------------------------------------------------- the walk-forward splitter
def test_purge_gap_is_asserted_for_every_horizon():
    cal = pd.bdate_range("2010-01-01", periods=4000)
    test_start = pd.Timestamp("2020-01-02")
    for h, gap in am.GAPS.items():
        cut = am.purge_cut(cal, test_start, h)
        i_cut, i_test = cal.get_loc(cut), cal.searchsorted(test_start)
        assert i_test - i_cut == gap and i_cut + h < i_test                              # the last training label ends before the first test day
    with pytest.raises(AssertionError):
        am.purge_cut(cal, test_start, 20, gap=10)                                        # a gap shorter than the horizon would leak: refused


def test_walk_forward_never_trains_on_labels_that_reach_the_test_period(monkeypatch):
    cal = pd.bdate_range("2008-01-01", periods=4200)
    keep = am.sample_dates(cal, 5, 250)
    rows = [{"date": d, "sym": s, "tr": True, "ind": "x", "f1": 0.0, "fwd5": 0.01, "fwd10": 0.01, "fwd20": 0.01, "hmm_p_highvol": 0.0} for d in keep for s in ("A", "B")]
    X = pd.DataFrame(rows)
    X["ind"] = X["ind"].astype("category")
    calls = []
    def fake_fit(train, h, feats, hp, regime):
        calls.append(["fit", h, train["date"].max(), None])
        return {"pooled": None, "calm": None, "stress": None, "n": len(train)}
    def fake_score(models, D, feats):
        calls[-1][3] = D["date"].min()                                                   # the first test day of this fold
        return np.full(len(D), 0.5), np.full(len(D), np.nan)
    monkeypatch.setattr(am, "fit_horizon", fake_fit)
    monkeypatch.setattr(am, "score_horizon", fake_score)
    monkeypatch.setattr(am, "hmm_series", lambda obs, cal, cut: pd.Series(0.0, index=cal))
    monkeypatch.setattr(am, "roc_auc_score", lambda y, p: 0.5)
    monkeypatch.setattr(am, "MIN_TRAIN_ROWS", 10)
    out = am.walk_forward(X, cal, pd.DataFrame({"r": 0.0, "rv5": 0.0}, index=cal), ["f1"], [5, 10, 20], regime=False, log=lambda *a: None)
    assert len(calls) > 30 and set(out) == {5, 10, 20}
    for _, h, last_train, first_test in calls:
        assert cal.get_loc(last_train) + h < cal.get_loc(first_test), (h, last_train, first_test)       # the last training label ends before the first test day
        assert cal.get_loc(first_test) - cal.get_loc(last_train) >= am.GAPS[h]                          # and the purge gap itself is respected
    for h, d in out.items():
        assert d["date"].dt.year.min() >= am.FIRST_TEST_YEAR

# ---------------------------------------------------------------- the paper trader
def test_paper_trader_never_enters_on_the_signal_days_close():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-05", periods=20)]
    bars = {"dates": dates, "o": np.arange(100.0, 120.0), "c": np.arange(200.0, 220.0)}
    pf = pt.empty_portfolio({"cost_roundtrip": 0.005, "notional": 1e5, "hold_days": 10, "max_open": 10, "threshold": 0.6})
    cfg = {"cost_roundtrip": 0.005, "notional": 1e5, "hold_days": 10, "max_open": 10, "threshold": 0.6, "entry_wait_days": 7}
    pt.add_signals(pf, [{"sym": "X", "signal_date": dates[7], "p_up": 0.7, "conf": "High", "agree": "3/3"}], cfg)
    pt.open_positions(pf, {"X": bars}, cfg)
    assert pf["open"][0]["entry_date"] == dates[8] and pf["open"][0]["entry_px"] == bars["o"][8] and pf["open"][0]["entry_px"] != bars["c"][7]
