"""Transport snapshot: only airborne, recent, positioned aircraft; honest cargo flag; OpenSky credit discipline; AIS merging; never fails the job."""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import transport_snapshot as ts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
NT = NOW.timestamp()
CAR = {"FDX": ["FedEx Express", True], "AIC": ["Air India", False]}


def st(icao, call, lon=77.1, lat=28.6, last=NT - 30, ground=False, alt=10000.4, vel=230.26, trk=271.4, country="India"):
    return [icao, call, country, last, last, lon, lat, alt, ground, vel, trk, 0, None, alt, "1000", False, 0, 3]


# ---------------------------------------------------------------- flights
def test_only_airborne_positioned_recent_aircraft_and_one_row_each():
    states = [st("a1", "FDX123 "), st("a2", "AIC101"), st("a3", "GND1", ground=True), st("a4", "NOPOS", lon=None), st("a5", "OLD1", last=NT - 3600),
              st("a1", "FDX123"), [None], st("a6", "XYZ9", alt=None, vel=None, trk=None)]
    rows = ts.parse_states(states, CAR, NT)
    assert [r[0] for r in rows] == ["a1", "a2", "a6"]
    assert rows[0] == ["a1", "FDX123", 28.6, 77.1, 10000, 230.3, 271, "India", 1]
    assert rows[1][8] == 0 and rows[2][4:7] == [None, None, None]


def test_cargo_flag_comes_only_from_a_freighter_airline_prefix():
    rows = ts.parse_states([st("a1", "fdx9"), st("a2", "AIC1"), st("a3", ""), st("a4", None)], CAR, NT)
    assert [r[8] for r in rows] == [1, 0, 0, 0]


def test_the_real_carrier_file_never_flags_a_passenger_airline_as_cargo():
    car = json.loads((ROOT / "data" / "config" / "cargo_carriers.json").read_text(encoding="utf-8"))["carriers"]
    assert car["FDX"][1] is True and car["UPS"][1] is True
    for k in ("AIC", "IGO", "UAE", "QTR", "DLH", "SIA"):
        assert car[k][1] is False, k
    assert all(len(k) == 3 and k.isupper() for k in car)


def test_credit_costs_follow_opensky_tiers_and_anonymous_use_stays_small():
    assert [ts.area_credits(b) for b in ([0, 0, 5, 5], [0, 0, 10, 10], [0, 0, 20, 20], [0, 0, 30, 30])] == [1, 2, 3, 4]
    lanes = json.loads((ROOT / "data" / "config" / "trade_lanes.json").read_text(encoding="utf-8"))
    anon = ts.pick_boxes(lanes["flight_boxes"], False, 6, lanes["anonymous_boxes"])
    full = ts.pick_boxes(lanes["flight_boxes"], True, 6, lanes["anonymous_boxes"])
    assert len(anon) == 3 and len(full) == 6
    per_run = sum(ts.area_credits(b["bbox"]) for b in anon)
    assert per_run * 24 <= 400, f"{per_run} credits a run would break the 400 a day anonymous limit when refreshed hourly"
    assert sum(ts.area_credits(b["bbox"]) for b in full) * 96 <= 4000


class Resp:
    def __init__(self, code=200, js=None, headers=None):
        self.status_code, self._js, self.headers = code, js or {}, headers or {}

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_a_429_stops_the_calls_keeps_what_was_fetched_and_never_raises():
    boxes = [{"id": "one", "bbox": [0, 0, 5, 5]}, {"id": "two", "bbox": [0, 0, 5, 5]}, {"id": "three", "bbox": [0, 0, 5, 5]}]
    calls = []

    def get(url, **k):
        calls.append(k["params"])
        return Resp(200, {"states": [st("a1", "FDX1")]}) if len(calls) == 1 else Resp(429, headers={"X-Rate-Limit-Retry-After-Seconds": "3600"})
    rows, credits, errors = ts.fetch_flights(boxes, CAR, None, get, NT)
    assert len(calls) == 2 and len(rows) == 1 and credits == 1
    assert "credits used up" in errors[0] and "3600" in errors[0]


def test_one_failing_area_does_not_lose_the_others():
    boxes = [{"id": "bad", "bbox": [0, 0, 5, 5]}, {"id": "good", "bbox": [0, 0, 5, 5]}]
    n = []

    def get(url, **k):
        n.append(1)
        if len(n) == 1:
            raise ConnectionError("down")
        return Resp(200, {"states": [st("a9", "AIC9")]})
    rows, credits, errors = ts.fetch_flights(boxes, CAR, None, get, NT)
    assert len(rows) == 1 and credits == 1 and errors[0].startswith("bad:")


def test_cap_keeps_freighters_first():
    states = [st(f"p{i:04d}", "AIC1", lat=10 + i % 10) for i in range(2600)] + [st("f0001", "FDX1")]
    rows, _, _ = ts.fetch_flights([{"id": "x", "bbox": [0, 0, 5, 5]}], CAR, None, lambda u, **k: Resp(200, {"states": states}), NT)
    assert len(rows) == ts.MAX_FLIGHTS and rows[0][0] == "f0001"


