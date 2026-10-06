// node --test tests/js/deps.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { sessionFraction, relVol, sweepBadge, shareText, docLabel, lineage, sectorDeps, houseDeps, rankShocks, shockSentence } from "../../desk-deps.js";

const node = (id, k, ind, n) => ({ id, k, ind: ind || null, n: n || id });
const edge = (id, s, d, o = {}) => ({ id, s, d, rel: "supplies", w: null, wb: null, per: "FY2025-26", conf: 0.9, kind: "disclosed", doc: "annual", comp: null, q: "q", url: "u", pg: 1, vq: true, ...o });
const G = () => ({
  cos: { A: {}, B: {}, C: {} },
  nodes: [node("A", "co", "Auto"), node("B", "co", "Auto"), node("C", "co", "Metals"), node("D", "co", "Metals"), node("T", "co", "Power"), node("X", "ext", null, "Steel Mills Ltd"), node("Z", "anon", null, "Unnamed customer")],
  edges: [
    edge("e1", "B", "A", { w: 0.30, wb: "purchases", comp: "Castings" }),
    edge("e2", "C", "A", { w: 0.20, wb: "purchases", conf: 0.8, comp: "Steel" }),
    edge("e3", "D", "A", { w: 0.10, wb: "purchases", conf: 0.7, comp: "steel" }),
    edge("e4", "A", "Z", { w: 0.25, wb: "revenue", conf: 0.6 }),
    edge("e5", "X", "A", { conf: 0.6 }),
    edge("e6", "T", "A", { w: 0.9, wb: "purchases", conf: 0.3 }),                       // below the confidence floor
    edge("e7", "T", "B", { w: 0.9, wb: "purchases", kind: "sector_io", conf: 0.3 }),   // sector-level: never used
    edge("e8", "A", "T", { w: 0.05, wb: "revenue", conf: 0.9 }),
  ],
});

test("session fraction: the straight-line part of 09:15-15:30 IST that has passed", () => {
  const ist = (d, h, m) => Date.UTC(2026, 9, d, h, m) - 5.5 * 3600e3;                 // 5 Oct 2026 is a Monday
  assert.equal(sessionFraction(ist(5, 9, 15 + 75)), 0.2);                              // 75 of 375 minutes
  assert.equal(sessionFraction(ist(5, 9, 16)), 0.04);                                  // floored so the first minutes do not blow the ratio up
  assert.equal(sessionFraction(ist(5, 15, 29)), 374 / 375);
  assert.equal(sessionFraction(ist(5, 15, 30)), 1);
  assert.equal(sessionFraction(ist(5, 8, 0)), 1);
  assert.equal(sessionFraction(ist(4, 11, 0)), 1);                                     // Sunday: the last full session
  assert.equal(sessionFraction(ist(10, 11, 0)), 1);                                    // Saturday
});

test("relative volume and the sweep badge", () => {
  assert.equal(relVol(2_000_000, 1_000_000, 1), 2);
  assert.equal(relVol(500_000, 1_000_000, 0.25), 2);                                   // half a day's average done in a quarter of the session
  assert.equal(relVol(null, 1e6, 1), null);
  assert.equal(relVol(1e6, 0, 1), null);
  assert.equal(relVol(1e6, null, 1), null);
  assert.equal(relVol(1e6, 1e6, 0), null);
  assert.deepEqual(sweepBadge(48.4), { arrow: "▲", n: 48, cls: "up" });
  assert.deepEqual(sweepBadge(-62), { arrow: "▼", n: 62, cls: "down" });
  assert.equal(sweepBadge(0), null);
  assert.equal(sweepBadge(null), null);
  assert.equal(sweepBadge(undefined), null);
});

test("share wording keeps the two bases apart", () => {
  assert.equal(shareText(edge("x", "a", "b", { w: 0.24, wb: "revenue" })), "24% of the supplier's revenue");
  assert.equal(shareText(edge("x", "a", "b", { w: 0.24, wb: "purchases" })), "24% of the customer's purchases");
  assert.equal(shareText(edge("x", "a", "b")), "no share stated");
  assert.equal(docLabel(edge("x", "a", "b", { doc: "transcript", per: "call 2026-09-01" })), "call 2026-09-01 earnings call");
  assert.equal(docLabel(edge("x", "a", "b", { per: null })), "period not stated annual report");
});

