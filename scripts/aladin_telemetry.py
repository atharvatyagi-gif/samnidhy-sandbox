"""
Live flight and vessel telemetry.

  python scripts/aladin_telemetry.py --once           one snapshot -> data/live_extra/aladin_telemetry.json (what the Live prices workflow runs; never fails the job)
  python scripts/aladin_telemetry.py --budget-report  what the free quotas allow, per corridor, before anything runs
  python scripts/aladin_telemetry.py --serve          the loop the local tick daemon runs inside its own WebSocket (message type "telemetry")

Cadence is a RESULT, not a promise: telemetry_sources.plan_cadence() works out how often every corridor can be refreshed inside OpenSky's daily credits, and that
number (`cadence_s`) is published and shown. Only the PC running the daemon gets the fast feed; the public site gets the workflow snapshot, whose positions are
marked "not live" once they are older than the extrapolation caps. Positions are real; cargo, bills of lading and consignees are not available and never shown.
"""
import argparse
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telemetry_sources as ts  # noqa: E402

ROOT = ts.ROOT
OUT = ROOT / "data" / "live_extra" / "aladin_telemetry.json"
MIN_REFRESH_S = 900                                   # a workflow snapshot is never refreshed more than every 15 minutes


def now_utc():
    return datetime.now(timezone.utc)


def pick_boxes(all_boxes, authenticated, budget, anonymous_n):
    return all_boxes[: (budget if authenticated else min(budget, anonymous_n))]


def corridor_boxes(lanes, cfg, mode):
    return pick_boxes(lanes.get("flight_boxes", []), mode == "oauth2", cfg["flight_bbox_budget"], lanes.get("anonymous_boxes", 3))


# ------------------------------------------------------------------ the state the daemon keeps, and the deltas it sends

class TelemetryState:
    """Latest record per aircraft and per ship. update_* returns only what changed; prune() removes records whose own fix is too old (`gone`)."""

    def __init__(self, drop_flight_s=600, drop_vessel_s=1800):
        self.fl, self.ve = {}, {}
        self.drop = {"fl": drop_flight_s, "ve": drop_vessel_s}

    @staticmethod
    def _upd(store, rows):
        ch = []
        for r in rows:
            if store.get(r[0]) != r:
                store[r[0]] = r
                ch.append(r)
        return ch

    def update_flights(self, rows):
        return self._upd(self.fl, rows)

    def update_vessels(self, rows):
        return self._upd(self.ve, rows)

    def prune(self, now_ts):
        gone = {"fl": [], "ve": []}
        for kind, store in (("fl", self.fl), ("ve", self.ve)):
            for k in [k for k, r in store.items() if now_ts - r[-1] > self.drop[kind]]:
                del store[k]
                gone[kind].append(k)
        return gone

    def full_msg(self, now_ts, cadence_s, extra=None):
        m = {"type": "telemetry", "t": int(now_ts), "cadence_s": cadence_s, "full": True, "fl": list(self.fl.values()), "ve": list(self.ve.values()), "gone": {"fl": [], "ve": []}}
        m.update(extra or {})
        return m

    def delta_msg(self, now_ts, cadence_s, fl, ve, gone, extra=None):
        m = {"type": "telemetry", "t": int(now_ts), "cadence_s": cadence_s, "full": False, "fl": fl, "ve": ve, "gone": gone}
        m.update(extra or {})
        return m


# ------------------------------------------------------------------ --serve

