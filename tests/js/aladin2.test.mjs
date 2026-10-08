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

import { addBusinessDays, fanLines, attribution } from "../../desk-aladin2.js";

test("business-day arithmetic skips weekends", () => {
  assert.equal(addBusinessDays("2026-10-06", 1), "2026-10-07"); assert.equal(addBusinessDays("2026-10-09", 1), "2026-10-12");           // Friday -> Monday
  assert.equal(addBusinessDays("2026-10-06", 5), "2026-10-13"); assert.equal(addBusinessDays("2026-10-06", 20), "2026-11-03");
});

test("fan lines for the main chart start at the as-of close, widen with the horizon, nest, and follow the layer toggles", () => {
  _test.reset(); assert.equal(fanLines("TST"), null);
  _test.put("TST", shard()); const f = fanLines("TST"), by = Object.fromEntries(f.lines.map(l => [l.id, l.points]));
  assert.deepEqual(Object.keys(by).sort(), ["hi50", "hi80", "hi95", "lo50", "lo80", "lo95", "med"]);
  for (const k of Object.keys(by)) { assert.deepEqual(by[k][0], ["2026-10-06", 100]); assert.equal(by[k].length, 4); }
  assert.ok(by.hi95[3][1] > by.hi80[3][1] && by.hi80[3][1] > by.hi50[3][1] && by.lo95[3][1] < by.lo80[3][1] && by.lo80[3][1] < by.lo50[3][1]);
  assert.deepEqual(by.hi50.map(p => p[0]), ["2026-10-06", "2026-10-07", "2026-10-13", "2026-11-03"]);                         // horizons 1, 5, 20 trading days
  const times = by.hi95.map(p => p[0]); assert.deepEqual([...times].sort(), times);                                           // strictly ascending, as the chart library requires
});

test("attribution shows only the model's own small step for a stock with no strategy behind it", () => {
  _test.reset(); _test.put("TST", shard()); const a = attribution(shard());
  assert.match(a, /1-day/); assert.match(a, /5-day/); assert.ok(!/20-day/.test(a)); assert.match(a, /no strategy is Active/); assert.match(a, /52% → 50%/);
});

test("a Validated stock's plan shows quantity, money at risk, the loss ladder and the gap row, from the same sizing rules", () => {
  _test.reset(); const d = shard(); d.state = "Validated"; d.signal = "bull"; d.plan = { entry: 100, stop: 95, zone: [99.5, 100.5], atr: 2, adv_shares: 1e9, mu: 0.01, sd: 0.05, p_stop: 0.4, horizon: 20 }; _test.put("TST", d);
  const h = html("TST"); assert.match(h, /BULLISH SIGNAL/); assert.match(h, /Quantity<\/span><b>1000/); assert.match(h, /Money at risk<\/span><b>₹5,000/); assert.match(h, /98\.00 \(-1 ATR\)/); assert.match(h, /₹10,000/); assert.match(h, /does not always fill at its level/);
});

import { weeklyBlock } from "../../desk-aladin2.js";
const wk = (signal) => ({ sym: "TST", signal, state: "Provisional", state_why: "no live weekly record yet", what_to_do: "Enter near 99.50-100.50 at the next open; leave at the open of the 5th trading day.", round_trip_cost_bps: 37,
  record: signal === "bull" ? { n: 3430, share_closing_up: 0.5548, gross_excess_bps: 63.6, net_bps: 27, net_ci95_bps: [6.3, 47.1], years_positive_net: "9/14" } : { n: 15225, share_closing_up: 0.4159, gross_excess_bps: -71.9, gross_excess_ci95_bps: [-86.5, -55.9], years_below_market: "14/14" },
  evidence: { aladin1_technical_p5: 0.62, aladin1_combined_p5: 0.6, aladin1_confidence: "Medium", aladin1_agreement: "2/3", outlook_p_beat_nifty_20d: null, sentiment_level: "NEUTRAL", supply_chain_impact: null, range_5d_80pct: [96, 104] } });

test("the weekly block states the signal through the labels dictionary, the measured record, and what did not help", () => {
  const labs = { none: "HOLD", bull: "BUY", bear: "SELL" };
  let h = weeklyBlock({ weekly: wk("bull") }, labs); assert.match(h, /<b>BUY<\/b> for the next 5 trading days/); assert.match(h, /27 bps after costs/); assert.match(h, /9\/14/); assert.match(h, /not measured/); assert.match(h, /none of it improved the weekly result/); assert.match(h, /Provisional/);
  h = weeklyBlock({ weekly: wk("bear") }, { ...labs, bear: "BEARISH SIGNAL" }); assert.match(h, /<b>BEARISH SIGNAL<\/b>/); assert.match(h, /closed higher only 42%/); assert.match(h, /14\/14/);
  h = weeklyBlock({ weekly: null }, labs); assert.match(h, /HOLD: this stock is not in the best 1% or worst 5%/);
});

test("a stock with a positive weekly signal gets a plan the risk panel can size, and one with a negative signal gets none", () => {
  _test.reset(); const d = shard(); d.signal = "bull"; d.state = "Provisional"; d.weekly = wk("bull"); d.plan = { entry: 100, stop: 96, zone: [99.5, 100.5], atr: 2, adv_shares: 1e9, mu: 0.0027, sd: 0.06, p_stop: null, horizon: 5 }; _test.put("TST", d); _test.board({ labels: { none: "HOLD", bull: "BUY", bear: "SELL", range: "price range" }, historical_simulation: { horizons: {} }, live: {} });
  const h = html("TST"); assert.match(h, /BUY/); assert.match(h, /Weekly signal/); assert.match(h, /Quantity<\/span><b>/); assert.match(h, /Money at risk/);
});
