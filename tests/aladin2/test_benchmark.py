import numpy as np
import pandas as pd

from scripts.aladin2 import evaluate as E


def sd(sym, dr, adv, trades):
    s = E.StockData(sym, "x", np.asarray(dr, float), np.asarray(adv, float), 5); s.trades = trades; return s


def trade(e, x, net):
    return {"e": np.array([e]), "x": np.array([x]), "net": np.array([net]), "bars": np.array([float(x - e)])}


def test_benchmark_is_the_universe_mean_return_over_the_trade_days_only():
    n = 10; a = np.full(n, 0.01); b = np.full(n, 0.03)                          # market mean = 2% a day
    U = {"A": sd("A", a, np.ones(n), {"s": trade(2, 5, 0.10)}), "B": sd("B", b, np.ones(n), {})}
    E.attach_benchmark(U, pd.bdate_range("2024-01-01", periods=n))
    assert abs(U["A"].trades["s"]["bm"][0] - 3 * 0.02) < 1e-12                  # days 2,3,4 (= bars) at 2% each
    assert abs(E.window(U["A"], "s", 0, 9)[0][0] - (0.10 - 0.06)) < 1e-12


def test_point_in_time_membership_uses_only_the_previous_days_liquidity():
    n = 30; cal = pd.bdate_range("2024-01-01", periods=n); dr = np.full(n, 0.001)
    adv = {"A": np.r_[np.full(15, 10.0), np.full(15, 1.0)], "B": np.full(n, 5.0)}               # A is the top stock until day 14, then falls below B
    U = {k: sd(k, dr, v, {"s": trade(3, 6, 0.0)}) for k, v in adv.items()}
    E.attach_benchmark(U, cal, top=1)
    assert U["A"].member[1] and U["A"].member[15] and not U["A"].member[16] and U["B"].member[16]      # the switch shows up one day late: known at the previous close
    adv2 = {"A": np.r_[np.full(15, 10.0), np.full(15, 100.0)], "B": np.full(n, 5.0)}               # change ONLY the future liquidity of A
    V = {k: sd(k, dr, v, {"s": trade(3, 6, 0.0)}) for k, v in adv2.items()}; E.attach_benchmark(V, cal, top=1)
    assert (U["A"].member[:16] == V["A"].member[:16]).all() and (U["B"].member[:16] == V["B"].member[:16]).all()


def test_trades_by_non_members_are_dropped():
    n = 30; cal = pd.bdate_range("2024-01-01", periods=n)
    U = {"A": sd("A", np.full(n, 0.0), np.full(n, 10.0), {"s": trade(5, 8, 0.01)}), "B": sd("B", np.full(n, 0.0), np.full(n, 1.0), {"s": trade(5, 8, 0.01)})}
    E.attach_benchmark(U, cal, top=1)
    assert len(U["A"].trades["s"]["e"]) == 1 and len(U["B"].trades["s"]["e"]) == 0


def test_block_bootstrap_is_wider_than_single_month_resampling_for_overlapping_trades():
    rng = np.random.default_rng(0); m = 120; z = rng.normal(0, 1, m); s = np.convolve(z, np.ones(8) / 8, "same") * 100; c = np.full(m, 100.0)
    wide = E._block_means(s, c, 3000, 8, rng).std(); narrow = E._block_means(s, c, 3000, 1, rng).std()
    assert wide > 1.5 * narrow and E.block_len(10) == 1 and E.block_len(100) == 10
