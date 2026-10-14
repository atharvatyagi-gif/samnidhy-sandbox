// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { blotterEvents, exposure, blotterHtml, shadowCompareHtml } from "../../desk-signals.js";

const doc = {
  equity: [["2026-10-12", 1010000, 1000, 2], ["2026-10-13", 1015000, 1000, 2]],
  open: [{ sym: "AAA", qty: 100, entry: 200, entry_date: "2026-10-12", value_now: 21000, risk_to_stop: 800, exit_due: "2026-10-19" },
         { sym: "ZZZ", side: "short", qty: 50, entry: 100, entry_date: "2026-10-12", value_now: 4800, risk_to_stop: 400, exit_due: "2026-10-19" }],
  trades: [{ sym: "OLD", qty: 10, entry: 100, exit: 110, entry_date: "2026-10-05", exit_date: "2026-10-12", reason: "time", days: 5, net: 95, capital: 1000 }],
  skipped: [{ sym: "SKP", as_of: "2026-10-09", why: "size 0 (fractional Kelly (edge too small)) or no cash/sector room" }],
  timeline: { weeks: [{ friday: "2026-10-09", entry_day: "2026-10-12" }], next_book: "2026-10-16", next_entry: "2026-10-19" }, rules: {} };

test("the blotter lists exits, fills and passes per day, newest first, with the next orders and the exposure", () => {
  const ev = blotterEvents(doc);
  assert.deepEqual(ev.filter(e => e.d === "2026-10-12").map(e => e.k + ":" + e.sym), ["out:OLD", "in:AAA", "in:ZZZ", "skip:SKP"]);
  assert.equal(ev[ev.length - 1].d, "2026-10-05");
  const X = exposure(doc); assert.equal(X.long, 21000); assert.equal(X.short, 4800); assert.equal(X.risk, 1200); assert.equal(X.day, 5000);
  const h = blotterHtml(doc, "2026-10-13");
  assert.match(h, /AAA exits at the open on 19 Oct/); assert.match(h, /New list after the close on 16 Oct/); assert.match(h, /short/); assert.match(h, /5-day limit/);
  assert.doesNotMatch(h, /\b(buy|sell|target|recommendation|guaranteed)/i);
});

test("the shadow comparison states the switch rule until it happens", () => {
  const h = shadowCompareHtml({ shadow_vs_bot: { weeks: 3, promote_after_weeks: 26, promoted: null, shadow_return_pct: 1.2, bot_return_pct: 0.8, shadow_dd_pct: -1, bot_dd_pct: -2, from: "2026-10-19", to: "2026-11-06" } });
  assert.match(h, /3 of 26/); assert.match(h, /failed their 2013-2026 history test/); assert.equal(shadowCompareHtml({}), "");
});
