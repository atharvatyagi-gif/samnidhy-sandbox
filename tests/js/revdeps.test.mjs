import test from "node:test";
import assert from "node:assert/strict";
import { plainSentence, summary, geoSegments, mostDependent } from "../../desk-revdeps.js";

const HAL = { lvl: "high", why: "one customer brings 97% of revenue", top: { share: 0.97, src: "stated", name: "Indian Defence Services" }, abroad: null };
const LUP = { lvl: "moderate", top: { share: 0.1054, src: "stated", name: null }, abroad: 0.6893, geo: { rows: [{ region: "USA", share: 0.41 }, { region: "India", share: 0.31 }, { region: "Others", share: 0.28 }] } };

test("plain sentence names the share, the customer when known, and the export share", () => {
  assert.equal(plainSentence(HAL, "HAL"), "About 97% of HAL’s revenue comes from Indian Defence Services.");
  assert.equal(plainSentence(LUP, "Lupin"), "About 11% of Lupin’s revenue comes from one customer; 69% comes from outside India.");
  assert.equal(plainSentence({ lvl: "low", abroad: 0.01 }, "Power Grid"), "No single customer brings in 10% of Power Grid’s revenue.");
  assert.equal(plainSentence({ lvl: "unknown", abroad: null }, "X"), null);
});

test("geography segments put India first and add to 100%", () => {
  const s = geoSegments(LUP.geo.rows);
  assert.equal(s[0].region, "India"); assert.ok(Math.abs(s.reduce((t, x) => t + x.share, 0) - 1) < 1e-9);
});

test("summary never invents a level and the most-dependent list ranks high first", () => {
  assert.equal(summary(null).lvl, "unknown");
  const doc = { cos: { HAL, LUPIN: LUP, PG: { lvl: "low" }, AAA: { lvl: "moderate", top: null } } };
  assert.deepEqual(mostDependent(doc).map(r => r.sym), ["HAL", "LUPIN", "AAA"]);
});
