// node --test tests/js/globe_fresh.test.mjs : the Globe's 7-day freshness rule, applied in the browser
import test from "node:test";
import assert from "node:assert/strict";
import { freshGlobe } from "../../globe-map.js";

const NOW = Date.parse("2026-10-02T12:00:00Z");
const ago = (days = 0, mins = 0) => new Date(NOW - days * 864e5 - mins * 6e4).toISOString();
const snap = (over = {}) => ({
  generated_utc: ago(0, 30),
  chokepoints: [{ id: "a", flights: { count: 9, sample: [{ callsign: "X" }] }, vessels: { date: ago(3).slice(0, 10), n_total: 50 },
    news: [{ title: "fresh", seen_utc: ago(1) }, { title: "week-old edge", seen_utc: ago(6.9) }, { title: "old", seen_utc: ago(8) }, { title: "undated" }] }],
  events: [{ title: "e1", seen_utc: ago(2) }, { title: "e2", seen_utc: ago(30) }],
  hazards: {
    disruptions: [{ name: "d1", from_utc: ago(40), to_utc: ago(-2) }, { name: "d2", from_utc: ago(40), to_utc: ago(35) }, { name: "d3", from_utc: ago(2), to_utc: ago(2) }],
    earthquakes: [{ mag: 5, time_utc: ago(1) }, { mag: 6, time_utc: ago(9) }],
    natural_events: [{ title: "n1", date: ago(3) }, { title: "n2", date: ago(20) }, { title: "n3" }],
    alerts: [{ name: "a1", from_utc: ago(285), to_utc: ago(0) }, { name: "a2", from_utc: ago(300), to_utc: ago(200) }, { name: "a3" }],
  }, ...over });

test("news older than 7 days or with no date is left out", () => {
  const f = freshGlobe(snap(), NOW);
  assert.deepEqual(f.chokepoints[0].news.map(n => n.title), ["fresh", "week-old edge"]);
  assert.deepEqual(f.events.map(e => e.title), ["e1"]);
  assert.equal(f.hidden.news, 2); assert.equal(f.hidden.events, 1);
});

test("hazards: only records from the last week (ongoing counts); undated records are dropped", () => {
  const f = freshGlobe(snap(), NOW);
  assert.deepEqual(f.hazards.disruptions.map(d => d.name), ["d1", "d3"]);       // d1 is still ongoing, d2 ended five weeks ago
  assert.deepEqual(f.hazards.earthquakes.map(q => q.mag), [5]);
  assert.deepEqual(f.hazards.natural_events.map(n => n.title), ["n1"]);
  assert.deepEqual(f.hazards.alerts.map(a => a.name), ["a1"]);                  // a1 was updated today; a2 ended long ago; a3 has no date
  assert.equal(f.hidden.hazards, 1 + 1 + 2 + 2);
});

test("vessel counts older than a week are dropped, recent ones kept", () => {
  assert.ok(freshGlobe(snap(), NOW).chokepoints[0].vessels);
  const old = snap(); old.chokepoints[0].vessels.date = ago(9).slice(0, 10);
  const f = freshGlobe(old, NOW);
  assert.equal(f.chokepoints[0].vessels, undefined); assert.equal(f.hidden.vessels, 1);
});

test("flights are used only while the snapshot is under 2 hours old", () => {
  assert.ok(freshGlobe(snap({ generated_utc: ago(0, 119) }), NOW).chokepoints[0].flights);
  const stale = freshGlobe(snap({ generated_utc: ago(0, 121) }), NOW);
  assert.equal(stale.chokepoints[0].flights, undefined); assert.equal(stale.hidden.flights, 9);
  assert.equal(stale.snapshot_age_min, 121);
});

test("a snapshot from a day ago shows no flights and its day-old news only while it is inside the week", () => {
  const f = freshGlobe(snap({ generated_utc: ago(1) }), NOW);
  assert.equal(f.chokepoints[0].flights, undefined);
  assert.equal(f.chokepoints[0].news.length, 2);
});

test("items age out by themselves as time passes", () => {
  const f1 = freshGlobe(snap(), NOW), f2 = freshGlobe(snap(), NOW + 2 * 864e5);
  assert.equal(f1.chokepoints[0].news.length, 2);
  assert.equal(f2.chokepoints[0].news.length, 1);                                 // 'week-old edge' turned 8.9 days old
});

test("missing or malformed input does not throw", () => {
  assert.equal(freshGlobe(null, NOW), null);
  assert.deepEqual(freshGlobe({ chokepoints: [] }, NOW).events, []);
  assert.doesNotThrow(() => freshGlobe({ generated_utc: "garbage", chokepoints: [{ id: "x", flights: { count: 1 } }] }, NOW));
});
