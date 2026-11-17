// node --test tests/js   The B-Lab research desk dashboard (lab.js) on a made-up status.
import test from "node:test";
import assert from "node:assert/strict";
import { headHtml, orgHtml, feedHtml, stockHtml, scoreHtml, filterFindings, age, esc } from "../../lab.js";

const doc = {
  generated_utc: "2026-11-16T15:30:00Z", findings_total: 2, findings_added: 1, min_scored: 20, repeat_days: 7, horizons: [5, 20, 63], note: "Educational analysis, not investment advice.",
  divisions: [{ id: "fundamental", name: "Fundamental", source: "filings", ok: 1, stale: 0, error: 0, planned: 1 }, { id: "sentiment", name: "Sentiment", source: "writing", ok: 1, stale: 0, error: 0, planned: 0 }],
  bots: [
    { id: "F1", division: "fundamental", name: "Statements scout", role: "scout", does: "d", state: "ok", items: 2007, as_of: "2026-11-15T14:19:59Z", age_h: 25, fresh_h: 60, took_s: 0.2, findings_total: 0, detail: "<b>x</b>", sources: ["NSE"], errors: [] },
    { id: "F5", division: "fundamental", name: "Blind-spot analyst", role: "analyst", does: "d", state: "planned", detail: "Arrives in step 2 of the plan.", sources: ["F1"], errors: [] },
    { id: "S5", division: "sentiment", name: "Headline scorer", role: "analyst", does: "d", state: "ok", items: 73, as_of: "2026-11-16", age_h: 2, fresh_h: 6, findings_total: 2, detail: "", sources: ["S1"], errors: [] }],
  findings_recent: [
    { seen: "2026-11-16", bot: "S5", division: "sentiment", sym: "IDEA", direction: -1, text: "3 headlines lean negative", evidence: [{ src: "Mint", url: "https://x.example/a", quote: "q" }, { src: "Bad", url: "javascript:alert(1)" }] },
    { seen: "2026-11-15", bot: "S5", division: "sentiment", sym: "TCS", direction: 1, text: "lean positive", evidence: [] }],
  scorecard: { S5: { directional: 2, 5: { n: 0, mean_pct: null, ci95_pct: null, right_pct: null, verdict: "too few so far (0 of 20)" } } },
};

test("ages and escaping", () => {
  assert.equal(age(0.4), "under 1 h old"); assert.equal(age(25), "25 h old"); assert.equal(age(557), "23 days old"); assert.equal(age(null), "");
  assert.equal(esc(`<a href="x">'`), "&lt;a href=&quot;x&quot;&gt;&#39;");
});

test("the header counts the states and never claims a blended score", () => {
  const h = headHtml(doc);
  assert.match(h, /2 working/); assert.match(h, /1 planned/); assert.match(h, /nothing here is blended into one score/); assert.match(h, /not investment advice/);
});

test("every division and every bot appears, planned ones marked, text escaped", () => {
  const h = orgHtml(doc);
  for (const id of ["F1", "F5", "S5"]) assert.ok(h.includes(`data-bot="${id}"`), id);
  assert.match(h, /Arrives in step 2/); assert.ok(!h.includes("<b>x</b>")); assert.match(h, /2,007 items/);
});

test("findings filter by division, bot and stock; unsafe links are not linked", () => {
  assert.equal(filterFindings(doc.findings_recent, { sym: "ide" }).length, 1);
  assert.equal(filterFindings(doc.findings_recent, { division: "fundamental" }).length, 0);
  const f = feedHtml(doc, {});
  assert.match(f, /href="https:\/\/x.example\/a"/); assert.ok(!f.includes("javascript:"));
  assert.match(feedHtml(doc, { division: "fundamental" }), /No findings match/);
});

test("one stock across divisions, and the scorecard says when there are too few", () => {
  const s = stockHtml(doc, "idea");
  assert.match(s, /3 headlines lean negative/); assert.match(s, /Nothing found on IDEA/);
  const c = scoreHtml(doc);
  assert.match(c, /too few so far \(0 of 20\)/); assert.match(c, /from the next close/);
  assert.ok(!/\b(buy|sell|target|recommendation|guaranteed)\b/i.test(headHtml(doc) + orgHtml(doc) + c));
});

