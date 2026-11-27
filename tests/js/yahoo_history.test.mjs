// node --test tests/js/yahoo_history.test.mjs
// Older chart history (60 days of 5-minute, 2 years of hourly, daily since listing) comes from Yahoo through the site's own Cloudflare
// worker, because the GitHub "intraday" and "history" branches are gone (account suspended 18 Nov 2026; the chart showed blank space).
import test from "node:test";
import assert from "node:assert/strict";
import { histUrl, yahooRows, HIST_BASE } from "../../yahoo-history.js";

const IST = 19800;
const at = (day, hm) => Date.parse(day + "T" + hm + ":00Z") / 1000 - IST;           // an IST wall-clock time as a Unix time
const reply = (ts, q, extra = {}) => ({ chart: { result: [{ meta: { gmtoffset: IST, ...extra }, timestamp: ts, indicators: { quote: [q] } }] } });

test("URLs: NSE stocks get .NS, indexes stay as they are, & is encoded, only the allowed requests are built", () => {
  assert.equal(histUrl("RELIANCE", "5m"), HIST_BASE + "RELIANCE.NS?i=5m&r=60d");
  assert.equal(histUrl("M&M", "1h", "365d"), HIST_BASE + "M%26M.NS?i=1h&r=365d");
  assert.equal(histUrl("^NSEI", "1d"), HIST_BASE + "%5ENSEI?i=1d&r=all");
  assert.throws(() => histUrl("RELIANCE", "1m"));
  assert.throws(() => histUrl("RELIANCE", "5m", "730d"));
});

test("intraday rows: IST time, market minutes only (09:15-15:29), empty candles dropped, 2 decimals", () => {
  const ts = [at("2026-11-27", "09:10"), at("2026-11-27", "09:15"), at("2026-11-27", "09:20"), at("2026-11-27", "15:25"), at("2026-11-27", "15:30")];
  const q = { open: [1, 850.123, null, 851, 9], high: [1, 852.456, null, 852, 9], low: [1, 849, null, 850, 9], close: [1, 851.239, null, 851.5, 9], volume: [5, 1200, null, null, 7] };
  assert.deepEqual(yahooRows(reply(ts, q), true), [
    ["2026-11-27 09:15", 850.12, 852.46, 849, 851.24, 1200],
    ["2026-11-27 15:25", 851, 852, 850, 851.5, 0],
  ]);
});

test("daily rows: one row per IST date (a later row for the same day replaces the earlier one), 4 decimals below Rs 1", () => {
  const ts = [at("2026-11-26", "09:15"), at("2026-11-27", "09:15"), at("2026-11-27", "14:41")];
  const q = { open: [0.51234, 0.52, 0.52], high: [0.6, 0.6, 0.61], low: [0.5, 0.5, 0.5], close: [0.55558, 0.56, 0.57771], volume: [10, 20, 30] };
  assert.deepEqual(yahooRows(reply(ts, q), false), [
    ["2026-11-26", 0.5123, 0.6, 0.5, 0.5556, 10],
    ["2026-11-27", 0.52, 0.61, 0.5, 0.5777, 30],
  ]);
});

test("nothing usable in the reply -> no rows (the chart then says there is no older history)", () => {
  assert.deepEqual(yahooRows(null, true), []);
  assert.deepEqual(yahooRows({ chart: { result: null, error: { code: "Not Found" } } }, false), []);
  assert.deepEqual(yahooRows(reply([], { open: [], high: [], low: [], close: [], volume: [] }), true), []);
});
