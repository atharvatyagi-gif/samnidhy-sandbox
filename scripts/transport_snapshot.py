"""
Positions of aircraft and ships, taken as ONE SNAPSHOT by the workflow (never live in the browser):  python scripts/transport_snapshot.py

  Flights  OpenSky Network /states/all for a few areas (data/config/trade_lanes.json "flight_boxes"). Anonymous use is 400 credits a day, free logins
           (OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET, OAuth2 client credentials) 4,000. The snapshot therefore refreshes at most once an hour without a login
           (every 15 minutes with one) and reuses the last PUBLISHED snapshot in between, so it can never overspend the free allowance.
  Vessels  AISstream.io over a WebSocket for a short listening window around the chokepoints and main Indian ports. Needs a free AISSTREAM_API_KEY; without
           it the vessel layer is simply off and the file says why.
Only positions are real here. Bills of lading, manifests and consignees are private or paid customs data and are not in this file and never will be;
the cargo flag marks airlines that fly dedicated freighters (from the callsign prefix), not what any one flight carries.
Writes data/live_extra/transport.json (gitignored; the site build copies it to site/transport.json). Always exits 0: a failed source must never fail the job.
"""
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANES = ROOT / "data" / "config" / "trade_lanes.json"
CARRIERS = ROOT / "data" / "config" / "cargo_carriers.json"
CFG = ROOT / "data" / "config" / "aladin_config.json"
OUT = ROOT / "data" / "live_extra" / "transport.json"
UA = "B-Lab-Desk/1.0 (student research; educational use)"
OS_STATES = "https://opensky-network.org/api/states/all"
OS_TOKEN = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
AIS_URL = "wss://stream.aisstream.io/v0/stream"
MAX_FLIGHTS = 2500
MAX_STATE_AGE_S = 900                       # a position older than 15 minutes is not "now"


def now_utc():
    return datetime.now(timezone.utc)


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_cfg():
    base = {"flight_bbox_budget": 6, "vessel_window_s": 20, "max_age_min": 20}
    base.update(((load_json(CFG, {}) or {}).get("nexus") or {}).get("transport") or {})
    return base


def area_credits(bbox):
    """OpenSky's price of one /states/all call: 1 / 2 / 3 / 4 credits for an area up to 25 / 100 / 400 / more square degrees."""
    a = abs(bbox[2] - bbox[0]) * abs(bbox[3] - bbox[1])
    return 1 if a <= 25 else 2 if a <= 100 else 3 if a <= 400 else 4


def pick_boxes(all_boxes, authenticated, budget, anonymous_n):
    return all_boxes[: (budget if authenticated else min(budget, anonymous_n))]


# ------------------------------------------------------------------ flights

def parse_states(states, carriers, now_ts, max_age_s=MAX_STATE_AGE_S, seen=None):
    """OpenSky state vectors -> [icao24, callsign, lat, lon, alt_m, vel_ms, hdg, country, cargo]. Airborne aircraft with a position and a recent contact only.
    cargo = 1 when the callsign starts with an airline that flies dedicated freighters (data/config/cargo_carriers.json), else 0. One row per aircraft."""
    seen = set() if seen is None else seen
    out = []
    for s in states or []:
        try:
            icao, call, country, last, lon, lat, alt, ground, vel, trk = s[0], (s[1] or "").strip(), s[2], s[4], s[5], s[6], s[7], s[8], s[9], s[10]
        except (IndexError, TypeError):
            continue
        if ground or lon is None or lat is None or not last or now_ts - last > max_age_s or icao in seen:
            continue
        seen.add(icao)
        pre = call[:3].upper()
        cargo = 1 if (carriers.get(pre) or [None, False])[1] else 0
        out.append([icao, call, round(lat, 3), round(lon, 3), None if alt is None else round(alt), None if vel is None else round(vel, 1),
                    None if trk is None else round(trk), country, cargo])
    return out


def oauth_token(client_id, client_secret, post):
    try:
        r = post(OS_TOKEN, data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}, timeout=20)
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception:  # noqa: BLE001 - fall back to anonymous
        pass
    return None


