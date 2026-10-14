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

/* ---------------- Predicted links (data/nexus_predict, scripts/nexus_predict.py) ----------------
   Model estimates, never facts: every row says "Predicted, not confirmed", lists the evidence it rests on, and the panel
   shows the model's fair test result. The site serves them as pl/index.json (summary + test) and pl/<A-Z or 0>.json. */
export const PRED_LABEL = "Predicted, not confirmed";
export const predShard = sym => { const c = String(sym || "").charAt(0).toUpperCase(); return c >= "A" && c <= "Z" ? c : "0"; };
const pct1 = v => (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%";
const KIND_LABEL = { filings: "Named in a filing", price: "Shares move together", business: "Businesses fit", group: "Same business group" };
export const kindLabel = k => KIND_LABEL[k] || k;

/* The model's test in one sentence (the fair number: without the filing evidence, which is where the confirmed links came from). */
export function predTestLine(idx) {
  const t = idx && idx.test && idx.test.without_filings;
  if (!t || t.hit10 == null) return null;
  return `In a fair test that hid ${idx.coverage ? idx.coverage.confirmed_listed_links + " " : ""}confirmed links, the real partner was in a company's top 10 here ${pct1(t.hit10)} of the time (by chance: ${pct1(t.random_hit10)}).`;
}

/* One prediction -> plain reasons a first-time reader can check, the best filing sentence, and the rival flag. */
export function predReasons(row, sym, names) {
  const ev = row.ev || {}, other = row.p, out = [];
  const nm = s => String((names && names.get && names.get(s)) || s).replace(/\s+(Limited|Ltd\.?)$/i, "");
  for (const n of ev.named || []) {
    const whom = n.by === sym ? other : sym, where = [n.kind === "annual" ? "annual report" : "filing", n.per, n.pg && n.pg.length ? "page " + n.pg[0] : null].filter(Boolean).join(", ");
    out.push(`${nm(n.by)} names ${nm(whom)} in its ${where}${n.sup ? ", in a sentence about supply, customers or orders" : ""}.`);
  }
  if (ev.corr != null && row.kinds.includes("price")) {
    const lead = ev.lead && ev.lead.v != null ? ` ${nm(ev.lead.first)} has tended to move a week earlier (${ev.lead.v.toFixed(2)}).` : "";
    out.push(`Over up to 3 years the two shares moved together beyond what the market and their industries explain (correlation ${ev.corr.toFixed(2)}).${lead}`);
  }
  if (ev.words) {
    const a = ev.words[sym] || [], b = ev.words[other] || [];
    if (a.length || b.length) out.push(`Their business descriptions point at each other${a.length ? `: ${nm(sym)} mentions “${a.join(", ")}”` : ""}${b.length ? `${a.length ? ";" : ":"} ${nm(other)} mentions “${b.join(", ")}”` : ""}.`);
  }
  if (ev.group) out.push(`Both belong to the ${ev.group}.`);
  const good = n => n.q && n.q.replace(/[^A-Za-z]/g, "").length >= 40;       // a fragment ("X Limited Associates 14.") says nothing: page and link only
  const q = (ev.named || []).find(n => good(n) && n.sup) || (ev.named || []).find(good) || null;
  const src = (ev.named || []).find(n => n.url) || null;
  return {
    sym: other, name: row.n || nm(other), rank: row.rank, kinds: row.kinds || [], reasons: out,
    quote: q ? { text: q.q, by: q.by, url: q.url || null, pg: q.pg && q.pg[0], per: q.per || null } : null,
    source: src ? src.url : null,
    rival: !!ev.same_ind, industry: ev.ind ? ev.ind[1] : null,
  };
}

/* A company's predicted links from its shard, best first. */
export function predList(shard, sym, names, max = 10) {
  const rows = (shard && shard.cos && shard.cos[sym]) || [];
  return rows.slice(0, max).map(r => predReasons(r, sym, names));
}
