// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { squarify, sectorRotation, trialCurve, median } from "../../desk-a2views.js";

test("treemap: areas are proportional to values, rectangles stay inside the frame, do not overlap and fill it", () => {
  const items = [6, 6, 4, 3, 2, 2, 1].map((v, i) => ({ key: "k" + i, value: v })), W = 100, H = 60, r = squarify(items, 0, 0, W, H), total = items.reduce((s, i) => s + i.value, 0);
  assert.equal(r.length, items.length);
  for (const t of r) { assert.ok(t.x >= -1e-9 && t.y >= -1e-9 && t.x + t.w <= W + 1e-9 && t.y + t.h <= H + 1e-9); assert.ok(Math.abs(t.w * t.h - t.value / total * W * H) < 1e-6); }
  assert.ok(Math.abs(r.reduce((s, t) => s + t.w * t.h, 0) - W * H) < 1e-6);
  for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) { const a = r[i], b = r[j]; assert.ok(a.x + a.w <= b.x + 1e-9 || b.x + b.w <= a.x + 1e-9 || a.y + a.h <= b.y + 1e-9 || b.y + b.h <= a.y + 1e-9); }
  assert.deepEqual(squarify([{ key: "z", value: 0 }], 0, 0, 10, 10), []);
});

test("sector rotation: quadrants from relative 3-month and 1-month medians, small sectors dropped", () => {
  const mk = (ind, r1m, r3m, n = 6) => Array.from({ length: n }, () => ({ ind, r1m, r3m }));
  const stocks = [...mk("A", 5, 20), ...mk("B", -2, 15), ...mk("C", 4, -10), ...mk("D", -5, -12), ...mk("Tiny", 1, 1, 3)];
  const r = Object.fromEntries(sectorRotation(stocks).map(x => [x.sector, x]));
  assert.equal(r.Tiny, undefined); assert.equal(r.A.quad, "Leading"); assert.equal(r.B.quad, "Weakening"); assert.equal(r.C.quad, "Improving"); assert.equal(r.D.quad, "Lagging");
  assert.equal(median([3, 1, 2]), 2); assert.equal(median([1, 2, 3, 4]), 2.5); assert.equal(median([]), null);
});

test("trial curve counts strategies in Probation or Active after each event", () => {
  const ev = [{ date: "2014-01-01", kind: "promoted_to_probation", strategy: "a", scope: "universe" }, { date: "2014-01-01", kind: "promoted_to_probation", strategy: "b", scope: "universe" },
    { date: "2014-06-01", kind: "promoted_to_active", strategy: "a", scope: "universe" }, { date: "2015-01-01", kind: "demoted", strategy: "a", scope: "universe" }, { date: "2015-03-01", kind: "retired", strategy: "a", scope: "universe" },
    { date: "2015-04-01", kind: "candidate_tested", strategy: "discovery", scope: "universe" }];
  assert.deepEqual(trialCurve(ev), [{ d: "2014-01-01", n: 2 }, { d: "2014-06-01", n: 2 }, { d: "2015-01-01", n: 1 }, { d: "2015-03-01", n: 1 }]);
});