import { techHtml } from "../../lab.js";
test("the strategy desk panel says which money rule applies, lists every active strategy, and shows the market states", () => {
  assert.equal(techHtml(doc), "");
  const st = (c, w) => ({ cagr_pct: c, worst_fall_pct: w, sharpe: 0.9, from: "2010-07-08", to: "2026-11-13" });
  const d = { ...doc, bots: [...doc.bots,
    { id: "T3", detail: "Today: up trend, high volatility.", data: { state: "up trend, high volatility" } },
    { id: "T4", data: { mode: "blend", explain: "The selector did not beat the blend, so the live account follows the blend.", live: ["mad_l200_s21"], tried: 52, go_live: "2026-11-18", holdout_from: "2024-11-13", blend_orders: 4,
      result: { selector: { whole: st(12.5, -58.5) }, blend: { whole: st(17.5, -56.9) }, nifty50: { whole: st(10.3, -38.4) } },
      candidates: [{ id: "mad_l200_s21", family: "Moving-average distance", rule: "hold the 10 stocks whose 21-day average is furthest above their 200-day average (monthly)", origin: "research grid", born: "2010-01-04", p_skill: 0.539, live: true, whole: st(28.7, -62.9), holdout: st(20.3, -20), positions: [["TCS", 3, 3000, "2026-10-01"]], orders: [["enter", "INFY"]] },
                   { id: "rsi_x", family: "RSI bounce", rule: "in when RSI(14) closes back above 30", origin: "AI scout: A paper", born: "2026-11-17", p_skill: null, live: false, whole: null, holdout: null, positions: [], orders: [] }],
      retired: [{ id: "rsi_hi55_k10_lo30", retired: "2011-06-01" }],
      states: { "NIFTY 50": { "up trend, high volatility": { days: 473, yearly_pct: 57.8 } }, "mad_l200_s21": { "down trend, high volatility": { days: 435, yearly_pct: -30.1 } } } } },
    { id: "T6", detail: "Read 40 new finance abstracts; 0 rules proposed.", data: { runs: [{ date: "2026-11-17", read: 40, proposed: [] }] } }] };
  const h = techHtml(d);
  for (const w of ["follows the blend of all active strategies", "Self-evolving selector (top 3)", "All active strategies, equal money", "NIFTY 50 held", "<b>live</b> · Moving-average distance",
                   "54%", "not yet", "AI scout: A paper", "in INFY", "TCS", "up trend, high volatility (today)", "+57.80%", "rsi_hi55_k10_lo30 (2011-06-01)", "AI paper scout:", "Companies listed today only"]) assert.ok(h.includes(w), w);
  assert.ok(!/\b(buy|sell|target|recommendation|guaranteed)\b/i.test(h.replace(/<[^>]+>/g, " ")));
});

import { macroHtml } from "../../lab.js";
test("the Macro panel lists every series with its lateness, today's factors and their tested outcome", () => {
  assert.equal(macroHtml(doc), "");
  const d = { ...doc, bots: [...doc.bots,
    { id: "M1", data: { series: [{ name: "RBI policy repo rate", unit: "%", value: 5.5, date: "2026-11-17", freq: "daily snapshot", source: "RBI", late: false },
      { name: "India CPI", unit: "", value: 198, date: "2025-12-01", freq: "monthly", source: "MOSPI", late: true, why_late: "the MOSPI API stops at December 2025", extra: "inflation 1.33% a year" }] } },
    { id: "M4", detail: "0 finding(s) filed.", data: { today: { oil: "flat" }, outcomes: { "NIFTY 50 63": { all_pct: 2.57, by: { oil: { flat: { n: 588, mean_pct: 2.03, diff_pct: -0.54, ci95_pct: [-3.39, 2.31], verdict: "no measurable difference" } } } } },
      strategies: { oil: { flat: { momentum: { n: 400, mean_pct: 1.1, ci95_pct: [0.2, 2.0], verdict: "measurably better than the average stock" } } } } } }] };
  const h = macroHtml(d);
  assert.match(h, /RBI policy repo rate/); assert.match(h, /5\.5%/); assert.match(h, /lab-pill st-stale">late/); assert.match(h, /stops at December 2025/);
  assert.match(h, /<b>flat<\/b>/); assert.match(h, /flat: \+2\.03% \(-0\.54%/); assert.match(h, /class="up">\+1\.10%/);
  assert.ok(!/\b(buy|sell|target|recommendation|guaranteed)\b/i.test(h));
});

import { sentimentHtml } from "../../lab.js";
test("the Sentiment panel shows the AI readings and the event history; unsafe links are not linked", () => {
  assert.equal(sentimentHtml(doc), "");
  const d = { ...doc, bots: [...doc.bots,
    { id: "S6", detail: "30 new headlines read.", data: { recent: [{ title: "Power Grid approves Rs 220 crore line", url: "https://x.example/pg", src: "ET", region: "IN", effect: "positive", confidence: "high", event: "capex or expansion", companies: ["Power Grid"], sectors: ["Power"], why: "investment expands assets" },
      { title: "Bad link", url: "javascript:alert(1)", region: "US", effect: "none", confidence: "low", event: "other", companies: [], sectors: [], why: "" }] } },
    { id: "S7", detail: "History spans 135 days.", data: { history: { from: "2026-07-04", to: "2026-11-16" }, study: { "Acquisition": { reaction: { n: 40, months: 4, mean_pct: 1.2, ci95_pct: [-0.5, 2.9], verdict: "too few months (4 of 12)" }, "21": { n: 40, months: 4, mean_pct: 4.49, ci95_pct: [0.1, 8.9], verdict: "too few months (4 of 12)" } } } } }] };
  const h = sentimentHtml(d);
  assert.match(h, /href="https:\/\/x\.example\/pg"/); assert.ok(!h.includes("javascript:"));
  assert.match(h, /class="up">positive/); assert.match(h, /Acquisition/); assert.match(h, /class="mut">\+4\.49%/); assert.match(h, /40 events, 4 months/);
  assert.ok(!/\b(buy|sell|target|recommendation|guaranteed)\b/i.test(h.replace(/<[^>]+>/g, " ")));   // visible text only: an <a target> attribute is not wording
});
