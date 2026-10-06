"""
Where flight and vessel positions come from, and how many calls the free quotas allow.

Flights  OpenSky Network, GET /api/states/all with a bounding box.
         Docs read at build time: https://openskynetwork.github.io/opensky-api/rest.html
         - OAuth2 client credentials ONLY (basic auth was withdrawn): POST the id and secret to
           https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token, send "Authorization: Bearer <token>", tokens last 30 minutes.
         - credits per call by box area: <= 25 sq deg 1, <= 100 sq deg 2, <= 400 sq deg 3, more 4.
         - daily credits: anonymous 400, standard account 4,000, active feeder 8,000.
         - every answer carries X-Rate-Limit-Remaining; a 429 carries X-Rate-Limit-Retry-After-Seconds.
         - anonymous data has 10 s time resolution, logged-in 5 s.
Vessels  VesselSource implementations: AISstream.io (default; free key AISSTREAM_API_KEY, streaming WebSocket; docs https://aisstream.io/documentation.html),
         AISHub (members who share an AIS feed only; ONE request per minute; https://www.aishub.net/api) and VesselAPI (paid; the response format and terms were NOT
         verified at build time, so that source stays off and says so). No source configured: vessels is null with a reason.
Only positions and movement are real here. Bills of lading, manifests and consignees are private or paid customs data and never appear.

Record shapes (the `fix` field is the SOURCE's own position time, epoch seconds, never the time the file was downloaded):
  flight  [icao24, callsign, lat, lon, alt_m, vel_ms, hdg_deg, vrate_ms, country, cargo, fix]
  vessel  [mmsi, name, lat, lon, sog_kn, cog_deg, hdg_deg, ship_type, dest, eta, fix]
A record whose speed or course is null is `static`: the map never moves it.
"""
import asyncio
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANES = ROOT / "data" / "config" / "trade_lanes.json"
CARRIERS = ROOT / "data" / "config" / "cargo_carriers.json"
CFG = ROOT / "data" / "config" / "aladin_config.json"
UA = "B-Lab-Desk/1.0 (student research; educational use)"
OS_STATES = "https://opensky-network.org/api/states/all"
OS_TOKEN = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
AIS_URL = "wss://stream.aisstream.io/v0/stream"
AISHUB_URL = "https://data.aishub.net/ws.php"
DAILY_CREDITS = {"anonymous": 400, "oauth2": 4000}
SAFETY = 0.8                                       # spend at most 80% of a day's credits: other tools and a restart also use them
MIN_RESOLUTION_S = {"anonymous": 10, "oauth2": 5}   # OpenSky's own time resolution: asking faster returns the same data
AIS_NA_HEADING = 511
AIS_SOG_INVALID = 102.3


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_cfg():
    base = {"interval_s": 30, "max_entities": 4000, "hours_per_day": 24, "flight_bbox_budget": 6, "vessel_window_s": 45, "drop_flight_after_s": 600, "drop_vessel_after_s": 1800}
    c = load_json(CFG, {}) or {}
    base.update((c.get("nexus") or {}).get("transport") or {})
    base.update(c.get("telemetry") or {})
    return base


# ------------------------------------------------------------------ credits

def area_credits(bbox):
    """OpenSky's price of one /states/all call for a [lomin, lamin, lomax, lamax] box."""
    a = abs(bbox[2] - bbox[0]) * abs(bbox[3] - bbox[1])
    return 1 if a <= 25 else 2 if a <= 100 else 3 if a <= 400 else 4


