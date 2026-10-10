/* Indices tab: every Indian index (NSE's 167 from its end-of-day file, SENSEX / BSE 100 / BSE 500 and Bitcoin from Yahoo) in one table,
   grouped like NSE groups them; click an index for its daily chart. Data: t/x/index.json and t/x/d/<key>.json (scripts/indices_eod.py).
   Every number is read from a file; an index with no free source says "not available". Educational analysis only, not investment advice. */
import { esc, inr } from "./desk-aladin2.js";
import { lineChart } from "./desk-signals.js";

let ctx = null, root = null, X = null, failed = false;
const st = { g: "All", q: "", sel: null, rg: "1Y" };
const cache = {};
export function init(c) { ctx = c; }

const sgn = (v, d = 2) => v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(d) + "%";
const cls = v => v == null ? "" : v >= 0 ? "up" : "down";
const RANGES = { "1M": 31, "6M": 183, "1Y": 366, "3Y": 1096, "5Y": 1830, All: 1e6 };

/* rows the table shows: group filter, then a case-insensitive search on the name (pure, tests/js/indices.test.mjs) */
export function filterRows(doc, g = "All", q = "") {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return ((doc && doc.indices) || []).filter(r => (g === "All" || r.group === g) && words.every(w => r.name.toLowerCase().includes(w)));
}
/* the candles inside a range, counted back from the last date */
export function sliceRange(d, rg) {
  if (!d || !d.length) return [];
  const last = Date.parse(d[d.length - 1][0] + "T00:00:00Z"), from = last - (RANGES[rg] || 366) * 864e5;
  return d.filter(r => Date.parse(r[0] + "T00:00:00Z") >= from);
}
/* where today's level sits in the 52-week range, 0..1 */
/* axis labels that fit: lakh for very large rupee amounts (Bitcoin in INR) */
export const axisFmt = v => v >= 1e5 ? inr(v / 1e5, 1) + " L" : inr(v, v >= 1000 ? 0 : 2);
export const rangePos = r => r.hi52 > r.lo52 ? Math.max(0, Math.min(1, (r.last - r.lo52) / (r.hi52 - r.lo52))) : null;