test("lineage: top three each way by share, bottlenecks only where one supplier supplies a component", () => {
  const L = lineage(G(), "A");
  assert.deepEqual(L.suppliers.map(e => e.id), ["e1", "e2", "e3"]);                    // 0.30, 0.20, 0.10; e5 (no share) would be 4th and is cut
  assert.deepEqual(L.customers.map(e => e.id), ["e4", "e8"]);                          // the 0.25 share first
  assert.deepEqual(L.bottlenecks.map(b => b.comp), ["Castings"]);                      // "Steel" has two suppliers: not a bottleneck
  assert.ok(L.any);
  assert.ok(!L.suppliers.some(e => e.id === "e6") && !L.suppliers.some(e => e.id === "e7"), "low-confidence and sector-level links are left out");
  const none = lineage(G(), "NOPE");
  assert.deepEqual([none.customers, none.suppliers, none.bottlenecks, none.any], [[], [], [], false]);
});

test("lineage with a lower floor lets the weak edge in", () => {
  assert.ok(lineage(G(), "A", 0.3).suppliers.some(e => e.id === "e6"));
});

test("sector dependency map: inside edges, counterparty sectors aggregated, coverage", () => {
  const r = sectorDeps(G(), "Auto", ["A", "B", "E"]);
  assert.deepEqual(r.inside.map(e => `${e.s}>${e.d}`), ["B>A"]);
  const m = Object.fromEntries(r.cross.map(c => [c.sector, c]));
  assert.equal(m.Metals.edges, 2);
  assert.ok(Math.abs(m.Metals.share - 0.30) < 1e-9 && m.Metals.stated === 2);          // C 0.20 + D 0.10
  assert.equal(m["Unlisted or unnamed"].edges, 2);                                      // the anonymous customer and the unlisted supplier
  assert.ok(Math.abs(m["Unlisted or unnamed"].share - 0.25) < 1e-9 && m["Unlisted or unnamed"].stated === 1);
  assert.equal(m.Power.edges, 1);                                                       // only the confident, non-sector-level link counts
  assert.deepEqual(r.cross.map(c => c.sector), ["Metals", "Unlisted or unnamed", "Power"]);    // by aggregated share
  assert.ok(Math.abs(m.Metals.conf - (0.8 * 0.2 + 0.7 * 0.1) / 0.3) < 1e-9);          // confidence weighted by share
  assert.equal(r.total, 3);
  assert.equal(r.covered, 2);                                                           // A and B have disclosed links, E none
  assert.equal(r.read, 2);                                                              // A and B were read (graph.cos), E was not
  assert.equal(r.top, "A");
});

test("a sector nobody in the graph belongs to", () => {
  const r = sectorDeps(G(), "Textiles", ["Q", "R"]);
  assert.deepEqual([r.inside, r.cross, r.covered, r.total, r.read, r.top], [[], [], 0, 2, 0, null]);
});

test("business group: inter-company links, external concentration with rupee amounts only where the basis allows", () => {
  const g = G();
  g.edges.push(edge("e9", "A", "X", { w: 0.10, wb: "revenue", conf: 0.8 }));         // A also sells to the unlisted X: 10% of A's revenue
  g.edges.push(edge("e10", "B", "X", { w: 0.50, wb: "purchases", conf: 0.8 }));      // 50% of X's purchases: cannot become rupees
  g.edges.push(edge("e11", "A", "B", { rel: "related_party", conf: 0.4 }));         // a related-party row stays visible although its confidence is low
  const r = houseDeps(g, ["A", "B"], { A: 1e12, B: 4e11 });
  assert.deepEqual(r.inter.map(e => e.id).sort(), ["e1", "e11"]);
  const cust = Object.fromEntries(r.customers.map(c => [c.id, c]));
  assert.ok(Math.abs(cust.Z.amount - 0.25e12) < 1 && cust.Z.convertible === 1 && !cust.Z.partial);   // 25% of A's revenue
  assert.ok(Math.abs(cust.X.amount - 0.10e12) < 1 && cust.X.partial && cust.X.edges === 2);          // only A's link converts: partial
  assert.equal(cust.X.maxShare, 0.5);
  assert.deepEqual(cust.X.members.sort(), ["A", "B"]);
  const sup = Object.fromEntries(r.suppliers.map(c => [c.id, c]));
  assert.equal(sup.C.amount, 0);                                                         // a share of A's purchases: never turned into rupees
  assert.equal(sup.C.maxShare, 0.2);
  assert.ok(!sup.A && !sup.B, "a member is not its own external supplier");
  assert.equal(r.cover.members, 2);
  assert.equal(r.cover.read, 2);
  assert.ok(r.cover.linked >= 2);
  assert.ok(r.customers[0].amount >= r.customers[r.customers.length - 1].amount);
});

