// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { groupOf, roundTripPct, reasons, search, alerts } from "../../desk-aladin-e.js";
import { isLegacy, normalise } from "../../desk-legacy.js";

const cal = { buckets: [
  { label: "best 5%", from: 0.95, to: 1, beat_market: 0.466, beat_market_ci95: [0.44, 0.49], mean_excess_pct: 2.55, mean_excess_ci95_pct: [1.94, 3.17], median_excess_pct: -1.2 },
  { label: "rest", from: 0, to: 0.95, beat_market: 0.44, beat_market_ci95: [0.43, 0.45], mean_excess_pct: 0.1, mean_excess_ci95_pct: [-0.2, 0.4], median_excess_pct: -2 }] };
const doc = { universe_size: 500, portfolio_size: 25, calibration: cal, risk: { risk_on: true, invested_share: 0.7 }, next_rebalance_in_sessions: 1,
  portfolio: [{ sym: "AAA", r126: 0.9 }, { sym: "LAST", r126: 0.4 }], stocks: { AAA: [1, 1, 0.9, true], ABB: [30, 0.94, 0.3, false], ZED: [400, 0.2, -0.1, false] } };
const costs = { stt_entry_pct: 0.1, stt_exit_pct: 0.1, exchange_txn_pct: 0.00297, sebi_fee_pct: 0.0001, stamp_duty_entry_pct: 0.015, brokerage_pct: 0, gst_pct_on_brokerage_and_charges: 18, dp_charge_per_scrip_exit_inr: 15.93, slippage_pct: { adv_ge_100cr: 0.05, adv_ge_20cr: 0.1, below: 0.2 } };

test("a rank falls into exactly one measured group, the top edge included", () => {
  assert.equal(groupOf(1, cal).label, "best 5%"); assert.equal(groupOf(0.95, cal).label, "best 5%"); assert.equal(groupOf(0.5, cal).label, "rest"); assert.equal(groupOf(0.5, null), null);
});

test("the round trip counts STT both sides, stamp, charges with GST, slippage both sides and the DP charge, which weighs more on a small position", () => {
  const big = roundTripPct(1e6, costs), small = roundTripPct(4000, costs);
  assert.ok(Math.abs(big - (0.2 + 0.015 + 2 * 0.00307 * 1.18 + 0.2 + 0.001593)) < 1e-9);
  assert.ok(small > big + 0.3); assert.equal(roundTripPct(0, costs), null);
});

test("reasons say the 6-month move, the rank, the group's record with its range, the risk check and the next change, in plain words", () => {
  const a = reasons("AAA", doc.stocks.AAA, doc), z = reasons("ZED", doc.stocks.ZED, doc);
  assert.match(a[0], /^Up 90\.0%/); assert.match(a[1], /in the portfolio/); assert.match(a[2], /46\.6%.*range 44\.0% to 49\.0%/); assert.match(a[3], /70% invested/); assert.match(a[4], /1 session;?/);
  assert.match(z[0], /^Down 10\.0%/); assert.match(z[1], /no signal/); assert.match(z[1], /\+40\.0%/);
  for (const l of [...a, ...z]) assert.doesNotMatch(l, /\b(buy|sell|target|recommend|guarantee)/i);
});

test("search finds by symbol or name and lists the best ranked first", () => {
  assert.deepEqual(search(doc, "a", new Map()), ["AAA", "ABB"]);
  assert.deepEqual(search(doc, "zebra", new Map([["ZED", "Zebra Ltd"]])), ["ZED"]); assert.deepEqual(search(doc, "", null), []);
});

test("alerts: late data, kill switch, accuracy alarm and the 4% pause; none on a normal day", () => {
  assert.deepEqual(alerts(doc), []);
  const a = alerts({ status: "degraded", degraded_reason: "prices 3 sessions old", risk: { kill: { reason: "fell 25%" }, pause_entries_next_open: true }, health: { alarm: "trails by 16%" } });
  assert.equal(a.length, 4); assert.equal(a[0][0], "down");
});

test("only the earlier models' files are kept behind the bot; the bot's own file and model E stay public", () => {
  for (const u of ["aladin.json", "./predict.json", "aladin2/weekly.json?x=1", "aladin2/stock/TCS.json", "paper.json"]) assert.ok(isLegacy(u), u);
  for (const u of ["aladin_e.json", "aladin2/bot.enc.json", "desk_data.json", "pl/A.json"]) assert.ok(!isLegacy(u), u);
  assert.equal(normalise(" ab-c 1 "), "ABC1");
});