def plan_cadence(boxes, mode, interval_s=30, hours_per_day=24, remaining=None, safety=SAFETY):
    """How often can EVERY corridor be refreshed without running out of credits?
    cycle_cost = credits for one pass over all boxes. A day allows limit*safety credits, so passes/day <= limit*safety / cycle_cost and the cadence
    can be no faster than hours*3600 / passes. It is also never faster than the requested interval or OpenSky's own time resolution."""
    limit = DAILY_CREDITS.get(mode, DAILY_CREDITS["anonymous"])
    cost = sum(area_credits(b["bbox"]) for b in boxes)
    if not boxes or not cost:
        return {"cadence_s": None, "cycle_credits": 0, "credits_per_day_limit": limit, "requests_per_day": 0, "credits_per_day": 0, "throttled": False, "boxes": 0}
    usable = limit * safety
    if remaining is not None:
        usable = min(usable, max(0, remaining))
    floor = max(interval_s, MIN_RESOLUTION_S.get(mode, 10))
    need = hours_per_day * 3600 * cost / usable if usable > 0 else math.inf
    cadence = max(floor, need)
    passes = hours_per_day * 3600 / cadence if math.isfinite(cadence) else 0
    return {"cadence_s": None if not math.isfinite(cadence) else (int(math.ceil(cadence)) if cadence >= 10 else round(cadence, 2)), "cycle_credits": cost, "credits_per_day_limit": limit,
            "requests_per_day": int(passes * len(boxes)), "credits_per_day": int(passes * cost), "throttled": bool(need > floor), "boxes": len(boxes)}


