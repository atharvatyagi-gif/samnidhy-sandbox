"""Ticker daemon tests: mock NSE server, fixtures of real responses, bars, sweeps, WebSocket. No network to NSE."""
import asyncio
import json
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_ticker_daemon as d  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- mock NSE
class Mock:
    def __init__(self):
        self.script = []          # list of (status, body) consumed per /api call; empty -> 200 {"ok":1}
        self.calls = 0
        self.warms = 0
        self.srv = None

    def start(self):
        m = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/api"):
                    m.calls += 1
                    st, body = m.script.pop(0) if m.script else (200, '{"ok":1}')
                else:
                    m.warms += 1
                    st, body = 200, "<html></html>"
                self.send_response(st)
                self.send_header("Content-Length", str(len(body.encode())))
                self.end_headers()
                self.wfile.write(body.encode())

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_port}"


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def mock():
    m = Mock()
    m.base = m.start()
    yield m
    m.srv.shutdown()


def session(mock, clk, **kw):
    return d.NseSession(mock.base, clock=clk.now, sleep=clk.sleep, jitter=lambda a, b: 1.0, **kw)


def test_heals_after_403_empty_body_and_429(mock):
    clk = FakeClock()
    mock.script = [(403, "no"), (200, ""), (429, "slow"), (200, '{"a":1}')]
    s = session(mock, clk)
    assert s.get_json("/api/x") == {"a": 1}
    assert s.heals == 2 and mock.warms >= 3 and 1.0 in clk.sleeps
    assert s.status["ok"]


def test_backoff_doubles_and_caps(mock):
    clk = FakeClock()
    mock.script = [(429, "")] * 4
    s = session(mock, clk)
    with pytest.raises(d.NseError):
        s.get_json("/api/x")
    waits = [x for x in clk.sleeps if x in (1.0, 2.0, 4.0, 8.0)]
    assert waits[:3] == [1.0, 2.0, 4.0]


def test_breaker_opens_after_five_failures_then_recovers(mock):
    clk = FakeClock()
    s = session(mock, clk)
    mock.script = [(500, "")] * 40
    for _ in range(5):
        with pytest.raises(d.NseError):
            s.get_json("/api/x", max_tries=1)
    with pytest.raises(d.NseError, match="circuit breaker"):
        s.get_json("/api/x")
    n = mock.calls
    with pytest.raises(d.NseError):
        s.get_json("/api/x")
    assert mock.calls == n                      # nothing sent while paused
    clk.t += 301
    mock.script = [(200, '{"ok":2}')]
    assert s.get_json("/api/x") == {"ok": 2}


def test_rate_never_exceeds_three_per_second(mock):
    clk = FakeClock()
    s = session(mock, clk)
    stamps = []
    for _ in range(30):
        s._throttle(); stamps.append(clk.t)
    for i in range(len(stamps)):
        assert sum(1 for x in stamps if stamps[i] <= x < stamps[i] + 1.0) <= 3


def test_proactive_rewarm(mock):
    clk = FakeClock()
    s = session(mock, clk)
    s.get_json("/api/x"); w = mock.warms
    clk.t += 500
    s.get_json("/api/x")
    assert mock.warms == w + 1


# ---------------------------------------------------------------- parsers on real responses
def test_parsers_on_real_fixtures():
    v = d.parse_variations(fx("nse_variations.json"))
    m = d.parse_most_active(fx("nse_most_active.json"))
    i = d.parse_indices(fx("nse_allindices.json"))
    assert v and m and i
    for t in list(v.values()) + list(m.values()) + list(i.values()):
        assert len(t) == 7 and t[0] > 0
    assert any(k.startswith("NIFTY") for k in i)
    assert all(t[6] and t[6] > 1.7e12 for t in v.values())


def test_parse_ts_formats():
    assert d.parse_ts("01-Oct-2026 16:00:00") == d.parse_ts("2026-10-01 16:00:00")
    assert d.parse_ts("garbage") is None


