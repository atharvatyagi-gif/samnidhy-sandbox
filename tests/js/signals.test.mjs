// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { buildRows, dependenciesOf, rowOf, fmtLevel } from "../../desk-signals.js";

const mk = (sym, side, rank, goal, stop, close = 100) => ({ sym, name: sym + " Ltd", sector: "IT", signal: side, close, goal, stop, reward_risk: goal ? 0.5 : null, rank_pct: rank, chance: { closes_higher: 0.55, beats_market: 0.52 }, goal_basis: goal ? "upper edge" : "not measured: no 5-day forecast range for this stock yet" });
const W = { book: { as_of: "2026-10-08", bull: [mk("AAA", "bull", 0.995, 103, 94), mk("BBB", "bull", 0.999, null, 95)], bear: [mk("ZZZ", "bear", 0.04, 90, 106), mk("YYY", "bear", 0.01, 88, 105)], ranks: { AAA: [0.995, 0.55, 0.52], MID: [0.5, 0.49, 0.49] }, counts: { bull: 2, bear: 2, hold: 1 } } };
const stocks = [{ s: "AAA", n: "Alpha Ltd", c: 100, ind: "IT" }, { s: "MID", n: "Middle Corp", c: 50, ind: "Banks" }, { s: "ILLQ", n: "Thin Trade Ltd", c: 10 }, { s: "ZZZ", n: "Zed", c: 100 }];

test("without a search the list is the week's signals: positive strongest first, then negative weakest first", () => {
  assert.deepEqual(buildRows(W, stocks).rows.map(r => r.sym), ["BBB", "AAA", "YYY", "ZZZ"]);
  assert.deepEqual(buildRows(W, stocks, { filter: "bear" }).rows.map(r => r.sym), ["YYY", "ZZZ"]); assert.equal(buildRows(null, stocks).rows.length, 0);
});

test("a search finds any stock: signal rows carry the levels, ranked stocks read no edge, thin ones say they are not ranked", () => {
  const a = buildRows(W, stocks, { q: "aaa" }).rows[0]; assert.equal(a.sig, "bull"); assert.equal(a.goal, 103); assert.equal(a.stop, 94); assert.ok(Math.abs(a.goalPct - 3) < 1e-9 && Math.abs(a.stopPct + 6) < 1e-9);
  const m = buildRows(W, stocks, { q: "middle" }).rows[0]; assert.equal(m.sig, "none"); assert.equal(m.goal, null); assert.equal(m.pu, 0.49);
  const i = buildRows(W, stocks, { q: "thin" }).rows[0]; assert.equal(i.sig, "na"); assert.equal(i.ranked, false); assert.equal(buildRows(W, stocks, { q: "nothing here" }).rows.length, 0);
});

test("a goal that has no forecast range stays not measured, never a made-up number", () => {
  const b = buildRows(W, stocks).rows[0]; assert.equal(b.sym, "BBB"); assert.equal(b.goal, null); assert.equal(b.goalPct, null); assert.equal(b.stop, 95); assert.equal(fmtLevel(null, null), null); assert.equal(fmtLevel(103, 3).price, "103.00");
  assert.equal(rowOf(mk("Q", "bull", 0.99, 100, 100), "bull").rr, 0.5);
});

const G = { coverage: { companies_done: 212, companies_total: 3525 }, cos: { AAA: { edges: 1 }, EMPTY: { edges: 0 } }, nodes: [{ id: "AAA", k: "co", n: "Alpha", sym: "AAA" }, { id: "CCC", k: "co", n: "Cee Ltd", sym: "CCC" }, { id: "EXT_X", k: "ext", n: "Foreign X" }],
  edges: [{ own: "AAA", s: "AAA", d: "CCC", rel: "supplies", w: 0.4, wb: "revenue", per: "FY26", conf: 0.9, url: "u", pg: 3, q: "quote" }, { own: "AAA", s: "EXT_X", d: "AAA", rel: "raw_material_from", w: null, per: "FY26", conf: 0.5 }, { own: "OTHER", s: "OTHER", d: "CCC", rel: "supplies" }] };

test("dependencies list who a company supplies and who supplies it, biggest share first, with the source, and say when the filings were not read", () => {
  const d = dependenciesOf(G, "AAA"); assert.equal(d.rows.length, 2); assert.equal(d.rows[0].share, 0.4); assert.match(d.rows[0].text, /AAA supplies Cee Ltd/); assert.equal(d.rows[0].other.sym, "CCC"); assert.equal(d.rows[0].page, 3); assert.equal(d.read, true);
  assert.match(d.rows[1].text, /Foreign X sources raw material from AAA/); assert.equal(d.rows[1].share, null);
  const none = dependenciesOf(G, "NOPE"); assert.equal(none.rows.length, 0); assert.equal(none.read, false); assert.equal(none.done, 212); assert.equal(none.total, 3525); assert.equal(dependenciesOf({ edges: [] }, "AAA").rows.length, 0); assert.equal(dependenciesOf(null, "AAA"), null);
  assert.equal(dependenciesOf(G, "EMPTY").read, true);
});
