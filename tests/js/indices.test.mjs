// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { filterRows, sliceRange, rangePos, axisFmt } from "../../desk-indices.js";

const doc = { indices: [{ name: "Nifty 50", group: "Broad market", key: "Nifty_2050" }, { name: "Nifty Bank", group: "Sectoral", key: "Nifty_20Bank" }, { name: "Nifty PSU Bank", group: "Sectoral", key: "x" },
  { name: "Bitcoin (INR)", group: "Crypto", key: "b" }, { name: "S&P BSE MidCap", group: "BSE", key: null, missing: "not available" }] };

test("group filter and word search pick the right indices", () => {
  assert.equal(filterRows(doc).length, 5);
  assert.deepEqual(filterRows(doc, "Sectoral").map(r => r.name), ["Nifty Bank", "Nifty PSU Bank"]);
  assert.deepEqual(filterRows(doc, "All", "psu BANK").map(r => r.name), ["Nifty PSU Bank"]);
  assert.deepEqual(filterRows(doc, "Crypto", "bitcoin").map(r => r.key), ["b"]); assert.equal(filterRows(null).length, 0);
});

test("chart range counts back from the last candle; 52-week position is 0..1", () => {
  const d = [["2025-01-01", 1, 1, 1, 1], ["2025-12-01", 1, 1, 1, 2], ["2026-06-01", 1, 1, 1, 3], ["2026-10-09", 1, 1, 1, 4]];
  assert.deepEqual(sliceRange(d, "1Y").map(r => r[0]), ["2025-12-01", "2026-06-01", "2026-10-09"]);
  assert.deepEqual(sliceRange(d, "6M").map(r => r[0]), ["2026-06-01", "2026-10-09"]); assert.equal(sliceRange(d, "All").length, 4); assert.deepEqual(sliceRange([], "1Y"), []);
  assert.equal(rangePos({ last: 150, lo52: 100, hi52: 200 }), 0.5); assert.equal(rangePos({ last: 250, lo52: 100, hi52: 200 }), 1); assert.equal(rangePos({ last: 1, lo52: 5, hi52: 5 }), null);
});

test("axis labels stay short", () => { assert.equal(axisFmt(8184325), "81.8 L"); assert.equal(axisFmt(22520.45), "22,520"); assert.equal(axisFmt(14.38), "14.38"); });