async function load() {
  if (X || failed) return;
  try { X = await ctx.getJSON("t/x/index.json", false); } catch (e) { failed = true; }
}
async function candles(key) {
  if (cache[key] !== undefined) return cache[key];
  try { cache[key] = (await ctx.getJSON(`t/x/d/${key}.json`, false)).d; } catch (e) { cache[key] = null; }
  return cache[key];
}
function shell() {
  const counts = {}; for (const r of X.indices) if (r.key) counts[r.group] = (counts[r.group] || 0) + 1;
  const chip = (g, n) => `<button type="button" class="sg-chip ${st.g === g ? "on" : ""}" data-g="${esc(g)}" aria-pressed="${st.g === g}">${esc(g)}${n != null ? ` <i>${n}</i>` : ""}</button>`;
  const when = X.generated_utc ? new Date(X.generated_utc).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) + " IST" : "--";
  return `<div class="page-head"><p class="kick">— Indices · NSE · BSE · crypto</p><h2>Every <span class="acc">Indian index.</span></h2><p class="asof">${X.count} indices · updated ${esc(when)}</p></div>
    <div id="ix-chart"></div>
    <div class="sg-bar"><div class="sg-chips" role="group" aria-label="Index group">${chip("All", X.count)}${X.groups.map(g => chip(g, counts[g] || 0)).join("")}</div>
      <input id="ix-q" type="search" placeholder="Search an index, e.g. bank" aria-label="Search indices" value="${esc(st.q)}"></div>
    <div id="ix-list"></div>
    <p class="note">${esc(X.note || "")}${X.discontinued && X.discontinued.length ? ` Renamed or ended, so not listed: ${X.discontinued.map(x => esc(x.name) + " (last " + esc(x.last_date) + ")").join(", ")}.` : ""}</p>`;
}
function rowHtml(r) {
  if (!r.key) return `<tr class="ix-na"><td class="sg-st"><b>${esc(r.name)}</b><small>${esc(r.group)}</small></td><td class="r sg-nm" colspan="7">${esc(r.missing || "not available")}</td></tr>`;
  const p = rangePos(r), dp = r.group === "Crypto" ? 0 : 2;
  return `<tr tabindex="0" data-k="${esc(r.key)}" class="${st.sel === r.key ? "on" : ""}"><td class="sg-st"><b>${esc(r.name)}</b><small>${esc(r.group)} · ${esc(r.as_of)}</small></td>
    <td class="r"><b>${inr(r.last, dp)}</b><small class="${cls(r.pct)}">${sgn(r.pct)}</small></td><td class="r ${cls(r.r1m)}">${sgn(r.r1m, 1)}</td><td class="r ${cls(r.r1y)}">${sgn(r.r1y, 1)}</td>
    <td class="ix-rg">${p == null ? "--" : `<span class="ix-bar" role="img" aria-label="52-week range ${inr(r.lo52, dp)} to ${inr(r.hi52, dp)}, now at ${Math.round(p * 100)}%"><i style="left:${(p * 100).toFixed(0)}%"></i></span><small>${inr(r.lo52, 0)} – ${inr(r.hi52, 0)}</small>`}</td>
    <td class="r">${r.pe ?? "--"}</td><td class="r">${r.pb ?? "--"}</td><td class="r">${r.dy != null ? r.dy + "%" : "--"}</td></tr>`;
}
function paintList() {
  const el = root.querySelector("#ix-list"), rows = filterRows(X, st.g, st.q); if (!el) return;
  el.innerHTML = rows.length ? `<div class="sg-tablewrap"><table class="sg-table ix-table"><thead><tr><th>Index</th><th class="r">Last · day</th><th class="r">1 month</th><th class="r">1 year</th><th>52-week range</th><th class="r">P/E</th><th class="r">P/B</th><th class="r">Yield</th></tr></thead><tbody>${rows.map(rowHtml).join("")}</tbody></table></div>`
    : `<div class="sg-empty"><b>Nothing found.</b><span>No index matches that search.</span></div>`;
  el.querySelectorAll("tr[data-k]").forEach(tr => { tr.onclick = () => open(tr.dataset.k); tr.onkeydown = e => { if (e.key === "Enter") open(tr.dataset.k); }; });
}
async function paintChart() {
  const el = root.querySelector("#ix-chart"); if (!el) return;
  const r = st.sel && X.indices.find(x => x.key === st.sel); if (!r) { el.innerHTML = ""; return; }
  const d = await candles(r.key), pts = sliceRange(d, st.rg).filter(c => c[4] != null).map(c => [c[0], c[4]]);
  const first = pts.length ? pts[0][1] : null, last = pts.length ? pts[pts.length - 1][1] : null, ch = first ? (last / first - 1) * 100 : null, dp = r.group === "Crypto" ? 0 : 2;
  const rgs = Object.keys(RANGES).map(k => `<button type="button" class="sg-chip ${st.rg === k ? "on" : ""}" data-rg="${k}" aria-pressed="${st.rg === k}">${k}</button>`).join("");
  el.innerHTML = `<div class="sg-card ix-card"><div class="ix-top"><div><h4>${esc(r.name)}</h4><p class="note">${esc(r.source)} · daily closes from ${esc(r.from)} to ${esc(r.as_of)}</p></div>
      <div class="ix-now"><b>${inr(r.last, dp)}</b><small class="${cls(ch)}">${sgn(ch)} over ${esc(st.rg === "All" ? "all data" : st.rg)}</small></div><button type="button" class="btn-line sm" data-x="close" aria-label="Close the chart">✕</button></div>
    <div class="sg-chips" role="group" aria-label="Chart range">${rgs}</div>
    ${pts.length > 1 ? lineChart([{ name: r.name, pts, cls: "a" }], { h: 240, label: `${r.name} daily close`, fmt: axisFmt }) : '<p class="note">Not enough history for this range.</p>'}</div>`;
  el.querySelectorAll("[data-rg]").forEach(b => b.onclick = () => { st.rg = b.dataset.rg; paintChart(); });
  el.querySelector("[data-x]").onclick = () => { st.sel = null; paintChart(); paintList(); };
}
function open(k) { st.sel = k; paintList(); paintChart(); const el = root.querySelector("#ix-chart"); if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
export async function mount() {
  root = document.getElementById("indices"); if (!root) return;
  if (!X) { root.innerHTML = '<p class="note">Loading…</p>'; await load(); }
  if (!X) { root.innerHTML = '<div class="sg-empty"><b>Indices are not published yet.</b><span>They arrive with the next daily update.</span></div>'; return; }
  root.innerHTML = shell(); paintList(); paintChart();
  root.querySelectorAll("[data-g]").forEach(b => b.onclick = () => { st.g = b.dataset.g; root.querySelectorAll("[data-g]").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); }); paintList(); });
  const q = root.querySelector("#ix-q"); q.oninput = () => { st.q = q.value; paintList(); };
}
export const _test = { set: x => { X = x; }, reset: () => { X = null; failed = false; st.g = "All"; st.q = ""; st.sel = null; } };
