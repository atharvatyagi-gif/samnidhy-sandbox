// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { moversHtml } from "../../desk-signals.js";

const r = (sym, em) => ({ sym, name: sym + " Ltd", p_big: 0.4, p_up: 0.6, size: 0.04, exp_move: em, sector: "IT", results_this_week: sym === "AAA" });
const doc = { label: "FORWARD TEST", method: "Three models.", book: { friday: "2026-10-16", counted: true, n: 900, k: 90, top: [r("AAA", 0.012)], bottom: [r("ZZZ", -0.01)] },
  forward: { weeks: [], done: 0, equity: 1000000, equity_all_stocks: 1000000 }, shadow: { weeks: 0, promote_after_weeks: 26, promoted: null },
  backtest: { gates: { size: false, direction: false, ranking: true }, auc_big: 0.64, auc_up: 0.519, deciles_expected_move: [{ mean_r5: -0.0013 }, { mean_r5: 0.0066 }] } };

test("the ranking shows both tenths, failed gates as failed, and the switch rule before it has happened", () => {
  const h = moversHtml(doc);
  assert.match(h, /AAA/); assert.match(h, /ZZZ/); assert.match(h, /Results due/); assert.match(h, /\+1\.20%/);
  assert.equal((h.match(/did not pass/g) || []).length, 2); assert.equal((h.match(/>passed</g) || []).length, 1);
  assert.match(h, /after 26 finished weeks/); assert.doesNotMatch(h, /Switched on/);
  assert.doesNotMatch(h, /\b(buy|sell|target|recommendation|guaranteed)\b/i);
});

test("before the first Friday, and after a switch, the page says so plainly", () => {
  assert.match(moversHtml({ ...doc, book: null }), /No ranking written yet/);
  assert.match(moversHtml(null), /not published yet/);
  const h = moversHtml({ ...doc, shadow: { weeks: 26, promote_after_weeks: 26, promoted: { ts: "2027-04-17T02:00:00", weeks: 26, movers_return_pct: 10, bot_return_pct: 5 } } });
  assert.match(h, /Switched on 2027-04-17/);
});
