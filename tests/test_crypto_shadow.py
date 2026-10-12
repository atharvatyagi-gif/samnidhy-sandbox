import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import crypto_flow as CF  # noqa: E402
import crypto_shadow as SH  # noqa: E402

needs = pytest.mark.skipif(not (CF.BARS.exists()), reason="the 15-minute bar file is not on disk")
LIVE = {"budget_usd": 10000.0, "fx0": 96.0, "sleeves": {"btc_flow_momentum": {"asset": "BTCUSDT", "equity": 2500.0}, "btc_flow_breakout": {"asset": "BTCUSDT", "equity": 2500.0},
                                                         "eth_flow_momentum": {"asset": "ETHUSDT", "equity": 2500.0}}}
NOW = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = tmp_path_factory.mktemp("shadow"); bars = CF.load_bars(symbol="BTCUSDT"); bars = bars[bars.index < pd.Timestamp("2026-09-30 08:45")]
    SH.MODEL = d / "model.json"; SH.RECENT = d / "recent.csv.gz"
    return d, bars


def q(bars):
    c = float(bars["c"].iloc[-1]); return {"bid": c - 1, "ask": c + 1}


@needs
def test_first_step_starts_fits_and_decides_once_a_day(world):
    d, bars = world; led, page = d / "a.jsonl", d / "a.json"
    out = SH.step(NOW, fetched=bars, quote=q(bars), ledger=led, page=page, live_doc=LIVE)
    lines = SH.read(led); kinds = [r["t"] for r in lines]
    assert kinds[:2] == ["start", "refit"] and kinds.count("decision") == 1 and lines[0]["budget_usd"] == 5000.0
    dec = [r for r in lines if r["t"] == "decision"][0]
    assert dec["day"] == "2026-09-30" and -1 <= dec["target"] <= 1 and abs(out["position"]) <= 1.0001
    n = len(lines); SH.step(NOW + timedelta(minutes=15), fetched=bars, quote=q(bars), ledger=led, page=page, live_doc=LIVE)
    assert len(SH.read(led)) == n                                                       # the same day is never decided twice, the model is not refitted


@needs
def test_a_short_receives_positive_funding_when_the_rate_is_published(world):
    d, bars = world; led, page = d / "b.jsonl", d / "b.json"
    SH.append({"t": "start", "ts": "2026-09-29T00:00:00+00:00", "budget_usd": 5000.0, "fx0": 96.0, "btc_sleeves_equity0": 5000.0}, led)
    SH.append({"t": "decision", "ts": "2026-09-30T04:05:00+00:00", "day": "2026-09-30", "score": -1.0}, led)
    px = float(bars["c"].iloc[-1]); SH.append({"t": "fill", "ts": "2026-09-29T20:00:00+00:00", "units": -0.03, "price": px, "cost": 1.0}, led)
    fu = pd.DataFrame({"ts": pd.to_datetime(["2026-09-30 00:00", "2026-09-30 08:00"]), "rate": [0.0001, 0.0002]})
    SH.step(NOW, fetched=bars, quote=q(bars), fu=fu, ledger=led, page=page, live_doc=LIVE, refit=False)
    f = [r for r in SH.read(led) if r["t"] == "funding"]
    assert [r["at"] for r in f] == ["2026-09-30 00:00:00", "2026-09-30 08:00:00"] and all(r["amount"] > 0 for r in f)
    SH.step(NOW, fetched=bars, quote=q(bars), fu=fu, ledger=led, page=page, live_doc=LIVE, refit=False)
    assert len([r for r in SH.read(led) if r["t"] == "funding"]) == 2                    # never paid twice


@needs
def test_promotion_needs_182_days_and_a_better_return_than_the_live_bitcoin_sleeves(world):
    d, bars = world
    for days, live_eq, want in ((100, 4000.0, False), (200, 6000.0, False), (200, 4000.0, True)):
        led, page = d / f"p{days}{int(live_eq)}.jsonl", d / "p.json"
        SH.append({"t": "start", "ts": (NOW - timedelta(days=days)).isoformat(), "budget_usd": 5000.0, "fx0": 96.0, "btc_sleeves_equity0": 5000.0}, led)
        SH.append({"t": "decision", "ts": NOW.isoformat(), "day": "2026-09-30", "score": 0.0}, led)
        live = json.loads(json.dumps(LIVE)); live["sleeves"]["btc_flow_momentum"]["equity"] = live_eq / 2; live["sleeves"]["btc_flow_breakout"]["equity"] = live_eq / 2
        out = SH.step(NOW, fetched=bars, quote=q(bars), ledger=led, page=page, live_doc=live, refit=False)
        assert bool(out["promoted"]) == want, (days, live_eq)
