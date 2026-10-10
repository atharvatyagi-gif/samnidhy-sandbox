import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import crypto_flow as CF  # noqa: E402
import crypto_live as CL  # noqa: E402

BARS = Path(__file__).resolve().parent.parent / "data" / "crypto" / "bars_15m.csv.gz"
ETH = Path(__file__).resolve().parent.parent / "data" / "crypto" / "bars_15m_eth.csv.gz"


def test_sizing_risks_two_percent_and_never_exceeds_the_account():
    assert CF.size_value(10_000, 100.0, 90.0) == pytest.approx(10_000 * 0.02 / 0.10)                       # 10% stop distance -> 20% of the account
    assert CF.size_value(10_000, 100.0, 99.9) == pytest.approx(10_000 / (1 + CF.COST))                      # tight stop -> capped at the whole account, no leverage
    assert CF.size_value(10_000, 100.0, 101.0) == 0.0 and CF.size_value(0, 100.0, 90.0) == 0.0


def test_replay_builds_cash_position_and_closed_trades_from_the_ledger_alone():
    L = [{"t": "start", "ts": "2026-10-10T00:00:00+00:00", "budget_usd": 10_000, "sleeves": {"a": {"share": 0.5}, "b": {"share": 0.5}}},
         {"t": "fill", "ts": "t1", "sleeve": "a", "side": "buy", "price": 100.0, "qty": 10.0, "cost": 1.2, "stop": 95.0},
         {"t": "fill", "ts": "t2", "sleeve": "a", "side": "sell", "price": 110.0, "qty": 10.0, "cost": 1.32, "why": "signal"}]
    _, S = CL.replay(L)
    assert S["b"]["cash"] == 5000 and S["a"]["qty"] == 0 and S["a"]["cash"] == pytest.approx(5000 - 1000 - 1.2 + 1100 - 1.32)
    t = S["a"]["trades"][0]; assert t["gross"] == 100.0 and t["costs"] == pytest.approx(2.52) and t["net"] == pytest.approx(97.48)


def test_a_stop_fills_at_its_price_or_the_open_if_the_candle_opened_through_it():
    idx = pd.date_range("2026-10-10 00:00", periods=4, freq="15min")
    bars = pd.DataFrame({"o": [100, 100, 94, 100], "h": [101, 101, 95, 101], "l": [99, 98, 93, 99], "c": [100, 99, 94, 100]}, index=idx, dtype=float)
    assert CL.stop_hit(bars, "2026-10-10T00:05:00+00:00", 95.0, 100.0)[0] == 94.0                              # candle 02 opened at 94 under the 95 stop: fills at the open
    bars2 = bars.copy(); bars2.loc[idx[2], ["o", "h", "l", "c"]] = [97.0, 98.0, 94.5, 96.0]
    assert CL.stop_hit(bars2, "2026-10-10T00:05:00+00:00", 95.0, 100.0) == (95.0, str(idx[2]))               # traded down through it: fills at the stop
    assert CL.stop_hit(bars.iloc[:2], "2026-10-10T00:05:00+00:00", 95.0, 94.0) == (94.0, None)                # no candle did it, the live bid is under the stop
    assert CL.stop_hit(bars.iloc[:2], "2026-10-10T00:05:00+00:00", 95.0, 99.0) is None


def _world(end="2026-06-30 12:00"):
    bb, be = CF.load_bars(), CF.load_bars(symbol="ETHUSDT"); e = pd.Timestamp(end); bars = {"BTCUSDT": bb[bb.index < e], "ETHUSDT": be[be.index < e]}
    q = {a: {"bid": float(b["c"].iloc[-1]) - 1, "ask": float(b["c"].iloc[-1]) + 1, "mid": float(b["c"].iloc[-1])} for a, b in bars.items()}; return bb, be, bars, q


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(CL, "MARKS", tmp_path / "m.jsonl"); monkeypatch.setattr(CL, "DEPTH", tmp_path / "d.jsonl")
    return tmp_path / "l.jsonl", tmp_path / "live.json"


