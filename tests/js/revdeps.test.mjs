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

import { tag, newsIndex, newsLinks } from "../../desk-revdeps.js";
const DOC = { cos: {
  HAL: { lvl: "high", top: { share: 0.97, name: "Indian Defence Services" }, customers: [{ name: "Indian Defence Services", anon: true, w: 0.97, wb: "revenue", per: "FY26" }] },
  SUP: { lvl: "moderate", top: { share: 0.18, name: "Maruti Suzuki India" }, customers: [{ name: "Maruti Suzuki India Limited", sym: "MARUTI", w: 0.18, wb: "revenue", per: "FY26" }, { name: "Others", w: 0.3, wb: "revenue" }] },
  UNK: { lvl: "unknown", customers: [] } } };
const NAMES = new Map([["HAL", "Hindustan Aeronautics Limited"], ["MARUTI", "Maruti Suzuki India Limited"], ["SUP", "Supplier Parts Ltd"], ["UNK", "Unknown Co Ltd"]]);

test("tags appear only where a level was measured", () => {
  assert.equal(tag(DOC.cos.UNK), null); assert.equal(tag(DOC.cos.HAL, "HAL").text, "97% one customer"); assert.equal(tag(DOC.cos.SUP).lvl, "moderate");
});

test("a headline about a big customer flags the supplier that depends on it; a company's own name flags its own dependency", () => {
  const idx = newsIndex(DOC, NAMES);
  const a = newsLinks("Maruti Suzuki cuts October output on chip shortage", [], idx, DOC); assert.equal(a[0].sym, "SUP"); assert.match(a[0].text, /18% of revenue from Maruti Suzuki India/);
  const b = newsLinks("Hindustan Aeronautics wins Rs 62,000 crore order", [], idx, DOC); assert.equal(b[0].sym, "HAL"); assert.ok(b[0].self);
  assert.deepEqual(newsLinks("Others report weak quarter", [], idx, DOC), []);                        // generic names never match
  assert.deepEqual(newsLinks("Unknown Co results", ["UNK"], idx, DOC), []);                           // no measured level, no link
  assert.equal(newsLinks("x", ["HAL"], idx, DOC)[0].sym, "HAL");
});