def test_oauth_token_and_fallback():
    assert ts.oauth_token("id", "secret", lambda *a, **k: Resp(200, {"access_token": "TOK"})) == "TOK"
    assert ts.oauth_token("id", "secret", lambda *a, **k: Resp(401)) is None
    assert ts.oauth_token("id", "secret", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("x"))) is None


# ---------------------------------------------------------------- vessels
def msg(mt, mmsi, name, body, **meta):
    return {"MessageType": mt, "MetaData": {"MMSI": mmsi, "ShipName": name, **meta}, "Message": {mt: body}}


def test_ais_messages_merge_per_ship_and_ignore_bad_positions():
    ships = {}
    ts.ais_merge(msg("PositionReport", 419000001, "SEA STAR  ", {"Latitude": 18.9, "Longitude": 72.8, "Sog": 11.2, "Cog": 200.0}), ships)
    ts.ais_merge(msg("ShipStaticData", 419000001, "SEA STAR", {"Type": 80, "Destination": "MUMBAI ", "Eta": {"Month": 10, "Day": 7, "Hour": 5, "Minute": 30}}), ships)
    ts.ais_merge(msg("PositionReport", 419000001, "SEA STAR", {"Latitude": 18.95, "Longitude": 72.85, "Sog": 10.0, "Cog": 201.0}), ships)   # the newer position wins
    ts.ais_merge(msg("PositionReport", 419000002, "NOWHERE", {"Latitude": 0.0, "Longitude": 0.0}), ships)                                       # 0,0 is "no fix"
    ts.ais_merge(msg("PositionReport", 419000003, "BAD", {"Latitude": 95.0, "Longitude": 10.0}), ships)
    ts.ais_merge(msg("ShipStaticData", 419000004, "NO FIX YET", {"Type": 70}), ships)                                                             # static data only: no row
    ts.ais_merge({"MessageType": "PositionReport"}, ships)                                                                                          # no MMSI: ignored
    assert ts.ships_rows(ships) == [[419000001, "SEA STAR", 18.95, 72.85, 10.0, 201.0, 80, "MUMBAI", "10-07 05:30"]]


def test_ais_listener_sends_a_lat_lon_subscription_and_stops_at_the_window():
    sent, feed = [], [json.dumps(msg("PositionReport", 1, "A", {"Latitude": 1.0, "Longitude": 2.0, "Sog": 3, "Cog": 4})),
                      json.dumps(msg("PositionReport", 2, "B", {"Latitude": 5.0, "Longitude": 6.0, "Sog": 7, "Cog": 8}))]

    class WS:
        async def send(self, s):
            sent.append(json.loads(s))

        async def recv(self):
            if feed:
                return feed.pop(0)
            await asyncio.sleep(10)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False
    rows = asyncio.run(ts.ais_listen("KEY", [{"id": "x", "bbox": [10, 20, 30, 40]}], 0.3, connect=lambda url: WS()))
    assert [r[0] for r in rows] == [1, 2]
    s = sent[0]
    assert s["APIKey"] == "KEY" and s["BoundingBoxes"] == [[[20, 10], [40, 30]]]       # [lat, lon] corners, as AISstream requires
    assert set(s["FilterMessageTypes"]) == {"PositionReport", "ShipStaticData"}


def test_ais_error_message_is_raised_so_the_layer_reports_it():
    class WS:
        async def send(self, s):
            pass

        async def recv(self):
            return json.dumps({"error": "Api Key Is Not Valid"})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False
    with pytest.raises(RuntimeError):
        asyncio.run(ts.ais_listen("BAD", [{"id": "x", "bbox": [0, 0, 1, 1]}], 1, connect=lambda url: WS()))


# ---------------------------------------------------------------- the whole document
def fake_get(url, **k):
    return Resp(200, {"states": [st("a1", "FDX1"), st("a2", "AIC2")]})


def test_without_an_ais_key_the_vessel_layer_is_off_and_says_why():
    d = ts.build(env={}, now=NOW, get=fake_get, post=None, prev=None, force=True)
    assert d["vessels"] is None and "AISSTREAM_API_KEY" in d["vessels_reason"]
    assert d["sources"]["flights"]["mode"] == "anonymous" and d["sources"]["flights"]["areas"] == 3 and d["refresh_min"] == 60 and d["max_age_min"] == 120
    assert d["flights"][0][8] == 1 and set(d["carriers"]) == {"FDX", "AIC"}
    assert "OpenSky" in d["sources"]["flights"]["attribution"] and "AISstream" in d["sources"]["vessels"]["attribution"]


def test_with_credentials_more_areas_and_a_faster_refresh():
    d = ts.build(env={"OPENSKY_CLIENT_ID": "i", "OPENSKY_CLIENT_SECRET": "s", "AISSTREAM_API_KEY": "k"}, now=NOW, get=fake_get,
                 post=lambda *a, **k: Resp(200, {"access_token": "T"}), ais=lambda key, boxes, secs: asyncio.sleep(0, result=[[1, "A", 1.0, 2.0, 3, 4, 70, None, None]]), prev=None, force=True)
    assert d["sources"]["flights"]["mode"] == "oauth2" and d["sources"]["flights"]["areas"] == 6 and d["refresh_min"] == 15 and d["max_age_min"] == 30
    assert d["vessels"] == [[1, "A", 1.0, 2.0, 3, 4, 70, None, None]] and d["vessels_reason"] is None


