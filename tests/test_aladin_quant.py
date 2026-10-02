"""ALADIN quant blocks: HMM filtering (no look-ahead), Kalman spread, PCA residuals, pairs, jumps. Synthetic data, fixed seeds."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_quant as q  # noqa: E402


def regime_data(n=1500, seed=1):
    rng = np.random.default_rng(seed)
    state = np.zeros(n, int)
    for t in range(1, n):
        state[t] = state[t - 1] if rng.random() > (0.04 if state[t - 1] == 0 else 0.08) else 1 - state[t - 1]
    r = rng.normal(0.0004, np.where(state == 1, 0.025, 0.007))
    rv5 = pd.Series(np.abs(r)).rolling(5, min_periods=1).mean().values
    return np.column_stack([r, rv5]), state


def test_hmm_recovers_the_stormy_state_and_labels_it_high_vol():
    X, state = regime_data()
    h = q.Gaussian2HMM().fit(X[:1000])
    p = h.filtered(X[1000:])
    truth = state[1000:]
    assert h.cov[1][0, 0] > h.cov[0][0, 0]
    assert p[truth == 1].mean() > 0.7 and p[truth == 0].mean() < 0.3
    assert np.mean((p > 0.5) == (truth == 1)) > 0.85


def test_hmm_filtered_probability_never_uses_future_data():
    X, _ = regime_data()
    h = q.Gaussian2HMM().fit(X[:1000])
    full = h.filtered(X[1000:1400])
    short = h.filtered(X[1000:1250])
    assert np.allclose(full[:250], short, atol=1e-12)                 # the first 250 values are identical whatever comes later


def test_hmm_uses_training_window_moments_only():
    X, _ = regime_data()
    a = q.Gaussian2HMM().fit(X[:1000])
    b = q.Gaussian2HMM().fit(X[:1000])
    assert np.allclose(a.filtered(X[1000:1100]), b.filtered(X[1000:1100]))       # deterministic
    assert np.allclose(a.m, X[:1000].mean(0))


def test_kalman_tracks_a_drifting_beta_and_spread_is_one_step_ahead():
    rng = np.random.default_rng(3)
    n = 800
    x = 5 + 2 * np.sin(np.linspace(0, 40, n)) + np.cumsum(rng.normal(0, 0.05, n))      # x must move enough to tell alpha and beta apart
    beta = 0.8 + 0.4 * np.sin(np.linspace(0, 3, n))
    y = 1.0 + beta * x + rng.normal(0, 0.002, n)
    a, b, s, state = q.kalman_spread(y, x, delta=1e-3)
    assert np.abs(b[-200:] - beta[-200:]).mean() < 0.08
    assert np.abs(s[-200:]).mean() < 0.02
    # the spread at t must not depend on y_t's own value beyond the prior state: changing the LAST y changes only the last spread
    y2 = y.copy(); y2[-1] += 1.0
    s2 = q.kalman_spread(y2, x, delta=1e-3)[2]
    assert np.allclose(s[:-1], s2[:-1]) and abs(s2[-1] - s[-1] - 1.0) < 1e-9


def test_kalman_can_be_continued_from_a_saved_state():
    rng = np.random.default_rng(4)
    x = np.cumsum(rng.normal(0, 0.01, 400)) + 5
    y = 2 + 0.9 * x + rng.normal(0, 0.003, 400)
    whole = q.kalman_spread(y, x)
    first = q.kalman_spread(y[:300], x[:300])
    rest = q.kalman_spread(y[300:], x[300:], init=first[3])
    assert np.allclose(whole[2][300:], rest[2])


def test_half_life_of_a_simulated_ar1():
    rng = np.random.default_rng(5)
    phi = 0.9
    s = np.zeros(3000)
    for t in range(1, 3000):
        s[t] = phi * s[t - 1] + rng.normal()
    hl = q.half_life(s)
    assert hl == pytest.approx(-math.log(2) / math.log(phi), rel=0.2)
    assert q.half_life(np.cumsum(rng.normal(size=500))) is None or q.half_life(np.cumsum(rng.normal(size=500))) > 30     # a random walk barely reverts
    assert q.half_life(np.arange(10.0)) is None


def factor_returns(n=500, k=3, m=60, seed=7):
    rng = np.random.default_rng(seed)
    F = rng.normal(0, 0.01, (n, k))
    L = rng.normal(0, 1, (k, m))
    idio = rng.normal(0, 0.004, (n, m))
    return pd.DataFrame(F @ L + idio, index=pd.bdate_range("2020-01-01", periods=n), columns=[f"S{i}" for i in range(m)]), F @ L


def test_pca_residuals_remove_the_common_factors():
    ret, common = factor_returns()
    resid, ks = q.pca_residuals(ret, var_share=0.8, kmax=6, window=250, refit_every=5, min_obs=240)
    tail = resid.iloc[300:]
    assert tail.notna().all().all() and ks.min() >= 1
    assert tail.values.std() < 0.6 * ret.iloc[300:].values.std()                       # most of the variance was the common part
    assert abs(np.corrcoef(tail.values.ravel(), common[300:].ravel())[0, 1]) < 0.2     # what is left is not the factors


def test_pca_residuals_do_not_depend_on_future_returns():
    ret, _ = factor_returns()
    full, _ = q.pca_residuals(ret, var_share=0.8, kmax=6, window=250, refit_every=5, min_obs=240)
    changed = ret.copy()
    changed.iloc[420:] = changed.iloc[420:] * 3 + 0.01                                  # rewrite the future
    alt, _ = q.pca_residuals(changed, var_share=0.8, kmax=6, window=250, refit_every=5, min_obs=240)
    assert np.allclose(full.iloc[:420].values, alt.iloc[:420].values, equal_nan=True)


def test_pca_features_shapes_and_range():
    ret, _ = factor_returns()
    resid, _ = q.pca_residuals(ret, var_share=0.8, kmax=6, window=250, refit_every=5, min_obs=240)
    z, r2 = q.pca_features(ret, resid)
    assert z.shape == ret.shape and (r2.dropna().values >= 0).all() and (r2.dropna().values <= 1).all()
    assert r2.iloc[-1].mean() > 0.5                                                      # factors explain most of the variance here


def test_engle_granger_finds_the_cointegrated_pair_not_random_walks():
    rng = np.random.default_rng(11)
    n = 400
    base = np.cumsum(rng.normal(0, 0.01, n))
    lp = pd.DataFrame({"A": base + 4, "B": 0.9 * base + 3 + rng.normal(0, 0.004, n),               # B follows A (cointegrated)
                       "C": np.cumsum(rng.normal(0, 0.01, n)) + 4, "D": np.cumsum(rng.normal(0, 0.01, n)) + 4})
    ind = {"A": "x", "B": "x", "C": "y", "D": "y"}
    pairs = q.engle_granger_pairs(lp, ind, top_n=10, p=0.05)
    assert pairs.get("A", {}).get("peer") == "B" and pairs.get("B", {}).get("peer") == "A"
    assert "C" not in pairs and "D" not in pairs


def test_jump_params_detect_planted_jumps():
    rng = np.random.default_rng(13)
    r = rng.normal(0, 0.01, 300)
    r[[50, 120, 290]] = [0.12, -0.15, 0.10]
    jp = q.jump_params(r)
    assert jp["lam"] == pytest.approx(3 / 250 * 252, abs=0.1)                 # all three planted jumps are inside the last 250 days
    assert jp["last"] == 9                                                    # the latest one is 9 days before the end (index 290 of 300)
    assert jp["sj"] > 0.05 and q.jump_params(r[:30]) is None


def test_bipower_jump_share_is_high_with_one_big_jump_and_low_without():
    rng = np.random.default_rng(17)
    calm = rng.normal(0, 0.01, 60)
    jump = calm.copy(); jump[30] = 0.2
    assert q.bipower_jump_share(jump) > 0.6 > q.bipower_jump_share(calm) + 0.3
    assert q.bipower_jump_share(calm[:10]) is None


def test_rolling_jump_features_agree_with_the_point_functions_and_use_no_future():
    rng = np.random.default_rng(19)
    r = pd.Series(rng.normal(0, 0.01, 600), index=pd.bdate_range("2020-01-01", periods=600))
    r.iloc[500] = 0.2
    f = q.jump_features(r)
    assert f["jump_recent"].iloc[505] == 1.0 and f["jump_recent"].iloc[540] == 0.0
    assert f["jump_lam"].iloc[-1] == pytest.approx(q.jump_params(r.values[1:])["lam"], abs=0.5)
    r2 = r.copy(); r2.iloc[550:] = 0.5
    f2 = q.jump_features(r2)
    assert np.allclose(f.iloc[:550].fillna(-9).values, f2.iloc[:550].fillna(-9).values)
