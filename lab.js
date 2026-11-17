/* B-Lab research desk dashboard (lab.html, linked from no menu). Reads blab/status.json (scripts/blab/run.py).
   Pure render functions are exported for tests/js/lab.test.mjs; the page boots only in a browser. */

export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = u => /^https?:\/\//i.test(String(u || "")) ? String(u) : null;
export const STATE = { ok: "Working", stale: "Stale source", error: "Error", planned: "Planned", no_key: "Needs free key", limit: "Free limit reached" };

export function age(h) {
  if (h == null) return "";
  if (h < 1) return "under 1 h old";
  if (h < 48) return `${Math.round(h)} h old`;
  return `${Math.round(h / 24)} days old`;
}

export function istTime(utc) {
  if (!utc) return "";
  const d = new Date(utc); if (isNaN(d)) return esc(utc);
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) + " IST";
}

export function headHtml(doc) {
  const n = s => doc.bots.filter(b => b.state === s).length;
  return `<p class="lab-kick">B-Lab research desk · experimental · not investment advice</p>
    <h1>How the research bots are working</h1>
    <p class="note">Updated ${esc(istTime(doc.generated_utc))}. ${doc.bots.length} bots in ${doc.divisions.length} divisions, split by where their information comes from, so nothing overlaps and nothing is left out.
      Each division reports its own evidence; nothing here is blended into one score.</p>
    <div class="lab-tally" role="list">${[["ok", n("ok")], ["stale", n("stale")], ["error", n("error")], ["no_key", n("no_key")], ["limit", n("limit")], ["planned", n("planned")]]
      .filter(([s, c]) => c || s === "ok" || s === "planned").map(([s, c]) => `<span role="listitem" class="lab-pill st-${s}">${c} ${esc(STATE[s].toLowerCase())}</span>`).join("")}
      <span role="listitem" class="lab-pill">${doc.findings_total} findings in the ledger${doc.findings_added ? ` (${doc.findings_added} new this run)` : ""}</span></div>`;
}

export function botCard(b) {
  const live = b.state !== "planned";
  return `<article class="lab-bot st-${esc(b.state)}" data-bot="${esc(b.id)}">
    <header><b>${esc(b.id)} · ${esc(b.name)}</b><span class="lab-pill st-${esc(b.state)}">${esc(STATE[b.state] || b.state)}</span></header>
    <p class="lab-role">${esc(b.role)} · ${esc(b.does)}</p>
    ${live ? `<p class="lab-meta">${b.items != null ? `<span>${Number(b.items).toLocaleString("en-IN")} items</span>` : ""}${b.as_of ? `<span>source ${esc(String(b.as_of).slice(0, 10))}, ${esc(age(b.age_h))} (limit ${esc(age(b.fresh_h))})</span>` : ""}${b.took_s != null ? `<span>ran in ${b.took_s} s</span>` : ""}${b.findings_total ? `<span>${b.findings_total} findings</span>` : ""}</p>` : ""}
    <p class="note">${esc(b.detail)}</p>
    ${b.wraps ? `<p class="note">Reports on: ${esc(b.wraps)}</p>` : ""}
    <p class="note">Sources: ${esc((b.sources || []).join(", "))}</p>
    ${b.errors && b.errors.length ? `<details><summary>${b.errors.length} error(s)</summary><ul>${b.errors.map(e => `<li>${esc(e)}</li>`).join("")}</ul></details>` : ""}
  </article>`;
}

export function orgHtml(doc) {
  return `<div class="lab-org">${doc.divisions.map(d => `<section class="lab-div" aria-label="${esc(d.name)} division">
    <h3>${esc(d.name)}</h3><p class="note">Source: ${esc(d.source)}. ${d.ok} working, ${d.stale} stale, ${d.error} errors, ${d.planned} planned.</p>
    ${doc.bots.filter(b => b.division === d.id).map(botCard).join("")}</section>`).join("")}</div>`;
}

export function filterFindings(list, f = {}) {
  const q = (f.sym || "").trim().toUpperCase();
  return list.filter(x => (!f.division || x.division === f.division) && (!f.bot || x.bot === f.bot) && (!q || (x.sym || "").toUpperCase().includes(q)));
}