class Telemetry:
    """Runs inside the daemon. `publish(msg_dict)` broadcasts to every connected browser; `snapshot()` is sent to a browser when it connects."""

    def __init__(self, env=None, cfg=None, lanes=None, carriers=None, flight_src=None, vessel_src=None, vessel_reason=None, clock=time.time, sleep=None):
        self.env = os.environ if env is None else env
        self.cfg = cfg or ts.load_cfg()
        self.lanes = lanes if lanes is not None else ts.load_json(ts.LANES, {})
        self.carriers = carriers if carriers is not None else (ts.load_json(ts.CARRIERS, {}) or {}).get("carriers", {})
        self.flight = flight_src or ts.OpenSkySource(self.env)
        if vessel_src is None and vessel_reason is None:
            vessel_src, vessel_reason = ts.pick_vessel_source(self.env)
        self.vessel, self.vessel_reason = vessel_src, vessel_reason
        self.state = TelemetryState(self.cfg["drop_flight_s"], self.cfg["drop_vessel_s"])
        self.book = ts.AisBook()
        self.clock = clock
        self.cadence_s = None
        self.status = {"flights": "starting", "vessels": "off" if vessel_src is None else "starting", "errors": []}

    def snapshot(self):
        return self.state.full_msg(self.clock(), self.cadence_s, {"vessels_reason": self.vessel_reason, "sources": self.sources()})

    def sources(self):
        s = {"flights": {"name": self.flight.name, "mode": self.flight.mode, "attribution": self.flight.attribution}}
        s["vessels"] = {"name": self.vessel.name, "attribution": self.vessel.attribution} if self.vessel else None
        return s

    def _err(self, text):
        self.status["errors"] = (self.status["errors"] + [text])[-5:]

    async def run(self, publish, stop):
        tasks = [self._flights(publish, stop)]
        if self.vessel is not None:
            tasks.append(self._vessels(publish, stop))
        await asyncio.gather(*tasks)

    async def _wait(self, stop, seconds):
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.2, seconds))
        except asyncio.TimeoutError:
            pass

    async def _flights(self, publish, stop):
        if self.flight.has_credentials:
            await asyncio.to_thread(self.flight.login)
        boxes = corridor_boxes(self.lanes, self.cfg, self.flight.mode)
        if not boxes:
            self.status["flights"] = "no corridors in data/config/trade_lanes.json"
            return
        i = 0
        while not stop.is_set():
            plan = ts.plan_cadence(boxes, self.flight.mode, self.cfg["interval_s"], self.cfg["hours_per_day"], self.flight.gate.remaining)
            self.cadence_s = plan["cadence_s"]
            if self.cadence_s is None:
                self.status["flights"] = "no credits left today"
                await self._wait(stop, 300)
                continue
            if self.flight.gate.wait_s() > 0:                              # a 429: wait exactly as long as OpenSky said
                self.status["flights"] = f"waiting {self.flight.gate.wait_s():.0f}s (rate limit)"
                await self._wait(stop, self.flight.gate.wait_s())
                continue
            box = boxes[i % len(boxes)]
            i += 1
            try:
                rows, info = await asyncio.to_thread(self.flight.fetch_box, box, self.carriers, self.clock())
                self.status["flights"] = "ok" if info["status"] == 200 else f"HTTP {info['status']}"
                ch = self.state.update_flights(rows)
                gone = self.state.prune(self.clock())
                if ch or gone["fl"] or gone["ve"]:
                    publish(self.state.delta_msg(self.clock(), self.cadence_s, ch, [], gone))
            except Exception as e:  # noqa: BLE001
                self.status["flights"] = "error"
                self._err(f"{box['id']}: {str(e)[:80]}")
            await self._wait(stop, self.cadence_s / len(boxes))              # round-robin: one box per slot, every box once per cadence_s

    async def _vessels(self, publish, stop):
        boxes = [{"id": c["id"], "bbox": c["bbox"]} for c in self.lanes.get("chokepoints", []) + self.lanes.get("ports", [])]
        dirty = {"v": False}

        def on_update(error=None):
            if error:
                self.status["vessels"] = "error"
                self._err("vessels: " + error)
            else:
                dirty["v"] = True
                self.status["vessels"] = "ok"

        async def pusher():
            while not stop.is_set():
                await self._wait(stop, 5)
                if dirty["v"]:
                    dirty["v"] = False
                    ch = self.state.update_vessels(self.book.rows())
                    gone = self.state.prune(self.clock())
                    if ch or gone["ve"]:
                        publish(self.state.delta_msg(self.clock(), self.cadence_s, [], ch, gone))

        if self.vessel.kind == "stream":
            await asyncio.gather(self.vessel.stream(boxes, self.book, stop, on_update), pusher())
        else:                                                              # AISHub: one call a minute at most
            while not stop.is_set():
                try:
                    rows = await asyncio.to_thread(self.vessel.fetch, boxes)
                    if rows is not None:
                        ch = self.state.update_vessels(rows)
                        gone = self.state.prune(self.clock())
                        self.status["vessels"] = "ok"
                        if ch or gone["ve"]:
                            publish(self.state.delta_msg(self.clock(), self.cadence_s, [], ch, gone))
                except Exception as e:  # noqa: BLE001
                    self.status["vessels"] = "error"
                    self._err("vessels: " + str(e)[:80])
                await self._wait(stop, self.vessel.min_interval_s)


