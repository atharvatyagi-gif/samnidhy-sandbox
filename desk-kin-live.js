/* The live-entity model behind the WebGL globe (desk-globe3d.js). Everything here is pure (no DOM, no three.js) and pinned by tests/js/kinematics.test.js.
   desk-kin.js has the spherical maths (destination, extrapolate); this file adds what the V4 spec (8.8) needs on top: the offset that smooths a new fix, the daemon's clock,
   per-entity trails, the picking grid and the performance governor. */
import { destination, KN_MS, R_EARTH_M } from "./desk-kin.js";

const RAD = Math.PI / 180;
const wrapLon = x => ((x + 540) % 360 + 360) % 360 - 180;
export { KN_MS };
export const TELE = { flightCap: 120, vesselCap: 300, dropFlight: 600, dropVessel: 1800, tau: 1.2, snapKm: 50, trailLen: 24, trailFadeS: 60, trailMoveM: 100, maxEntities: 4000, frameBudgetMs: 18, minVesselV: 0.26, minFlightV: 1 };
const M_PER_DEG = R_EARTH_M * Math.PI / 180;

/* metres north and east of (lat, lon) -> a position (local flat frame: exact enough for the offsets of a few km used here) */
export function addMeters(lat, lon, north, east) {
  return [lat + north / M_PER_DEG, wrapLon(lon + east / (M_PER_DEG * Math.max(1e-6, Math.cos(lat * RAD))))];
}
export function metersBetween(lat0, lon0, lat1, lon1) {
  const dLon = ((lon1 - lon0 + 540) % 360 + 360) % 360 - 180;
  return { north: (lat1 - lat0) * M_PER_DEG, east: dLon * M_PER_DEG * Math.cos(lat0 * RAD) };
}

/* An entity: its last fix and how it moves. v in m/s (vessels: knots x KN_MS), hdg degrees true. A record with no speed or no course is static and never moves. */
export function makeEntity(kind, id, lat, lon, fix, v, hdg, extra = {}) {
  return { kind, id, lat0: lat, lon0: lon, fix, v: v == null ? null : v, hdg: hdg == null ? null : hdg, static: v == null || hdg == null, offN: 0, offE: 0, tFixLocal: 0, snapped: false, ...extra };
}
export const capOf = (E, T = TELE) => (E.kind === "vessel" ? T.vesselCap : T.flightCap);
export const isStill = (E, T = TELE) => E.static || E.v == null || E.v < (E.kind === "vessel" ? T.minVesselV : T.minFlightV);

/* predict(E, now): where the entity is at server time `nowS`, from its FIX time (never from when the record arrived); stops at the cap */
export function predict(E, nowS, T = TELE) {
  const dt = Math.max(0, Math.min(nowS - E.fix, capOf(E, T)));
  if (isStill(E, T) || dt === 0) return [E.lat0, E.lon0];
  return destination(E.lat0, E.lon0, E.hdg, E.v * dt);
}
export const fixAge = (E, nowS) => Math.max(0, nowS - E.fix);
export const isGhost = (E, nowS, T = TELE) => fixAge(E, nowS) > capOf(E, T);
export const isGone = (E, nowS, T = TELE) => fixAge(E, nowS) > (E.kind === "vessel" ? T.dropVessel : T.dropFlight);

/* what is drawn: the prediction plus the leftover offset of the last correction, decaying with exp(-(now - t) / tau) */
export function renderPos(E, nowS, T = TELE) {
  const [la, lo] = predict(E, nowS, T);
  if (!E.offN && !E.offE) return [la, lo];
  const k = Math.exp(-Math.max(0, nowS - E.tFixLocal) / T.tau);
  return k < 1e-4 ? [la, lo] : addMeters(la, lo, E.offN * k, E.offE * k);
}

/* A new fix arrives: keep what is on screen now, move the model to the new fix, and let the difference fade out (no teleporting, no overshoot).
   A correction larger than snapKm snaps instead (E.snapped = true: the caller fades the marker in). `nowS` is the server clock (ClockSync). */
export function applyFix(E, f, nowS, T = TELE) {
  const shown = renderPos(E, nowS, T);
  Object.assign(E, { lat0: f.lat, lon0: f.lon, fix: f.fix, v: f.v == null ? null : f.v, hdg: f.hdg == null ? null : f.hdg, static: f.v == null || f.hdg == null });
  const where = predict(E, nowS, T), d = metersBetween(where[0], where[1], shown[0], shown[1]);
  E.snapped = Math.hypot(d.north, d.east) > T.snapKm * 1000;
  E.offN = E.snapped ? 0 : d.north;
  E.offE = E.snapped ? 0 : d.east;
  E.tFixLocal = nowS;
  return E;
}

