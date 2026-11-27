// node --test tests/js/market_state.test.mjs
// A stale price file that says "closed" must never be shown as "Market closed" while the exchange clock says it is open (27 Nov 2026).
import test from "node:test";
import assert from "node:assert/strict";
import { clockOpen, priceState, STALE_MIN } from "../../market-state.js";

const ist = (iso) => new Date(iso + "+05:30");          // an instant given in IST
const FRI_1045 = ist("2026-11-27T10:45:00");
const file = (utc, market) => ({ market, generated_utc: utc });

test("the exchange clock: weekdays 09:15-15:30 IST only", () => {
  assert.equal(clockOpen(FRI_1045), true);
  assert.equal(clockOpen(ist("2026-11-27T09:14:00")), false);
  assert.equal(clockOpen(ist("2026-11-27T15:31:00")), false);
  assert.equal(clockOpen(ist("2026-11-28T10:45:00")), false);   // Saturday
});

test("the 27 Nov case: market open by the clock, file says closed and is 90 min old -> stale, not closed", () => {
  const f = file("2026-11-27T03:43:19+00:00", "closed");       // generated 09:13 IST
  const s = priceState(f, FRI_1045);
  assert.equal(s.state, "stale");
  assert.ok(s.ageMin > 91 && s.ageMin < 92);
});

test("a fresh 'closed' file during market hours (a holiday, or the first minutes) stays closed", () => {
  const f = file("2026-11-27T05:10:00+00:00", "closed");        // 10:40 IST, 5 min old
  assert.equal(priceState(f, FRI_1045).state, "closed");
});

test("after the close a closed file is closed, however old", () => {
  assert.equal(priceState(file("2026-11-27T10:00:00+00:00", "closed"), ist("2026-11-27T20:00:00")).state, "closed");
  assert.equal(priceState(file("2026-11-20T10:00:00+00:00", "closed"), ist("2026-11-28T11:00:00")).state, "closed");
});

test("an open file: live while fresh, delayed once it is 45 min old", () => {
  assert.equal(priceState(file("2026-11-27T05:00:00+00:00", "open"), FRI_1045).state, "open");     // 15 min
  assert.equal(priceState(file("2026-11-27T04:00:00+00:00", "open"), FRI_1045).state, "delayed");  // 75 min
});

test("no file or no time stamp is never called closed or open", () => {
  assert.equal(priceState(null, FRI_1045).state, "unknown");
  assert.equal(priceState({ market: "closed" }, FRI_1045).state, "unknown");
  assert.ok(STALE_MIN > 0);
});