# ------------------------------------------------------------------ --once

def previous_snapshot(get, repo_env=None):
    """The snapshot the site serves right now (https://<owner>.github.io/<repo>/telemetry.json), or None. Lets a run that starts from a clean checkout know how old it is."""
    repo = repo_env or os.environ.get("GITHUB_REPOSITORY")
    if not repo or "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    try:
        r = get(f"https://{owner}.github.io/{name}/telemetry.json", timeout=10, headers={"User-Agent": ts.UA})
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def age_s(doc, now):
    try:
        return (now - datetime.fromisoformat(doc["generated_utc"].replace("Z", "+00:00"))).total_seconds()
    except (KeyError, ValueError, TypeError, AttributeError):
        return math.inf


def build(env=None, now=None, get=None, post=None, vessel_connect=None, prev=None, force=False):
    env = os.environ if env is None else env
    now = now or now_utc()
    import requests
    get = get or requests.get
    cfg, lanes = ts.load_cfg(), ts.load_json(ts.LANES, {})
    carriers = (ts.load_json(ts.CARRIERS, {}) or {}).get("carriers", {})
    src = ts.OpenSkySource(env, get=get, post=post)
    src.login()
    boxes = corridor_boxes(lanes, cfg, src.mode)
    plan = ts.plan_cadence(boxes, src.mode, cfg["interval_s"], cfg["hours_per_day"])
    refresh = max(MIN_REFRESH_S, plan["cadence_s"] or MIN_REFRESH_S)
    if not force:
        prev = prev if prev is not None else previous_snapshot(get)
        if prev and prev.get("refresh_s") == refresh and age_s(prev, now) < refresh:       # same mode and still inside its own cadence: spend no credits
            prev["reused"] = True
            return prev
    flights, credits, errors, remaining = [], 0, [], None
    if src.login_failed:
        errors.append("OpenSky refused the login (check OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET): using anonymous access")
    seen = set()
    for b in boxes:
        if src.gate.wait_s() > 0:
            break
        try:
            rows, info = src.fetch_box(b, carriers, now.timestamp())
            remaining = info["remaining"] if info["remaining"] is not None else remaining
            if info["status"] == 429:
                errors.append(f"{b['id']}: OpenSky credits used up (retry after {info['retry_after']} s)")
                break
            credits += info["credits"]
            flights += [r for r in rows if r[0] not in seen and not seen.add(r[0])]
        except Exception as e:  # noqa: BLE001
            errors.append(f"{b['id']}: {str(e)[:80]}")
    vsrc, vreason = ts.pick_vessel_source(env, vessel_connect)
    vessels = None
    if vsrc is not None:
        vboxes = [{"id": c["id"], "bbox": c["bbox"]} for c in lanes.get("chokepoints", []) + lanes.get("ports", [])]
        try:
            if vsrc.kind == "stream":
                vessels = asyncio.run(vsrc.listen(vboxes, cfg["vessel_window_s"]))
            else:
                vessels = vsrc.fetch(vboxes) or []
        except ImportError:
            vsrc, vreason = None, "The websockets package is not installed."
        except Exception as e:  # noqa: BLE001
            vsrc, vreason = None, f"Vessel feed unavailable: {str(e)[:80]}"
    choke = [c["bbox"] for c in lanes.get("chokepoints", [])]
    flights, vessels_c = ts.cap_entities(flights, vessels, choke, cfg["max_entities"])
    vessels = vessels_c if vessels is not None else None
    used = {r[1][:3].upper() for r in flights if r[1]}
    fixes = [r[-1] for r in flights + (vessels or [])]
    stale = bool(fixes) and now.timestamp() - max(fixes) > cfg["drop_flight_s"]
    sources = {"flights": {"name": src.name, "url": src.url, "mode": src.mode, "login_failed": src.login_failed, "areas": len(boxes), "credits_used": credits, "errors": errors, "attribution": src.attribution},
               "vessels": {"name": vsrc.name, "url": vsrc.url, "window_s": cfg["vessel_window_s"] if vsrc.kind == "stream" else None, "attribution": vsrc.attribution} if vsrc else None}
    return {"generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "cadence_s": refresh, "refresh_s": refresh, "credits_remaining": remaining,
            "sources": sources, "attribution": [s["attribution"] for s in sources.values() if s and s.get("attribution")], "stale": stale,
            "areas": [{"id": b["id"], "name": b.get("name"), "bbox": b["bbox"]} for b in boxes],
            "carriers": {p: carriers[p] for p in sorted(used) if p in carriers},
            "flights": flights, "vessels": vessels, "reason": vreason if vessels is None else None}


