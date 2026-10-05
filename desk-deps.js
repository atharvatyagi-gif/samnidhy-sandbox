/* Pure logic for the Movers, Sectors and Houses views: supply lineage of a stock, the dependency map of a sector, a business group's inter-company and external
   dependencies, supply-chain shocks, relative volume and the sweep badge. No DOM and no network, so every rule is unit-tested (tests/js/deps.test.mjs).
   Honesty rules built in: only disclosed, source-quoted edges are used; a share is a share of the SUPPLIER's revenue or of the CUSTOMER's purchases and is never
   mixed; where a figure cannot be worked out it is left out and the row says why; wording is "linked move" and "association, not proof of cause". */

const MIN_CONF = 0.5;
const UNLISTED = "Unlisted or unnamed";

/* ---------- Movers: relative volume and the sweep badge ---------- */

/* share of the NSE session (09:15-15:30 IST, 375 minutes) that has passed, as a fraction. Outside the session, or on a weekend, the volume shown is a full
   session's, so 1. Never below 4% so the first minutes do not blow the ratio up. */
export function sessionFraction(nowMs = Date.now()) {
  const ist = new Date(nowMs + 5.5 * 3600e3), dow = ist.getUTCDay(), m = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  if (dow === 0 || dow === 6 || m < 9 * 60 + 15 || m >= 15 * 60 + 30) return 1;
  return Math.max(0.04, (m - (9 * 60 + 15)) / 375);
}
/* today's volume over the 20-day average volume, pro-rated by the part of the session gone (a straight line: approximate). null when either number is missing. */
export function relVol(volume, avgv20, frac = 1) {
  if (volume == null || !(avgv20 > 0) || !(frac > 0)) return null;
  return volume / (avgv20 * frac);
}
export function sweepBadge(score) {
  if (score == null || !isFinite(score) || score === 0) return null;
  return { arrow: score > 0 ? "▲" : "▼", n: Math.abs(Math.round(score)), cls: score > 0 ? "up" : "down" };
}

/* ---------- edges ---------- */
const listed = n => n && n.k === "co";
export const nodeMap = graph => (graph._n || (graph._n = new Map((graph.nodes || []).map(n => [n.id, n]))));
const usable = (e, min) => e.kind !== "sector_io" && (e.conf ?? 0) >= min;
const byStrength = (a, b) => (b.w || 0) - (a.w || 0) || (b.conf || 0) - (a.conf || 0) || String(a.id).localeCompare(String(b.id));

export function shareText(e) {
  if (e.w == null) return "no share stated";
  return `${Math.round(e.w * 100)}% of the ${e.wb === "revenue" ? "supplier's revenue" : "customer's purchases"}`;
}
export function docLabel(e) {
  return `${e.per || "period not stated"} ${e.doc === "annual" ? "annual report" : "earnings call"}`;
}

/* ---------- a stock's supply lineage (Movers row expansion) ---------- */
export function lineage(graph, sym, min = MIN_CONF) {
  const es = (graph.edges || []).filter(e => usable(e, min) && (e.s === sym || e.d === sym));
  const customers = es.filter(e => e.s === sym && e.d !== sym).sort(byStrength).slice(0, 3);
  const suppliers = es.filter(e => e.d === sym && e.s !== sym).sort(byStrength).slice(0, 3);
  const byComp = new Map();
  for (const e of es.filter(x => x.d === sym && x.comp)) {
    const k = e.comp.trim().toLowerCase();
    if (!byComp.has(k)) byComp.set(k, { comp: e.comp.trim(), from: new Map() });
    byComp.get(k).from.set(e.s, e);
  }
  const bottlenecks = [...byComp.values()].filter(c => c.from.size === 1).map(c => ({ comp: c.comp, edge: [...c.from.values()][0] }));
  return { customers, suppliers, bottlenecks, any: es.length > 0 };
}

/* ---------- a sector's dependency map (Sectors view) ---------- */
/* members: symbols of the sector's companies in the universe. -> { inside: top edges between two companies of the sector, cross: counterparty sectors with
   edges aggregated (share-weighted confidence), covered: companies with a disclosed edge, total: companies in the sector, read: companies whose filings were read } */
