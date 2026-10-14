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

import { plainSentence as PS2, brsrLines } from "../../desk-revdeps.js";
test("a BRSR export share reads as exports of turnover, not revenue from abroad; the BRSR block lists the business mix", () => {
  assert.match(PS2({ lvl: "unknown", abroad: 0.3, abroad_src: "BRSR exports" }, "AAA"), /Exports are 30% of AAA’s turnover/);
  assert.match(PS2({ lvl: "unknown", abroad: 0.3, abroad_src: "segment note" }, "AAA"), /30% of AAA’s revenue comes from outside India/);
  assert.deepEqual(brsrLines({ brsr: { fy: "2025-26", mix: [{ d: "Parts", share: 0.9 }, { d: "x", share: 0 }], cust: "OEMs" } }).mix, [{ d: "Parts", share: 0.9 }]);
  assert.equal(brsrLines({}), null);
});

import { predShard, predList, predTestLine, PRED_LABEL, kindLabel } from "../../desk-revdeps.js";

const SHARD = { cos: { MARUTI: [
  { p: "BHARATSE", n: "Bharat Seats Limited", rank: 1, kinds: ["filings", "business"], ev: { named: [{ by: "MARUTI", n: 15, sup: 1, pg: [210], q: "Long Term Contract with recurring transactions for the purchase of seats from Bharat Seats.", url: "https://x/ar.pdf", kind: "annual", per: "FY2025-26" }], words: { MARUTI: ["vehicles"], BHARATSE: ["seats", "passenger"] }, ind: ["Auto Manufacturers", "Auto Parts"] } },
  { p: "TVSMOTOR", n: "TVS Motor Company Limited", rank: 2, kinds: ["price", "business"], ev: { corr: 0.25, lead: { v: 0.21, first: "TVSMOTOR" }, words: { MARUTI: ["vehicles"], TVSMOTOR: [] }, same_ind: true, ind: ["Auto Manufacturers", "Auto Manufacturers"] } },
  { p: "TATAPOWER", rank: 3, kinds: ["group"], ev: { group: "Tata Group" } }] } };
const PNAMES = new Map([["MARUTI", "Maruti Suzuki India Limited"], ["BHARATSE", "Bharat Seats Ltd"], ["TVSMOTOR", "TVS Motor"]]);

test("predicted links: shard by first letter, digits share one shard", () => {
  assert.equal(predShard("MARUTI"), "M"); assert.equal(predShard("20MICRONS"), "0"); assert.equal(predShard("m&m"), "M");
});

test("predicted links: every row says why, with the filing sentence and the rival flag", () => {
  const r = predList(SHARD, "MARUTI", PNAMES);
  assert.equal(r.length, 3);
  assert.equal(r[0].reasons[0], "Maruti Suzuki India names Bharat Seats in its annual report, FY2025-26, page 210, in a sentence about supply, customers or orders.");
  assert.equal(r[0].quote.url, "https://x/ar.pdf"); assert.equal(r[0].rival, false);
  assert.match(r[1].reasons[0], /correlation 0\.25\)\. TVS Motor has tended to move a week earlier \(0\.21\)/);
  assert.equal(r[1].rival, true);
  assert.equal(r[2].reasons[0], "Both belong to the Tata Group."); assert.equal(r[2].name, "TATAPOWER");
  assert.deepEqual(predList(SHARD, "NOPE", PNAMES), []); assert.deepEqual(predList(null, "MARUTI"), []);
});

test("predicted links: the headline test is the fair one and never invented", () => {
  const idx = { coverage: { confirmed_listed_links: 39 }, test: { without_filings: { hit10: 0.225, random_hit10: 0.0032 }, all_evidence: { hit10: 0.338 } } };
  assert.equal(predTestLine(idx), "In a fair test that hid 39 confirmed links, the real partner was in a company's top 10 here 23% of the time (by chance: 0.3%).");
  assert.equal(predTestLine(null), null); assert.equal(predTestLine({ test: {} }), null);
  assert.equal(PRED_LABEL, "Predicted, not confirmed"); assert.equal(kindLabel("price"), "Shares move together");
});

test("predicted links: a filing fragment is not shown as a quote, the filing link still is", () => {
  const sh = { cos: { A: [{ p: "B", rank: 1, kinds: ["filings"], ev: { named: [{ by: "A", n: 2, sup: 0, pg: [9], q: "B Limited Associates 14.", url: "https://x/a.pdf" }] } }] } };
  const [r] = predList(sh, "A", new Map());
  assert.equal(r.quote, null); assert.equal(r.source, "https://x/a.pdf");
});

import { linkedOf, sameWay, decodeKinds } from "../../desk-revdeps.js";

test("linked companies: confirmed first with their role, then predicted ones not already confirmed", () => {
  const graph = { nodes: [{ id: "MARUTI", sym: "MARUTI" }, { id: "GABRIEL", sym: "GABRIEL" }, { id: "ANON_X" }], edges: [{ s: "GABRIEL", d: "MARUTI" }, { s: "MARUTI", d: "ANON_X" }] };
  const compact = { cos: { MARUTI: [["GABRIEL", "p"], ["BHARATSE", "fb"], ["TVSMOTOR", "br"]] } };
  const L = linkedOf("MARUTI", graph, compact);
  assert.deepEqual(L.map(l => [l.sym, l.confirmed, l.role]), [["GABRIEL", true, "supplier"], ["BHARATSE", false, null], ["TVSMOTOR", false, null]]);
  assert.deepEqual(L[1].kinds, ["filings", "business"]); assert.equal(L[2].rival, true);
  assert.deepEqual(linkedOf("NONE", null, null), []); assert.deepEqual(decodeKinds("gx"), ["group"]);
});

test("same-way count needs a real move and counts only partners with a quote", () => {
  const L = [{ sym: "A" }, { sym: "B" }, { sym: "C" }, { sym: "D" }], mv = { A: 2.1, B: -1.2, C: 0.2 };
  const r = sameWay(3.4, L, s => mv[s] ?? null);
  assert.equal(r.same, 1); assert.equal(r.quoted, 3);
  assert.equal(sameWay(0.1, L, s => mv[s] ?? null).same, 0);
});
