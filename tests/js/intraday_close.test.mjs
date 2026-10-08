// node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { withOfficialClose } from "../../intraday-close.js";

const day = "2026-10-08", T = (hh, mm) => Date.UTC(2026, 9, 8, hh, mm) / 1000;
const bar = (hh, mm, o, h, l, c, v) => ({ time: T(hh, mm), o, h, l, c, v, day, lbl: `${day} ${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}` });
const meta = { market: "closed", session_date: day }, u = { date: day, c: 2076, h: 2141.5, l: 2060, v: 1000 };

test("a feed that stops at 15:10 gets one closing candle from NSE's official close, with the missing volume", () => {
  const bars = [bar(9, 15, 2104, 2141, 2100, 2110, 300), bar(15, 10, 2080, 2082, 2070, 2078, 200)];
  const out = withOfficialClose(bars, u, meta, 300); assert.equal(out.length, 3); const c = out[2];
  assert.equal(c.time, T(15, 25)); assert.equal(c.o, 2078); assert.equal(c.c, 2076); assert.equal(c.v, 500); assert.match(c.lbl, /close \(NSE official\)/); assert.equal(c.h, 2078); assert.equal(c.l, 2076);
  assert.equal(bars.length, 2, "the input is not changed");
});

test("the closing candle never copies NSE's day high or low, which would draw a false spike", () => {
  const out = withOfficialClose([bar(9, 15, 2104, 2141.3, 2060, 2110, 300), bar(15, 10, 2080, 2082, 2070, 2078, 200)], u, meta, 300), c = out[2];
  assert.ok(c.h < 2100 && c.l >= 2076);
});

test("a last candle already in the closing slot is completed, not duplicated", () => {
  const out = withOfficialClose([bar(9, 15, 2104, 2141.5, 2060, 2110, 300), bar(15, 25, 2080, 2082, 2070, 2078, 200)], u, meta, 300); assert.equal(out.length, 2); assert.equal(out[1].c, 2076); assert.equal(out[1].v, 700);
});

test("it does nothing while the market is open, for another day's data, for hourly and longer candles, or when there is no official row", () => {
  const bars = [bar(15, 10, 2080, 2082, 2070, 2078, 200)];
  assert.equal(withOfficialClose(bars, u, { ...meta, market: "open" }, 300), bars); assert.equal(withOfficialClose(bars, { ...u, date: "2026-10-07" }, meta, 300), bars);
  assert.equal(withOfficialClose(bars, u, meta, 3600), bars); assert.equal(withOfficialClose(bars, null, meta, 300), bars); assert.equal(withOfficialClose([], u, meta, 300).length, 0);
});
