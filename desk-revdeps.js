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
  const exp = p.abroad_src === "BRSR exports";                                       // the BRSR figure is exports as a share of turnover, not revenue earned abroad
  if (p.abroad != null && p.abroad >= 0.05) parts.push(exp ? (parts.length ? `exports are ${P(p.abroad)} of turnover` : `Exports are ${P(p.abroad)} of ${who} turnover`)
    : parts.length ? `${P(p.abroad)} comes from outside India` : `${P(p.abroad)} of ${who} revenue comes from outside India`);
  return parts.length ? parts.join("; ") + "." : null;
}

/* The level, its reason and the evidence, flattened for rendering. */
export function summary(p) {
  if (!p) return { lvl: "unknown", ...LEVELS.unknown, why: "This company's filings have not been read yet.", top: null, abroad: null, geo: [], listed: [] };
  const L = LEVELS[p.lvl] || LEVELS.unknown;
  return { lvl: p.lvl, ...L, why: p.why, top: p.top, abroad: p.abroad, abroad_src: p.abroad_src || null, brsr: p.brsr || null, geo: (p.geo && p.geo.rows) || [],
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

/* A short tag for tables and headers, only where the filings measured a level (an unknown level gets no tag, never a guess).
   -> null | { lvl, tone, text, title } e.g. { text: "97% one customer" } */
export function tag(p, sym = "the company") {
  if (!p || !(p.lvl === "high" || p.lvl === "moderate" || p.lvl === "low")) return null;
  const L = LEVELS[p.lvl], s = p.top && p.top.share;
  const text = p.lvl === "low" ? "no customer ≥10%" : s != null ? `${P(s)} one customer` : "one customer ≥10%";
  return { lvl: p.lvl, tone: L.tone, label: L.label, text, title: plainSentence(p, sym) || `${sym} ${L.say}` };
}

const RX_SPECIAL = /[.*+?^${}()|[\]\\]/g;
const NOISE = /\b(customer|client|party|parties|others?|related|group compan|government|unnamed|segment|domestic|export)s?\b/i;
const clean = n => String(n || "").replace(/\((india|i)\)/ig, "").replace(/\b(limited|ltd|pvt|private|plc|inc|corporation of india)\b\.?/ig, "").replace(/[.,]+$/, "").replace(/\s+/g, " ").trim();

/* An index that finds, in a headline, the companies whose revenue the story touches:
     the company itself, when its own dependency is measured ("HAL: 97% of revenue from Indian Defence Services"), and
     the SUPPLIERS of a customer the headline names ("Indian Defence Services is 97% of HAL's revenue").
   doc = dependencies.json, names = Map(sym -> company name). One alternation regex, so a page of headlines is matched in one pass each. */
export function newsIndex(doc, names) {
  const by = new Map(), put = (k, link) => { if (k.length < 5 || NOISE.test(k) && !link.self) return; const l = by.get(k) || by.set(k, []).get(k); if (!l.some(x => x.sym === link.sym)) l.push(link); };
  const add = (name, link) => { const k = clean(name).toLowerCase(); put(k, link); const short = k.replace(/\s+india$/, ""); if (short !== k && short.includes(" ")) put(short, link); };   // "Maruti Suzuki India" is "Maruti Suzuki" in headlines
  for (const [sym, p] of Object.entries((doc && doc.cos) || {})) {
    const nm = names && names.get(sym), t = tag(p, sym);
    if (t) { const self = { sym, self: true, lvl: t.lvl, tone: t.tone, text: `${sym}: ${t.text}`, title: t.title }; add(nm || sym, self); }
    for (const c of p.customers || []) {                    // news about a customer touches the company that supplies it
      if (c.wb === "cost" || (c.w != null && c.w < 0.05)) continue;
      const who = c.sym ? (names && names.get(c.sym)) || c.sym : c.anon ? null : c.name;
      if (!who) continue;
      const known = c.w != null, link = known
        ? { sym, self: false, lvl: c.w >= 0.25 ? "high" : c.w >= 0.10 ? "moderate" : "low", tone: c.w >= 0.25 ? "down" : "warn", text: `${sym}: ${P(c.w)} of revenue from ${clean(who)}`,
            title: `${clean(who)} brings about ${P(c.w)} of ${sym}’s revenue (${c.per || "period not stated"}), from its filing.` }
        : { sym, self: false, lvl: "link", tone: "mut", text: `${sym} supplies ${clean(who)}`, title: `${sym}’s filing names ${clean(who)} as a customer; the share of revenue is not disclosed.` };
      add(who, link);
    }
    for (const c of p.suppliers || []) {                    // news about a supplier touches the company that sources from it
      const who = c.sym ? (names && names.get(c.sym)) || c.sym : c.anon ? null : c.name;
      if (!who) continue;
      add(who, { sym, self: false, lvl: "link", tone: "mut", text: `${sym} sources from ${clean(who)}`, title: `${sym}’s filing names ${clean(who)} as a supplier${c.w != null ? ` (${P(c.w)} of its ${c.wb || "purchases"})` : "; the share is not disclosed"}.` });
    }
  }
  const keys = [...by.keys()].sort((a, b) => b.length - a.length);
  const alt = keys.map(k => k.replace(RX_SPECIAL, "\\$&")).join("|");
  const re = keys.length ? new RegExp("(?<![\\w&])(" + alt + ")(?![\\w&])", "gi") : null;
  return { re, by, size: keys.length };
}

/* The revenue links a headline touches: tickers already tagged on it first, then names found in its text. Strongest first, one per company. */
export function newsLinks(title, tickers, idx, doc, max = 3) {
  const out = new Map(), put = l => { const o = out.get(l.sym); if (!o || (!o.self && l.self)) out.set(l.sym, l); };
  for (const s of tickers || []) { const t = tag(doc && doc.cos && doc.cos[s], s); if (t) put({ sym: s, self: true, lvl: t.lvl, tone: t.tone, text: `${s}: ${t.text}`, title: t.title }); }
  if (idx && idx.re && title) for (const m of String(title).matchAll(idx.re)) for (const l of idx.by.get(m[1].toLowerCase()) || []) put(l);
  const rank = { high: 0, moderate: 1, low: 2, link: 3 };
  return [...out.values()].sort((a, b) => rank[a.lvl] - rank[b.lvl]).slice(0, max);
}

/* The BRSR part (the company's own sustainability filing): turnover by business activity and the types of customers, for a short block. */
export function brsrLines(p) {
  const b = p && p.brsr; if (!b) return null;
  const mix = (b.mix || []).filter(m => m.share != null && m.share > 0).map(m => ({ d: m.d, share: m.share }));
  return { fy: b.fy || null, mix, cust: b.cust || null, exports: b.exports, pdf: b.pdf || null };
}
