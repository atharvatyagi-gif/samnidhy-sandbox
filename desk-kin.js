/* Where is it NOW? Pure functions (no DOM), shared by the Globe and tested in tests/js/kinematics.test.js.
   A position report is only true at its own fix time. Between reports the marker is moved along the reported course with spherical destination-point math
   (a degree of longitude shrinks with latitude, so adding metres to degrees would drift badly away from the equator), starting from the FIX time, never from the
   time the file was downloaded. Past a cap the marker stops moving and is drawn as a ghost: after that nobody knows where it is. */
export const R_EARTH_M = 6371008.8;
export const KN_MS = 1852 / 3600;                       // 1 knot in metres per second
const RAD = Math.PI / 180, DEG = 180 / Math.PI;
export const CAPS = { flight: 120, vessel: 300 };       // seconds of extrapolation allowed (aladin_config.json telemetry.*_extrap_cap_s overrides)

const wrapLon = x => ((x + 540) % 360 + 360) % 360 - 180;       // [-180, 180)

/* the point reached from (lat, lon) after `meters` along true course `trackDeg` (0 = north, clockwise) */
export function destination(lat, lon, trackDeg, meters) {
  const d = meters / R_EARTH_M, th = trackDeg * RAD, p1 = lat * RAD, l1 = lon * RAD;
  const sp = Math.sin(p1), cp = Math.cos(p1), sd = Math.sin(d), cd = Math.cos(d);
  const p2 = Math.asin(Math.max(-1, Math.min(1, sp * cd + cp * sd * Math.cos(th))));
  const l2 = l1 + Math.atan2(Math.sin(th) * sd * cp, cd - sp * Math.sin(p2));
  return [p2 * DEG, wrapLon(l2 * DEG)];
}

/* flight row [icao24, callsign, lat, lon, alt_m, vel_ms, hdg_deg, vrate_ms, country, cargo, fix]
   vessel row [mmsi, name, lat, lon, sog_kn, cog_deg, hdg_deg, ship_type, dest, eta, fix] -> {lat, lon, vel (m/s), trk, fix} */
export const flightKin = r => ({ lat: r[2], lon: r[3], vel: r[5], trk: r[6], fix: r[10] });
export const vesselKin = r => ({ lat: r[2], lon: r[3], vel: r[4] == null ? null : r[4] * KN_MS, trk: r[5] != null ? r[5] : r[6], fix: r[10] });

/* -> {lat, lon, age (s since the fix), ghost (older than the cap), moving} ; nowS in epoch seconds */
export function extrapolate(k, nowS, capS) {
  const age = Math.max(0, nowS - k.fix), still = k.vel == null || k.trk == null || !(k.vel > 0);
  const ghost = age > capS;
  if (still || age === 0) return { lat: k.lat, lon: k.lon, age, ghost, moving: false };
  const [lat, lon] = destination(k.lat, k.lon, k.trk, k.vel * Math.min(age, capS));
  return { lat, lon, age, ghost, moving: true };
}

/* telemetry messages from the local daemon: {type:"telemetry", t, cadence_s, full, fl, ve, gone:{fl, ve}}.
   The doc keeps one Map per kind so a delta replaces exactly the records it names and removes the ones listed as gone. */
export function docFromFull(msg) {
  const doc = { live: true, generated_utc: new Date(msg.t * 1000).toISOString(), cadence_s: msg.cadence_s ?? null, sources: msg.sources || {}, vessels_reason: msg.vessels_reason || null, carriers: {}, _f: new Map(), _v: new Map() };
  return applyTelemetry(doc, msg);
}
export function applyTelemetry(doc, msg) {
  if (msg.full) { doc._f.clear(); doc._v.clear(); }
  for (const r of msg.fl || []) doc._f.set(r[0], r);
  for (const r of msg.ve || []) doc._v.set(String(r[0]), r);
  for (const id of (msg.gone || {}).fl || []) doc._f.delete(id);
  for (const id of (msg.gone || {}).ve || []) doc._v.delete(String(id));
  doc.generated_utc = new Date(msg.t * 1000).toISOString();
  if (msg.cadence_s != null) doc.cadence_s = msg.cadence_s;
  if (msg.sources) doc.sources = msg.sources;
  if ("vessels_reason" in msg) doc.vessels_reason = msg.vessels_reason;
  doc.flights = [...doc._f.values()];
  doc.vessels = (doc.sources.vessels === null && !doc._v.size) ? null : [...doc._v.values()];
  doc.lastMsgAt = msg.t;
  return doc;
}

/* "12 s", "3 min", "1.5 h" for an age in seconds */
export function ageLabel(s) {
  if (s == null || !Number.isFinite(s)) return "age unknown";
  return s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
}