const dir = d => d === 1 ? '<span class="up">positive</span>' : d === -1 ? '<span class="down">negative</span>' : '<span class="mut">none</span>';
const evid = f => (f.evidence || []).slice(0, 3).map(e => { const u = safeUrl(e.url); return u ? `<a href="${esc(u)}" rel="noopener noreferrer" target="_blank" title="${esc(e.quote)}">${esc(e.src || "source")}</a>` : esc(e.src || ""); }).join(", ");

export function feedHtml(doc, f = {}) {
  const rows = filterFindings(doc.findings_recent || [], f);
  if (!rows.length) return `<p class="note">No findings match. Most bots are scouts that collect data; findings come from analysts, and most analysts arrive in later steps.</p>`;
  return `<div class="lab-scroll" tabindex="0" role="region" aria-label="Findings"><table class="lab-tbl"><thead><tr><th>Seen</th><th>Bot</th><th>Stock</th><th>Lean</th><th>What was found</th><th>Evidence</th></tr></thead>
    <tbody>${rows.slice(0, 300).map(x => `<tr><td>${esc(x.seen)}</td><td>${esc(x.bot)}</td><td class="sym">${esc(x.sym || x.scope || "")}</td><td>${dir(x.direction)}</td><td>${esc(x.text)}</td><td>${evid(x)}</td></tr>`).join("")}</tbody></table></div>`;
}

/* "One stock, every division": any NSE stock can be looked up (sx.names); the 500 the bots cover get a full card (sx.cards)
   with what each division holds on them, findings or not. Without sx (an older status), findings only. */
export function resolveStock(q, sx) {
  const v = (q || "").trim();
  if (!v) return null;
  const up = v.toUpperCase().split(" · ")[0].trim();
  const names = (sx && sx.names) || [];
  const bySym = names.find(n => n[0] === up);
  if (bySym) return bySym;
  const lo = v.toLowerCase();
  const byName = names.filter(n => (n[1] || "").toLowerCase() === lo || (n[1] || "").toLowerCase().startsWith(lo));
  return byName.length === 1 ? byName[0] : names.length ? null : [up, "", true];
}

const findList = xs => xs && xs.length ? xs.map(x => `<p>${dir(x.dir)} · ${esc(x.text)} <span class="mut">(${esc(x.bot)}, ${esc(x.seen)})</span></p>`).join("") : "";
const none = what => `<p class="note">${esc(what)}</p>`;

