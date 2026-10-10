// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { liveEquity, isStale, minutesSince, tradedSince } from "../../desk-crypto.js";
import { parseTrade, bucketBook, flowWindow } from "../../desk-cryptofeed.js";
import { ParticlePool, priceToY, tradeLook, K } from "../../desk-crypto3d.js";

test("a trade message says who was the aggressor: when the buyer is the maker, the seller hit the bid", () => {
  const b = parseTrade({ stream: "btcusdt@aggTrade", data: { s: "BTCUSDT", p: "80000.5", q: "0.25", T: 1000, m: false } }), s = parseTrade({ data: { s: "ETHUSDT", p: "2500", q: "2", T: 2000, m: true } });
  assert.deepEqual([b.buy, b.usd, b.sym], [true, 20000.125, "BTCUSDT"]); assert.equal(s.buy, false); assert.equal(s.usd, 5000); assert.equal(parseTrade({}), null); assert.equal(parseTrade(null), null);
});

test("flow window: dollars bought and sold inside the window only", () => {
  const now = 1_000_000, t = [{ t: now - 90_000, usd: 900, buy: true }, { t: now - 30_000, usd: 300, buy: true }, { t: now - 20_000, usd: 100, buy: false }, { t: now - 1_000, usd: 200, buy: false }];
  const w = flowWindow(t, now, 60_000); assert.equal(w.buy, 300); assert.equal(w.sell, 300); assert.equal(w.imbalance, 0); assert.equal(w.n, 3); assert.equal(w.perSec, 3 / 60);
  assert.equal(flowWindow([], now).imbalance, 0);
});

test("order book buckets cover the whole fetched book, bids below the mid and asks above", () => {
  const bids = [[99.9, 1], [99.5, 2], [99.0, 3]], asks = [[100.1, 4], [100.5, 1]], b = bucketBook(bids, asks, 100, 10);
  assert.equal(b.bids.length, 10); assert.equal(b.bids.reduce((a, v) => a + v, 0), 99.9 + 199 + 297); assert.equal(b.asks.reduce((a, v) => a + v, 0), 400.4 + 100.5); assert.ok(b.bids[0] > 0 && b.asks[0] > 0);
});

test("account value follows each coin's live price; a late engine is flagged; trades are noticed once", () => {
  const doc = { engine_ts: "2026-10-10T05:00:00Z", stale_after_min: 45, assets: { BTCUSDT: { bid: 100 }, ETHUSDT: { bid: 10 } }, sleeves: { a: { asset: "BTCUSDT", cash: 500, qty: 2 }, b: { asset: "ETHUSDT", cash: 1000, qty: 5 } } };
  assert.equal(liveEquity(doc, { BTCUSDT: 110, ETHUSDT: 20 }), 500 + 220 + 1000 + 100); assert.equal(liveEquity(doc, {}), 500 + 200 + 1000 + 50); assert.equal(liveEquity(null, {}), null);
  const t = Date.parse("2026-10-10T05:30:00Z"); assert.equal(minutesSince(doc.engine_ts, t), 30); assert.equal(isStale(doc, t), false); assert.equal(isStale(doc, t + 20 * 60000), true); assert.equal(isStale(null), true);
  assert.deepEqual(tradedSince(null, doc.sleeves), []); assert.deepEqual(tradedSince({ a: 0, b: 5 }, doc.sleeves).map(x => [x.sleeve, x.side]), [["a", "buy"]]); assert.deepEqual(tradedSince({ a: 2, b: 5 }, { a: { ...doc.sleeves.a, qty: 0 }, b: doc.sleeves.b }).map(x => [x.sleeve, x.side]), [["a", "sell"]]);
});

test("particles: a fixed pool, oldest overwritten, they drift, fade and die; a rising reference price lowers them", () => {
  const p = new ParticlePool(3); for (let i = 0; i < 4; i++) p.spawn({ x: 10, y: 0, z: 0, vx: -1, r: 1, g: 0, b: 0, size: 1, life: 2 }); assert.equal(p.head, 1); assert.equal(p.update(0), 3);
  p.update(1, 0.5); assert.equal(p.pos[0], 9); assert.equal(p.pos[1], -0.5); assert.ok(p.alpha[0] > 0 && p.alpha[0] < 1);
  assert.equal(p.update(1.5), 0); assert.equal(p.alpha[0], 0); assert.equal(p.alpha[1], 0);
});

test("price height and particle size", () => {
  assert.equal(priceToY(100, 100), 0); assert.ok(Math.abs(priceToY(100.01, 100) - 1 * K) < 1e-9); assert.ok(priceToY(99, 100) < 0);
  assert.ok(tradeLook(50).size < tradeLook(50_000).size); assert.equal(tradeLook(100_000).big, false); assert.equal(tradeLook(300_000).big, true); assert.ok(tradeLook(1e9).glow <= 1);
});
