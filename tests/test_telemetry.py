"""Telemetry: record shapes and invalid-value handling, the credit budgeter, 429 handling, delta messages, the snapshot (--once) and the vessel sources.
Fixtures: tests/fixtures/opensky_states.json and aisstream_messages.json are REAL responses recorded from the live services (see their _note);
tests/fixtures/aishub_sample.json is `synthetic_from_docs` (AISHub is members-only, so no real response could be recorded)."""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_telemetry as at  # noqa: E402
import telemetry_sources as ts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
CAR = {"FDX": ["FedEx Express", True], "AIC": ["Air India", False]}
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
NT = NOW.timestamp()
CFG = {"interval_s": 30, "hours_per_day": 24, "max_entities": 4000, "flight_bbox_budget": 6, "vessel_window_s": 0.3, "drop_flight_s": 600, "drop_vessel_s": 1800}


def st(icao, call, lon=77.1, lat=28.6, tpos=NT - 30, ground=False, alt=10000.4, vel=230.26, trk=271.4, vr=1.3, country="India"):
    return [icao, call, country, tpos, tpos, lon, lat, alt, ground, vel, trk, vr, None, alt, "1000", False, 0, 3]


class Resp:
    def __init__(self, code=200, js=None, headers=None):
        self.status_code, self._js, self.headers = code, js if js is not None else {}, headers or {}

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def fixed_config(monkeypatch):
    monkeypatch.setattr(ts, "load_cfg", lambda: dict(CFG))                      # tests must not depend on the tunables in the real config file


# ---------------------------------------------------------------- flights: shapes, nulls, sentinels
def test_real_opensky_response_parses_to_11_field_records_with_the_sources_own_fix_time():
    fx = json.loads((FIX / "opensky_states.json").read_text(encoding="utf-8"))
    states = fx["response"]["states"]
    rows = ts.parse_states(states, CAR)
    assert rows and all(len(r) == 11 for r in rows)
    by_icao = {s[0]: s for s in states}
    for r in rows:
        s = by_icao[r[0]]
        assert r[10] == s[3] and isinstance(r[10], int)                          # fix = time_position, not last_contact and not the download time
        assert r[2] == pytest.approx(s[6], abs=1e-4) and r[3] == pytest.approx(s[5], abs=1e-4)
        assert s[8] is False                                                      # never an aircraft on the ground
    assert fx["recorded_at"] > 0 and "REAL" in fx["_note"]


def test_nulls_ground_and_duplicates_are_dropped_but_missing_speed_is_kept_as_static():
    states = [st("a1", "FDX123 "), st("a2", "AIC101"), st("a3", "GND1", ground=True), st("a4", "NOPOS", lon=None), st("a5", "NOFIX", tpos=None),
              st("a1", "FDX123"), [None], st("a6", "XYZ9", alt=None, vel=None, trk=None, vr=None), st("a7", "BAD", lat=95.0)]
    rows = ts.parse_states(states, CAR)
    assert [r[0] for r in rows] == ["a1", "a2", "a6"]
    assert rows[0] == ["a1", "FDX123", 28.6, 77.1, 10000, 230.3, 271.4, 1.3, "India", 1, int(NT - 30)]
    assert rows[1][9] == 0
    assert rows[2][4:8] == [None, None, None, None]                              # static: the map never moves it


def test_old_fixes_are_dropped_when_a_clock_is_given():
    rows = ts.parse_states([st("a1", "FDX1"), st("a2", "FDX2", tpos=NT - 3600)], CAR, now_ts=NT)
    assert [r[0] for r in rows] == ["a1"]


def test_cargo_flag_comes_only_from_a_freighter_airline_prefix():
    rows = ts.parse_states([st("a1", "fdx9"), st("a2", "AIC1"), st("a3", ""), st("a4", None)], CAR)
    assert [r[9] for r in rows] == [1, 0, 0, 0]


def test_the_real_carrier_file_never_flags_a_passenger_airline_as_cargo():
    car = json.loads((ROOT / "data" / "config" / "cargo_carriers.json").read_text(encoding="utf-8"))["carriers"]
    assert car["FDX"][1] is True and car["UPS"][1] is True
    for k in ("AIC", "IGO", "UAE", "QTR", "DLH", "SIA"):
        assert car[k][1] is False, k
    assert all(len(k) == 3 and k.isupper() for k in car)