# ---------------------------------------------------------------- bars
def ms(day, hh, mm, ss=0):
    return int(datetime.strptime(f"{day} {hh:02d}:{mm:02d}:{ss:02d}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=d.IST).timestamp() * 1000)


def test_bars_volume_deltas_and_close():
    b = d.BarBuilder()
    day = "2026-10-01"
    assert b.on_tick("X", 100, 1000, ms(day, 9, 15, 5)) == []
    b.on_tick("X", 101, 1500, ms(day, 9, 20))
    b.on_tick("X", 99, 1400, ms(day, 9, 25))           # cumulative went down: delta clamped to 0
    closed = b.on_tick("X", 100, 1900, ms(day, 9, 31))
    assert len(closed) == 1
    c = closed[0]
    assert c.closed and c.partial and c.h == 101 and c.l == 99 and c.v == 500


def test_bars_ignore_outside_session_and_reset_day():
    b = d.BarBuilder()
    assert b.on_tick("X", 1, 1, ms("2026-10-01", 8, 0)) == []
    b.on_tick("X", 100, 10, ms("2026-10-01", 15, 20))
    b.on_tick("X", 100, 20, ms("2026-10-02", 9, 16))
    assert b.developing("X").v == 0 and b.developing("X").partial


# ---------------------------------------------------------------- levels and sweeps
def daily(n=70, base=100.0):
    return [[f"2026-{(i // 28) + 6:02d}-{(i % 28) + 1:02d}", base, base + 2, base - 2, base, 1000] for i in range(n)]


def test_pdh_pdl_and_swings():
    rows = daily()
    rows[-1] = ["2026-09-30", 100, 103, 98, 100, 1]
    rows[-5][2], rows[-5][3] = 104, 96.5
    L = {x.kind: x for x in d.build_levels(rows, "2026-10-01")}
    assert L["PDH"].price == 103 and L["PDL"].price == 98 and L["PDH"].w == 0.6
    assert L["SWH"].price == 104 and L["SWL"].price == 96.5 and L["SWH"].w == 0.8
    # a level shared by two kinds keeps the heavier weight
    rows[-1][2] = 104
    assert [x.w for x in d.build_levels(rows, "2026-10-01") if x.price == 104] == [0.8]


def test_today_is_excluded_from_levels():
    rows = daily()
    rows[-1] = ["2026-10-01", 100, 140, 60, 100, 1]
    assert max(x.price for x in d.build_levels(rows, "2026-10-01")) < 110


def test_eq_highs_cluster_within_tolerance():
    rows = [["d%03d" % i, 100, 101, 99, 100, 1] for i in range(40)]
    for i, h in ((10, 104.0), (25, 104.1)):             # two fractal highs 0.096% apart
        rows[i][2] = h
    eq = [x for x in d.build_levels(rows) if x.kind == "EQH"]
    assert len(eq) == 1 and eq[0].price == 104.1 and eq[0].w == 1.0
    rows[25][2] = 104.5                                 # 0.48% apart: no cluster
    assert not [x for x in d.build_levels(rows) if x.kind == "EQH"]


def mk_bar(o, h, l, c, v, closed=True):
    return d.Bar("X", 0, o, h, l, c, v, closed)


def test_sweep_high_is_bearish_and_needs_all_conditions():
    det = d.SweepDetector(d.load_cfg())
    lv = [d.Level("PDH", 100.0, 0.6)]
    good = mk_bar(99.5, 101.0, 99.4, 99.6, 3000)        # wick above = (101-99.6)/1.6 = .875
    out = det.evaluate(good, lv, 1000)
    assert len(out) == 1 and out[0].dir == -1 and out[0].confirmed
    assert det.evaluate(good, lv, None) == []                                   # rvol unavailable -> no signal
    assert det.evaluate(mk_bar(99.5, 101.0, 99.4, 99.6, 1500), lv, 1000) == []   # rvol 1.5
    assert det.evaluate(mk_bar(99.5, 101.0, 99.4, 100.5, 3000), lv, 1000) == []  # closed above: a breakout, not a sweep
    assert det.evaluate(mk_bar(99.5, 100.01, 99.4, 99.6, 3000), lv, 1000) == []  # breach too small
    assert det.evaluate(mk_bar(99.0, 101.0, 98.0, 99.9, 3000), lv, 1000) == []  # wick only 37% of the range


def test_sweep_low_is_bullish_and_tiny_range_ignored():
    det = d.SweepDetector(d.load_cfg())
    lv = [d.Level("PDL", 100.0, 1.0)]
    bar = mk_bar(100.5, 100.6, 99.0, 100.4, 3000)
    out = det.evaluate(bar, lv, 1000)
    assert out and out[0].dir == 1
    assert det.evaluate(mk_bar(100.0, 100.1, 99.95, 100.05, 9999), lv, 1000) == []   # range < 0.2%


def test_score_decay_and_clip():
    lv = d.Level("EQL", 100, 1.0)
    sw = d.Sweep("X", 1, lv, 0, 4.0, 0.9, 1.0, True, 0)
    assert d.s_sweep([sw], 0) == 100
    assert abs(d.s_sweep([sw], 45 * 60000) - 100 * 0.3679) < 0.5
    assert d.s_sweep([sw] * 5, 0) == 100                                  # clipped
    neg = d.Sweep("X", -1, lv, 0, 4.0, 0.9, 1.0, True, 0)
    assert d.s_sweep([sw, neg], 0) == 0
    assert d.s_sweep([d.Sweep("X", 1, lv, 0, 4, .9, 1, False, 0)], 0) == 0   # unconfirmed forming bars don't score


def test_hub_end_to_end_sweep_and_daily_reset(tmp_path):
    class LB:
        def build(self, sym, day):
            return [d.Level("PDH", 100.0, 1.0)]

    class SV:
        def mean(self, *a):
            return 1000.0

    t = [0]
    hub = d.Hub(d.load_cfg(), levelbook=LB(), slotvols=SV(), sweep_log_dir=tmp_path, clock=lambda: t[0] / 1000)
    day = "2026-10-01"
    # full 9:15 bar: spike to 101 on heavy volume then back to 99.6
    hub.on_tick("X", 99.5, 99.5, 99.5, 99.5, 98, 0, ms(day, 9, 14, 59) + 60000 - 1)    # at 9:15:59 baseline (partial bar)
    for hh, mm, p, v in ((9, 30, 99.5, 100), (9, 33, 99.4, 150), (9, 37, 101.0, 2000), (9, 43, 99.6, 3300), (9, 44, 99.6, 3400)):
        t[0] = ms(day, hh, mm)
        hub.on_tick("X", p, 99.5, p, 99.4, 98, v, t[0])
    t[0] = ms(day, 9, 46)
    hub.on_tick("X", 99.7, 99.5, 99.7, 99.4, 98, 3500, t[0])
    t[0] = ms(day, 9, 50)
    hub.on_tick("X", 99.7, 99.5, 99.7, 99.4, 98, 3600, t[0])
    t[0] = ms(day, 10, 1)
    hub.on_tick("X", 99.7, 99.5, 99.7, 99.4, 98, 3700, t[0])        # closes the 9:45 bar
    # 9:30 bar (opened at the 9:30 baseline tick) holds the spike: closes at 9:45
    assert hub.confirmed.get("X"), "sweep expected"
    ch, ns = hub.drain()
    assert ns and ns[0].dir == -1 and hub.sweep_msg(ns)["agg"]["X"] < 0
    assert list(tmp_path.glob("*.jsonl"))
    hub.on_tick("X", 99.0, 99, 99, 99, 98, 10, ms("2026-10-02", 9, 20))
    assert hub.confirmed == {}


def test_hub_emits_changes_only():
    hub = d.Hub(d.load_cfg(), levelbook=type("L", (), {"build": lambda s, a, b: []})(), slotvols=type("S", (), {"mean": lambda s, *a: None})())
    assert hub.on_tick("A", 1, 1, 1, 1, 1, 5, 1) is True
    assert hub.on_tick("A", 1, 1, 1, 1, 1, 5, 2) is False
    assert hub.on_tick("A", 2, 1, 2, 1, 1, 5, 3) is True
    ch, _ = hub.drain()
    assert list(ch) == ["A"] and hub.drain() == ({}, [])


def test_market_window():
    assert d.market_window(ms("2026-10-02", 10, 0))            # Friday
    assert not d.market_window(ms("2026-10-02", 15, 45))
    assert not d.market_window(ms("2026-10-03", 10, 0))        # Saturday


# ---------------------------------------------------------------- websocket
def test_websocket_messages_origin_and_health():
    websockets = pytest.importorskip("websockets")
    from websockets.asyncio.client import connect
    import urllib.request

    hub = d.Hub(d.load_cfg(), levelbook=type("L", (), {"build": lambda s, a, b: []})(), slotvols=type("S", (), {"mean": lambda s, *a: None})())
    hub.on_tick("TCS", 100, 99, 101, 98, 99, 500, 1_700_000_000_000)
    src = d.NseWebSource(d.NseSession("http://127.0.0.1:9"))
    src.poll_once = lambda: ({}, {})

    async def run():
        stop = asyncio.Event()
        port = 18787
        task = asyncio.create_task(d.serve(hub, src, port, stop=stop))
        await asyncio.sleep(0.5)
        async with connect(f"ws://127.0.0.1:{port}/ws/ticks", origin="https://atharvatyagi-gif.github.io") as ws:
            hello = json.loads(await ws.recv())
            snap = json.loads(await ws.recv())
            await ws.send(json.dumps({"type": "focus", "syms": ["TCS", "ZZZ"]}))
            warn = json.loads(await asyncio.wait_for(ws.recv(), 3))
        bad = None
        try:
            async with connect(f"ws://127.0.0.1:{port}/ws/ticks", origin="https://evil.example"):
                bad = "connected"
        except Exception as e:
            bad = type(e).__name__
        health = await asyncio.to_thread(lambda: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3).read()))
        stop.set()
        await asyncio.wait_for(task, 5)
        return hello, snap, warn, bad, health

    hello, snap, warn, bad, health = asyncio.run(run())
    assert hello["type"] == "hello" and hello["ok"] and hello["src"] == "nse-web"
    assert snap["type"] == "snap" and snap["q"]["TCS"][0] == 100
    assert warn["type"] == "warn" and "ZZZ" in warn["msg"]
    assert bad != "connected"
    assert health["src"] == "nse-web" and health["symbols_tracked"] == 1
