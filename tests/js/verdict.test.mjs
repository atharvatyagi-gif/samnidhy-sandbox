// node --test tests/js   The stock page's "Three questions" box (desk-verdict.js), on made-up records.
import test from "node:test";
import assert from "node:assert/strict";
import { techLean, tenDayLean, eLean, together, verdictHtml } from "../../desk-verdict.js";

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const rec = { from: "2023-05-18", to: "2026-09-22", record: { 10: {
  "Strongly bearish": { mean_excess_pct: -0.37, ci95_pct: [-0.71, -0.04] },
  Neutral: { mean_excess_pct: 0.06, ci95_pct: [-0.61, 0.73] },
  "Strongly bullish": { mean_excess_pct: 0.3, ci95_pct: [0.02, 0.58] } } } };
const best = { label: "best 5% (in the portfolio)", beat_market: 0.466, beat_market_ci95: [0.456, 0.477], mean_excess_pct: 2.55, mean_excess_ci95_pct: [1.94, 3.17] };
const worst = { label: "worst 20%", beat_market: 0.4, beat_market_ci95: [0.39, 0.41], mean_excess_pct: -1.92, mean_excess_ci95_pct: [-2.22, -1.6] };
const mid = { label: "50th-80th", beat_market: 0.467, beat_market_ci95: [0.46, 0.47], mean_excess_pct: 0.1, mean_excess_ci95_pct: [-0.1, 0.3] };

test("the Technicals label leans only when its tested record is clear of zero", () => {
  assert.equal(techLean("Strongly bearish", rec).lean, -1);
  assert.match(techLean("Strongly bearish", rec).text, /slightly worse than the average stock over the next 10 trading days \(−0\.37%, range −0\.71% to −0\.04%\)/);
  assert.equal(techLean("Neutral", rec).lean, 0);
  assert.equal(techLean("Bearish", rec).lean, null);                       // no record for it: not measured, never guessed
  assert.equal(techLean(null, rec).lean, null);
});

test("ALADIN 1 leans only in its top or bottom 10%; a 54% chance in the middle is no lean", () => {
  const v = { p: 0.54, h: 10, rank: 62, top: 0.543, bottom: 0.435, base: 0.498 };
  assert.equal(tenDayLean(v).lean, 0);
  assert.match(tenDayLean(v).text, /no clear lean, about as likely to rise as any stock/);
  assert.equal(tenDayLean({ ...v, rank: 93 }).lean, 1);
  assert.equal(tenDayLean({ ...v, p: 0.45, rank: 4 }).lean, -1);
  assert.equal(tenDayLean(null).lean, null);
});

test("model E's lean uses the group's average lead, not how often it beat the average", () => {
  assert.equal(eLean([3, 0.99, 0.8, 1], best, 500).lean, 1);             // beat only 46.6% of the time, yet +2.55% on average
  assert.match(eLean([3, 0.99, 0.8, 1], best, 500).text, /In the portfolio, rank 3 of 500.*a few large gains carry the average/);
  assert.equal(eLean([450, 0.1, -0.2, 0], worst, 500).lean, -1);
  assert.equal(eLean([200, 0.6, 0.1, 0], mid, 500).lean, 0);
  assert.equal(eLean(null, null, 500).lean, null);
});

test("read together: no lean, agreement, and the strongly-bearish-but-ranked-well case", () => {
  assert.match(together([{ name: "a", span: "x", lean: 0 }, { name: "b", span: "y", lean: null }]), /None of these shows a measurable lean/);
  assert.match(together([{ name: "the trend so far", span: "next 2 weeks", lean: 1 }, { name: "model E", span: "3 months", lean: 1 }, { name: "ALADIN 1", span: "10 days", lean: 0 }]),
    /the trend so far \(next 2 weeks\) and model E \(3 months\) show a positive lean; ALADIN 1 shows none/);
  const s = together([{ name: "the trend so far", span: "next 2 weeks", lean: -1 }, { name: "ALADIN 1", span: "10 days", lean: 0 }, { name: "model E", span: "3 months", lean: 1 }]);
  assert.match(s, /point different ways because they cover different time spans: model E \(3 months\) leans positive, the trend so far \(next 2 weeks\) leans negative/);
});

test("the box shows all three questions, escapes text and uses no banned word", () => {
  const h = verdictHtml({ sym: "A&B", tech: "Strongly bearish", techRec: rec, e: { row: [3, 0.99, 0.8, 1], group: best, universe: 500 }, ten: { p: 0.54, h: 10, rank: 62, top: 0.543, bottom: 0.435, base: 0.498 } }, esc);
  for (const w of ["Trend so far", "Next 10 days", "Next 3 months", "Read together", "not investment advice", 'data-sym="A&amp;B"']) assert.ok(h.includes(w), w);
  assert.ok(!/\b(buy|sell|target|recommendation|guaranteed)\b/i.test(h));
  const empty = verdictHtml({ sym: "X", tech: null, techRec: null, e: null, ten: null }, esc);
  assert.match(empty, /None of these shows a measurable lean/);
});
