/* Revenue dependency, shared by the terminal (stock details, NEXUS panel) and the stock page of the home search: one reading of dependencies.json
   (scripts/dependency_profile.py) so a company's dependency reads the same everywhere. Pure functions, no DOM, no fetch (tests/js/revdeps.test.mjs). */

export const LEVELS = {
  high: { label: "High", tone: "down", say: "depends heavily on one customer" },
  moderate: { label: "Moderate", tone: "warn", say: "has one customer worth 10% or more of revenue" },
  low: { label: "Low", tone: "up", say: "has no single customer worth 10% of revenue" },
  unknown: { label: "Not disclosed", tone: "mut", say: "has not disclosed customer concentration in the filings read so far" },
};
const P = v => v == null ? "--" : (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%";
const INDIA = /^(india|domestic|within india|in india)$/i;

/* One plain sentence for a first-time reader, e.g. "About 37% of revenue comes from one customer, and 51% from outside India." */
export function plainSentence(p, name = "the company") {
  if (!p) return null;
  const parts = [], who = name + "’s";
  if (p.lvl === "high" || p.lvl === "moderate") parts.push(p.top && p.top.share != null
    ? `About ${P(p.top.share)} of ${who} revenue comes from ${p.top.name ? p.top.name : "one customer"}${p.top.src === "derived" ? " (worked out from its related-party sales)" : ""}`
    : `One customer brings in 10% or more of ${who} revenue`);
  else if (p.lvl === "low") parts.push(`No single customer brings in 10% of ${who} revenue`);
  if (p.abroad != null && p.abroad >= 0.05) parts.push(parts.length ? `${P(p.abroad)} comes from outside India` : `${P(p.abroad)} of ${who} revenue comes from outside India`);
  return parts.length ? parts.join("; ") + "." : null;
}

/* The level, its reason and the evidence, flattened for rendering. */
export function summary(p) {
  if (!p) return { lvl: "unknown", ...LEVELS.unknown, why: "This company's filings have not been read yet.", top: null, abroad: null, geo: [], listed: [] };
  const L = LEVELS[p.lvl] || LEVELS.unknown;
  return { lvl: p.lvl, ...L, why: p.why, top: p.top, abroad: p.abroad, geo: (p.geo && p.geo.rows) || [],
           listed: [...new Set([...(p.listed_customers || []), ...(p.listed_suppliers || [])])], customers: p.customers || [], suppliers: p.suppliers || [],
           major: p.major || { status: "not_found", customers: [] }, read: p.read || {} };
}

/* Revenue by region as segments that add to 100% (India first), for a stacked bar. */
export function geoSegments(rows) {
  const r = (rows || []).filter(x => x && x.share != null && x.share > 0).slice().sort((a, b) => (INDIA.test(b.region.trim()) - INDIA.test(a.region.trim())) || b.share - a.share);
  const tot = r.reduce((t, x) => t + x.share, 0) || 1;
  return r.map(x => ({ region: x.region, share: x.share / tot, home: INDIA.test(x.region.trim()) }));
}

/* The most dependent companies, for a list: high first, then moderate, largest single-customer share first. */
export function mostDependent(doc, n = 30) {
  const rank = { high: 0, moderate: 1 };
  return Object.entries((doc && doc.cos) || {}).filter(([, p]) => p.lvl in rank)
    .sort((a, b) => rank[a[1].lvl] - rank[b[1].lvl] || ((b[1].top && b[1].top.share) || 0.1) - ((a[1].top && a[1].top.share) || 0.1)).slice(0, n)
    .map(([sym, p]) => ({ sym, lvl: p.lvl, share: p.top ? p.top.share : null, name: p.top ? p.top.name : null, abroad: p.abroad, why: p.why }));
}
