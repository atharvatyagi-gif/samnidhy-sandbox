// node --test tests/js/lanes.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { inBox, lanesAt, chokepointAt, countIn, carrierOf, ageMin, ageText, isStale, shipTypeLabel, exposureRows, lerpColor, hotspotColor, hotspotRadius, filterItems, mergeLayers } from "../../desk-lanes.js";

const LANES = JSON.parse(readFileSync(new URL("../../data/config/trade_lanes.json", import.meta.url), "utf8"));

test("inBox is inclusive and order-correct ([lonMin, latMin, lonMax, latMax])", () => {
  const b = [10, 20, 30, 40];
  assert.ok(inBox(20, 10, b) && inBox(40, 30, b) && inBox(30, 20, b));
  assert.ok(!inBox(41, 20, b) && !inBox(19.9, 20, b) && !inBox(30, 9, b) && !inBox(30, 31, b));
});

test("a position is matched to the real lanes: Hormuz tanker, Red Sea ship, an aircraft over Delhi", () => {
  const ids = (lat, lon, k) => lanesAt(lat, lon, LANES.lanes, k).map(l => l.id);
  assert.ok(ids(26.6, 56.3).includes("gulf_india_energy"));
  assert.ok(ids(20.0, 38.0).includes("redsea_europe_trade"));
  assert.ok(ids(28.6, 77.1, "air").includes("india_air_corridors"));
  assert.deepEqual(ids(28.6, 77.1, "sea"), []);
  assert.deepEqual(ids(-60, -120), []);                                    // open South Pacific: no lane, so nothing is claimed
  assert.equal(chokepointAt(26.6, 56.3, LANES.chokepoints).id, "hormuz");
  assert.equal(chokepointAt(-34.4, 18.5, LANES.chokepoints).id, "cape");
  assert.equal(chokepointAt(0, 0, LANES.chokepoints), null);
});

test("vessel counts use the vessel's own latitude and longitude", () => {
  const hormuz = LANES.chokepoints.find(c => c.id === "hormuz").bbox;
  const v = [[1, "A", 26.6, 56.3], [2, "B", 26.0, 56.0], [3, "C", 10, 10], [4, "D", null, null]];
  assert.equal(countIn(v, hormuz), 2);
  assert.equal(countIn(null, hormuz), 0);
});

test("a callsign names the operator (inferred) and never claims what is on board", () => {
  const car = { FDX: ["FedEx Express", true], AIC: ["Air India", false] };
  assert.deepEqual(carrierOf("fdx123", car), { prefix: "FDX", name: "FedEx Express", cargo: true });
  assert.deepEqual(carrierOf(" AIC101", car), { prefix: "AIC", name: "Air India", cargo: false });
  assert.equal(carrierOf("ZZZ1", car), null);
  assert.equal(carrierOf("", car), null);
  assert.equal(carrierOf(null, null), null);
});

test("snapshot age, wording and staleness follow the snapshot's own max age", () => {
  const now = Date.parse("2026-10-05T12:00:00Z");
  assert.equal(ageMin("2026-10-05T11:53:00Z", now), 7);
  assert.equal(ageMin("garbage", now), null);
  assert.equal(ageText(7), "7 min old");
  assert.equal(ageText(0), "under a minute old");
  assert.equal(ageText(150), "2.5 h old");
  assert.equal(ageText(null), "age unknown");
  assert.equal(isStale({ generated_utc: "2026-10-05T11:30:00Z", max_age_min: 120 }, now), false);
  assert.equal(isStale({ generated_utc: "2026-10-05T09:00:00Z", max_age_min: 120 }, now), true);
  assert.equal(isStale({ generated_utc: "2026-10-05T11:50:00Z" }, now), false);          // default limit 20 minutes
  assert.equal(isStale({ generated_utc: "2026-10-05T11:30:00Z" }, now), true);
  assert.equal(isStale(null, now), true);
  assert.equal(isStale({ generated_utc: "nope" }, now), true);
});

test("ship types", () => {
  assert.equal(shipTypeLabel(84), "Tanker");
  assert.equal(shipTypeLabel(70), "Cargo ship");
  assert.equal(shipTypeLabel(60), "Passenger ship");
  assert.equal(shipTypeLabel(52), "Tug");
  assert.equal(shipTypeLabel(null), "Type not broadcast");
  assert.equal(shipTypeLabel("abc"), "Type not broadcast");
  assert.equal(shipTypeLabel(99), "Other");
});

test("every lane exposure row carries a reason, and rows are labelled with their lane", () => {
  const rows = exposureRows(LANES.lanes);
  assert.ok(rows.length >= 12);
  for (const r of rows) assert.ok(r.why.length > 25 && r.lane && r.laneId && (r.sym || r.ind));
  assert.deepEqual(exposureRows(null), []);
});

test("hotspot colour and size: quiet below 35, gold at 35 blending to the hot colour at 100", () => {
  assert.equal(hotspotColor(null, "Q", "#f0c674", "#ff7a59"), "Q");
  assert.equal(hotspotColor(20, "Q", "#f0c674", "#ff7a59"), "Q");
  assert.equal(hotspotColor(35, "Q", "#f0c674", "#ff7a59"), "rgb(240,198,116)");
  assert.equal(hotspotColor(100, "Q", "#f0c674", "#ff7a59"), "rgb(255,122,89)");
  assert.equal(lerpColor("#000", "#fff", 0.5), "rgb(128,128,128)");
  assert.equal(lerpColor("rgb(0,0,0)", "rgba(100,200,50,0.4)", 1), "rgb(100,200,50)");
  assert.equal(hotspotRadius(null), 5);
  assert.equal(hotspotRadius(100), 15);
  assert.equal(hotspotRadius(250), 15);
});

test("list view filter and remembered layer switches", () => {
  const items = [{ type: "flight", id: "a1", name: "FDX123", detail: "India" }, { type: "vessel", id: "9", name: "EVER GIVEN", detail: "Suez" }];
  assert.equal(filterItems(items, "ever").length, 1);
  assert.equal(filterItems(items, "FLIGHT").length, 1);
  assert.equal(filterItems(items, "").length, 2);
  assert.equal(filterItems(items, "zzz").length, 0);
  const d = { hot: true, air: false, ship: true };
  assert.deepEqual(mergeLayers(d, { air: true, ship: "yes", extra: true }), { hot: true, air: true, ship: true });
  assert.deepEqual(mergeLayers(d, null), d);
  assert.deepEqual(mergeLayers(d, "junk"), d);
});
