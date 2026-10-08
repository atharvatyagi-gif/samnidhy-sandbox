import numpy as np
import pytest

from scripts.aladin2 import evaluate as E
from scripts.aladin2 import lifecycle as LC


def test_bh_matches_the_textbook_example():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216, 0.222, 0.251, 0.269, 0.275, 0.34, 0.341, 0.384, 0.569, 0.594, 0.696, 0.762, 0.94, 0.942, 0.975, 0.986])
    assert E.bh_reject(p, 0.05).sum() == 1 and E.bh_reject(p, 0.25).sum() == 6            # hand-checked: p_(i) <= q*i/25, largest such i (0.05: i=1; 0.25: i=6 because 0.06 <= 0.06)
    assert E.bh_reject(np.array([]), 0.1).size == 0 and not E.bh_reject(np.array([0.5, 0.9]), 0.1).any()


def test_bootstrap_pvalue_is_roughly_uniform_under_the_null_and_small_for_a_real_mean():
    rng = np.random.default_rng(0); ps = []
    for _ in range(300):
        x = rng.normal(0, 0.03, 60); ps.append(E.boot_test(x, 400, 3, rng)[0])
    ps = np.array(ps); assert 0.02 < (ps < 0.05).mean() < 0.10 and 0.35 < ps.mean() < 0.65
    x = rng.normal(0.02, 0.03, 60); p, lb = E.boot_test(x, 800, 3, rng); assert p < 0.01 and lb > 0


def test_bootstrap_respects_dependence_wider_than_iid():
    rng = np.random.default_rng(1); z = rng.normal(0, 1, 400); x = np.convolve(z, np.ones(10) / 10, "same")            # strongly autocorrelated series
    sd_blk = E.stationary_bootstrap(x, 2000, 12, rng).std(); sd_iid = E.stationary_bootstrap(x, 2000, 1.0001, rng).std()
    assert sd_blk > 1.5 * sd_iid


def test_shrinkage_pools_when_there_is_no_real_dispersion_and_trusts_data_when_there_is():
    rng = np.random.default_rng(2); n = np.full(200, 40.0); s2 = np.full(200, 0.0009)
    m_null = rng.normal(0.001, np.sqrt(s2 / n)); sh, w, mu0, tau2 = E.eb_shrink(m_null, n, s2)
    assert w.mean() < 0.15 and abs(sh.mean() - m_null.mean()) < 1e-6 and sh.std() < 0.2 * m_null.std()
    m_real = rng.normal(0.0, 0.01, 200) + rng.normal(0, np.sqrt(s2 / n)); sh2, w2, _, _ = E.eb_shrink(m_real, n, s2)
    assert w2.mean() > 0.6


def test_psr_dsr_properties():
    assert LC.psr(0.0, 100) == pytest.approx(0.5, abs=1e-9)
    assert LC.psr(0.3, 100) > LC.psr(0.3, 30) > 0.5 and LC.psr(-0.3, 100) < 0.5
    x = np.random.default_rng(3).normal(0.01, 0.03, 200)
    assert LC.dsr(x, 40, 0.01) < LC.psr_of(x) and LC.dsr(x, 400, 0.01) < LC.dsr(x, 4, 0.01)         # more trials -> a higher bar


def test_cusum_triggers_on_a_sustained_drop_not_on_noise():
    rng = np.random.default_rng(4)
    assert LC.cusum_alarm(rng.normal(0.01, 0.03, 200), 0.01, 0.03)[0] is None
    x = np.r_[rng.normal(0.01, 0.03, 30), rng.normal(-0.03, 0.03, 30)]
    i, peak = LC.cusum_alarm(x, 0.01, 0.03, 0.5, 5.0); assert i is not None and 30 <= i <= 45 and peak > 5
