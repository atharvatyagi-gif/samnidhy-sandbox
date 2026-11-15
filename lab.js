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

export function stockHtml(doc, sym) {
  const s = (sym || "").trim().toUpperCase();
  if (!s) return `<p class="note">Type a stock symbol to see what each division has found on it, side by side.</p>`;
  const mine = (doc.findings_recent || []).filter(x => (x.sym || "").toUpperCase() === s);
  return `<div class="lab-org">${doc.divisions.map(d => { const xs = mine.filter(x => x.division === d.id);
    return `<section class="lab-div" aria-label="${esc(d.name)} on ${esc(s)}"><h3>${esc(d.name)}</h3>${xs.length ? xs.map(x => `<p>${dir(x.direction)} · ${esc(x.text)} <span class="mut">(${esc(x.bot)}, ${esc(x.seen)})</span></p>`).join("") : `<p class="note">Nothing found on ${esc(s)} in the last 45 days.</p>`}</section>`; }).join("")}</div>`;
}

export function scoreHtml(doc) {
  const H = doc.horizons || [5, 20, 63], ids = Object.keys(doc.scorecard || {});
  const note = `<p class="note">Each finding with a lean is checked later: the stock's change after it was seen (from the next close, so nothing is looked up in advance) minus the NIFTY 500's over the same days, counted in the finding's direction. A verdict needs at least ${doc.min_scored} scored findings and a 95% range clear of zero. The same bot, stock and lean count once per ${doc.repeat_days} days.</p>`;
  if (!ids.length) return note + `<p class="note">${esc(doc.scorecard_note || "No bot has a finding with a lean yet.")}</p>`;
  const cell = c => !c ? "" : `${c.n} scored${c.mean_pct != null ? ` · ${c.mean_pct > 0 ? "+" : ""}${c.mean_pct}%` : ""}${c.ci95_pct ? ` (${c.ci95_pct[0]} to ${c.ci95_pct[1]})` : ""}<br><small>${esc(c.verdict)}</small>`;
  return note + (doc.scorecard_note ? `<p class="note">${esc(doc.scorecard_note)}</p>` : "") + `<div class="lab-scroll" tabindex="0" role="region" aria-label="Scorecards"><table class="lab-tbl"><thead><tr><th>Bot</th><th>Findings with a lean</th>${H.map(h => `<th>After ${h} sessions</th>`).join("")}</tr></thead>
    <tbody>${ids.map(id => `<tr><td>${esc(id)}</td><td>${doc.scorecard[id].directional}</td>${H.map(h => `<td>${cell(doc.scorecard[id][String(h)])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
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
    <h2 class="sec-t">Findings</h2>${filtersHtml(doc)}<div id="lab-feed"></div>
    <h2 class="sec-t">One stock, every division</h2><div class="lab-filters"><label>Stock <input id="lab-one" type="search" autocomplete="off" spellcheck="false" placeholder="e.g. IDEA"></label></div><div id="lab-stock">${stockHtml(doc, "")}</div>
    <h2 class="sec-t">Scorecards</h2>${scoreHtml(doc)}
    <p class="note lab-foot">${esc(doc.note)} Plan: docs/blab/PLAN.md in the repository.</p>`;
  const f = () => ({ division: document.getElementById("lab-div").value, bot: document.getElementById("lab-bot").value, sym: document.getElementById("lab-sym").value });
  const paint = () => { document.getElementById("lab-feed").innerHTML = feedHtml(doc, f()); };
  ["lab-div", "lab-bot", "lab-sym"].forEach(id => document.getElementById(id).addEventListener("input", paint));
  document.getElementById("lab-one").addEventListener("input", e => { document.getElementById("lab-stock").innerHTML = stockHtml(doc, e.target.value); });
  paint();
}

if (typeof document !== "undefined" && document.getElementById("lab")) boot();
