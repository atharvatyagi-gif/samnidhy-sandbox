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


@pytest.mark.skipif(not BARS.exists(), reason="the 15-minute bar file is not on disk")
def test_live_step_buys_once_sells_on_the_exit_signal_and_never_breaks_the_budget(tmp_path, monkeypatch):
    b = CF.load_bars(); end = pd.Timestamp("2026-06-30 12:00"); bars = b[b.index < end]                          # last complete 15m bar starts 11:45; the 4h bar 08:00 closed at 12:00
    now = datetime(2026, 6, 30, 12, 20, tzinfo=timezone.utc); q = {"bid": float(bars["c"].iloc[-1]) - 5, "ask": float(bars["c"].iloc[-1]) + 5, "mid": float(bars["c"].iloc[-1])}
    led, out = tmp_path / "l.jsonl", tmp_path / "live.json"; monkeypatch.setattr(CL, "MARKS", tmp_path / "m.jsonl")
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([False] * (len(f) - 1) + [s == "flow_momentum"]).values, pd.Series([False] * len(f)).values))
    d1 = CL.live_step(now, bars, q, 96.0, led, out); lines = CL.read_ledger(led); fills = [r for r in lines if r["t"] == "fill"]
    assert len(fills) == 1 and fills[0]["sleeve"] == "flow_momentum" and fills[0]["price"] == round(q["ask"], 2) and fills[0]["stop"] < q["ask"]
    assert fills[0]["qty"] * fills[0]["price"] <= 1_000_000 / 96.0 * 0.5 + 1e-6 and d1["budget_usd"] == round(1_000_000 / 96.0, 2)
    n = len(lines); CL.live_step(now, bars, q, 96.0, led, out); assert len(CL.read_ledger(led)) == n                  # the same bar is never decided twice
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([False] * len(f)).values, pd.Series([True] * len(f)).values))
    bars2 = b[b.index < end + pd.Timedelta(hours=4)]; now2 = datetime(2026, 6, 30, 16, 10, tzinfo=timezone.utc); q2 = {"bid": float(bars2["c"].iloc[-1]), "ask": float(bars2["c"].iloc[-1]) + 5, "mid": float(bars2["c"].iloc[-1])}
    d2 = CL.live_step(now2, bars2, q2, 96.0, led, out); _, S = CL.replay(CL.read_ledger(led))
    assert S["flow_momentum"]["qty"] == 0 and len(S["flow_momentum"]["trades"]) == 1 and d2["trades"][0]["why"] in ("signal", "stop")
    assert d2["equity_usd"] <= d2["budget_usd"] * 1.5 and d2["invested_pct"] == 0.0


@pytest.mark.skipif(not BARS.exists(), reason="the 15-minute bar file is not on disk")
def test_a_late_decision_is_skipped_and_logged(tmp_path, monkeypatch):
    b = CF.load_bars(); bars = b[b.index < pd.Timestamp("2026-06-30 12:00")]; now = datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc); monkeypatch.setattr(CL, "MARKS", tmp_path / "m.jsonl")
    monkeypatch.setattr(CF, "signals", lambda f, s: (pd.Series([True] * len(f)).values, pd.Series([False] * len(f)).values))
    CL.live_step(now, bars, {"bid": 1.0, "ask": 1.0, "mid": 1.0}, 96.0, tmp_path / "l.jsonl", tmp_path / "o.json")
    ds = [r for r in CL.read_ledger(tmp_path / "l.jsonl") if r["t"] == "decision"]
    assert all(r["action"] == "skipped" for r in ds) and not [r for r in CL.read_ledger(tmp_path / "l.jsonl") if r["t"] == "fill"]