FLAT = {"BTCUSDT": {"imb_near": 0.1, "imb_wide": 0.05, "spread_bps": 0.1}, "ETHUSDT": {"imb_near": -0.1, "imb_wide": -0.05, "spread_bps": 0.2}}
needs = pytest.mark.skipif(not (BARS.exists() and ETH.exists()), reason="the 15-minute bar files are not on disk")


@needs
def test_four_sleeves_share_one_hard_budget_and_buy_once_at_the_ask(tmp_path, monkeypatch):
    bb, be, bars, q = _world(); led, out = _paths(tmp_path, monkeypatch); now = datetime(2026, 6, 30, 12, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([False] * (len(f) - 1) + [s == "flow_momentum"]).values, pd.Series([False] * len(f)).values))
    d1 = CL.live_step(now, bars, q, 96.0, led, out, depth=FLAT); lines = CL.read_ledger(led); fills = [r for r in lines if r["t"] == "fill"]
    assert sorted(r["sleeve"] for r in fills) == ["btc_flow_momentum", "eth_flow_momentum"] and all(r["stop"] < r["ask"] for r in fills)
    assert {r["sleeve"]: r["price"] for r in fills} == {"btc_flow_momentum": round(q["BTCUSDT"]["ask"], 2), "eth_flow_momentum": round(q["ETHUSDT"]["ask"], 2)}
    assert all(r["qty"] * r["price"] <= 1_000_000 / 96.0 * 0.25 + 1e-6 for r in fills) and d1["budget_usd"] == round(1_000_000 / 96.0, 2) and sum(v["share"] for v in CL.SLEEVES.values()) == 1.0
    n = len(lines); CL.live_step(now, bars, q, 96.0, led, out, depth=FLAT); assert len(CL.read_ledger(led)) == n                  # the same bar is never decided twice
    assert d1["invested_pct"] > 0 and d1["equity_usd"] < d1["budget_usd"] and set(d1["assets"]) == {"BTCUSDT", "ETHUSDT"}


@needs
def test_exit_signal_sells_at_the_bid_and_the_account_stays_inside_the_budget(tmp_path, monkeypatch):
    bb, be, bars, q = _world(); led, out = _paths(tmp_path, monkeypatch); now = datetime(2026, 6, 30, 12, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([False] * (len(f) - 1) + [True]).values, pd.Series([False] * len(f)).values)); CL.live_step(now, bars, q, 96.0, led, out, depth=FLAT)
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([False] * len(f)).values, pd.Series([True] * len(f)).values))
    e = pd.Timestamp("2026-06-30 16:00"); bars2 = {"BTCUSDT": bb[bb.index < e], "ETHUSDT": be[be.index < e]}; q2 = {a: {"bid": float(b["c"].iloc[-1]), "ask": float(b["c"].iloc[-1]) + 1, "mid": float(b["c"].iloc[-1])} for a, b in bars2.items()}
    d2 = CL.live_step(datetime(2026, 6, 30, 16, 10, tzinfo=timezone.utc), bars2, q2, 96.0, led, out, depth=FLAT); _, S = CL.replay(CL.read_ledger(led))
    assert all(v["qty"] == 0 for v in S.values()) and sum(len(v["trades"]) for v in S.values()) == 4 and d2["invested_pct"] == 0.0 and d2["equity_usd"] <= d2["budget_usd"] * 1.5


@needs
def test_a_late_decision_is_skipped_and_logged(tmp_path, monkeypatch):
    bb, be, bars, q = _world(); led, out = _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([True] * len(f)).values, pd.Series([False] * len(f)).values))
    CL.live_step(datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc), bars, q, 96.0, led, out, depth=FLAT)
    ds = [r for r in CL.read_ledger(led) if r["t"] == "decision"]
    assert len(ds) == 4 and all(r["action"] == "skipped" for r in ds) and not [r for r in CL.read_ledger(led) if r["t"] == "fill"] and all("just started" in r["why"] or "started" in r["why"] for r in ds)