export function sectorDeps(graph, sector, members, min = MIN_CONF) {
  const N = nodeMap(graph), inSec = id => { const n = N.get(id); return listed(n) && n.ind === sector; };
  const es = (graph.edges || []).filter(e => usable(e, min));
  const inside = es.filter(e => inSec(e.s) && inSec(e.d)).sort(byStrength).slice(0, 10);
  const agg = new Map();
  for (const e of es) {
    const a = inSec(e.s), b = inSec(e.d);
    if (a === b) continue;                                                           // inside (both) or unrelated (neither)
    const other = N.get(a ? e.d : e.s), label = listed(other) ? (other.ind || "Sector not known") : UNLISTED;
    const g = agg.get(label) || { sector: label, edges: 0, stated: 0, share: 0, wsum: 0, csum: 0 };
    const w = e.w ?? 0.05;                                                           // an unstated share still counts a little in the weighted confidence
    g.edges++; if (e.w != null) { g.stated++; g.share += e.w; } g.wsum += w; g.csum += (e.conf ?? 0) * w;
    agg.set(label, g);
  }
  const cross = [...agg.values()].map(g => ({ sector: g.sector, edges: g.edges, stated: g.stated, share: g.share, conf: g.csum / g.wsum }))
    .sort((a, b) => b.share - a.share || b.edges - a.edges || a.sector.localeCompare(b.sector)).slice(0, 10);
  const set = new Set(members), touched = new Map();
  for (const e of es) for (const id of [e.s, e.d]) if (set.has(id)) touched.set(id, (touched.get(id) || 0) + 1);
  const read = members.filter(s => graph.cos && graph.cos[s]).length;
  const top = [...touched.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
  return { inside, cross, covered: touched.size, total: members.length, read, top: top ? top[0] : null };
}

/* ---------- a business group's dependencies (Houses row expansion) ---------- */
/* members: symbols; rev: { SYM: revenue in rupees } where known. Inter-subsidiary links are edges with both ends in the group; external concentration aggregates the
   group's links to companies outside it. The amount is the sum of (share x the member's revenue), and ONLY for links whose share is of the member's revenue (a share
   of someone else's purchases cannot be turned into rupees); otherwise the largest single share is shown and labelled. */
export function houseDeps(graph, members, rev = {}, min = MIN_CONF) {
  const M = new Set(members), N = nodeMap(graph), es = (graph.edges || []).filter(e => usable(e, min) || e.rel === "related_party");
  const inter = es.filter(e => M.has(e.s) && M.has(e.d) && e.s !== e.d).sort(byStrength);
  const side = (isMemberEnd, otherEnd) => {
    const g = new Map();
    for (const e of es) {
      if (!isMemberEnd(e) || M.has(otherEnd(e))) continue;
      const id = otherEnd(e), n = N.get(id), r = g.get(id) || { id, name: (n && n.n) || id, kind: n ? n.k : "ext", edges: 0, members: new Set(), amount: 0, convertible: 0, maxShare: null, maxEdge: null };
      r.edges++; r.members.add(isMemberEnd(e) === 1 ? e.s : e.d);
      const mem = M.has(e.s) ? e.s : e.d;
      if (M.has(e.s) && e.wb === "revenue" && e.w != null && rev[mem] != null) { r.amount += e.w * rev[mem]; r.convertible++; }
      if (e.w != null && (r.maxShare == null || e.w > r.maxShare)) { r.maxShare = e.w; r.maxEdge = e; }
      g.set(id, r);
    }
    return [...g.values()].map(r => ({ ...r, members: [...r.members], partial: r.convertible > 0 && r.convertible < r.edges }))
      .sort((a, b) => b.amount - a.amount || (b.maxShare || 0) - (a.maxShare || 0) || b.edges - a.edges || a.id.localeCompare(b.id)).slice(0, 5);
  };
  const customers = side(e => M.has(e.s) ? 1 : 0, e => e.d), suppliers = side(e => M.has(e.d) ? 2 : 0, e => e.s);
  const read = members.filter(s => graph.cos && graph.cos[s]).length;
  const linked = new Set(es.flatMap(e => [e.s, e.d]).filter(id => M.has(id))).size;
  return { inter, customers, suppliers, cover: { members: members.length, read, linked } };
}

/* ---------- supply-chain shocks (Movers view) ---------- */
const pctNum = v => v == null || !isFinite(v) ? null : v;
/* shocks: rows of shocks.json { focal, cp, rel, w, conf, z, edge, cp_ret, focal_ret } (returns as fractions, as of the last close). liveMove(sym) -> % today or null.
   Only edges at or above the confidence floor; ordered by share x |the counterparty's move today|, falling back to the stored close-to-close move when there is no live
   quote (those rows are flagged `stored`). */
export function rankShocks(shocks, edges, liveMove, min = MIN_CONF) {
  const E = new Map((edges || []).map(e => [e.id, e]));
  const rows = [];
  for (const s of shocks || []) {
    const e = E.get(s.edge);
    if (!e || (e.conf ?? s.conf ?? 0) < min) continue;
    const lc = pctNum(liveMove && liveMove(s.cp)), lf = pctNum(liveMove && liveMove(s.focal));
    const cpMove = lc != null ? lc : s.cp_ret != null ? s.cp_ret * 100 : null, focalMove = lf != null ? lf : s.focal_ret != null ? s.focal_ret * 100 : null;
    rows.push({ ...s, edgeRow: e, cpMove, focalMove, stored: lc == null || lf == null, key: (s.w || 0) * Math.abs(cpMove ?? 0) });
  }
  return rows.sort((a, b) => b.key - a.key || (b.w || 0) - (a.w || 0) || a.edge.localeCompare(b.edge));
}
const sgn = v => v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
/* one honest sentence: who moved, the linked stock's move, how much of what it is, from which filing, and that this is association. */
export function shockSentence(row) {
  const e = row.edgeRow, supplier = e.d === row.focal, role = supplier ? "Supplier" : "Customer", noun = supplier ? "purchases" : "revenue";
  const part = e.w == null ? `${row.cp} is linked to ${row.focal} (no share stated)` : `${row.cp} is ${Math.round(e.w * 100)}% of ${row.focal}'s ${noun}`;
  return `${role} ${row.cp} ${sgn(row.cpMove)} today · ${row.focal} ${sgn(row.focalMove)} · ${part} (${docLabel(e)}, conf ${(e.conf ?? 0).toFixed(1)}) — association, not proof of cause${row.stored ? " · move shown is the last close, not live" : ""}`;
}
