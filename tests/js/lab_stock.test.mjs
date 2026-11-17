// node --test tests/js   The "One stock, every division" search (lab.js): every stock can be looked up, covered ones get a card.
import test from "node:test";
import assert from "node:assert/strict";
import { resolveStock, stockHtml } from "../../lab.js";

const sx = {
  names: [["TCS", "Tata Consultancy Services Limited", true], ["TATAMOTORS", "Tata Motors Limited", true], ["20MICRONS", "20 Microns Limited", false], ["INFY", "Infosys Limited", true]],
  cards: {
    TCS: { fundamental: { promoter: { quarter: "2026-09-30", pct: 71.77, chg_1y: -0.3, public: 28.2 }, governance: [], governance_n: 0, sast: [], sast_n: 0, findings: [] },
           technical: { picks: [], deals: [], deals_n: 0, findings: [] },
           sentiment: { ai: [{ date: "2026-11-16", title: "TCS wins deal", url: "https://n.example/t", effect: "positive", confidence: "high" }], announcements: [["2026-11-12", "Press Release", { mean_pct: 3.09, verdict: "too few months (4 of 12)" }]], findings: [] } },
    TATAMOTORS: { fundamental: {}, technical: { picks: ["momentum"], deals: [["2026-11-13", "bulk", "BUY", "A FUND", 1000, 650]], deals_n: 1, findings: [] }, sentiment: {} },
    INFY: { fundamental: { findings: [{ seen: "2026-11-16", bot: "F5", kind: "debt jump", dir: -1, text: "Total debt rose 60%" }] }, technical: {}, sentiment: {} } },
};
const doc = { divisions: [], bots: [{ id: "M1", data: { series: [{ id: "repo", unit: "%", value: 5.5 }] } }, { id: "M4", data: { today: { oil: "flat" } } }] };

test("a stock is found by symbol, by the start of its name, or not at all", () => {
  assert.deepEqual(resolveStock("tcs", sx), ["TCS", "Tata Consultancy Services Limited", true]);
  assert.deepEqual(resolveStock("Infosys", sx), ["INFY", "Infosys Limited", true]);
  assert.equal(resolveStock("Tata", sx), null);                                   // two companies start with "Tata": pick from the suggestions
  assert.equal(resolveStock("ZZZZ", sx), null);
});

test("a covered stock with no findings still gets a card from all four divisions", () => {
  const h = stockHtml(doc, "TCS", sx);
  for (const w of ["Fundamental", "Technical", "Macro", "Sentiment", "Promoters hold <b>71.77%</b>", "-0.3 points", "Not among the strategy lab", "No bulk or block deals", "repo 5.5%", "oil <b>flat</b>", "TCS wins deal", "Press Release", "No red flag."]) assert.ok(h.includes(w), w);
  assert.match(stockHtml(doc, "TATAMOTORS", sx), /A current pick of: <b>momentum<\/b>/);
  assert.match(stockHtml(doc, "INFY", sx), /Total debt rose 60%/);
});

test("a listed stock outside the 500 says so, and an unknown one says how to search", () => {
  assert.match(stockHtml(doc, "20MICRONS", sx), /outside the 500 most-traded stocks the research bots cover/);
  assert.match(stockHtml(doc, "ZZZZ", sx), /No NSE main-board stock matches/);
  assert.match(stockHtml(doc, "", sx), /Every NSE main-board stock can be looked up/);
});