def fetch_flights(boxes, carriers, token, get, now_ts):
    """-> (rows, credits_used, errors). Stops at the first 429 (credits used up) and keeps what it already has."""
    rows, errors, credits, seen = [], [], 0, set()
    for b in boxes:
        try:
            r = get(OS_STATES, params={"lomin": b["bbox"][0], "lamin": b["bbox"][1], "lomax": b["bbox"][2], "lamax": b["bbox"][3]},
                    headers={"Authorization": "Bearer " + token, "User-Agent": UA} if token else {"User-Agent": UA}, timeout=25)
            if r.status_code == 429:
                errors.append(f"{b['id']}: OpenSky credits used up (retry after {r.headers.get('X-Rate-Limit-Retry-After-Seconds', '?')} s)")
                break
            r.raise_for_status()
            credits += area_credits(b["bbox"])
            rows += parse_states(r.json().get("states"), carriers, now_ts, seen=seen)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{b['id']}: {str(e)[:80]}")
    rows.sort(key=lambda x: (-x[8], x[0]))                  # freighters first, then everything else, so the cap drops the least interesting
    return rows[:MAX_FLIGHTS], credits, errors


# ------------------------------------------------------------------ vessels

def ais_merge(msg, ships):
    """One AISstream message into `ships` {mmsi: record}. PositionReport gives position and movement, ShipStaticData the type and destination."""
    mt = msg.get("MessageType")
    meta = msg.get("MetaData") or msg.get("Metadata") or {}
    body = (msg.get("Message") or {}).get(mt) or {}
    mmsi = meta.get("MMSI") or body.get("UserID")
    if not mmsi:
        return
    rec = ships.setdefault(int(mmsi), {})
    name = (meta.get("ShipName") or body.get("Name") or "").strip()
    if name:
        rec["name"] = name
    if mt == "PositionReport":
        lat = body.get("Latitude", meta.get("latitude", meta.get("Latitude")))
        lon = body.get("Longitude", meta.get("longitude", meta.get("Longitude")))
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0):
            rec.update(lat=round(lat, 3), lon=round(lon, 3), sog=body.get("Sog"), cog=body.get("Cog"))
    elif mt == "ShipStaticData":
        eta = body.get("Eta") or {}
        rec.update(type=body.get("Type"), dest=(body.get("Destination") or "").strip() or None,
                   eta=f"{eta.get('Month', 0):02d}-{eta.get('Day', 0):02d} {eta.get('Hour', 0):02d}:{eta.get('Minute', 0):02d}" if eta.get("Month") else None)


def ships_rows(ships):
    """-> [mmsi, name, lat, lon, sog, cog, ship_type, dest, eta] for ships that have a position."""
    return [[m, r.get("name"), r["lat"], r["lon"], r.get("sog"), r.get("cog"), r.get("type"), r.get("dest"), r.get("eta")]
            for m, r in sorted(ships.items()) if "lat" in r]