export function stockHtml(doc, sym, sx) {
  const v = (sym || "").trim();
  if (!v) return `<p class="note">Type a symbol or a company name. Every NSE main-board stock can be looked up; the 500 most-traded, which the bots cover, get a card from every division.</p>`;
  if (!sx) {
    const s = v.toUpperCase();
    const mine = (doc.findings_recent || []).filter(x => (x.sym || "").toUpperCase() === s);
    return `<div class="lab-org">${doc.divisions.map(d => { const xs = mine.filter(x => x.division === d.id);
      return `<section class="lab-div" aria-label="${esc(d.name)} on ${esc(s)}"><h3>${esc(d.name)}</h3>${xs.length ? xs.map(x => `<p>${dir(x.direction)} · ${esc(x.text)} <span class="mut">(${esc(x.bot)}, ${esc(x.seen)})</span></p>`).join("") : `<p class="note">Nothing found on ${esc(s)} in the last 45 days.</p>`}</section>`; }).join("")}</div>`;
  }
  const hit = resolveStock(v, sx);
  if (!hit) return `<p class="note">No NSE main-board stock matches "${esc(v)}". Try the symbol (e.g. TCS) or the start of the company name, and pick from the suggestions.</p>`;
  const [s, name] = hit, c = (sx.cards || {})[s];
  const head = `<p class="note"><b>${esc(s)}</b>${name ? ` · ${esc(name)}` : ""}</p>`;
  if (!c) return head + `<p class="note">${esc(s)} is listed on NSE but is outside the 500 most-traded stocks the research bots cover, so no division has collected anything on it yet.</p>`;
  const F = c.fundamental || {}, T = c.technical || {}, S = c.sentiment || {}, p = F.promoter;
  const by = id => (doc.bots || []).find(b => b.id === id) || {};
  const ser = ((by("M1").data || {}).series || []), m4 = (by("M4").data || {}).today || {};
  const val = id => { const r = ser.find(x => x.id === id); return r && r.value != null ? `${r.unit === "Rs" ? "Rs " : ""}${r.value}${r.unit === "%" ? "%" : ""}` : "not measured"; };
  const fund = (p ? `<p>Promoters hold <b>${esc(p.pct)}%</b> (quarter to ${esc(p.quarter)})${p.chg_1y != null ? `, <span class="${p.chg_1y < 0 ? "down" : p.chg_1y > 0 ? "up" : "mut"}">${p.chg_1y > 0 ? "+" : ""}${esc(p.chg_1y)} points</span> in a year` : ""}; public ${esc(p.public ?? "not measured")}%.</p>` : none("Shareholding not collected yet."))
    + (F.governance_n ? `<p>${F.governance_n} governance announcement(s) in 90 days:</p><ul class="lab-ul">${F.governance.map(g => `<li>${esc(g[0])} · ${esc(g[1])}</li>`).join("")}</ul>` : none("No governance announcements in the last 90 days."))
    + (F.sast_n ? `<p>${F.sast_n} takeover-code disclosure(s) in 90 days:</p><ul class="lab-ul">${F.sast.map(x => `<li>${esc(x[0])} · ${esc(x[1])} by ${esc(x[2])} (holds ${esc(x[3])}% after)</li>`).join("")}</ul>` : "")
    + (findList(F.findings) || none("No red flag."));
  const tech = (T.picks && T.picks.length ? `<p>A current pick of: <b>${esc(T.picks.join(", "))}</b> (strategy lab).</p>` : none("Not among the strategy lab's current picks."))
    + (T.deals_n ? `<p>${T.deals_n} bulk or block deal(s) in 30 days:</p><ul class="lab-ul">${T.deals.map(x => `<li>${esc(x[0])} · ${esc(x[1])} ${esc((x[2] || "").toLowerCase())} by ${esc(x[3])}, ${Number(x[4] || 0).toLocaleString("en-IN")} shares at Rs ${esc(x[5])}</li>`).join("")}</ul>` : none("No bulk or block deals in 30 days."))
    + findList(T.findings);
  const macro = `<p>Market-wide, the same for every stock: repo ${esc(val("repo"))}, India 10-year ${esc(val("INDIRLTLT01STM"))}, the rupee at ${esc(val("inr_usd"))} per US dollar.</p>`
    + (Object.keys(m4).length ? `<p>Today: ${Object.entries(m4).map(([f, l]) => `${esc(f)} <b>${esc(l || "not measured")}</b>`).join(", ")}.</p>` : "");
  const sent = (S.ai && S.ai.length ? `<p>AI news readings naming it:</p><ul class="lab-ul">${S.ai.map(r => { const u = safeUrl(r.url); return `<li>${esc(r.date)} · <span class="${r.effect === "positive" ? "up" : r.effect === "negative" ? "down" : "mut"}">${esc(r.effect)}</span> (${esc(r.confidence)}) · ${u ? `<a href="${esc(u)}" rel="noopener noreferrer" target="_blank">${esc(r.title)}</a>` : esc(r.title)}</li>`; }).join("")}</ul>` : none("No AI news reading names it yet."))
    + (S.announcements && S.announcements.length ? `<p>Its announcements in 30 days, and what that kind historically led to (next 21 sessions vs NIFTY 500):</p><ul class="lab-ul">${S.announcements.map(a => `<li>${esc(a[0])} · ${esc(a[1])}${a[2] ? ` · ${esc(pc2(a[2].mean_pct))} (${esc(a[2].verdict)})` : ""}</li>`).join("")}</ul>` : none("No company announcements in 30 days."))
    + findList(S.findings);
  const col = (n, body) => `<section class="lab-div" aria-label="${esc(n)} on ${esc(s)}"><h3>${esc(n)}</h3>${body}</section>`;
  return head + `<div class="lab-org">${col("Fundamental", fund)}${col("Technical", tech)}${col("Macro", macro)}${col("Sentiment", sent)}</div>`;
}

