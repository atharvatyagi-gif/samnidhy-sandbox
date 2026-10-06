// Dead-reckoning and telemetry-delta tests. CommonJS on purpose: it loads the ES module with import(), so it runs as `node --test tests/js/kinematics.test.js`.
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const load = () => import(pathToFileURL(path.join(__dirname, "..", "..", "desk-kin.js")).href);
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg || ""} ${a} vs ${b} (tol ${tol})`);
const M_PER_DEG = 6371008.8 * Math.PI / 180;           // 111,194.93 m

test("due north from the equator: 1 degree of latitude is R*pi/180 metres", async () => {
  const { destination } = await load();
  const [lat, lon] = destination(0, 10, 0, M_PER_DEG);
  near(lat, 1, 1e-9); near(lon, 10, 1e-9);
});

test("due east at 60N: a degree of longitude is only half as long (the naive degrees formula would be wrong by 2x)", async () => {
  const { destination } = await load();
  const [lat, lon] = destination(60, 0, 90, M_PER_DEG * 0.5);
  near(lon, 1, 0.01, "longitude");           // great-circle east bends toward the equator a hair, so the latitude drops very slightly
  near(lat, 60, 0.01, "latitude");
  // what adding metres to degrees would give instead:
  assert.ok(Math.abs(lon - 0.5) > 0.4);
});

test("longitude wraps across the date line into [-180, 180)", async () => {
  const { destination } = await load();
  const [, lon] = destination(0, 179.5, 90, M_PER_DEG * 1);
  near(lon, -179.5, 1e-6);
  const [, w] = destination(0, -179.5, 270, M_PER_DEG * 1);
  near(w, 179.5, 1e-6);
  assert.ok(lon >= -180 && lon < 180 && w >= -180 && w < 180);
});

test("a zero-length move and a move over the pole stay valid", async () => {
  const { destination } = await load();
  assert.deepEqual(destination(12.5, 77.5, 123, 0).map(x => +x.toFixed(9)), [12.5, 77.5]);
  const [lat, lon] = destination(89, 0, 0, M_PER_DEG * 2);       // over the pole: latitude comes back down on the other side
  near(lat, 89, 1e-6); near(Math.abs(lon), 180, 1e-6);
});

test("extrapolation starts from the FIX time, not from when the file was read", async () => {
  const { extrapolate, flightKin } = await load();
  const row = ["abc123", "FDX1", 10, 20, 9000, 250, 90, 0, "United States", 1, 1000000];       // 250 m/s due east, fix at t=1,000,000
  const k = flightKin(row);
  const at0 = extrapolate(k, 1000000, 120);
  assert.equal(at0.lat, 10); assert.equal(at0.lon, 20); assert.equal(at0.moving, false); assert.equal(at0.ghost, false);
  const at60 = extrapolate(k, 1000060, 120);                      // 15 km east of the fix after 60 s
  near((at60.lon - 20) * M_PER_DEG * Math.cos(10 * Math.PI / 180), 15000, 30);
  assert.equal(at60.age, 60); assert.equal(at60.ghost, false); assert.equal(at60.moving, true);
});

test("extrapolation stops at the cap and the marker becomes a ghost", async () => {
  const { extrapolate, flightKin } = await load();
  const k = flightKin(["a", "X", 0, 0, 1, 200, 0, 0, "", 0, 5000]);
  const capped = extrapolate(k, 5000 + 120, 120), later = extrapolate(k, 5000 + 3600, 120);
  assert.equal(capped.ghost, false);
  assert.equal(later.ghost, true);
  assert.equal(later.lat, capped.lat);                           // no more movement after the cap
  near(later.lat * M_PER_DEG, 200 * 120, 1);
});

test("a vessel's speed is knots (1 kn = 1852/3600 m/s), course comes from COG and heading 511 was already replaced by the server", async () => {
  const { extrapolate, vesselKin } = await load();
  const row = [419000001, "MV TEST", 0, 72, 10, 0, 0, 70, "MUNDRA", "10-12 06:00", 7000];       // 10 kn due north
  const k = vesselKin(row);
  near(k.vel, 5.14444, 1e-4);
  const p = extrapolate(k, 7000 + 200, 300);
  near(p.lat * M_PER_DEG, 5.14444 * 200, 1);
});

test("null speed or course means static: never moved, but still ghosted once old", async () => {
  const { extrapolate, flightKin, vesselKin } = await load();
  const f = extrapolate(flightKin(["a", "X", 5, 6, 1, null, 90, 0, "", 0, 100]), 400, 120);
  assert.equal(f.lat, 5); assert.equal(f.lon, 6); assert.equal(f.moving, false); assert.equal(f.ghost, true);
  const v = extrapolate(vesselKin([1, "S", 1, 2, null, null, null, 0, null, null, 100]), 150, 300);
  assert.equal(v.moving, false); assert.equal(v.ghost, false);
  const zero = extrapolate(flightKin(["a", "X", 5, 6, 1, 0, 90, 0, "", 0, 100]), 130, 120);
  assert.equal(zero.moving, false);
});

test("a fix in the future (clock skew) is treated as age 0, never as a move backwards", async () => {
  const { extrapolate, flightKin } = await load();
  const r = extrapolate(flightKin(["a", "X", 1, 2, 1, 100, 45, 0, "", 0, 2000]), 1990, 120);
  assert.equal(r.age, 0); assert.equal(r.lat, 1); assert.equal(r.lon, 2);
});

test("telemetry: a full message replaces everything, a delta changes only the named records and removes the gone ones", async () => {
  const { docFromFull, applyTelemetry } = await load();
  const A = ["a1", "AAA1", 10, 20, 1, 100, 90, 0, "IN", 0, 1000], B = ["b2", "BBB2", 11, 21, 1, 100, 90, 0, "IN", 1, 1000];
  const V1 = [111, "S1", 1, 2, 5, 90, 90, 70, null, null, 1000];
  const doc = docFromFull({ type: "telemetry", t: 1010, cadence_s: 2160, full: true, fl: [A, B], ve: [V1], gone: { fl: [], ve: [] }, sources: { flights: { name: "OpenSky" }, vessels: { name: "AISstream.io" } } });
  assert.equal(doc.flights.length, 2); assert.equal(doc.vessels.length, 1); assert.equal(doc.cadence_s, 2160); assert.equal(doc.live, true);
  const A2 = ["a1", "AAA1", 10.5, 20.5, 1, 100, 90, 0, "IN", 0, 1030];
  applyTelemetry(doc, { type: "telemetry", t: 1040, cadence_s: 2160, full: false, fl: [A2], ve: [], gone: { fl: ["b2"], ve: [] } });
  assert.deepEqual(doc.flights, [A2]); assert.equal(doc.vessels.length, 1);
  applyTelemetry(doc, { type: "telemetry", t: 1100, full: false, fl: [], ve: [], gone: { fl: [], ve: [111] } });
  assert.equal(doc.vessels.length, 0);
  applyTelemetry(doc, { type: "telemetry", t: 1200, full: true, fl: [], ve: [], gone: { fl: [], ve: [] } });
  assert.equal(doc.flights.length, 0);
});

test("telemetry: no vessel source means vessels is null (with a reason), not an empty list", async () => {
  const { docFromFull } = await load();
  const doc = docFromFull({ type: "telemetry", t: 1, cadence_s: 60, full: true, fl: [], ve: [], gone: { fl: [], ve: [] }, vessels_reason: "add a key", sources: { flights: { name: "OpenSky" }, vessels: null } });
  assert.equal(doc.vessels, null); assert.equal(doc.vessels_reason, "add a key");
});

test("ageLabel", async () => {
  const { ageLabel } = await load();
  assert.equal(ageLabel(12), "12 s"); assert.equal(ageLabel(600), "10 min"); assert.equal(ageLabel(7200), "2.0 h"); assert.equal(ageLabel(null), "age unknown");
});
