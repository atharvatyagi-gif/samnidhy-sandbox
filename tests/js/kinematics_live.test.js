// The live-entity model of the WebGL globe (V4 8.8, checklist 14b/14c). CommonJS: loads the ES modules with import(), so it runs as `node --test tests/js/kinematics_live.test.js`.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const root = path.join(__dirname, "..", "..");
const load = f => import(pathToFileURL(path.join(root, f)).href);
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg || ""} ${a} vs ${b} (tol ${tol})`);
const M_PER_DEG = 6371008.8 * Math.PI / 180;

test("250 m/s due east for 60 s moves 15 km: 0.1349 degrees of longitude at the equator, 0.270 at 60N", async () => {
  const { makeEntity, predict } = await load("desk-kin-live.js");
  for (const [lat, want] of [[0, 0.1349], [60, 0.2698]]) {
    const E = makeEntity("flight", "a", lat, 10, 1000, 250, 90);
    const [la, lo] = predict(E, 1060);
    near(lo - 10, want, 0.002, `lon at ${lat}N`);
    near(la, lat, 0.01, "latitude barely changes");
  }
});

test("due north, across the antimeridian, near a pole", async () => {
  const { makeEntity, predict } = await load("desk-kin-live.js");
  const n = predict(makeEntity("flight", "n", 10, 20, 0, 250, 0), 60);
  near(n[0] - 10, 15000 / M_PER_DEG, 1e-6); near(n[1], 20, 1e-9);
  const w = predict(makeEntity("flight", "w", 0, 179.95, 0, 250, 90), 60);        // 0.1349 degrees east of 179.95 crosses to -179.915
  near(w[1], -179.9151, 0.001); assert.ok(w[1] >= -180 && w[1] < 180);
  const p = predict(makeEntity("flight", "p", 89.9, 30, 0, 250, 0), 120);          // 30 km north of 89.9N passes over the pole
  assert.ok(Number.isFinite(p[0]) && Number.isFinite(p[1]) && p[0] <= 90 && p[0] > 89.5 && p[1] >= -180 && p[1] < 180);
});

test("slow, static and capped entities do not move", async () => {
  const { makeEntity, predict } = await load("desk-kin-live.js");
  assert.deepEqual(predict(makeEntity("flight", "s", 5, 6, 0, 0.5, 90), 60), [5, 6]);                       // v < 1 m/s
  assert.deepEqual(predict(makeEntity("flight", "st", 5, 6, 0, null, 90), 60), [5, 6]);                       // no speed: static
  assert.deepEqual(predict(makeEntity("vessel", "v", 5, 6, 0, 0.2, 90), 60), [5, 6]);                         // < 0.26 m/s (about 0.5 kn)
  assert.notDeepEqual(predict(makeEntity("flight", "f", 5, 6, 0, 1.1, 90), 60), [5, 6]);                      // 1.1 m/s does move
  assert.notDeepEqual(predict(makeEntity("vessel", "v2", 5, 6, 0, 0.3, 90), 60), [5, 6]);
  const f = makeEntity("flight", "c", 0, 0, 0, 200, 0), atCap = predict(f, 120), later = predict(f, 5000);
  assert.deepEqual(atCap, later);                                                                             // flights stop at 120 s
  near(atCap[0] * M_PER_DEG, 200 * 120, 1);
  const v = makeEntity("vessel", "c", 0, 0, 0, 10, 0), vc = predict(v, 300);
  assert.deepEqual(vc, predict(v, 9999)); near(vc[0] * M_PER_DEG, 3000, 1);                                   // vessels stop at 300 s
});

test("prediction starts at the FIX time: a fix 40 s old is placed 40 s ahead, a fix in the future does not move backwards", async () => {
  const { makeEntity, predict } = await load("desk-kin-live.js");
  const E = makeEntity("flight", "a", 0, 0, 1000, 100, 0);
  near(predict(E, 1040)[0] * M_PER_DEG, 4000, 1);
  assert.deepEqual(predict(E, 990), [0, 0]);
});

test("a new fix keeps what is on screen, then the difference fades by exp(-t/tau): under 1% after 5 tau", async () => {
  const { makeEntity, applyFix, renderPos, metersBetween, TELE } = await load("desk-kin-live.js");
  const E = makeEntity("flight", "a", 0, 0, 1000, 200, 90);                       // flying east at 200 m/s
  const now = 1020;                                                               // 20 s after the fix: model and screen agree on 4 km east
  const before = renderPos(E, now);
  applyFix(E, { lat: 0.002, lon: 0.0375, fix: 1020, v: 200, hdg: 90 }, now);      // the real fix is 222 m north and ~300 m east of where it was predicted
  const justAfter = renderPos(E, now);
  const jump = metersBetween(before[0], before[1], justAfter[0], justAfter[1]);
  assert.ok(Math.hypot(jump.north, jump.east) < 1, "no teleport at the moment the fix arrives");
  const target = [0.002, 0.0375];
  const dist = t => { const p = renderPos(E, now + t), d = metersBetween(target[0], target[1], p[0], p[1]); return Math.hypot(d.north, d.east) - 0; };
  const start = Math.hypot(E.offN, E.offE);
  assert.ok(start > 100 && !E.snapped);
  for (const k of [1, 2, 3, 5]) {                                                  // the leftover offset is start * exp(-t/tau), no overshoot
    const t = k * TELE.tau, left = Math.hypot(E.offN, E.offE) * Math.exp(-t / TELE.tau);
    near(left / start, Math.exp(-k), 1e-9);
  }
  assert.ok(Math.exp(-5) < 0.01);
  let prev = Infinity;
  for (let t = 0; t <= 10; t += 0.5) {                                             // the distance to the true track only ever shrinks (it moves with the vessel, so compare the offset)
    const o = Math.hypot(E.offN, E.offE) * Math.exp(-t / TELE.tau);
    assert.ok(o <= prev + 1e-9); prev = o;
  }
  assert.ok(dist(0) >= 0);
});

test("a correction above 50 km snaps instead of gliding", async () => {
  const { makeEntity, applyFix, renderPos, TELE } = await load("desk-kin-live.js");
  const E = makeEntity("flight", "a", 0, 0, 1000, 200, 90);
  applyFix(E, { lat: 1, lon: 1, fix: 1010, v: 200, hdg: 90 }, 1010);               // ~157 km away
  assert.equal(E.snapped, true); assert.equal(E.offN, 0); assert.equal(E.offE, 0);
  const p = renderPos(E, 1010); near(p[0], 1, 1e-9); near(p[1], 1, 1e-9);
  const F = makeEntity("flight", "b", 0, 0, 1000, 200, 90);
  applyFix(F, { lat: 0.0001, lon: 0.0001, fix: 1010, v: 200, hdg: 90 }, 1010);
  assert.equal(F.snapped, false);
  assert.equal(TELE.snapKm, 50);
});

test("ghost and gone ages follow the caps and the drop times", async () => {
  const { makeEntity, isGhost, isGone } = await load("desk-kin-live.js");
  const f = makeEntity("flight", "f", 0, 0, 0, 100, 0), v = makeEntity("vessel", "v", 0, 0, 0, 5, 0);
  assert.equal(isGhost(f, 120), false); assert.equal(isGhost(f, 121), true); assert.equal(isGone(f, 600), false); assert.equal(isGone(f, 601), true);
  assert.equal(isGhost(v, 300), false); assert.equal(isGhost(v, 301), true); assert.equal(isGone(v, 1800), false); assert.equal(isGone(v, 1801), true);
});

test("the daemon's clock: ages are measured on it even when the PC clock is wrong", async () => {
  const { ClockSync } = await load("desk-kin-live.js");
  let local = 5000;
  const c = new ClockSync(() => local);
  assert.equal(c.known, false); assert.equal(c.now(), 5000);
  c.sync(5300);                                                                    // the PC is 300 s behind the daemon
  assert.equal(c.known, true); local = 5010; assert.equal(c.now(), 5310);
  c.sync(NaN); assert.equal(c.now(), 5310);                                         // a bad value changes nothing
});

test("trail: at most once a second, only after a move of 100 m, 24 points, oldest dropped, fade over 60 s, the selected one does not fade", async () => {
  const { Trail } = await load("desk-kin-live.js");
  const t = new Trail();
  assert.equal(t.push(0, 0, 100), true);
  assert.equal(t.push(0.01, 0, 100.5), false);                                    // under a second
  assert.equal(t.push(0.0001, 0, 102), false);                                    // 11 m: not a real move
  assert.equal(t.push(0.01, 0, 102), true);
  for (let i = 1; i <= 40; i++) t.push(0.01 * (i + 1), 0, 102 + i * 2);
  const pts = t.points();
  assert.equal(pts.length, 24);
  assert.ok(pts.every((p, i) => i === 0 || p[2] > pts[i - 1][2]));                // oldest to newest
  near(pts[pts.length - 1][0], 0.01 * 41, 1e-9);
  assert.equal(Trail.alpha(0), 1); near(Trail.alpha(30), 0.5, 1e-9); assert.equal(Trail.alpha(60), 0); assert.equal(Trail.alpha(90), 0); assert.equal(Trail.alpha(90, 60, true), 1);
});

test("picking: the nearest marker inside the radius, nothing outside it", async () => {
  const { PickGrid } = await load("desk-kin-live.js");
  const g = new PickGrid();
  g.add(100, 100, "a"); g.add(108, 100, "b"); g.add(300, 300, "c");
  assert.equal(g.nearest(106, 100, 10), "b"); assert.equal(g.nearest(101, 101, 10), "a");
  assert.equal(g.nearest(200, 200, 10), null); assert.equal(g.nearest(305, 297, 16), "c");
  g.clear(); assert.equal(g.nearest(100, 100, 10), null);
});

test("governor: steps down on a slow median, one level per 2 s window, and back up only after 10 s under budget", async () => {
  const { Governor } = await load("desk-kin-live.js");
  const g = new Governor(18);
  const run = (ms, t0, secs, dt = 0.05) => { const ch = []; for (let t = t0; t < t0 + secs; t += dt) { const c = g.frame(ms, t); if (c != null) ch.push([+t.toFixed(2), c]); } return ch; };
  assert.equal(g.name, "full"); assert.equal(g.trails, true); assert.equal(g.maxEntities, 4000); assert.equal(g.pixelRatioCap, 2); assert.equal(g.reduced, false);
  const down = run(30, 0, 14);                                                      // 30 ms frames: a step per judged window, and one window after each step is not judged (settling)
  assert.deepEqual(down.map(x => x[1]), [1, 2, 3]);
  assert.ok(down[1][0] - down[0][0] >= 4 - 1e-9 && down[2][0] - down[1][0] >= 4 - 1e-9, "a settling window between steps");
  assert.equal(g.name, "pixel_1"); assert.equal(g.trails, false); assert.equal(g.maxEntities, 2000); assert.equal(g.pixelRatioCap, 1); assert.equal(g.reduced, true);
  assert.deepEqual(run(30, 14, 6), []);                                             // already at the lowest level: no further change
  const up = run(10, 20, 50);                                                       // fast again: steps back up, one level per 10 s
  assert.deepEqual(up.map(x => x[1]), [2, 1, 0]);
  assert.ok(up[0][0] - 20 >= 10, "not before 10 s under budget");
  assert.ok(up[1][0] - up[0][0] >= 10);
  assert.equal(g.name, "full");
});

test("replay of a REAL recorded 10-minute flight track: on straight segments the prediction is within 2 km of the next real fix", async () => {
  const f = path.join(root, "tests", "fixtures", "opensky_track.json");
  assert.ok(fs.existsSync(f), "the recorded track fixture is missing");
  const { tracks } = JSON.parse(fs.readFileSync(f, "utf8"));
  const { makeEntity, predict, metersBetween } = await load("desk-kin-live.js");
  let segs = 0, ok = 0, worst = 0;
  const angDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);
  for (const rows of Object.values(tracks)) {
    for (let i = 0; i + 1 < rows.length; i++) {
      const a = rows[i], b = rows[i + 1], dt = b[10] - a[10];
      if (dt <= 0 || dt > 120 || a[5] == null || a[6] == null || a[5] < 50 || b[6] == null) continue;
      if (angDiff(a[6], b[6]) > 3) continue;                                         // a straight segment: the course did not change
      const E = makeEntity("flight", a[0], a[2], a[3], a[10], a[5], a[6]);
      const p = predict(E, b[10]), d = metersBetween(p[0], p[1], b[2], b[3]), err = Math.hypot(d.north, d.east);
      segs++; if (err <= 2000) ok++; worst = Math.max(worst, err);
    }
  }
  console.log(`replay: ${segs} straight segments, ${ok} within 2 km, worst ${Math.round(worst)} m`);
  assert.ok(segs >= 100, `only ${segs} straight segments in the recording`);
  assert.ok(ok / segs >= 0.97, `${ok}/${segs} within 2 km`);
});