# ------------------------------------------------------------------ --budget-report

def budget_report(env=None):
    env = os.environ if env is None else env
    cfg, lanes = ts.load_cfg(), ts.load_json(ts.LANES, {})
    cid, secret = (env.get("OPENSKY_CLIENT_ID") or "").strip(), (env.get("OPENSKY_CLIENT_SECRET") or "").strip()
    out = [f"OpenSky: {'login settings present (used only if the token request succeeds)' if cid and secret else 'no login: anonymous access'}"]
    for mode in ("anonymous", "oauth2"):
        boxes = corridor_boxes(lanes, cfg, mode)
        p = ts.plan_cadence(boxes, mode, cfg["interval_s"], cfg["hours_per_day"])
        out.append(f"\nmode {mode}: {ts.DAILY_CREDITS[mode]} credits/day, spend at most {int(ts.SAFETY * 100)}% = {int(ts.DAILY_CREDITS[mode] * ts.SAFETY)}; asked for {cfg['interval_s']} s; OpenSky's own resolution is {ts.MIN_RESOLUTION_S[mode]} s")
        out.append(f"  corridors: {p['boxes']}; credits per pass over all: {p['cycle_credits']}")
        for b in boxes:
            c = ts.area_credits(b["bbox"])
            solo = ts.plan_cadence([b], mode, cfg["interval_s"], cfg["hours_per_day"])
            out.append(f"    {b['id']:<18} {c} credit(s) per request; alone it could refresh every {solo['cadence_s']} s")
        out.append(f"  ACHIEVABLE cadence for every corridor together: {p['cadence_s']} s ({p['cadence_s'] / 60:.1f} min){' (limited by credits)' if p['throttled'] else ' (the requested interval)'}")
        out.append(f"  => {p['requests_per_day']} requests/day, {p['credits_per_day']} credits/day over {cfg['hours_per_day']} h")
    out.append(f"\nworkflow snapshot: refreshed at most every {MIN_REFRESH_S // 60} min, or the cadence above if slower; the published file carries this as cadence_s")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="ALADIN flight and vessel telemetry")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--budget-report", action="store_true")
    ap.add_argument("--force", action="store_true", help="ignore the last published snapshot")
    a = ap.parse_args(argv)
    try:
        from aladin_env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    if a.budget_report:
        print(budget_report())
        return 0
    if a.serve:
        async def go():
            stop = asyncio.Event()
            t = Telemetry()
            await t.run(lambda m: print(json.dumps(m)[:200]), stop)
        try:
            asyncio.run(go())
        except KeyboardInterrupt:
            pass
        return 0
    t0 = time.time()
    try:
        doc = build(force=a.force)
    except Exception as e:  # noqa: BLE001 - never fail the workflow
        doc = {"generated_utc": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "cadence_s": None, "credits_remaining": None, "sources": {"flights": None, "vessels": None}, "attribution": [],
               "stale": True, "flights": [], "vessels": None, "reason": f"telemetry failed: {str(e)[:100]}", "areas": [], "carriers": {}}
        print("telemetry failed:", str(e)[:120])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUT)
    fl = (doc.get("sources") or {}).get("flights") or {}
    print(f"telemetry: {len(doc['flights'])} flights ({sum(r[9] for r in doc['flights'])} on freighter callsigns), "
          f"{'no vessel feed: ' + str(doc.get('reason')) if doc['vessels'] is None else str(len(doc['vessels'])) + ' vessels'}; "
          f"OpenSky {fl.get('mode')}, {fl.get('credits_used')} credits, cadence {doc.get('cadence_s')} s, errors: {fl.get('errors') or 'none'}"
          f"{' (reused the last published snapshot)' if doc.get('reused') else ''} ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
