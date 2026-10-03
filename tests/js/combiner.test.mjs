// node --test tests/js/combiner.test.mjs   (the same cases tests/test_aladin_model.py runs against combine_py)
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { combine } from "../../desk-aladin.js";

const { cases } = JSON.parse(readFileSync(new URL("../fixtures/combiner_cases.json", import.meta.url), "utf8"));

test("combine() meets every shared fixture case", () => {
  assert.ok(cases.length > 300);
  for (const c of cases) {
    const r = combine(c.in.p_tech, c.in.F, c.in.S, c.in.sweep, c.in.w, c.in.I);
    assert.ok(Math.abs(r.p - c.out.p) < 2e-4, `${c.name}: p ${r.p} vs ${c.out.p}`);
    assert.ok(Math.abs(r.q - c.out.q) < 2e-4, `${c.name}: q`);
    assert.ok(Math.abs(r.T - c.out.T) < 0.11, `${c.name}: T ${r.T} vs ${c.out.T}`);
    assert.equal(r.conf, c.out.conf, `${c.name}: confidence`);
    assert.equal(r.agree, c.out.agree, `${c.name}: agreement`);
  }
});

test("combine() meets the hand-worked numbers independently of the fixture's own output", () => {
  const hand = cases.filter(c => c.hand);
  assert.ok(hand.length >= 8);
  for (const c of hand) {
    const r = combine(c.in.p_tech, c.in.F, c.in.S, c.in.sweep, c.in.w, c.in.I);
    for (const [k, v] of Object.entries(c.hand)) {
      if (typeof v === "number") assert.ok(Math.abs(r[k] - v) < 1.5e-3, `${c.name}: ${k} ${r[k]} vs ${v}`);
      else assert.equal(r[k], v, `${c.name}: ${k}`);
    }
  }
});

test("missing fronts are zero, not an error", () => {
  assert.equal(combine(0.5, null, undefined, null).p, 0.5);
  assert.equal(combine(0.5).agree, "0/1");
});