test("business group with no revenue known: shares only, no invented rupees", () => {
  const r = houseDeps(G(), ["A"], {});
  assert.ok(r.customers.every(c => c.amount === 0 && c.convertible === 0));
  assert.equal(r.customers.find(c => c.id === "Z").maxShare, 0.25);
});

const SHOCKS = [
  { focal: "A", cp: "B", rel: "supplies", w: 0.30, conf: 0.9, z: -2.0, edge: "e1", cp_ret: -0.04, focal_ret: -0.01 },
  { focal: "A", cp: "C", rel: "supplies", w: 0.20, conf: 0.8, z: -1.6, edge: "e2", cp_ret: -0.10, focal_ret: -0.01 },
  { focal: "A", cp: "T", rel: "supplies", w: 0.90, conf: 0.3, z: -3.0, edge: "e6", cp_ret: -0.20, focal_ret: 0 },
  { focal: "A", cp: "Q", rel: "supplies", w: 0.90, conf: 0.9, z: -3.0, edge: "gone", cp_ret: -0.20, focal_ret: 0 },
];

test("shocks: ordered by share x the counterparty's move today; low confidence and unknown edges dropped; stored closes flagged", () => {
  const live = { B: -6.0, A: -3.2 };                                                   // C has no live quote: its stored close (-10%) is used
  const r = rankShocks(SHOCKS, G().edges, s => live[s] ?? null);
  assert.deepEqual(r.map(x => x.edge), ["e2", "e1"]);                                  // 0.20 x 10.0 = 2.0 beats 0.30 x 6.0 = 1.8
  assert.equal(r[0].stored, true);
  assert.equal(r[0].cpMove, -10);
  assert.equal(r[0].focalMove, -3.2);
  assert.equal(r[1].stored, false);
  assert.ok(Math.abs(r[1].key - 1.8) < 1e-9);
  assert.deepEqual(rankShocks([], G().edges, () => null), []);
  assert.deepEqual(rankShocks(null, null, null), []);
});

