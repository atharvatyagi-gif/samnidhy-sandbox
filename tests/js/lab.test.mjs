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
