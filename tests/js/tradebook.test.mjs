// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { tradeBookHtml, tradeBookRows, tradeBookCsv } from "../../desk-signals.js";

const base = { rules: { risk_per_trade_pct: 2, max_position_pct: 20, adv_participation_max: 0.05, max_open: 10, max_sector_pct: 30 }, stats: { from: "2026-10-12" }, equity: [["2026-10-13", 1002482.55, 150.75, 1]],
  open: [{ sym: "AAA", qty: 100, entry: 200, last: 210, pnl: 950, days_held: 1, days_left: 4, as_of: "2026-10-09", entry_date: "2026-10-12", capital: 20000, pct_of_account: 2, sized_by: "max position size", risk_to_stop: 800, cost_in: 50, value_now: 21000, exit_due: "2026-10-19" }],
  trades: [{ sym: "ZZZ", qty: 10, entry: 100, exit: 90, entry_date: "2026-10-05", exit_date: "2026-10-12", reason: "time", costs: 5, net: -105, ret_pct: -10.5 }],
  skipped: [{ sym: "SKP", as_of: "2026-10-09", why: "size 0 (fractional Kelly (edge too small)) or no cash/sector room" }] };

test("every position is listed with the money it used, what sized it, costs and result; filters and CSV agree", () => {
  const h = tradeBookHtml(base);
  assert.match(h, /AAA/); assert.match(h, /ZZZ/); assert.match(h, /2\.0% of account/); assert.match(h, /per-stock cap/); assert.match(h, /₹1,000/);   // ZZZ capital from shares x entry
  assert.match(h, /size came out at zero \(small-edge cap\)/); assert.match(h, /All \(2\)/);
  assert.doesNotMatch(tradeBookHtml(base, "open"), /ZZZ/); assert.doesNotMatch(tradeBookHtml(base, "closed"), />AAA</);
  assert.equal(tradeBookCsv(base).split("\n").length, 3);
  assert.doesNotMatch(h, /\b(buy|sell|target|recommendation|guaranteed)\b/i);
});

test("the real live file renders, and a field the bot has not recorded yet is shown as missing, not guessed", () => {
  const doc = JSON.parse(readFileSync(new URL("../../data/aladin2/paper/live.json", import.meta.url)));
  const rows = tradeBookRows(doc); assert.equal(rows.length, doc.open.length + doc.trades.length);
  for (const r of rows) assert.ok(Math.abs(r.capital - r.qty * r.entry) < 0.02);
  if (!doc.open[0].pct_of_account) assert.match(tradeBookHtml(doc), /of today's account/);
});

test("the small account explains whole shares and the depository charge", () => {
  const h = tradeBookHtml({ ...base, rules: { ...base.rules, budget_inr: 10000, first_list: "2026-10-16", dp_charge_per_sale_inr: 15.93 } });
  assert.match(h, /Small account \(₹10,000\)/); assert.match(h, /₹2,000/); assert.match(h, /₹15\.93 depository charge/);
});