# ---------------------------------------------------------------- vessels
def test_real_ais_messages_give_11_field_records_and_the_fix_comes_from_time_utc():
    fx = json.loads((FIX / "aisstream_messages.json").read_text(encoding="utf-8"))
    book = ts.AisBook()
    for m in fx["messages"]:
        book.merge(m["msg"], m["recv_ts"])
    rows = book.rows()
    assert rows and all(len(r) == 11 for r in rows)
    first = next(m for m in fx["messages"] if m["msg"]["MessageType"] == "PositionReport")["msg"]
    want = int(datetime.strptime(first["MetaData"]["time_utc"].split(".")[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    row = next(r for r in rows if r[0] == first["MetaData"]["MMSI"])
    assert row[10] == want and "REAL" in fx["_note"]


def pos(mmsi=1, lat=10.0, lon=70.0, sog=12.3, cog=45.0, hdg=47, ts_sec=30, meta_time=None):
    meta = {"MMSI": mmsi, "ShipName": "TEST "}
    if meta_time:
        meta["time_utc"] = meta_time
    return {"MessageType": "PositionReport", "MetaData": meta, "Message": {"PositionReport": {"UserID": mmsi, "Latitude": lat, "Longitude": lon, "Sog": sog, "Cog": cog, "TrueHeading": hdg, "Timestamp": ts_sec}}}


def test_ais_sentinels_heading_511_sog_102_3_cog_360_bad_positions():
    b = ts.AisBook()
    b.merge(pos(1, hdg=511, cog=88.0), 1_000_030)                                # heading not available: use the course
    b.merge(pos(2, sog=102.3), 1_000_030)                                        # speed not available: static
    b.merge(pos(3, cog=360, hdg=200), 1_000_030)                                 # course not available
    b.merge(pos(4, lat=0.0, lon=0.0), 1_000_030)                                 # null island
    b.merge(pos(5, lat=91.0), 1_000_030)
    b.merge(pos(6, ts_sec=60), 1_000_030)                                        # no usable time: dropped
    r = {x[0]: x for x in b.rows()}
    assert set(r) == {1, 2, 3}
    assert r[1][6] == 88.0 and r[1][5] == 88.0
    assert r[2][4] is None
    assert r[3][5] is None and r[3][6] == 200


def test_ais_fix_from_the_reports_own_second_puts_it_in_the_right_minute():
    b = ts.AisBook()
    recv = 1_000_000 - (1_000_000 % 60) + 5                                      # received 5 s into a minute
    b.merge(pos(1, ts_sec=58), recv)                                             # second 58 can only be the previous minute
    b.merge(pos(2, ts_sec=3), recv)
    r = {x[0]: x for x in b.rows()}
    assert r[1][10] == recv - 5 - 2                                                # minute start - 2 s = second 58 of the PREVIOUS minute
    assert r[2][10] == recv - 2


def test_static_data_fills_type_destination_eta():
    b = ts.AisBook()
    b.merge(pos(7, meta_time="2026-10-06 09:00:00.5 +0000 UTC"))
    b.merge({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 7}, "Message": {"ShipStaticData": {"UserID": 7, "Type": 80, "Destination": "MUNDRA  ", "Eta": {"Month": 10, "Day": 12, "Hour": 6, "Minute": 0}}}})
    row = b.rows()[0]
    assert row[7] == 80 and row[8] == "MUNDRA" and row[9] == "10-12 06:00"


def test_aisstream_subscription_is_lat_lon_and_the_window_ends_on_time():
    sent, fake = {}, None

    class WS:
        async def send(self, m):
            sent["m"] = json.loads(m)

        async def recv(self):
            await asyncio.sleep(10)

    class Ctx:
        async def __aenter__(self):
            return WS()

        async def __aexit__(self, *a):
            return False

    src = ts.AisstreamSource("KEY", connect=lambda url: Ctx())
    rows = asyncio.run(src.listen([{"id": "x", "bbox": [50, 10, 60, 20]}], 0.2))
    assert rows == [] and sent["m"]["BoundingBoxes"] == [[[10, 50], [20, 60]]] and sent["m"]["FilterMessageTypes"] == ["PositionReport", "ShipStaticData"]


def test_aisstream_error_message_is_raised():
    class WS:
        async def send(self, m):
            pass

        async def recv(self):
            return json.dumps({"error": "Api Key Is Not Valid"})

    class Ctx:
        async def __aenter__(self):
            return WS()

        async def __aexit__(self, *a):
            return False

    with pytest.raises(RuntimeError, match="Api Key"):
        asyncio.run(ts.AisstreamSource("K", connect=lambda u: Ctx()).listen([{"id": "x", "bbox": [0, 0, 1, 1]}], 1))


def test_aishub_parser_limit_and_error_header():
    fx = json.loads((FIX / "aishub_sample.json").read_text(encoding="utf-8"))
    assert fx["_note"].startswith("synthetic_from_docs")
    rows = ts.parse_aishub(fx["response"])
    assert [r[0] for r in rows] == [419000001, 419000002] and all(len(r) == 11 for r in rows)
    assert rows[0][10] == int(datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc).timestamp())
    assert rows[1][4] is None and rows[1][5] is None and rows[1][6] is None            # SOG 102.3, COG 360, HEADING 511 -> not available
    clock = [1000.0]
    src = ts.AishubSource("member", get=lambda *a, **k: Resp(200, fx["response"]), clock=lambda: clock[0])
    assert len(src.fetch([{"id": "x", "bbox": [0, 0, 10, 10]}])) == 2
    assert src.fetch([{"id": "x", "bbox": [0, 0, 10, 10]}]) is None                    # inside the one-request-a-minute limit: no call
    clock[0] += 61
    assert src.fetch([{"id": "x", "bbox": [0, 0, 10, 10]}]) is not None
    with pytest.raises(RuntimeError, match="AISHub"):
        ts.parse_aishub([{"ERROR": True, "ERROR_MESSAGE": "Too frequent requests!"}, []])


def test_vessel_source_choice_and_the_off_states():
    assert isinstance(ts.pick_vessel_source({"AISSTREAM_API_KEY": "k"})[0], ts.AisstreamSource)
    assert isinstance(ts.pick_vessel_source({"AISHUB_USERNAME": "m"})[0], ts.AishubSource)
    src, why = ts.pick_vessel_source({"VESSELAPI_KEY": "k"})
    assert src is None and "not verified" in why
    src, why = ts.pick_vessel_source({})
    assert src is None and "AISSTREAM_API_KEY" in why
    with pytest.raises(RuntimeError):
        ts.VesselApiSource("k").fetch([])


# ---------------------------------------------------------------- the budgeter
def test_credit_tiers_follow_opensky():
    assert [ts.area_credits(b) for b in ([0, 0, 5, 5], [0, 0, 10, 10], [0, 0, 20, 20], [0, 0, 30, 30])] == [1, 2, 3, 4]


def test_cadence_arithmetic_for_the_default_corridors():
    lanes = json.loads((ROOT / "data" / "config" / "trade_lanes.json").read_text(encoding="utf-8"))
    anon = at.corridor_boxes(lanes, CFG, "anonymous")
    full = at.corridor_boxes(lanes, CFG, "oauth2")
    assert (len(anon), len(full)) == (3, 6)
    p = ts.plan_cadence(anon, "anonymous", 30, 24)
    cost = sum(ts.area_credits(b["bbox"]) for b in anon)
    assert p["cycle_credits"] == cost == 8 and p["cadence_s"] == 2160 and p["throttled"] is True          # 86400 * 8 / (400 * 0.8)
    assert p["credits_per_day"] <= 320
    q = ts.plan_cadence(full, "oauth2", 30, 24)
    assert q["cycle_credits"] == 14 and q["cadence_s"] == 378 and q["credits_per_day"] <= 3200


def test_the_requested_interval_wins_when_credits_allow_it():
    p = ts.plan_cadence([{"id": "a", "bbox": [0, 0, 3, 3]}], "oauth2", 30, 24)             # 1 credit a pass: 3,200 passes a day would allow 27 s
    assert p["cadence_s"] == 30 and p["throttled"] is False
    assert ts.plan_cadence([{"id": "a", "bbox": [0, 0, 3, 3]}], "oauth2", 1, 24)["cadence_s"] >= 5       # never below OpenSky's own 5 s resolution


def test_remaining_credits_and_no_boxes():
    boxes = [{"id": "a", "bbox": [0, 0, 10, 10]}]
    assert ts.plan_cadence(boxes, "anonymous", 30, 24, remaining=0)["cadence_s"] is None
    low = ts.plan_cadence(boxes, "anonymous", 30, 24, remaining=40)["cadence_s"]
    assert low > ts.plan_cadence(boxes, "anonymous", 30, 24)["cadence_s"]
    assert ts.plan_cadence([], "anonymous")["cadence_s"] is None


def test_rate_gate_reads_headers_and_honours_retry_after():
    t = [100.0]
    g = ts.RateGate(clock=lambda: t[0])
    assert g.on_response(200, {"X-Rate-Limit-Remaining": "397"}) == 0 and g.remaining == 397 and g.wait_s() == 0
    assert g.on_response(429, {"X-Rate-Limit-Retry-After-Seconds": "3600"}) == 3600
    assert g.wait_s() == pytest.approx(3600)
    t[0] += 1000
    assert g.wait_s() == pytest.approx(2600)
    assert ts.RateGate(clock=lambda: 0).on_response(429, {}) == 60                      # no header: a minute, never a retry storm


# ---------------------------------------------------------------- OpenSky source: 429, 401, refused login
def test_a_429_returns_nothing_sets_retry_after_and_does_not_raise():
    src = ts.OpenSkySource({}, get=lambda *a, **k: Resp(429, {}, {"X-Rate-Limit-Retry-After-Seconds": "120"}))
    rows, info = src.fetch_box({"id": "x", "bbox": [0, 0, 10, 10]}, CAR)
    assert rows == [] and info["status"] == 429 and info["retry_after"] == 120 and src.gate.wait_s() > 100


def test_an_expired_token_is_renewed_once():
    calls = {"get": 0, "post": 0}

    def get(url, params=None, headers=None, timeout=0):
        calls["get"] += 1
        return Resp(401) if headers.get("Authorization") == "Bearer OLD" else Resp(200, {"states": [st("a1", "FDX1", tpos=NT)]}, {"X-Rate-Limit-Remaining": "3990"})

    def post(url, data=None, timeout=0):
        calls["post"] += 1
        return Resp(200, {"access_token": "OLD" if calls["post"] == 1 else "NEW", "expires_in": 1800})

    src = ts.OpenSkySource({"OPENSKY_CLIENT_ID": "i", "OPENSKY_CLIENT_SECRET": "s"}, get=get, post=post)
    rows, info = src.fetch_box({"id": "x", "bbox": [0, 0, 10, 10]}, CAR, NT)
    assert calls["post"] == 2 and calls["get"] == 2 and len(rows) == 1 and info["remaining"] == 3990 and src.mode == "oauth2"


def test_a_refused_login_means_anonymous_and_the_smaller_budget():
    src = ts.OpenSkySource({"OPENSKY_CLIENT_ID": "id", "OPENSKY_CLIENT_SECRET": "s3cr3t-xyz"}, post=lambda *a, **k: Resp(401, {"error": "unauthorized_client"}))
    assert src.login() is False and src.mode == "anonymous" and src.login_failed is True
    lanes = json.loads((ROOT / "data" / "config" / "trade_lanes.json").read_text(encoding="utf-8"))
    assert len(at.corridor_boxes(lanes, CFG, src.mode)) == 3


# ---------------------------------------------------------------- state and delta messages
def test_updates_return_only_changes_and_prune_removes_old_fixes():
    s = at.TelemetryState(600, 1800)
    A = ["a", "A", 1, 2, 1, 100, 90, 0, "IN", 0, 1000]
    B = ["b", "B", 3, 4, 1, 100, 90, 0, "IN", 1, 1000]
    assert s.update_flights([A, B]) == [A, B]
    assert s.update_flights([A, B]) == []                                              # nothing changed: nothing sent
    A2 = A[:2] + [1.1, 2.1] + A[4:10] + [1030]
    assert s.update_flights([A2]) == [A2]
    V = [9, "V", 1, 1, 5, 90, 90, 70, None, None, 1000]
    s.update_vessels([V])
    assert s.prune(1000 + 599) == {"fl": [], "ve": []}
    g = s.prune(1000 + 601)
    assert g == {"fl": ["b"], "ve": []}                                                # b's fix is 601 s old; a was refreshed at 1030; the vessel keeps 30 min
    assert s.prune(1030 + 601)["fl"] == ["a"] and s.prune(1000 + 1801)["ve"] == [9]


def test_messages_have_the_documented_shape():
    s = at.TelemetryState()
    A = ["a", "A", 1, 2, 1, 100, 90, 0, "IN", 0, 1000]
    s.update_flights([A])
    full = s.full_msg(1010.4, 2160)
    assert full == {"type": "telemetry", "t": 1010, "cadence_s": 2160, "full": True, "fl": [A], "ve": [], "gone": {"fl": [], "ve": []}}
    d = s.delta_msg(1020, 2160, [A], [], {"fl": ["z"], "ve": []})
    assert d["full"] is False and d["gone"] == {"fl": ["z"], "ve": []} and set(d) == {"type", "t", "cadence_s", "full", "fl", "ve", "gone"}


class FakeFlights:
    name, mode, has_credentials, attribution = "Fake", "anonymous", False, "fake"

    def __init__(self, rows_by_call):
        self.rows, self.n, self.gate = rows_by_call, 0, ts.RateGate()

    def login(self):
        return False

    def fetch_box(self, box, carriers, now_ts=None):
        r = self.rows[min(self.n, len(self.rows) - 1)]
        self.n += 1
        return r, {"status": 200, "credits": 1, "remaining": None, "retry_after": None}


def run_serve(tele, seconds):
    out, stop = [], asyncio.Event()

    async def go():
        task = asyncio.create_task(tele.run(out.append, stop))
        await asyncio.sleep(seconds)
        stop.set()
        await task
    asyncio.run(go())
    return out


def test_the_serve_loop_sends_deltas_only_when_something_changed(monkeypatch):
    monkeypatch.setattr(ts, "MIN_RESOLUTION_S", {"anonymous": 0, "oauth2": 0})
    now = [1_000_000.0]
    a1 = ["a", "A", 1, 2, 1, 100, 90, 0, "IN", 0, 999_990]
    a2 = ["a", "A", 1.1, 2.1, 1, 100, 90, 0, "IN", 0, 1_000_000]
    cfg = {**CFG, "interval_s": 0.05, "hours_per_day": 0.00001}
    tele = at.Telemetry(env={}, cfg=cfg, lanes={"flight_boxes": [{"id": "x", "bbox": [0, 0, 3, 3]}], "anonymous_boxes": 1, "chokepoints": [], "ports": []},
                        carriers={}, flight_src=FakeFlights([[a1], [a1], [a2]]), vessel_src=None, vessel_reason="no key", clock=lambda: now[0])
    msgs = run_serve(tele, 0.6)
    assert msgs and all(m["type"] == "telemetry" and m["full"] is False for m in msgs)
    assert [m["fl"] for m in msgs][0] == [a1]
    assert sum(1 for m in msgs if m["fl"] == [a1]) == 1                                # the unchanged repeat was not sent again
    assert any(m["fl"] == [a2] for m in msgs)
    snap = tele.snapshot()
    assert snap["full"] is True and snap["vessels_reason"] == "no key" and snap["sources"]["vessels"] is None
    assert tele.cadence_s is not None


def test_the_serve_loop_waits_out_a_429(monkeypatch):
    monkeypatch.setattr(ts, "MIN_RESOLUTION_S", {"anonymous": 0, "oauth2": 0})
    src = FakeFlights([[]])
    src.gate.blocked_until = src.gate.clock() + 3600
    cfg = {**CFG, "interval_s": 0.05, "hours_per_day": 0.00001}
    tele = at.Telemetry(env={}, cfg=cfg, lanes={"flight_boxes": [{"id": "x", "bbox": [0, 0, 3, 3]}], "anonymous_boxes": 1, "chokepoints": [], "ports": []},
                        carriers={}, flight_src=src, vessel_src=None, vessel_reason="x")
    run_serve(tele, 0.3)
    assert src.n == 0 and "rate limit" in tele.status["flights"]                      # not one request while the block is on


# ---------------------------------------------------------------- the snapshot (--once)
def fake_get_factory(rows):
    def get(url, params=None, headers=None, timeout=0):
        return Resp(200, {"states": rows}, {"X-Rate-Limit-Remaining": "390"})
    return get


def test_once_snapshot_has_the_documented_fields_and_a_reason_when_vessels_are_off():
    fx = json.loads((FIX / "opensky_states.json").read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(fx["recorded_at"] + 20, tz=timezone.utc)               # 20 s after the real response was recorded
    d = at.build(env={}, now=now, get=fake_get_factory(fx["response"]["states"]), prev=None, force=True)
    for k in ("generated_utc", "cadence_s", "credits_remaining", "sources", "attribution", "stale", "flights", "vessels", "reason"):
        assert k in d
    assert d["vessels"] is None and "AISSTREAM_API_KEY" in d["reason"] and d["cadence_s"] == 2160 and d["credits_remaining"] == 390
    assert d["sources"]["flights"]["mode"] == "anonymous" and d["sources"]["flights"]["areas"] == 3
    assert d["flights"] and all(len(r) == 11 for r in d["flights"]) and d["stale"] is False


def test_a_snapshot_whose_newest_fix_is_older_than_the_drop_age_is_marked_stale():
    d = at.build(env={}, now=NOW, get=fake_get_factory([st("a1", "XYZ1", tpos=NT - 700)]), prev=None, force=True)
    assert d["flights"] and d["stale"] is True


def test_a_recent_snapshot_is_reused_and_spends_no_credits():
    prev = {"generated_utc": (NOW - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ"), "refresh_s": 2160, "flights": [], "vessels": None, "sources": {}}
    d = at.build(env={}, now=NOW, get=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call OpenSky")), prev=prev)
    assert d["reused"] is True
    old = {**prev, "generated_utc": (NOW - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    fresh = at.build(env={}, now=NOW, get=fake_get_factory([]), prev=old)
    assert "reused" not in fresh


def test_a_429_mid_snapshot_keeps_what_was_fetched_and_never_raises():
    seq = iter([Resp(200, {"states": [st("a1", "FDX1", tpos=NT)]}), Resp(429, {}, {"X-Rate-Limit-Retry-After-Seconds": "600"})])
    d = at.build(env={}, now=NOW, get=lambda *a, **k: next(seq), prev=None, force=True)
    assert len(d["flights"]) == 1 and any("credits used up" in e for e in d["sources"]["flights"]["errors"])


def test_one_failing_corridor_does_not_lose_the_others():
    n = {"i": 0}

    def get(url, params=None, headers=None, timeout=0):
        n["i"] += 1
        if n["i"] == 1:
            raise OSError("boom")
        return Resp(200, {"states": [st(f"a{n['i']}", "XYZ1", tpos=NT)]})
    d = at.build(env={}, now=NOW, get=get, prev=None, force=True)
    assert len(d["flights"]) == 2 and any("boom" in e for e in d["sources"]["flights"]["errors"])


def test_a_failing_vessel_feed_turns_only_the_vessel_layer_off():
    def broken(url):
        raise OSError("no route")
    d = at.build(env={"AISSTREAM_API_KEY": "k"}, now=NOW, get=fake_get_factory([st("a1", "FDX1", tpos=NT)]), vessel_connect=broken, prev=None, force=True)
    assert len(d["flights"]) == 1 and d["vessels"] is None and "unavailable" in d["reason"]


def test_a_working_vessel_feed_fills_vessels_and_clears_the_reason():
    fx = json.loads((FIX / "aisstream_messages.json").read_text(encoding="utf-8"))
    msgs = [json.dumps(m["msg"]) for m in fx["messages"]]

    class WS:
        def __init__(self):
            self.q = list(msgs)

        async def send(self, m):
            pass

        async def recv(self):
            if self.q:
                return self.q.pop(0)
            await asyncio.sleep(10)

    class Ctx:
        async def __aenter__(self):
            return WS()

        async def __aexit__(self, *a):
            return False
    d = at.build(env={"AISSTREAM_API_KEY": "k"}, now=NOW, get=fake_get_factory([]), vessel_connect=lambda url: Ctx(), prev=None, force=True)
    assert d["vessels"] and d["reason"] is None and d["sources"]["vessels"]["name"] == "AISstream.io"


def test_main_never_fails_writes_atomically_and_leaves_no_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(at, "OUT", tmp_path / "t.json")
    monkeypatch.setattr(at, "build", lambda **k: (_ for _ in ()).throw(RuntimeError("everything is down")))
    assert at.main(["--once"]) == 0
    d = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert d["flights"] == [] and d["vessels"] is None and "everything is down" in d["reason"] and d["stale"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_budget_report_names_the_achievable_cadence(capsys):
    assert at.main(["--budget-report"]) == 0
    out = capsys.readouterr().out
    assert "ACHIEVABLE cadence" in out and "2160 s" in out and "378 s" in out and "per request" in out


def test_the_old_transport_files_are_gone():
    assert not (ROOT / "scripts" / ("transport" + "_snapshot.py")).exists()


def test_trade_lane_file_is_complete_exact_and_honest():
    lanes = json.loads((ROOT / "data" / "config" / "trade_lanes.json").read_text(encoding="utf-8"))
    uni = ROOT / "data" / "terminal" / "universe.json"
    stocks = {s["s"]: s for s in json.loads(uni.read_text(encoding="utf-8"))["stocks"]} if uni.exists() else None
    inds = {s.get("ind") for s in stocks.values()} if stocks else None
    ids = [c["id"] for c in lanes["chokepoints"]] + [p["id"] for p in lanes["ports"]] + [l["id"] for l in lanes["lanes"]]
    assert len(ids) == len(set(ids)) and {"suez", "malacca", "bab_el_mandeb", "hormuz", "taiwan", "cape"} <= set(ids)
    for b in [c["bbox"] for c in lanes["chokepoints"] + lanes["ports"]] + [f["bbox"] for f in lanes["flight_boxes"]] + [x for l in lanes["lanes"] for x in l["bbox"]]:
        assert len(b) == 4 and b[0] < b[2] and b[1] < b[3] and -180 <= b[0] and b[2] <= 180 and -90 <= b[1] and b[3] <= 90, b
    assert len(lanes["flight_boxes"]) >= 6
    assert "never a statement about one flight" in lanes["note"] and "private or paid customs data" in lanes["note"]
    for l in lanes["lanes"]:
        assert l["kind"] in ("sea", "air") and len(l["path"]) >= 3 and l["exposure"], l["id"]
        for e in l["exposure"]:
            assert e["dir"] in ("+", "-") and len(e["why"]) > 25 and ("sym" in e) != ("ind" in e), (l["id"], e)
            if stocks is not None:
                assert (e["sym"] in stocks) if "sym" in e else (e["ind"] in inds), (l["id"], e)
    geo = {r["id"] for r in json.loads((ROOT / "data" / "config" / "geo_exposure.json").read_text(encoding="utf-8"))["regions"]}
    assert all(x.get("geo_region") in geo | {None} for x in lanes["chokepoints"] + lanes["lanes"])
    text = json.dumps(lanes).lower()
    for w in ("buy", "sell", "target", "recommendation", "guaranteed"):
        assert f" {w} " not in text and f'"{w}' not in text


class ConnectionClosedError(Exception):
    """Stands in for websockets.exceptions.ConnectionClosedError (the class name is what the code recognises)."""


def _ais_ws(messages, then_raise=None):
    class WS:
        def __init__(self):
            self.q = list(messages)

        async def send(self, m):
            pass

        async def recv(self):
            if self.q:
                return self.q.pop(0)
            if then_raise:
                raise then_raise
            await asyncio.sleep(10)

    class Ctx:
        async def __aenter__(self):
            return WS()

        async def __aexit__(self, *a):
            return False
    return lambda url: Ctx()


def test_a_dropped_ais_connection_keeps_the_ships_that_already_arrived():
    fx = json.loads((FIX / "aisstream_messages.json").read_text(encoding="utf-8"))
    msgs = [json.dumps(m["msg"]) for m in fx["messages"]]
    src = ts.AisstreamSource("K", connect=_ais_ws(msgs, then_raise=ConnectionClosedError("no close frame received or sent")))
    rows = asyncio.run(src.listen([{"id": "x", "bbox": [0, 0, 1, 1]}], 5))
    assert rows and all(len(r) == 11 for r in rows)                               # the ships from before the drop are kept


def test_a_connection_dropped_before_anything_arrived_is_an_error_the_layer_reports():
    src = ts.AisstreamSource("K", connect=_ais_ws([], then_raise=ConnectionClosedError("no close frame received or sent")))
    with pytest.raises(RuntimeError, match="closed the connection before sending anything"):
        asyncio.run(src.listen([{"id": "x", "bbox": [0, 0, 1, 1]}], 5))
    other = ts.AisstreamSource("K", connect=_ais_ws([], then_raise=ValueError("a real bug")))
    with pytest.raises(ValueError):                                                 # anything that is not a dropped connection still surfaces
        asyncio.run(other.listen([{"id": "x", "bbox": [0, 0, 1, 1]}], 5))
