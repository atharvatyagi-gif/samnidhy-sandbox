import math

import numpy as np
import pandas as pd

from scripts.aladin2 import data_lake as L
from scripts.aladin2 import forecast as FC
from scripts.aladin2 import synthetic as S


def px_syn(seed=1, n=3000):
    return L.clean_prices(S.make("noise", n=n, seed=seed)[["o", "h", "l", "c", "v"]])


def test_volatility_inputs_are_causal_and_targets_look_forward_only():
    px = px_syn(); gk = FC.gk_var(px); D = px.index[1500]
    pd.testing.assert_frame_equal(FC.har_terms(gk).loc[:D], FC.har_terms(gk.loc[:D]))
    y = FC.forward_logvar(gk, 20)
    assert y.iloc[-1:].isna().all() and np.isfinite(y.iloc[1500])
    assert abs(y.iloc[1500] - np.log(gk.iloc[1501:1521].mean())) < 1e-12                      # bars t+1 .. t+20, never bar t
    bad = pd.Series(False, index=px.index); bad.iloc[1510] = True
    r = FC.forward_return(px["c"], 20, bad); assert np.isnan(r.iloc[1495]) and np.isfinite(r.iloc[1530]) and abs(r.iloc[1530] - np.log(px["c"].iloc[1550] / px["c"].iloc[1530])) < 1e-12


def test_har_volatility_forecast_is_unbiased_on_synthetic_stochastic_volatility():
    ratios = []
    rows = []
    for sd in range(8):
        px = px_syn(sd, 3000); gk = FC.gk_var(px); T = FC.har_terms(gk); lr = np.log(px["c"] / px["c"].shift())
        mk = np.log((lr ** 2).rolling(22).mean().clip(lower=FC.FLOOR)); D = T.assign(mkt_lrv22=mk); D["y"] = FC.forward_logvar(gk, 20)
        D["real"] = lr[::-1].rolling(20).std()[::-1].shift(-1); rows.append(D.dropna())
    A = pd.concat(rows); har = FC.HAR().fit(A, A["y"].values); ratio = (A["real"] / har.sigma(A)).median()
    assert 0.8 < ratio < 1.15                                                                # realised 20-day vol is close to the forecast on average


def test_conformal_makes_a_too_narrow_band_cover_its_nominal_share():
    rng = np.random.default_rng(0); n = 6000; z = rng.standard_t(5, n) * 1.3
    narrow = np.column_stack([np.full(n, -0.2), np.full(n, 0.2)])                              # a deliberately overconfident 'model'
    corr = FC.conformal_adjust(narrow[:3000], z[:3000], 0.8)
    inside = ((z[3000:] > narrow[3000:, 0] - corr) & (z[3000:] < narrow[3000:, 1] + corr)).mean()
    assert abs(inside - 0.8) < 0.025 and corr > 0.5
    assert abs(((z[3000:] > narrow[3000:, 0]) & (z[3000:] < narrow[3000:, 1])).mean() - 0.8) > 0.4         # without it: nowhere near


def test_adjusted_quantiles_never_cross_and_p_up_is_monotone_in_the_centre():
    rng = np.random.default_rng(1); Q = np.sort(rng.normal(0, 1, (200, 7)), axis=1)
    A = FC.adjusted_quantiles(Q, {"50": 0.1, "80": 0.3, "95": 0.6}); assert (np.diff(A, axis=1) >= 0).all()
    base = np.array([-1.9, -1.3, -0.7, 0.0, 0.7, 1.3, 1.9]); shifts = np.linspace(-1, 1, 9)
    p = FC.p_up_from_quantiles(np.array([base + s for s in shifts])); assert (np.diff(p) >= 0).all() and 0.01 <= p.min() and p.max() <= 0.99
    assert abs(FC.p_up_from_quantiles(base[None, :])[0] - 0.5) < 1e-9


def test_path_simulator_matches_theory_for_driftless_returns():
    rng = np.random.default_rng(2); res = FC.standardise(rng.standard_normal(200000)); s = 0.02; H = 20
    paths = FC.simulate_paths(s, s, H, 20000, res, rng, alpha=0.0, beta=0.0)                  # constant volatility: plain random walk
    assert abs(paths[:, -1].std() / (s * math.sqrt(H)) - 1) < 0.03 and abs(paths[:, -1].mean()) < 0.003
    lvl = s * math.sqrt(H); p = FC.touch_prob(paths, lvl); assert 0.22 < p < 0.33                  # continuous theory 0.317; daily monitoring lowers it
    assert abs(FC.touch_prob(paths, -lvl) - p) < 0.03
    f = FC.fan(paths); assert f.shape == (7, H) and (np.diff(f, axis=0) >= 0).all()


def test_ece_and_pinball_basics():
    rng = np.random.default_rng(3); p = rng.uniform(0.2, 0.8, 50000); y = (rng.random(50000) < p).astype(int)
    assert FC.ece(p, y)[0] < 0.01 and FC.ece(np.clip(p + 0.15, 0, 1), y)[0] > 0.1
    z = rng.normal(0, 1, 20000); assert FC.pinball(z, np.full(20000, 0.0), 0.5) < FC.pinball(z, np.full(20000, 1.0), 0.5)
