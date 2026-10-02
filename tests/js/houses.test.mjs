// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { members, summarise, weightedReturn, refDates } from "../../desk-houses.js";

const uni = new Map([["A", { n: "A Ltd", n500: true }], ["B", { n: "B Ltd", n500: false }], ["C", { n: "C Ltd", n500: true }]]);
const quotes = { A: { p: 110, pc: 100, pct: 10 }, B: { p: 45, pc: 50, pct: -10 }, C: { p: 20, pc: 20, pct: 0 } };
const getQ = s => quotes[s] || null;
const house = { id: "h", name: "H", symbols: ["A", "B", "C", "GONE"] };

test("members: market cap = shares x price; no share count -> kept but not counted", () => {
  const r = members(house, getQ, { A: { sh: 10, at: "2026-10-01" }, B: { sh: 100 } }, uni);
  assert.equal(r.length, 4);
  assert.equal(r[0].mcap, 1100); assert.equal(r[0].prev, 1000);
  assert.equal(r[1].mcap, 4500);
  assert.equal(r[2].mcap, null);               // C has no shares
  assert.equal(r[3].p, null);                  // GONE is not in the universe
});

test("summarise: totals only over counted companies; breadth over priced ones", () => {
  const s = summarise(members(house, getQ, { A: { sh: 10 }, B: { sh: 100 } }, uni));
  assert.equal(s.mcap, 5600); assert.equal(s.prev, 6000);
  assert.ok(Math.abs(s.dayPct - (5600 / 6000 - 1) * 100) < 1e-9);
  assert.equal(s.dayCr, (5600 - 6000) / 1e7);
  assert.equal(s.counted, 2); assert.equal(s.missing, 2);
  assert.deepEqual([s.up, s.down, s.flat], [1, 1, 1]);
  assert.equal(s.best.s, "A"); assert.equal(s.worst.s, "B");
});

test("summarise: nothing counted -> dashes, not zeros", () => {
  const s = summarise(members(house, getQ, {}, uni));
  assert.equal(s.dayPct, null); assert.equal(s.dayCr, null); assert.equal(s.mcap, 0);
});

test("refDates: 1W, 1M and the last close before 1 January", () => {
  assert.deepEqual(refDates("2026-10-02"), { "1W": "2026-09-25", "1M": "2026-09-02", YTD: "2025-12-31" });
});

test("weightedReturn: market-cap weighted, uses the close on/before the date, skips missing history", () => {
  const rows = [{ s: "A", sh: 10, p: 110 }, { s: "B", sh: 100, p: 45 }, { s: "C", sh: 5, p: 20 }];
  const h = new Map([
    ["A", [["2026-09-20", 0, 0, 0, 90], ["2026-09-24", 0, 0, 0, 100], ["2026-09-30", 0, 0, 0, 105]]],
    ["B", [["2026-09-24", 0, 0, 0, 50]]],
    ["C", null],                                // failed to load
  ]);
  const r = weightedReturn(rows, h, "2026-09-25");
  assert.equal(r.n, 2);
  assert.ok(Math.abs(r.pct - ((10 * 110 + 100 * 45) / (10 * 100 + 100 * 50) - 1) * 100) < 1e-9);
  assert.equal(weightedReturn(rows, h, "2026-01-01"), null);     // history starts later than the reference date
});
