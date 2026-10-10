// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { flowStats, liveEquity, isStale, minutesSince } from "../../desk-crypto.js";

test("flow stats: buy and sell volume, imbalance and delta inside the window only", () => {
  const now = 1_000_000, t = [{ t: now - 400_000, q: 9, buy: true }, { t: now - 100_000, q: 3, buy: true }, { t: now - 50_000, q: 1, buy: false }, { t: now - 10_000, q: 2, buy: false }];
  const f = flowStats(t, now); assert.equal(f.buy, 3); assert.equal(f.sell, 3); assert.equal(f.imbalance, 0); assert.equal(f.cvd, 0); assert.equal(f.n, 3);
  const g = flowStats([{ t: now, q: 3, buy: true }, { t: now, q: 1, buy: false }], now); assert.equal(g.imbalance, 0.5); assert.deepEqual(flowStats([], now), { buy: 0, sell: 0, total: 0, imbalance: 0, cvd: 0, line: [], n: 0 });
});

test("account value follows the live price; a late engine is flagged", () => {
  const doc = { bid: 100, engine_ts: "2026-10-10T05:00:00Z", stale_after_min: 45, sleeves: { a: { cash: 500, btc: 2 }, b: { cash: 1000, btc: 0 } } };
  assert.equal(liveEquity(doc, 110), 1720); assert.equal(liveEquity(doc), 1700); assert.equal(liveEquity(null, 1), null);
  const t = Date.parse("2026-10-10T05:30:00Z"); assert.equal(minutesSince(doc.engine_ts, t), 30); assert.equal(isStale(doc, t), false); assert.equal(isStale(doc, t + 20 * 60000), true); assert.equal(isStale(null), true);
});