test("shock sentence: who moved, the share, the filing, and that it is association", () => {
  const live = { B: -6.0, A: -3.2 };
  const [e2, e1] = rankShocks(SHOCKS, G().edges, s => live[s] ?? null);
  assert.equal(shockSentence(e1), "Supplier B −6.0% today · A −3.2% · B is 30% of A's purchases (FY2025-26 annual report, conf 0.9) — association, not proof of cause");
  assert.ok(shockSentence(e2).endsWith("— association, not proof of cause · move shown is the last close, not live"));
  const cust = rankShocks([{ focal: "A", cp: "Z", rel: "supplies", w: 0.25, conf: 0.6, z: 2, edge: "e4", cp_ret: 0.03, focal_ret: 0 }], G().edges, () => null)[0];
  assert.match(shockSentence(cust), /^Customer Z \+3\.0% today · A 0\.0% · Z is 25% of A's revenue \(FY2025-26 annual report, conf 0\.6\)/);
  const noShare = rankShocks([{ focal: "A", cp: "X", rel: "supplies", w: null, conf: 0.6, z: 2, edge: "e5", cp_ret: 0.02, focal_ret: 0 }], G().edges, () => null)[0];
  assert.match(shockSentence(noShare), /X is linked to A \(no share stated\)/);
  for (const w of ["buy", "sell", "target", "recommend", "guarantee"]) assert.ok(!new RegExp(`\\b${w}`, "i").test(shockSentence(e1)));
});

test("the real supply graph runs through every function without surprises", () => {
  const g = JSON.parse(readFileSync(new URL("../../data/supply_graph.json", import.meta.url), "utf8"));
  const cos = g.nodes.filter(n => n.k === "co");
  assert.ok(cos.length > 5);
  for (const n of cos) {
    const L = lineage(g, n.id);
    assert.ok(L.customers.length <= 3 && L.suppliers.length <= 3);
    assert.ok(L.customers.every(e => e.s === n.id) && L.suppliers.every(e => e.d === n.id));
  }
  const sectors = [...new Set(cos.map(n => n.ind).filter(Boolean))];
  for (const s of sectors) {
    const members = cos.filter(n => n.ind === s).map(n => n.id), r = sectorDeps(g, s, members);
    assert.ok(r.inside.length <= 10 && r.cross.length <= 10 && r.covered <= r.total && r.read <= r.total);
    const byId = new Map(g.nodes.map(n => [n.id, n]));
    assert.ok(r.inside.every(e => byId.get(e.s).ind === s && byId.get(e.d).ind === s));
  }
  const h = houseDeps(g, cos.slice(0, 4).map(n => n.id), {});
  assert.ok(h.customers.length <= 5 && h.suppliers.length <= 5 && h.cover.members === 4);
});

/* ---------- coverage states and the "N of M" number ---------- */
import { coverageState, listedDependencyStocks } from "../../desk-deps.js";
const NOW = Date.parse("2026-10-06T00:00:00Z");

test("every company gets one honest coverage state", () => {
  const g = { cos: {
    OK: { at: "2026-09-01T00:00:00Z", edges: 3, fac: 1, notes: ["annual: 100 pages"] },
    NONE: { at: "2026-09-01T00:00:00Z", edges: 0, fac: 0, notes: ["annual: 120 pages, 6 relevant, 2 sent"] },
    GONE: { at: "2026-09-01T00:00:00Z", edges: 0, fac: 0, notes: ["no filing found"] },
    SCAN: { at: "2026-09-01T00:00:00Z", edges: 0, fac: 0, notes: ["annual: no readable text"] },
    OLD: { at: "2024-01-01T00:00:00Z", edges: 2, fac: 0, notes: [] },
  } };
  assert.equal(coverageState(g, "MISSING", NOW).code, "not_processed");
  assert.equal(coverageState(g, "GONE", NOW).code, "filing_unavailable");
  assert.equal(coverageState(g, "SCAN", NOW).code, "unreadable");
  assert.equal(coverageState(g, "OLD", NOW).code, "stale");
  assert.equal(coverageState(g, "NONE", NOW).code, "read_none");
  assert.equal(coverageState(g, "OK", NOW).code, "read");
  assert.match(coverageState(g, "OK", NOW).label, /3 dependencies/);
  assert.equal(coverageState(null, "X", NOW).code, "not_processed");
});

test("the synthetic graph: only listed-to-listed edges with a share count, attributed to the node the share measures", () => {
  const g = JSON.parse(readFileSync(new URL("../fixtures/synthetic_graph.json", import.meta.url), "utf8"));
  const L = listedDependencyStocks(g);
  assert.equal(L.edges, 2);                                         // s3 has an unlisted end
  assert.deepEqual([...L.focal].sort(), ["CUSB", "SUPA"]);           // s1: SUPA's revenue share (SUPA depends on CUSB); s2: CUSB's purchases share (CUSB depends on SUPA)
  assert.equal(listedDependencyStocks({ nodes: [], edges: [] }).focal.size, 0);
});

test("the shock table on the synthetic graph is ranked by share x the counterparty's move", () => {
  const g = JSON.parse(readFileSync(new URL("../fixtures/synthetic_graph.json", import.meta.url), "utf8"));
  const shocks = [{ focal: "SUPA", cp: "CUSB", rel: "supplies", w: 0.30, conf: 0.9, dr: -6, edge: "s1", cp_ret: -0.06, focal_ret: -0.01 },
                  { focal: "CUSB", cp: "SUPA", rel: "supplies", w: 0.20, conf: 0.8, dr: 4, edge: "s2", cp_ret: 0.04, focal_ret: 0.0 }];
  const rows = rankShocks(shocks, g.edges, () => null);
  assert.deepEqual(rows.map(r => r.edge), ["s1", "s2"]);
  assert.match(shockSentence(rows[0]), /association, not proof of cause/);
});
