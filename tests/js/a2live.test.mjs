// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { focusOrder, pastPaths, pathStats, replayTable, replayAt, decisionLines, markup } from "../../desk-a2live.js";

test("the focus order alternates positive and negative signals so both sides are shown", () => {
  const t = [{ sym: "A", signal: "bull" }, { sym: "B", signal: "bull" }, { sym: "X", signal: "bear" }, { sym: "Y", signal: "bear" }, { sym: "Z", signal: "bear" }];
  assert.deepEqual(focusOrder(t).map(x => x.sym), ["A", "X", "B", "Y", "Z"]); assert.deepEqual(focusOrder([]), []);
});

test("past 5-day paths are the stock's own earlier moves, relative to each start", () => {
  const c = [100, 101, 102, 101, 103, 104, 105, 104]; const p = pastPaths(c);
  assert.equal(p.length, 3); assert.deepEqual(p[0].map(v => +v.toFixed(4)), [0, 0.01, 0.02, 0.01, 0.03, 0.04]);
  const st = pathStats(p); assert.equal(st.n, 3); assert.ok(st.up > 0.99); assert.equal(pathStats([]), null); assert.deepEqual(pastPaths([1, 2, 3]), []);
});

test("the replay counts the weeks in which the positive signals beat the market, from the cumulative curve", () => {
  const w = { dates: ["a", "b", "c", "d"], bull_cumulative_net_excess: [0, 1, 0.5, 2], bear_cumulative_underperformance: [0, 0.1, 0.2, 0.3] }, tab = replayTable(w);
  assert.deepEqual(tab.pos, [0, 1, 1, 2]); const r = replayAt(w, tab, 3); assert.equal(r.week, 4); assert.equal(r.hit, 2 / 3); assert.equal(replayAt(w, tab, 99).date, "d"); assert.equal(replayAt(w, tab, 0).hit, null);
});

test("the decision lines say 'not measured' instead of inventing a chance", () => {
  const P = { kpis: { stocks_ranked: 1326 } }, base = { rank_pct: 0.9996, p5: 0.524, cost_bps: 79.6, signal: "bull", invalidation: 86.94, exit: "x", fno: false, size: null };
  assert.match(decisionLines({ ...base, chance: null }, P)[2], /not measured/); assert.match(decisionLines({ ...base, chance: { closes_higher: 0.5548, closes_higher_ci95: [0.53, 0.58], beats_market: 0.52 } }, P)[2], /55\.5%/);
  assert.match(decisionLines({ ...base, signal: "bear" }, P)[4], /cash shares cannot be shorted/);
});

test("the page markup carries every panel, the labels from the file and the disclaimer", () => {
  const P = { as_of: "2026-10-07", mode: "directional", labels: { bull: "BUY", bear: "SELL", none: "HOLD" }, status: {}, kpis: { signals_today: { bull: 1, bear: 1, hold: 3 }, stocks_ranked: 5, forecasts_made: 10, forecast_batches: 1, history: {}, live_weekly: {} },
    charts: { probability_curve: [{ p_up: 0.5, p_up_ci95: [0.4, 0.6], p_beat_market: 0.5 }] }, decision_steps: ["one", "two"], traces: [{ sym: "A", name: "A", signal: "bull", chance: { closes_higher: 0.55 } }], activity: [{ when: "2026-10-08T05:00:00", what: "did a thing" }], stages: [{ name: "1 · Read", what: "w", how: "h", numbers: {} }] };
  const m = markup(P); for (const k of ["a2l-scan", "a2l-dial", "a2l-focus", "a2l-steps", "a2l-curve", "a2l-replay", "a2l-hist", "a2l-sig", "a2l-tape", "a2l-pipe"]) assert.ok(m.includes(k), k);
  assert.match(m, /BUY/); assert.match(m, /not investment advice/); assert.match(m, /did a thing/);
});

test("the console's cut-offs follow the payload (worst 2% since 2026-10-09)", async () => {
  const { setCuts } = await import("../../desk-a2live.js");
  assert.deepEqual(setCuts({ cuts: { bull: 0.99, bear: 0.02 } }), { bull: 0.99, bear: 0.02 });
  assert.match(decisionLines({ signal: "bear", rank_pct: 0.01, p5: 0.4, chance: null, cost_bps: 40, fno: false }, { kpis: { stocks_ranked: 1000 }, cuts: { bull: 0.99, bear: 0.02 } })[1], /worst 2%/);
  setCuts({});
});
