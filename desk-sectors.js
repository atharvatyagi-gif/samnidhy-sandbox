/* SECTORS: a "Dependency map" for the selected sector, inside the existing detail card. It is closed until opened, and the supply-chain file is fetched only then.
   It shows the strongest disclosed links between two companies of the sector, which other sectors (or unlisted / unnamed parties) the sector's companies are linked to
   with the shares added up (confidence weighted by share), and an honest coverage line: how many of the sector's companies have a disclosed link at all.
   Every link was read from a filing with a verified quote; a share is a share of the supplier's revenue or of the customer's purchases, never mixed.
   Association, not proof of cause. ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. */
import { sectorDeps, shareText } from "./desk-deps.js";

let ctx = null, graph = null, loading = null;
const open = new Set();
const files = () => ctx.S.deskMan || {};
const pct = v => (v * 100).toFixed(0) + "%";

export function init(c) { ctx = c; }

async function ensure() {
  if (graph !== null || !files().graph) return;
  loading = loading || ctx.getJSON("supply_graph.json", false).then(j => { graph = j; }).catch(() => { graph = false; }).finally(() => { loading = null; });
  await loading;
}
const members = k => ctx.S.uni.stocks.filter(s => s.ind === k && s.n500).map(s => s.s);

function bodyHtml(k) {
  const { esc } = ctx;
  if (!files().graph) return '<p class="mut">The supply-chain data has not been published yet.</p>';
  if (graph === false) return '<p class="mut">The supply-chain data could not be loaded. Try again in a minute.</p>';
  if (!graph) return open.has(k) ? '<p class="mut">Loading the disclosed links…</p>' : '<p class="mut">Open to load the disclosed supply-chain links.</p>';
  const r = sectorDeps(graph, k, members(k));
  const edgeRows = r.inside.map(e => `<tr><td>${esc(e.s)}</td><td>→</td><td>${esc(e.d)}</td><td>${esc(shareText(e))}</td><td class="r">${(e.conf ?? 0).toFixed(2)}</td><td>${esc(e.per || "—")}</td><td><button class="lnk" data-nexus="edge:${esc(e.id)}">evidence</button></td></tr>`).join("");
  const crossRows = r.cross.map(c => `<tr><td>${esc(c.sector)}</td><td class="r">${c.edges}</td><td class="r">${c.stated ? pct(c.share) + ` <span class="mut">(${c.stated} stated)</span>` : '<span class="mut">no share stated</span>'}</td><td class="r">${c.conf.toFixed(2)}</td></tr>`).join("");
  return `<p>Disclosed links for <b>${r.covered}</b> of <b>${r.total}</b> companies in this sector. <span class="mut">${r.read} of them have had their filings read; the graph covers ${graph.coverage.companies_done} of ${graph.coverage.companies_total.toLocaleString("en-IN")} listed companies so far.</span></p>
    <div class="sec-t">Strongest links between two companies of this sector</div>
    ${edgeRows ? `<div class="tablecard"><table class="tbl sm"><thead><tr><th>Supplier</th><th></th><th>Customer</th><th>Share</th><th class="r">Conf</th><th>Period</th><th><span class="sr">Evidence</span></th></tr></thead><tbody>${edgeRows}</tbody></table></div>` : '<p class="mut">None disclosed in the filings read so far.</p>'}
    <div class="sec-t">Linked to other sectors</div>
    ${crossRows ? `<div class="tablecard"><table class="tbl sm"><thead><tr><th>Counterparty sector</th><th class="r">Links</th><th class="r">Shares added up</th><th class="r">Conf (share-weighted)</th></tr></thead><tbody>${crossRows}</tbody></table></div>` : '<p class="mut">None disclosed in the filings read so far.</p>'}
    <p><button class="btn-line sm" data-nexus="company:${esc(r.top || "")}" ${r.top ? "" : "disabled"}>${r.top ? `Open the graph for ${esc(r.top)}` : "No graph to open yet"}</button></p>
    <p class="mut">Counterparties that are not listed companies, or are not named in the filing, are grouped as "Unlisted or unnamed". Association, not proof of cause.</p>`;
}
/* the markup that goes at the end of the sector's detail card */
export function shell(k) {
  const { esc } = ctx;
  return `<details class="sec-dep" data-k="${esc(k)}"${open.has(k) ? " open" : ""}><summary>Dependency map · disclosed supply-chain links</summary><div class="sec-dep-body" id="sec-dep-body">${bodyHtml(k)}</div></details>`;
}
/* after the detail card has been (re)drawn */
export function bind(k) {
  const d = ctx.$("#sec-detail .sec-dep"); if (!d) return;
  const paint = () => { const b = ctx.$("#sec-dep-body"); if (b && b.closest(".sec-dep").dataset.k === k) b.innerHTML = bodyHtml(k); };
  d.addEventListener("toggle", () => { if (d.open) { open.add(k); paint(); ensure().then(paint); } else open.delete(k); });
  if (open.has(k)) ensure().then(paint);
}