/* The PC's clock may be wrong: the daemon says what time it is (hello.t, epoch seconds) and fix ages are measured on the daemon's clock. */
export class ClockSync {
  constructor(localNow = () => Date.now() / 1000) { this.localNow = localNow; this.offset = 0; this.known = false; }
  sync(serverT) { if (Number.isFinite(serverT)) { this.offset = serverT - this.localNow(); this.known = true; } }
  now() { return this.localNow() + this.offset; }
}

/* ---------- per-entity trail: a ring buffer of the last N points, appended at most once a second and only after a real move ---------- */
export class Trail {
  constructor(len = TELE.trailLen) { this.len = len; this.pts = new Float64Array(len * 3); this.n = 0; this.head = 0; this.lastT = -Infinity; this.lastLat = null; this.lastLon = null; }
  push(lat, lon, t, T = TELE) {
    if (t - this.lastT < 1) return false;
    if (this.lastLat != null) { const d = metersBetween(this.lastLat, this.lastLon, lat, lon); if (Math.hypot(d.north, d.east) < T.trailMoveM) return false; }
    const i = this.head * 3;
    this.pts[i] = lat; this.pts[i + 1] = lon; this.pts[i + 2] = t;
    this.head = (this.head + 1) % this.len;
    this.n = Math.min(this.n + 1, this.len);
    this.lastT = t; this.lastLat = lat; this.lastLon = lon;
    return true;
  }
  /* oldest -> newest [lat, lon, t] */
  points() {
    const out = [];
    for (let k = 0; k < this.n; k++) { const j = ((this.head - this.n + k + this.len * 2) % this.len) * 3; out.push([this.pts[j], this.pts[j + 1], this.pts[j + 2]]); }
    return out;
  }
  /* alpha of a trail point: fades linearly to 0 over trailFadeS; the trail of the selected entity does not fade */
  static alpha(age, fadeS = TELE.trailFadeS, selected = false) { return selected ? 1 : Math.max(0, 1 - age / fadeS); }
}

/* ---------- picking: a screen-space grid hash (cell 16 px), refreshed about 10 times a second; the nearest hit inside the radius ---------- */
export class PickGrid {
  constructor(cell = 16) { this.cell = cell; this.map = new Map(); }
  clear() { this.map.clear(); }
  add(x, y, i) { const k = Math.floor(x / this.cell) + "," + Math.floor(y / this.cell); let a = this.map.get(k); if (!a) this.map.set(k, a = []); a.push([x, y, i]); }
  nearest(x, y, radius) {
    const c = this.cell, r = Math.ceil(radius / c), cx = Math.floor(x / c), cy = Math.floor(y / c);
    let best = null, bd = radius * radius;
    for (let i = cx - r; i <= cx + r; i++) for (let j = cy - r; j <= cy + r; j++) for (const [px, py, id] of this.map.get(i + "," + j) || []) { const d = (px - x) ** 2 + (py - y) ** 2; if (d <= bd) { bd = d; best = id; } }
    return best;
  }
}

/* ---------- performance governor: the median frame time over 2 s windows; steps down (trails off -> at most 2,000 entities -> pixel ratio 1) and back up after 10 s under budget ---------- */
export class Governor {
  static STEPS = ["full", "no_trails", "cap_2000", "pixel_1"];
  constructor(budgetMs = TELE.frameBudgetMs) { this.budget = budgetMs; this.level = 0; this.win = []; this.winStart = null; this.calmSince = null; this.settle = 0; }
  /* feed one frame (its time in ms, the clock in seconds); returns the new level when it changed, else null */
  frame(ms, tS) {
    if (this.winStart == null) this.winStart = tS;
    this.win.push(ms);
    if (tS - this.winStart < 2) return null;
    const s = this.win.slice().sort((a, b) => a - b), med = s[s.length >> 1];
    this.win = []; this.winStart = tS;
    if (this.settle > 0) { this.settle--; return null; }                 // the window right after a step is not judged: the effect of cutting trails or markers shows with a delay
    if (med > this.budget) {
      this.calmSince = null;
      if (this.level < Governor.STEPS.length - 1) { this.level++; this.settle = 1; return this.level; }
      return null;
    }
    if (this.calmSince == null) this.calmSince = tS;
    if (this.level > 0 && tS - this.calmSince >= 10) { this.level--; this.calmSince = tS; this.settle = 1; return this.level; }
    return null;
  }
  get name() { return Governor.STEPS[this.level]; }
  get trails() { return this.level < 1; }
  get maxEntities() { return this.level >= 2 ? 2000 : TELE.maxEntities; }
  get pixelRatioCap() { return this.level >= 3 ? 1 : 2; }
  get reduced() { return this.level > 0; }
}