export function scoreHtml(doc) {
  const H = doc.horizons || [5, 20, 63], ids = Object.keys(doc.scorecard || {});
  const note = `<p class="note">Each finding with a lean is checked later: the stock's change after it was seen (from the next close, so nothing is looked up in advance) minus the NIFTY 500's over the same days, counted in the finding's direction. A verdict needs at least ${doc.min_scored} scored findings and a 95% range clear of zero. The same bot, stock and lean count once per ${doc.repeat_days} days.</p>`;
  if (!ids.length) return note + `<p class="note">${esc(doc.scorecard_note || "No bot has a finding with a lean yet.")}</p>`;
  const cell = c => !c ? "" : `${c.n} scored${c.mean_pct != null ? ` · ${c.mean_pct > 0 ? "+" : ""}${c.mean_pct}%` : ""}${c.ci95_pct ? ` (${c.ci95_pct[0]} to ${c.ci95_pct[1]})` : ""}<br><small>${esc(c.verdict)}</small>`;
  return note + (doc.scorecard_note ? `<p class="note">${esc(doc.scorecard_note)}</p>` : "") + `<div class="lab-scroll" tabindex="0" role="region" aria-label="Scorecards"><table class="lab-tbl"><thead><tr><th>Bot</th><th>Findings with a lean</th>${H.map(h => `<th>After ${h} sessions</th>`).join("")}</tr></thead>
    <tbody>${ids.map(id => `<tr><td>${esc(id)}</td><td>${doc.scorecard[id].directional}</td>${H.map(h => `<td>${cell(doc.scorecard[id][String(h)])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const STATES = ["up trend, low volatility", "up trend, normal volatility", "up trend, high volatility", "down trend, low volatility", "down trend, normal volatility", "down trend, high volatility"];
const pc2 = v => v == null ? "" : `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;

/* The Technical division's own evidence: today's state, the strategy-by-state record, the analog days. "" when not published. */
export function techHtml(doc) {
  const by = id => (doc.bots || []).find(b => b.id === id) || {};
  const T3 = by("T3"), T4 = by("T4"), T5 = by("T5");
  const rec = T4.data && T4.data.record, today = (T4.data && T4.data.today_state) || (T3.data && T3.data.state), an = T5.data && T5.data.analogs;
  if (!rec && !an) return "";
  let h = `<p class="note">Today's market state: <b>${esc(today || "not measured")}</b>. ${esc(T3.detail || "")}</p>`;
  if (rec) {
    const strats = [...new Set(Object.values(rec).flatMap(x => Object.keys(x)))];
    const cell = c => !c ? "" : `<span class="${/better/.test(c.verdict) ? "up" : /worse/.test(c.verdict) ? "down" : "mut"}">${esc(pc2(c.mean_pct))}</span><br><small>${c.ci95_pct ? esc(`${pc2(c.ci95_pct[0])} to ${pc2(c.ci95_pct[1])}`) : ""} · ${c.n}</small>`;
    h += `<div class="lab-scroll" tabindex="0" role="region" aria-label="Strategy lab by market state"><table class="lab-tbl"><caption class="note">Strategy lab: each strategy's best 10% against the average stock over the next 21 sessions, after a 0.4% cost, by the market state on the day it picked (range, start days). Green or red only when the range is clear of zero.</caption>
      <thead><tr><th>Strategy</th>${STATES.map(s => `<th${s === today ? ' class="lab-now"' : ""}>${esc(s)}${s === today ? " (today)" : ""}</th>`).join("")}</tr></thead>
      <tbody>${strats.map(k => `<tr><td>${esc(k)}</td>${STATES.map(s => `<td${s === today ? ' class="lab-now"' : ""}>${cell((rec[s] || {})[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  if (an && an.days) {
    h += `<p class="note">${esc(T5.detail || "")}</p><div class="lab-scroll" tabindex="0" role="region" aria-label="Analog days"><table class="lab-tbl"><thead><tr><th>Past day most like today</th><th>Distance</th><th>NIFTY 50, next 21 sessions</th><th>next 63</th><th>Bank Nifty, next 21</th></tr></thead>
      <tbody>${an.days.map(x => `<tr><td>${esc(x.date)}</td><td>${esc(x.distance)}</td><td class="${x.n50_21 > 0 ? "up" : "down"}">${esc(pc2(x.n50_21))}</td><td class="${x.n50_63 > 0 ? "up" : "down"}">${esc(pc2(x.n50_63))}</td><td>${esc(x.bank_21 == null ? "not measured" : pc2(x.bank_21))}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Compared on: ${esc((an.features || []).join(", "))}.</p>`;
  }
  return h;
}

/* The Macro division's own evidence: every series (value, date, source, late or not), today's factor levels and what NIFTY 50
   and the strategies did next on such days. "" when not published. */
export function macroHtml(doc) {
  const by = id => (doc.bots || []).find(b => b.id === id) || {};
  const series = ["M1", "M2", "M3"].flatMap(id => ((by(id).data || {}).series || []).map(s => ({ ...s, bot: id })));
  const M4 = (by("M4").data || {});
  if (!series.length && !M4.today) return "";
  let h = "";
  if (series.length) h += `<div class="lab-scroll" tabindex="0" role="region" aria-label="Macro series"><table class="lab-tbl"><caption class="note">Every macro series the scouts collect. US series are used only for their effect on Indian markets.</caption>
    <thead><tr><th>Series</th><th>Latest</th><th>Dated</th><th>Source</th><th>On time?</th></tr></thead>
    <tbody>${series.map(s => `<tr><td>${esc(s.name)}</td><td>${s.value == null ? "not measured" : esc(`${s.unit === "Rs" ? "Rs " : ""}${s.value}${s.unit === "%" ? "%" : ""}`)}${s.extra ? `<br><small>${esc(s.extra)}</small>` : ""}</td><td>${esc(s.date || "")} <small>(${esc(s.freq)})</small></td><td>${esc(s.source)}</td>
      <td>${s.late ? `<span class="lab-pill st-stale">late</span>${s.why_late ? `<br><small>${esc(s.why_late)}</small>` : ""}` : '<span class="lab-pill st-ok">on time</span>'}</td></tr>`).join("")}</tbody></table></div>`;
  const o = (M4.outcomes || {})["NIFTY 50 63"];
  if (M4.today && o) {
    h += `<div class="lab-scroll" tabindex="0" role="region" aria-label="Macro factors"><table class="lab-tbl"><caption class="note">Six macro factors since 2007, each value counted from the day it was published. NIFTY 50 over the next 63 sessions: on all days ${esc(pc2(o.all_pct))} on average; by level below (difference from all days, 95% range, start days). Green or red only when the range is clear of zero.</caption>
      <thead><tr><th>Factor</th><th>Today</th><th>NIFTY 50 next 63 sessions, by level</th></tr></thead>
      <tbody>${Object.entries(M4.today).map(([f, lev]) => `<tr><td>${esc(f)}</td><td><b>${esc(lev || "not measured")}</b></td><td>${Object.entries((o.by || {})[f] || {}).map(([l, c]) =>
        `<span class="${/better/.test(c.verdict) ? "up" : /worse/.test(c.verdict) ? "down" : "mut"}">${l === lev ? "<b>" : ""}${esc(l)}: ${esc(pc2(c.mean_pct))} (${esc(pc2(c.diff_pct))}${c.ci95_pct ? esc(`, ${pc2(c.ci95_pct[0])} to ${pc2(c.ci95_pct[1])}`) : ""}, ${c.n})${l === lev ? "</b>" : ""}</span>`).join("<br>")}</td></tr>`).join("")}</tbody></table></div>`;
    const st = M4.strategies || {};
    const strats = [...new Set(Object.values(st).flatMap(x => Object.values(x).flatMap(y => Object.keys(y))))];
    if (strats.length) h += `<div class="lab-scroll" tabindex="0" role="region" aria-label="Strategies under today's macro"><table class="lab-tbl"><caption class="note">The Technical division's six strategies against the average stock over 21 sessions after costs, on past days with the same level as today for each factor.</caption>
      <thead><tr><th>Strategy</th>${Object.entries(M4.today).map(([f, l]) => `<th>${esc(f)}: ${esc(l || "-")}</th>`).join("")}</tr></thead>
      <tbody>${strats.map(k => `<tr><td>${esc(k)}</td>${Object.entries(M4.today).map(([f, l]) => { const c = ((st[f] || {})[l] || {})[k];
        return `<td>${c ? `<span class="${/better/.test(c.verdict) ? "up" : /worse/.test(c.verdict) ? "down" : "mut"}">${esc(pc2(c.mean_pct))}</span><br><small>${c.ci95_pct ? esc(`${pc2(c.ci95_pct[0])} to ${pc2(c.ci95_pct[1])}`) : ""} · ${c.n}</small>` : ""}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>`;
    h += `<p class="note">${esc(by("M4").detail || "")}</p>`;
  }
  return h;
}

/* The Sentiment division's own evidence: the AI analyst's latest readings and the event historian's table. "" when not published. */
export function sentimentHtml(doc) {
  const by = id => (doc.bots || []).find(b => b.id === id) || {};
  const S6 = by("S6"), S7 = by("S7");
  const recent = (S6.data || {}).recent || [], study = (S7.data || {}).study || {}, hist = (S7.data || {}).history || {};
  if (!recent.length && !Object.keys(study).length) return "";
  const cls = e => e === "positive" ? "up" : e === "negative" ? "down" : "mut";
  let h = "";
  if (recent.length) h += `<p class="note">${esc(S6.detail || "")}</p><div class="lab-scroll" tabindex="0" role="region" aria-label="AI news readings"><table class="lab-tbl"><caption class="note">The AI analyst's latest readings (a free model). Findings come only from "high" confidence readings; the scorecard checks them later.</caption>
    <thead><tr><th>Headline</th><th>From</th><th>Effect on Indian stocks</th><th>Event</th><th>Companies, sectors</th><th>Why</th></tr></thead>
    <tbody>${recent.slice(0, 25).map(r => { const u = safeUrl(r.url); return `<tr><td>${u ? `<a href="${esc(u)}" rel="noopener noreferrer" target="_blank">${esc(r.title)}</a>` : esc(r.title)}<br><small>${esc(r.src || "")}</small></td><td>${esc(r.region === "US" ? "US" : "India")}</td>
      <td><span class="${cls(r.effect)}">${esc(r.effect)}</span><br><small>${esc(r.confidence)} confidence</small></td><td>${esc(r.event)}</td><td>${esc([...(r.companies || []), ...(r.sectors || [])].join(", ") || "-")}</td><td>${esc(r.why)}</td></tr>`; }).join("")}</tbody></table></div>`;
  const cats = Object.entries(study).sort((a, b) => ((b[1]["21"] || {}).n || 0) - ((a[1]["21"] || {}).n || 0));
  if (cats.length) {
    const cell = c => !c ? "" : `<span class="${/above/.test(c.verdict) ? "up" : /below/.test(c.verdict) ? "down" : "mut"}">${esc(pc2(c.mean_pct))}</span><br><small>${c.ci95_pct ? esc(`${pc2(c.ci95_pct[0])} to ${pc2(c.ci95_pct[1])}`) : ""} · ${c.n} events, ${c.months || "?"} months</small>`;
    h += `<p class="note">${esc(S7.detail || "")}</p><div class="lab-scroll" tabindex="0" role="region" aria-label="Event history"><table class="lab-tbl"><caption class="note">Event historian: the 500 stocks against NIFTY 500 after each kind of NSE announcement, ${esc(hist.from || "")} to ${esc(hist.to || "")}. Reaction: the close before the day to the first close after it. Then 5 and 21 sessions from that close. The range uses monthly averages; green or red only when it is clear of zero with 12+ months.</caption>
      <thead><tr><th>Announcement</th><th>Reaction</th><th>Next 5 sessions</th><th>Next 21 sessions</th></tr></thead>
      <tbody>${cats.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${cell(v.reaction)}</td><td>${cell(v["5"])}</td><td>${cell(v["21"])}</td></tr>`).join("")}</tbody></table></div>`;
  }
  return h;
}

export function filtersHtml(doc) {
  return `<div class="lab-filters"><label>Division <select id="lab-div"><option value="">All</option>${doc.divisions.map(d => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("")}</select></label>
    <label>Bot <select id="lab-bot"><option value="">All</option>${doc.bots.filter(b => b.role === "analyst" || b.findings_total).map(b => `<option value="${esc(b.id)}">${esc(b.id)} · ${esc(b.name)}</option>`).join("")}</select></label>
    <label>Stock <input id="lab-sym" type="search" autocomplete="off" spellcheck="false" placeholder="e.g. TCS"></label></div>`;
}

async function boot() {
  const root = document.getElementById("lab");
  let doc;
  try { const r = await fetch("blab/status.json", { cache: "no-store" }); if (!r.ok) throw new Error(r.status); doc = await r.json(); }
  catch (e) { root.innerHTML = `<p class="note">The research desk has not published yet (blab/status.json is missing). It runs every evening after the daily update.</p>`; return; }
  root.innerHTML = `<header class="lab-head">${headHtml(doc)}</header>
    <h2 class="sec-t">Divisions and bots</h2>${orgHtml(doc)}
    ${techHtml(doc) ? `<h2 class="sec-t">Technical: market state, strategies, analogs</h2>${techHtml(doc)}` : ""}
    ${macroHtml(doc) ? `<h2 class="sec-t">Macro: India and US inputs, tested on Indian markets</h2>${macroHtml(doc)}` : ""}
    ${sentimentHtml(doc) ? `<h2 class="sec-t">Sentiment: AI news readings and event history</h2>${sentimentHtml(doc)}` : ""}
    <h2 class="sec-t">Findings</h2>${filtersHtml(doc)}<div id="lab-feed"></div>
    <h2 class="sec-t">One stock, every division</h2><div class="lab-filters"><label>Stock <input id="lab-one" type="search" autocomplete="off" spellcheck="false" placeholder="symbol or company name, e.g. TCS" list="lab-stocks"></label><datalist id="lab-stocks"></datalist></div><div id="lab-stock">${stockHtml(doc, "", {})}</div>
    <h2 class="sec-t">Scorecards</h2>${scoreHtml(doc)}
    <p class="note lab-foot">${esc(doc.note)} Plan: docs/blab/PLAN.md in the repository.</p>`;
  const f = () => ({ division: document.getElementById("lab-div").value, bot: document.getElementById("lab-bot").value, sym: document.getElementById("lab-sym").value });
  const paint = () => { document.getElementById("lab-feed").innerHTML = feedHtml(doc, f()); };
  ["lab-div", "lab-bot", "lab-sym"].forEach(id => document.getElementById(id).addEventListener("input", paint));
  let sx = null;                                                // every stock's card (blab/stocks.json), loaded once
  const emb = document.getElementById("blab-stocks");
  const loadSx = () => sx ? Promise.resolve(sx) : (emb ? Promise.resolve(JSON.parse(emb.textContent)) : fetch("blab/stocks.json", { cache: "no-store" }).then(r => r.ok ? r.json() : null)).catch(() => null)
    .then(j => { sx = j || { names: [], cards: {} }; document.getElementById("lab-stocks").innerHTML = (sx.names || []).map(n => `<option value="${esc(n[0])}">${esc(n[1] || "")}${n[2] ? "" : " (not covered)"}</option>`).join(""); return sx; });
  const one = document.getElementById("lab-one");
  const show = () => loadSx().then(x => { document.getElementById("lab-stock").innerHTML = stockHtml(doc, one.value, x); });
  one.addEventListener("focus", loadSx, { once: true });
  one.addEventListener("input", show); one.addEventListener("change", show);
  paint();
}

if (typeof document !== "undefined" && document.getElementById("lab")) boot();