async def ais_listen(key, boxes, seconds, connect=None):
    if connect is None:
        import websockets
        connect = websockets.connect
    sub = {"APIKey": key, "BoundingBoxes": [[[b["bbox"][1], b["bbox"][0]], [b["bbox"][3], b["bbox"][2]]] for b in boxes],        # AISstream wants [lat, lon] corners
           "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}
    ships = {}
    async with connect(AIS_URL) as ws:
        await ws.send(json.dumps(sub))
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
            except ValueError:
                continue
            if isinstance(msg, dict) and "error" in msg:
                raise RuntimeError(str(msg["error"])[:100])
            ais_merge(msg, ships)
    return ships_rows(ships)


# ------------------------------------------------------------------ assembling

def previous_snapshot(get, repo_env=None):
    """The snapshot the site is serving right now (https://<owner>.github.io/<repo>/transport.json), or None. Lets a run that starts from a clean checkout
    still know how old the last snapshot is."""
    repo = repo_env or os.environ.get("GITHUB_REPOSITORY")
    if not repo or "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    try:
        r = get(f"https://{owner}.github.io/{name}/transport.json", timeout=10, headers={"User-Agent": UA})
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def age_min(doc, now):
    try:
        return (now - datetime.fromisoformat(doc["generated_utc"].replace("Z", "+00:00"))).total_seconds() / 60
    except (KeyError, ValueError, TypeError, AttributeError):
        return math.inf


def build(env=None, now=None, get=None, post=None, ais=None, prev=None, force=False):
    env = os.environ if env is None else env
    now = now or now_utc()
    import requests
    get = get or requests.get
    post = post or requests.post
    ais = ais or ais_listen
    cfg, lanes, car = load_cfg(), load_json(LANES, {}), (load_json(CARRIERS, {}) or {}).get("carriers", {})
    cid, secret, akey = env.get("OPENSKY_CLIENT_ID", "").strip(), env.get("OPENSKY_CLIENT_SECRET", "").strip(), env.get("AISSTREAM_API_KEY", "").strip()
    authed = bool(cid and secret)
    refresh = 15 if authed else 60                                     # minutes between real OpenSky calls
    if not force:
        prev = prev if prev is not None else previous_snapshot(get)
        if prev and age_min(prev, now) < refresh and prev.get("refresh_min") == refresh:
            prev["reused"] = True
            return prev
    boxes = pick_boxes(lanes.get("flight_boxes", []), authed, cfg["flight_bbox_budget"], lanes.get("anonymous_boxes", 3))
    token = oauth_token(cid, secret, post) if authed else None
    mode = "oauth2" if token else "anonymous"
    flights, credits, ferr = [], 0, []
    try:
        flights, credits, ferr = fetch_flights(boxes, car, token, get, now.timestamp())
    except Exception as e:  # noqa: BLE001
        ferr.append(str(e)[:100])
    vessels, vreason = None, "No free keyless AIS feed: add a free AISSTREAM_API_KEY to turn the vessel layer on."
    if akey:
        vboxes = [{"id": c["id"], "bbox": c["bbox"]} for c in lanes.get("chokepoints", []) + lanes.get("ports", [])]
        try:
            vessels = asyncio.run(ais(akey, vboxes, cfg["vessel_window_s"]))
            vreason = None
        except ImportError:
            vreason = "The websockets package is not installed."
        except Exception as e:  # noqa: BLE001
            vreason = f"AIS feed unavailable: {str(e)[:80]}"
    used = {r[1][:3].upper() for r in flights if r[1]}
    return {"generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "refresh_min": refresh, "max_age_min": refresh * 2,
            "sources": {"flights": {"name": "OpenSky Network", "url": "https://opensky-network.org", "mode": mode, "areas": len(boxes), "credits_used": credits, "errors": ferr,
                                    "attribution": "Flight positions: The OpenSky Network, https://opensky-network.org (free ADS-B data, as received; coverage has gaps)."},
                        "vessels": {"name": "AISstream.io", "url": "https://aisstream.io", "window_s": cfg["vessel_window_s"] if akey else None,
                                    "attribution": "Vessel positions: AISstream.io (terrestrial AIS, a short listening window; coverage has gaps)."}},
            "areas": [{"id": b["id"], "name": b.get("name"), "bbox": b["bbox"]} for b in boxes],
            "carriers": {p: car[p] for p in sorted(used) if p in car},
            "flights": flights, "vessels": vessels, "vessels_reason": vreason}


def main(argv=None):
    force = "--force" in (argv or sys.argv[1:])
    t0 = time.time()
    try:
        from aladin_env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    try:
        doc = build(force=force)
    except Exception as e:  # noqa: BLE001 - never fail the workflow
        print("transport snapshot failed:", str(e)[:120])
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUT)
    src = doc["sources"]["flights"]
    print(f"transport snapshot: {len(doc['flights'])} flights ({sum(r[8] for r in doc['flights'])} on freighter callsigns), "
          f"{'no vessel feed: ' + doc['vessels_reason'] if doc['vessels'] is None else str(len(doc['vessels'])) + ' vessels'}; "
          f"OpenSky {src['mode']}, {src['credits_used']} credits, errors: {src['errors'] or 'none'}{' (reused the last published snapshot)' if doc.get('reused') else ''} ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
