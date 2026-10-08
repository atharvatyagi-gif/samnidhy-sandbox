// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { riskCalc, lossLadder, fanGeometry, pct, inr, sentence, html, wrap, _test } from "../../desk-aladin2.js";

const shard = () => ({
  sym: "TST", name: "Test Ltd", as_of: "2026-10-06", close: 100, state: "Learning", state_why: ["x"], signal: "none", signal_why: "state is Learning", horizons: [1, 5, 20],
  bands: [1, 5, 20].map((H, i) => ({ H, lo50: 100 - 1 * (i + 1), hi50: 100 + 1 * (i + 1), lo80: 100 - 2 * (i + 1), hi80: 100 + 2 * (i + 1), lo95: 100 - 3 * (i + 1), hi95: 100 + 3 * (i + 1), p_up: H <= 5 ? 0.5 : null, base_rate: 0.52 })),
  strategies: [{ id: "a", name: "Moving-average crossover (a)", state: "Retired", since: "2025-08-04", last_change: "Retired" }], plan: null, plan_why: "A trade plan is shown only for Validated stocks.",
  series: { d: ["2026-10-01", "2026-10-02", "2026-10-03"], c: [99, 100, 100] }, disclaimer: "x" });

test("risk sizing matches the Python fixtures (tests/aladin2/test_signals.py)", () => {
  const base = { capital: 1_000_000, entry: 100, stop: 95, advShares: 1e9, mu: 0.01, sd: 0.05, riskPct: 1 };
  let r = riskCalc(base); assert.equal(r.caps["risk per trade"], 2000); assert.equal(r.caps["max position size"], 1000); assert.equal(r.qty, 1000); assert.equal(r.binding, "max position size");
  r = riskCalc({ ...base, advShares: 10000 }); assert.equal(r.qty, 500); assert.equal(r.binding, "liquidity");
  r = riskCalc({ ...base, mu: 0.0002 }); assert.equal(r.qty, 200); assert.ok(r.binding.startsWith("fractional Kelly"));
  assert.equal(riskCalc({ ...base, mu: -0.001 }).qty, 0); assert.equal(riskCalc({ ...base, riskPct: 0.2 }).qty, 400);
  assert.equal(riskCalc({ ...base, stop: 100 }).qty, 0);
});

test("capital at risk is quantity times the stop distance, and the loss ladder is in ATR steps", () => {
  const r = riskCalc({ capital: 1_000_000, entry: 100, stop: 95, advShares: 1e9, mu: 0.01, sd: 0.05, riskPct: 0.5 });
  assert.equal(r.capitalAtRisk, 5000); assert.equal(r.capitalAtRisk, r.qty * 5);
  const l = lossLadder(100, 2, 50); assert.deepEqual(l.map(x => x.price), [98, 96, 94]); assert.deepEqual(l.map(x => x.loss), [100, 200, 300]);
});

test("fan geometry: bands widen with the horizon, nest, and stay inside the drawing", () => {
  const g = fanGeometry(shard(), 320, 150);
  assert.ok(g.band95.length > 6 && g.hist.length === 3);
  const all = [...g.band95, ...g.band80, ...g.band50, ...g.hist]; for (const [x, y] of all) { assert.ok(x >= 0 && x <= 320 && y >= 0 && y <= 150); }
  const top = (b) => Math.min(...b.map(p => p[1])), bot = (b) => Math.max(...b.map(p => p[1]));
  assert.ok(top(g.band95) <= top(g.band80) && top(g.band80) <= top(g.band50) && bot(g.band95) >= bot(g.band80) && bot(g.band80) >= bot(g.band50));
  assert.ok(g.xh(1) < g.xh(5) && g.xh(5) < g.xh(20));
});

test("formatting and the plain sentence", () => {
  assert.equal(pct(5.04), "+5.0%"); assert.equal(pct(-2.26), "-2.3%"); assert.equal(pct(null), "--"); assert.equal(inr(1234.5), "1,234.50"); assert.equal(inr(undefined), "--");
  const s = sentence(shard(), {}); assert.match(s, /20 trading days TST/); assert.match(s, /₹94\.00 and ₹106\.00/); assert.match(s, /no reliable edge/);
});

test("the brief reads its wording from the published labels and carries the disclaimer", () => {
  _test.reset(); _test.put("TST", shard());
  let h = html("TST"); assert.match(h, /NO EDGE: stand aside/); assert.match(h, /LEARNING/); assert.match(h, /ALADIN is a statistical model built by students\. It is often wrong\./); assert.match(h, /Past performance does not predict future results/);
  assert.ok(!/\b(buy|sell|target|recommendation|guaranteed)\b/i.test(h));
  _test.board({ labels: { none: "HOLD", bull: "BUY", bear: "SELL", range: "price range" }, historical_simulation: { horizons: {} }, live: {} });
  h = html("TST"); assert.match(h, /HOLD: stand aside/); assert.match(h, /price range/);                        // one dictionary controls every label
  assert.match(html("NOPE"), /Loading the brief/);
});

test("the wrapper's signature changes only when the content changes (the rail keeps its DOM otherwise)", () => {
  _test.reset(); _test.put("TST", shard()); const a = wrap("TST"), b = wrap("TST"); assert.equal(a, b);
  const d = shard(); d.close = 101; _test.put("TST", d); assert.notEqual(wrap("TST"), a);
});
