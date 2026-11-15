// node --test tests/js   The Technicals gauge's track record (scripts/technicals_record.mjs) on made-up samples.
import test from "node:test";
import assert from "node:assert/strict";
import { summarise, verdict } from "../../scripts/technicals_record.mjs";

test("excess is against the same day's average, and a label that always lags is measured as worse", () => {
  const samples = [];
  for (let d = 0; d < 60; d++) {
    const day = `2024-01-${String(d).padStart(3, "0")}`, mkt = (d % 7 - 3) / 100;      // the market moves; excess must remove it
    for (let i = 0; i < 40; i++) samples.push({ day, label: "Strongly bearish", f10: mkt - 0.01 + (i % 5) / 1000, f63: mkt });
    for (let i = 0; i < 40; i++) samples.push({ day, label: "Strongly bullish", f10: mkt + 0.01 + (i % 5) / 1000, f63: mkt });
  }
  const r = summarise(samples);
  assert.equal(r[10]["Strongly bearish"].mean_excess_pct, -1);
  assert.equal(r[10]["Strongly bullish"].mean_excess_pct, 1);
  assert.equal(r[63]["Strongly bearish"].mean_excess_pct, 0);
  assert.equal(r[10].Neutral.n, 0);
  const v = verdict(r);
  assert.equal(v["Strongly bearish"], "did worse than the average stock");
  assert.equal(v["Strongly bullish"], "did better than the average stock");
  assert.equal(v.Neutral, "not measured");
});

test("days with fewer than 50 sampled stocks are left out", () => {
  const r = summarise([{ day: "2024-01-01", label: "Bullish", f10: 0.1, f63: 0.1 }]);
  assert.equal(r[10].Bullish.n, 0);
});