class RateGate:
    """One request in flight per host, honouring Retry-After. Pure bookkeeping (the caller sleeps), so tests need no clock."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.blocked_until = 0.0
        self.remaining = None
        self.last_retry_after = None

    def wait_s(self):
        return max(0.0, self.blocked_until - self.clock())

    def on_response(self, status, headers):
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        rem = h.get("x-rate-limit-remaining")
        if rem is not None:
            try:
                self.remaining = int(float(rem))
            except ValueError:
                pass
        if status == 429:
            try:
                ra = float(h.get("x-rate-limit-retry-after-seconds") or h.get("retry-after") or 60)
            except ValueError:
                ra = 60.0
            self.last_retry_after = ra
            self.blocked_until = self.clock() + ra
            return ra
        return 0.0


# ------------------------------------------------------------------ flights

def parse_states(states, carriers, seen=None, now_ts=None, max_age_s=900):
    """OpenSky state vectors -> flight records. Dropped: on the ground, no position, no position time, an old fix (when now_ts is given), a repeat of an aircraft.
    Kept but static: rows with no velocity or no track (the map shows them, never moves them)."""
    seen = set() if seen is None else seen
    out = []
    for s in states or []:
        try:
            icao, call, country, tpos, lon, lat, alt, ground, vel, trk, vr = s[0], (s[1] or "").strip(), s[2], s[3], s[5], s[6], s[7], s[8], s[9], s[10], s[11]
        except (IndexError, TypeError):
            continue
        if ground or lon is None or lat is None or not tpos or icao in seen:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        if now_ts is not None and now_ts - tpos > max_age_s:
            continue
        seen.add(icao)
        cargo = 1 if (carriers.get(call[:3].upper()) or [None, False])[1] else 0
        out.append([icao, call, round(lat, 4), round(lon, 4), None if alt is None else round(alt), None if vel is None else round(vel, 1),
                    None if trk is None else round(trk, 1), None if vr is None else round(vr, 1), country, cargo, int(tpos)])
    return out


class OpenSkySource:
    """FlightSource: one bounding box per call. `get` and `post` are injectable (tests pass fakes)."""
    name = "OpenSky Network"
    url = "https://opensky-network.org"
    attribution = "Flight positions: The OpenSky Network, https://opensky-network.org (free ADS-B data, as received; coverage has gaps)."

    def __init__(self, env=None, get=None, post=None, gate=None, clock=time.time):
        import requests
        self.env = os.environ if env is None else env
        self.get, self.post = get or requests.get, post or requests.post
        self.gate = gate or RateGate()
        self.clock = clock
        self.cid = (self.env.get("OPENSKY_CLIENT_ID") or "").strip()
        self.secret = (self.env.get("OPENSKY_CLIENT_SECRET") or "").strip()
        self.token, self.token_until, self.login_failed = None, 0, False

    @property
    def has_credentials(self):
        return bool(self.cid and self.secret)

    @property
    def mode(self):
        return "oauth2" if self.token else "anonymous"

    def login(self):
        """OAuth2 client credentials. A refused login means anonymous access (never a bigger budget)."""
        if not self.has_credentials:
            return False
        try:
            r = self.post(OS_TOKEN, data={"grant_type": "client_credentials", "client_id": self.cid, "client_secret": self.secret}, timeout=20)
            if r.status_code == 200 and r.json().get("access_token"):
                self.token = r.json()["access_token"]
                self.token_until = self.clock() + max(60, int(r.json().get("expires_in", 1800)) - 60)
                self.login_failed = False
                return True
        except Exception:  # noqa: BLE001
            pass
        self.token, self.login_failed = None, True
        return False

    def fetch_box(self, box, carriers, now_ts=None):
        """-> (rows, info). info = {status, credits, remaining, retry_after}. Raises nothing for 429 (retry_after is set instead)."""
        if self.has_credentials and not self.login_failed and (not self.token or self.clock() >= self.token_until):
            self.login()
        for attempt in (0, 1):
            hdr = {"User-Agent": UA}
            if self.token:
                hdr["Authorization"] = "Bearer " + self.token
            r = self.get(OS_STATES, params={"lomin": box["bbox"][0], "lamin": box["bbox"][1], "lomax": box["bbox"][2], "lamax": box["bbox"][3]}, headers=hdr, timeout=25)
            ra = self.gate.on_response(r.status_code, getattr(r, "headers", {}))
            if r.status_code == 401 and self.token and attempt == 0:      # token expired (30 min): get a new one once
                self.token = None
                if self.login():
                    continue
            break
        info = {"status": r.status_code, "credits": 0, "remaining": self.gate.remaining, "retry_after": ra or None}
        if r.status_code == 429:
            return [], info
        r.raise_for_status()
        info["credits"] = area_credits(box["bbox"])
        return parse_states(r.json().get("states"), carriers, now_ts=now_ts), info


# ------------------------------------------------------------------ vessels

def _ais_time(meta, ts_field, recv_ts):
    """The position time of an AIS report. MetaData.time_utc ("2022-12-29 18:22:32.318353 +0000 UTC") when present; else the report's own second-of-minute
    put on the receive time (the receive time is only used to place that second in the right minute, never as the fix itself)."""
    t = (meta or {}).get("time_utc")
    if isinstance(t, str):
        try:
            return int(datetime.strptime(t.split(".")[0].split(" +")[0].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    if isinstance(ts_field, int) and 0 <= ts_field <= 59:
        base = int(recv_ts) - int(recv_ts) % 60 + ts_field
        return base - 60 if base > recv_ts + 1 else base
    return None


class AisBook:
    """Merges AISstream messages per ship (position reports give movement, static data gives type, destination and ETA). Keeps only valid positions."""

    def __init__(self):
        self.ships = {}

    def merge(self, msg, recv_ts=None):
        recv_ts = time.time() if recv_ts is None else recv_ts
        mt = msg.get("MessageType")
        meta = msg.get("MetaData") or msg.get("Metadata") or {}
        body = (msg.get("Message") or {}).get(mt) or {}
        mmsi = meta.get("MMSI") or body.get("UserID")
        if not mmsi:
            return
        rec = self.ships.setdefault(int(mmsi), {})
        name = (meta.get("ShipName") or body.get("Name") or "").strip()
        if name:
            rec["name"] = name
        if mt == "PositionReport":
            lat = body.get("Latitude", meta.get("latitude", meta.get("Latitude")))
            lon = body.get("Longitude", meta.get("longitude", meta.get("Longitude")))
            if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)):
                return
            sog, cog, hdg = body.get("Sog"), body.get("Cog"), body.get("TrueHeading")
            if not isinstance(sog, (int, float)) or sog >= AIS_SOG_INVALID:
                sog = None                                   # 102.3 kn = "not available": the ship is shown as static
            if not isinstance(cog, (int, float)) or cog >= 360:
                cog = None
            if not isinstance(hdg, (int, float)) or hdg == AIS_NA_HEADING or hdg >= 360:
                hdg = cog                                    # heading 511 = not available: use the course
            fix = _ais_time(meta, body.get("Timestamp"), recv_ts)
            if fix is None:
                return
            rec.update(lat=round(lat, 4), lon=round(lon, 4), sog=sog, cog=cog, hdg=hdg, fix=fix)
        elif mt == "ShipStaticData":
            eta = body.get("Eta") or {}
            rec.update(type=body.get("Type"), dest=(body.get("Destination") or "").strip() or None,
                       eta=f"{eta.get('Month', 0):02d}-{eta.get('Day', 0):02d} {eta.get('Hour', 0):02d}:{eta.get('Minute', 0):02d}" if eta.get("Month") else None)

    def rows(self):
        return [[m, r.get("name"), r["lat"], r["lon"], r.get("sog"), r.get("cog"), r.get("hdg"), r.get("type"), r.get("dest"), r.get("eta"), r["fix"]]
                for m, r in sorted(self.ships.items()) if "lat" in r]


def ais_subscription(key, boxes):
    return {"APIKey": key, "BoundingBoxes": [[[b["bbox"][1], b["bbox"][0]], [b["bbox"][3], b["bbox"][2]]] for b in boxes],      # AISstream wants [lat, lon] corners
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}


class AisstreamSource:
    """VesselSource (default). Needs a free AISSTREAM_API_KEY."""
    name = "AISstream.io"
    url = "https://aisstream.io"
    attribution = "Vessel positions: AISstream.io (terrestrial AIS; coverage has gaps; no SLA)."
    kind = "stream"

    def __init__(self, key, connect=None):
        self.key, self.connect = key, connect

    def _conn(self):
        if self.connect:
            return self.connect
        import websockets
        return websockets.connect

    async def listen(self, boxes, seconds, book=None):
        """A short listening window (workflow snapshot)."""
        book = book or AisBook()
        async with self._conn()(AIS_URL) as ws:
            await ws.send(json.dumps(ais_subscription(self.key, boxes)))
            loop = asyncio.get_event_loop()
            end = loop.time() + seconds
            while True:
                left = end - loop.time()
                if left <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=left)
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(msg, dict) and "error" in msg:
                    raise RuntimeError(str(msg["error"])[:100])
                book.merge(msg)
        return book.rows()

    async def stream(self, boxes, book, stop, on_update=None):
        """Long-lived connection for the local daemon: reconnects with a growing pause, never faster than once a second (AISstream's subscription limit)."""
        pause = 2
        while not stop.is_set():
            try:
                async with self._conn()(AIS_URL) as ws:
                    await ws.send(json.dumps(ais_subscription(self.key, boxes)))
                    pause = 2
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(msg, dict) and "error" in msg:
                            raise RuntimeError(str(msg["error"])[:100])
                        book.merge(msg)
                        if on_update:
                            on_update()
            except Exception as e:  # noqa: BLE001
                if on_update:
                    on_update(error=str(e)[:100])
                try:
                    await asyncio.wait_for(stop.wait(), timeout=pause)
                except asyncio.TimeoutError:
                    pass
                pause = min(pause * 2, 120)


class AishubSource:
    """VesselSource for AISHub members. The terms allow ONE request a minute, so this is a poll, never a stream."""
    name = "AISHub"
    url = "https://www.aishub.net"
    attribution = "Vessel positions: AISHub (shared AIS feed, members only; coverage depends on contributing stations)."
    kind = "poll"
    min_interval_s = 60

    def __init__(self, username, get=None, clock=time.time):
        import requests
        self.username, self.get, self.clock, self.last = username, get or requests.get, clock, 0.0

    def fetch(self, boxes):
        """One call for the union of the boxes. Returns vessel records, or None when called inside the 60 s limit."""
        if self.clock() - self.last < self.min_interval_s:
            return None
        self.last = self.clock()
        lonmin, latmin = min(b["bbox"][0] for b in boxes), min(b["bbox"][1] for b in boxes)
        lonmax, latmax = max(b["bbox"][2] for b in boxes), max(b["bbox"][3] for b in boxes)
        r = self.get(AISHUB_URL, params={"username": self.username, "format": 1, "output": "json", "compress": 0,
                                         "latmin": latmin, "latmax": latmax, "lonmin": lonmin, "lonmax": lonmax}, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        return parse_aishub(r.json(), boxes)


def parse_aishub(js, boxes=None):
    """AISHub JSON is [header, [records]]; the header carries ERROR. Records: MMSI, TIME ("YYYY-MM-DD HH:MM:SS GMT"), LATITUDE, LONGITUDE, SOG, COG, HEADING, NAME, TYPE, DEST, ETA."""
    if not isinstance(js, list) or len(js) < 2:
        return []
    if isinstance(js[0], dict) and js[0].get("ERROR"):
        raise RuntimeError(f"AISHub: {js[0].get('ERROR_MESSAGE', 'error')}")
    out = []
    for r in js[1] or []:
        try:
            lat, lon = float(r["LATITUDE"]), float(r["LONGITUDE"])
            fix = int(datetime.strptime(str(r["TIME"]).replace(" GMT", "").strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except (KeyError, ValueError, TypeError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        sog, cog, hdg = r.get("SOG"), r.get("COG"), r.get("HEADING")
        sog = None if sog is None or float(sog) >= AIS_SOG_INVALID else float(sog)
        cog = None if cog is None or float(cog) >= 360 else float(cog)
        hdg = cog if hdg is None or int(hdg) == AIS_NA_HEADING or float(hdg) >= 360 else float(hdg)
        out.append([int(r["MMSI"]), (r.get("NAME") or "").strip() or None, round(lat, 4), round(lon, 4), sog, cog, hdg, r.get("TYPE"), (r.get("DEST") or "").strip() or None, r.get("ETA"), fix])
    return out


class VesselApiSource:
    """Off on purpose: VesselAPI is a paid plan and its response format and terms were not verified at build time."""
    name = "VesselAPI"
    url = "https://vesselapi.com"
    attribution = ""
    kind = "poll"

    def __init__(self, key):
        self.key = key

    def fetch(self, boxes):
        raise RuntimeError("VesselAPI is not enabled: its terms and response format were not verified when this was built")


def pick_vessel_source(env, connect=None):
    """-> (source or None, reason or None). AISstream first (free), then AISHub, then VesselAPI (never enabled)."""
    key = (env.get("AISSTREAM_API_KEY") or "").strip()
    if key:
        return AisstreamSource(key, connect), None
    hub = (env.get("AISHUB_USERNAME") or "").strip()
    if hub:
        return AishubSource(hub), None
    if (env.get("VESSELAPI_KEY") or "").strip():
        return None, "VesselAPI key found but that source is off: its terms and response format were not verified. Add a free AISSTREAM_API_KEY instead."
    return None, "No free keyless AIS feed: add a free AISSTREAM_API_KEY to turn the vessel layer on."


# ------------------------------------------------------------------ limits

def cap_entities(flights, vessels, boxes_choke, max_entities=4000):
    """Keep at most max_entities: cargo flights first, then vessels inside chokepoint boxes, other vessels, other flights."""
    def inside(v):
        return any(b[0] <= v[3] <= b[2] and b[1] <= v[2] <= b[3] for b in boxes_choke)
    cargo = [f for f in flights if f[9] == 1]
    other_f = [f for f in flights if f[9] != 1]
    vessels = vessels or []
    choke = [v for v in vessels if inside(v)]
    other_v = [v for v in vessels if not inside(v)]
    order = [("fl", cargo), ("ve", choke), ("ve", other_v), ("fl", other_f)]
    keep, left = {"fl": [], "ve": []}, max_entities
    for kind, rows in order:
        take = rows[:max(0, left)]
        keep[kind] += take
        left -= len(take)
    return keep["fl"], keep["ve"]