def test_a_failing_ais_feed_turns_only_the_vessel_layer_off():
    def boom(key, boxes, secs):
        raise RuntimeError("socket closed")
    d = ts.build(env={"AISSTREAM_API_KEY": "k"}, now=NOW, get=fake_get, ais=boom, prev=None, force=True)
    assert d["vessels"] is None and "socket closed" in d["vessels_reason"] and len(d["flights"]) == 2


def test_a_recent_published_snapshot_is_reused_so_credits_are_not_spent():
    prev = {"generated_utc": (NOW - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ"), "refresh_min": 60, "flights": [["x"]]}
    calls = []
    d = ts.build(env={}, now=NOW, get=lambda *a, **k: calls.append(1) or fake_get(*a, **k), prev=prev)
    assert d["reused"] is True and d["flights"] == [["x"]] and calls == []
    old = {**prev, "generated_utc": (NOW - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    d2 = ts.build(env={}, now=NOW, get=fake_get, prev=old)
    assert "reused" not in d2 and len(d2["flights"]) == 2
    other_mode = {**prev, "refresh_min": 15}                                         # the login changed: do not trust the old cadence
    assert "reused" not in ts.build(env={}, now=NOW, get=fake_get, prev=other_mode)


def test_previous_snapshot_is_read_from_the_site_and_failures_mean_none():
    seen = []

    def get(url, **k):
        seen.append(url)
        return Resp(200, {"generated_utc": "2026-10-05T11:00:00Z"})
    assert ts.previous_snapshot(get, "octo/site")["generated_utc"] == "2026-10-05T11:00:00Z"
    assert seen == ["https://octo.github.io/site/transport.json"]
    assert ts.previous_snapshot(lambda *a, **k: Resp(404), "octo/site") is None
    assert ts.previous_snapshot(lambda *a, **k: (_ for _ in ()).throw(ConnectionError()), "octo/site") is None
    assert ts.previous_snapshot(get, None) is None and ts.age_min({}, NOW) == float("inf")


def test_main_never_fails_and_writes_atomically(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ts, "OUT", tmp_path / "transport.json")
    monkeypatch.setattr(ts, "build", lambda **k: (_ for _ in ()).throw(RuntimeError("everything is down")))
    assert ts.main([]) == 0 and not (tmp_path / "transport.json").exists()
    assert "failed" in capsys.readouterr().out
    good = {"generated_utc": "x", "flights": [["a", "b", 1, 2, 3, 4, 5, "c", 1]], "vessels": None, "vessels_reason": "off",
            "sources": {"flights": {"mode": "anonymous", "credits_used": 3, "errors": []}}}
    monkeypatch.setattr(ts, "build", lambda **k: good)
    assert ts.main([]) == 0
    assert json.loads((tmp_path / "transport.json").read_text(encoding="utf-8"))["flights"][0][0] == "a"
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------- the lane configuration
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


def test_a_refused_login_does_not_buy_the_bigger_budget_and_is_retried_only_hourly():
    env = {"OPENSKY_CLIENT_ID": "id", "OPENSKY_CLIENT_SECRET": "s3cr3t-xyz"}
    d = ts.build(env=env, now=NOW, get=fake_get, post=lambda *a, **k: Resp(401, {"error": "unauthorized_client"}), prev=None, force=True)
    f = d["sources"]["flights"]
    assert f["mode"] == "anonymous" and f["login_failed"] is True and f["areas"] == 3 and d["refresh_min"] == 60 and d["max_age_min"] == 120
    assert any("refused the login" in e for e in f["errors"]) and "s3cr3t-xyz" not in json.dumps(d)
    prev = {**d, "generated_utc": (NOW - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    again = ts.build(env=env, now=NOW, get=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call OpenSky")), prev=prev)
    assert again["reused"] is True                                                    # 20 minutes old: the hourly cadence still holds, no 15-minute retries
    stale = {**d, "generated_utc": (NOW - timedelta(minutes=70)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    ok = ts.build(env=env, now=NOW, get=fake_get, post=lambda *a, **k: Resp(200, {"access_token": "T"}), prev=stale)
    assert ok["sources"]["flights"]["mode"] == "oauth2" and ok["sources"]["flights"]["login_failed"] is False and ok["refresh_min"] == 15 and ok["sources"]["flights"]["areas"] == 6


def test_no_credentials_at_all_is_not_a_failed_login():
    d = ts.build(env={}, now=NOW, get=fake_get, prev=None, force=True)
    assert d["sources"]["flights"]["login_failed"] is False and d["sources"]["flights"]["errors"] == []


def test_the_vessel_window_is_long_enough_to_catch_the_few_ships_free_ais_coverage_gives():
    assert ts.load_cfg()["vessel_window_s"] >= 40