def test_depth_stats_wait_for_enough_samples_then_report_a_rank_correlation_per_coin():
    rows = []
    for i in range(80):
        t = pd.Timestamp("2026-10-10 00:00", tz="UTC") + pd.Timedelta(hours=i); rows.append({"ts": t.isoformat(), "sym": "BTCUSDT", "mid": 100.0 + i, "imb_near": 0.5 if i % 2 else -0.5, "imb_wide": 0.0, "spread_bps": 0.1})
    st = CL.depth_stats(rows); b = st["BTCUSDT"]
    assert b["n"] == 80 and b["next_1h"]["n"] == 79 and b["next_1h"]["rho"] is not None and b["next_1h"]["needs_abs_rho_above"] == pytest.approx(2 / 79 ** 0.5, abs=1e-3) and st["ETHUSDT"] == {"n": 0}
    assert CL.depth_stats(rows[:10])["BTCUSDT"]["next_1h"]["rho"] is None                                        # too few samples: no number


def test_a_trailing_stop_is_tested_against_the_level_in_force_at_each_candle():
    idx = pd.date_range("2026-10-10 00:00", periods=6, freq="15min"); lows = [99, 95, 95, 99, 98, 99]
    bars = pd.DataFrame({"o": [100.0] * 6, "h": [101.0] * 6, "l": [float(x) for x in lows], "c": [100.0] * 6}, index=idx)
    hist = [("2026-10-10T00:05:00+00:00", 90.0), ("2026-10-10T00:45:00+00:00", 98.5)]                         # stop 90 until 00:45, then raised to 98.5
    assert CL.stop_hit(bars, "2026-10-10T00:05:00+00:00", hist, 100.0) == (98.5, str(idx[4]))              # the 95 lows before 00:45 were above the old stop; the 98 low at 01:00 is under the raised one
    assert CL.stop_hit(bars, "2026-10-10T00:05:00+00:00", hist[:1], 100.0) is None
    assert CL.stop_hit(bars, "2026-10-10T00:05:00+00:00", 94.0, 100.0) is None and CL.stop_hit(bars, "2026-10-10T00:05:00+00:00", 96.0, 100.0)[0] == 96.0


@needs
def test_the_bitcoin_momentum_stop_ratchets_up_with_price_and_never_down(tmp_path, monkeypatch):
    bb, be, bars, q = _world(); led, out = _paths(tmp_path, monkeypatch); now = datetime(2026, 6, 30, 12, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([False] * (len(f) - 1) + [s == "flow_momentum"]).values, pd.Series([False] * len(f)).values)); CL.live_step(now, bars, q, 96.0, led, out, depth=FLAT)
    _, S = CL.replay(CL.read_ledger(led)); s0 = S["btc_flow_momentum"]["stop"]; assert s0 is not None and S["eth_flow_momentum"]["stop"] is not None
    e = pd.Timestamp("2026-06-30 16:00"); b2 = bb[bb.index < e].copy(); b2.loc[b2.index[-16:], ["o", "h", "l", "c"]] *= 1.03; bars2 = {"BTCUSDT": b2, "ETHUSDT": be[be.index < e]}
    q2 = {a: {"bid": float(b["c"].iloc[-1]), "ask": float(b["c"].iloc[-1]) + 1, "mid": float(b["c"].iloc[-1])} for a, b in bars2.items()}; monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([False] * len(f)).values, pd.Series([False] * len(f)).values))
    CL.live_step(datetime(2026, 6, 30, 16, 10, tzinfo=timezone.utc), bars2, q2, 96.0, led, out, depth=FLAT); lines = CL.read_ledger(led); _, S2 = CL.replay(lines)
    ups = [r for r in lines if r["t"] == "stop"]; assert len(ups) == 1 and ups[0]["sleeve"] == "btc_flow_momentum" and ups[0]["stop"] > s0 and S2["btc_flow_momentum"]["stop"] == ups[0]["stop"]
    assert S2["eth_flow_momentum"]["stop"] == S["eth_flow_momentum"]["stop"] and any(r["t"] == "rule_change" for r in lines)                  # only the Bitcoin momentum sleeve trails
    n = len(lines); CL.live_step(datetime(2026, 6, 30, 16, 20, tzinfo=timezone.utc), bars2, q2, 96.0, led, out, depth=FLAT); assert len(CL.read_ledger(led)) == n               # the same bar never raises it twice
