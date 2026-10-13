/* ALADIN: the one front page for signals. Three things on the surface for each stock (the signal, the price goal, the stop); everything else opens when you click a stock:
   how the signal was made, the forecast range and chances, and the revenue dependencies from NEXUS.
   Data (all published nightly, read-only): aladin2/weekly.json (the week's book and the chance table), aladin.json (ALADIN 1's inputs), supply_graph.json (NEXUS), the desk's own stock list.
   Wording (the signal names, the goal and stop labels) comes from the labels dictionary inside weekly.json, so switching vocabulary is a config change.
   Every number is read from a file; a missing input says "not measured" with its reason. The goal and stop are the model's own levels, not promises.
   UI patterns (table, badge, tabs, sheet, search, stat card, marker bar, stepper) are re-drawn in the desk's own CSS after the shadcn/ui and Tremor patterns listed on designeer.xyz; no third-party code is copied.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. */
import { esc, inr, pct } from "./desk-aladin2.js";
import * as A2 from "./desk-aladin2.js";
import { shareText } from "./desk-deps.js";

let ctx = null, root = null, W = null, graph = null, loading = null, failed = false;
const st = { q: "", filter: "all", sel: null, tab: "summary", page: "signals", pmode: "live", tb: "all", acct: "big" };
let paper = null, paperLoading = false, movers;
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results.";
const REL = { supplies: "supplies", equipment_for: "supplies equipment to", raw_material_from: "sources raw material from", logistics_for: "provides logistics to", related_party: "is a related party of", customer_of: "is a customer of" };
const TABS = [["summary", "Summary"], ["how", "How it was made"], ["range", "Range and chance"], ["deps", "Revenue dependencies"]];

export function init(c) { ctx = c; }

/* ---------- pure helpers (tests/js/signals.test.mjs) ---------- */
const rel = (v, base) => v == null || !base ? null : (v / base - 1) * 100;
export function rowOf(r, side) {
  return { sym: r.sym, name: r.name, sector: r.sector, sig: side, close: r.close, goal: r.goal ?? null, stop: r.stop ?? null, goalPct: rel(r.goal, r.close), stopPct: rel(r.stop, r.close), rr: r.reward_risk ?? null,
    rank: r.rank_pct, pu: r.chance ? r.chance.closes_higher : null, pb: r.chance ? r.chance.beats_market : null, ranked: true, book: r };
}
/* The list the page shows. No search: the week's signals, positive ones strongest first, then negative ones weakest first. With a search: every stock whose symbol or name matches, signal or not. */
export function buildRows(Wk, stocks, { q = "", filter = "all", limit = 80 } = {}) {
  const book = Wk && Wk.book; if (!book) return { rows: [], total: 0 };
  const sigs = new Map(); for (const r of book.bull) sigs.set(r.sym, rowOf(r, "bull")); for (const r of book.bear) sigs.set(r.sym, rowOf(r, "bear"));
  const ql = String(q || "").trim().toLowerCase(); let rows;
  if (!ql) rows = [...book.bull].sort((a, b) => b.rank_pct - a.rank_pct).map(r => sigs.get(r.sym)).concat([...book.bear].sort((a, b) => a.rank_pct - b.rank_pct).map(r => sigs.get(r.sym)));
  else {
    const hit = (stocks || []).filter(s => s.s.toLowerCase().startsWith(ql) || s.s.toLowerCase().includes(ql) || String(s.n || "").toLowerCase().includes(ql)).sort((a, b) => (b.s.toLowerCase() === ql) - (a.s.toLowerCase() === ql) || (b.s.toLowerCase().startsWith(ql)) - (a.s.toLowerCase().startsWith(ql)) || a.s.length - b.s.length);
    rows = hit.map(s => {
      if (sigs.has(s.s)) return sigs.get(s.s);
      const k = book.ranks && book.ranks[s.s];
      return { sym: s.s, name: s.n, sector: s.ind, sig: k ? "none" : "na", close: s.c, goal: null, stop: null, goalPct: null, stopPct: null, rr: null, rank: k ? k[0] : null, pu: k ? k[1] : null, pb: k ? k[2] : null, ranked: !!k, book: null };
    });
  }
  const total = rows.length; if (filter === "bull" || filter === "bear") rows = rows.filter(r => r.sig === filter);
  return { rows: rows.slice(0, limit), total, shown: Math.min(rows.length, limit), more: Math.max(0, rows.length - limit) };
}
/* Revenue dependencies of a company from the NEXUS graph: who it supplies and who supplies it, with the share when the filing gives one, the period and the source. */
export function dependenciesOf(g, sym) {
  if (!g || !g.edges) return null;
  const nm = new Map((g.nodes || []).map(n => [n.id, n])), done = g.cos && g.cos[sym];
  const own = g.edges.filter(e => e.own === sym || e.s === sym || e.d === sym);
  const label = id => { const n = nm.get(id); if (n) return { id, name: n.n || id, listed: n.k === "co", sym: n.k === "co" ? (n.sym || id) : null }; if (g.anon && g.anon[id]) return { id, name: "Unnamed counterparty of " + g.anon[id].owner, listed: false, sym: null }; return { id, name: id, listed: false, sym: null }; };
  const rows = own.map(e => {
    const other = e.s === sym ? e.d : e.s, out = e.s === sym;
    return { other: label(other), text: out ? `${sym} ${REL[e.rel] || e.rel} ${label(e.d).name}` : `${label(e.s).name} ${REL[e.rel] || e.rel} ${sym}`, share: e.w ?? null, period: e.per || null, wb: e.wb, wd: e.wd, w: e.w, conf: e.conf ?? null, url: e.url || null, page: e.pg || null, quote: e.q || null, tier: e.tier ?? null, kind: e.kind || null };
  }).sort((a, b) => (b.share ?? -1) - (a.share ?? -1) || (b.conf ?? 0) - (a.conf ?? 0));
  return { rows, read: !!done, done: g.coverage ? g.coverage.companies_done : null, total: g.coverage ? g.coverage.companies_total : null };
}
/* ---------- paper account helpers (tests/js/signals.test.mjs) ---------- */
export function downsample(a, n = 360) { if (!a || a.length <= n) return a || []; const out = []; for (let i = 0; i < n; i++) out.push(a[Math.round(i * (a.length - 1) / (n - 1))]); return out; }
/* weekly returns [[date, r]] compounded from `start`: [[date, value]] */
export function compound(weekly, start) { let v = start; return (weekly || []).map(([d, r]) => [d, (v *= 1 + r)]); }
const tms = d => Date.parse(d + "T00:00:00Z");
/* A line chart as inline SVG. series: [{name, pts:[[date, value]], cls}], base: a horizontal reference value (the budget). Times are on a true date axis. */
export function lineChart(series, { w = 640, h = 220, base = null, label = "chart", fmt = v => String(Math.round(v)) } = {}) {
  const all = series.flatMap(s => s.pts); if (all.length < 2) return "";
  const xs = all.map(p => tms(p[0])), ys = all.map(p => p[1]).concat(base != null ? [base] : []), x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys), hi = Math.max(...ys), pad = (hi - lo) * 0.06 || 1;
  const L = 56, R = 8, T = 8, B = 20, X = d => L + (w - L - R) * (tms(d) - x0) / ((x1 - x0) || 1), Y = v => T + (h - T - B) * (1 - (v - (lo - pad)) / ((hi + pad) - (lo - pad)));
  const ticks = [lo, (lo + hi) / 2, hi].map(v => `<line x1="${L}" x2="${w - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="a2-grid"/><text x="${L - 4}" y="${(Y(v) + 3).toFixed(1)}" class="a2-ax end">${esc(fmt(v))}</text>`).join("");
  const yrs = []; for (let y = new Date(x0).getUTCFullYear() + 1; y <= new Date(x1).getUTCFullYear(); y++) { if (new Date(x1).getUTCFullYear() - new Date(x0).getUTCFullYear() > 6 && y % 2) continue; yrs.push(`<text x="${X(y + "-01-01").toFixed(1)}" y="${h - 5}" class="a2-ax mid">${y}</text>`); }
  const lines = series.map(s => `<polyline class="sg-ln ${s.cls || ""}" points="${downsample(s.pts).map(p => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ")}"><title>${esc(s.name)}: ${esc(fmt(s.pts[s.pts.length - 1][1]))} at the end</title></polyline>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" class="a2v-svg sg-svg" role="img" aria-label="${esc(label)}">${ticks}${base != null ? `<line x1="${L}" x2="${w - R}" y1="${Y(base).toFixed(1)}" y2="${Y(base).toFixed(1)}" class="a2v-ref"/>` : ""}${yrs.join("")}${lines}</svg><div class="a2b-leg">${series.map(s => `<span class="a2b-k sg-k ${s.cls || ""}">${esc(s.name)}</span>`).join("")}</div>`;
}
export const fmtLevel = (v, p) => v == null ? null : { price: inr(v, 2), rel: pct(p, 1) };

/* ---------- loading ---------- */
async function load() {
  if (W || failed) return;
  if (!loading) loading = Promise.all([
    ctx.getJSON("aladin2/weekly.json", false).then(j => { W = j; }).catch(() => { failed = true; }),
    ctx.S.aladin ? 0 : ctx.getJSON("aladin.json", false).then(j => { ctx.S.aladin = j; }).catch(() => 0)]).finally(() => { loading = null; });
  await loading;
}
function loadGraph() { if (graph || !ctx) return; ctx.getJSON("supply_graph.json", false).then(j => { graph = j; if (st.sel && st.tab === "deps") paintSheet(); }).catch(() => { graph = { edges: [], missing: true }; if (st.sel && st.tab === "deps") paintSheet(); }); }

/* ---------- drawing ---------- */
const lab = () => (W && W.labels) || { bull: "BULLISH SIGNAL", bear: "BEARISH SIGNAL", none: "NO EDGE", goal: "Range edge", stop: "Exit level", signal: "Signal" };
const sigName = sig => sig === "bull" ? lab().bull : sig === "bear" ? lab().bear : sig === "none" ? lab().none : "NOT RANKED";
const badge = sig => `<span class="sg-badge ${sig}">${esc(sigName(sig))}</span>`;
function levelCell(v, p, basis, by) { const f = fmtLevel(v, p); return f ? `<b>${f.price}</b><small class="${p >= 0 ? "up" : "down"}">${f.rel}${by ? ` <span class="sg-by">by ${esc(shortDate(by))}</span>` : ""}</small>` : `<span class="sg-nm" title="${esc(basis || "")}">${basis ? "not measured" : "--"}</span>`; }
export const shortDate = d => d ? new Date(d + "T00:00:00Z").toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" }) : "";

function shell() {
  const b = W && W.book, c = b ? b.counts : null, L = lab();
  const chip = (k, t, n) => `<button type="button" class="sg-chip ${st.filter === k ? "on" : ""}" data-f="${k}" aria-pressed="${st.filter === k}">${esc(t)}${n != null ? ` <i>${n}</i>` : ""}</button>`;
  return `<div class="sg">
    <div class="sg-head"><div><h2>ALADIN signals</h2><p>${b ? `Weekly view as of the ${esc(b.as_of)} close · hold for ${b.horizon_trading_days} trading days` : "Loading…"}</p></div>
      <div class="sg-links"><div class="sg-chips" role="group" aria-label="Page"><button type="button" class="sg-chip ${st.page === "signals" ? "on" : ""}" data-page="signals" aria-pressed="${st.page === "signals"}">Signals</button><button type="button" class="sg-chip ${st.page === "paper" ? "on" : ""}" data-page="paper" aria-pressed="${st.page === "paper"}">Paper account</button></div><button type="button" class="btn-line sm" data-go="a2bot">Bot console</button><button type="button" class="btn-line sm" data-go="a2">Research pages</button></div></div>
    <div id="sg-p1" ${st.page === "signals" ? "" : "hidden"}>${b ? `<div class="sg-stats"><div class="sg-stat"><span>${esc(L.bull)} signals</span><b class="up">${c.bull}</b></div><div class="sg-stat"><span>${esc(L.bear)} signals</span><b class="down">${c.bear}</b></div><div class="sg-stat"><span>${esc(L.none)}</span><b>${c.hold.toLocaleString("en-IN")}</b></div>
      <div class="sg-stat wide"><span>Chance the best-ranked closes higher</span><b>${esc(pct0(bestChance()))}</b><small>measured 2013 to 2026, checked on years the model had not seen</small></div></div>` : ""}
    <div class="sg-bar"><div class="sg-search"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="M14 14l4 4"/></svg><input id="sg-q" type="search" inputmode="search" autocomplete="off" spellcheck="false" placeholder="Search any stock: symbol or company name" value="${esc(st.q)}" aria-label="Search any stock"></div>
      <div class="sg-chips" role="group" aria-label="Filter">${chip("all", "All", null)}${chip("bull", L.bull, c ? c.bull : null)}${chip("bear", L.bear, c ? c.bear : null)}</div></div>
    <div id="sg-list"></div></div><div id="sg-p2" ${st.page === "paper" ? "" : "hidden"}></div>
    <p class="note a2v-dis">${DISCLAIMER}</p>
    <div id="sg-sheet-host"></div></div>`;
}
const pct0 = v => v == null ? "--" : (v * 100).toFixed(1) + "%";
function bestChance() { const c = W && W.book && W.book.bull[0] && W.book.bull[0].chance; return c ? c.closes_higher : null; }

function listHtml() {
  const { rows, total, more } = buildRows(W, ctx.S.uni ? ctx.S.uni.stocks : [], { q: st.q, filter: st.filter }), L = lab();
  if (!W || !W.book) return `<p class="note">${failed ? "The signals file is not published yet." : "Loading…"}</p>`;
  if (!rows.length) return `<div class="sg-empty"><b>Nothing found.</b><span>${st.q ? "No stock matches that search." : "No signals this week: every stock reads as " + esc(L.none) + "."}</span></div>`;
  const body = rows.map(r => `<tr tabindex="0" data-sym="${esc(r.sym)}" class="${r.sym === st.sel ? "on" : ""}"><td class="sg-st"><b>${esc(r.sym)}</b><small>${esc(r.name || "")}</small></td><td>${badge(r.sig)}</td>
      <td class="r">${r.sig === "bull" || r.sig === "bear" ? levelCell(r.goal, r.goalPct, r.book && r.book.goal_basis, r.book && r.book.goal_by) : '<span class="sg-nm">--</span>'}</td><td class="r">${r.sig === "bull" || r.sig === "bear" ? levelCell(r.stop, r.stopPct, r.book && r.book.stop_basis || "x") : '<span class="sg-nm">--</span>'}</td><td class="sg-go" aria-hidden="true">›</td></tr>`).join("");
  return `<div class="sg-tablewrap"><table class="sg-table"><thead><tr><th>Stock</th><th>${esc(L.signal || "Signal")}</th><th class="r">${esc(L.goal || "Range edge")} <span class="sg-by">· 5 trading days</span></th><th class="r">${esc(L.stop || "Exit level")}</th><th></th></tr></thead><tbody>${body}</tbody></table></div>
    <p class="note">${more ? `Showing ${rows.length} of ${total}. Search to find any other stock. ` : ""}${st.q ? "" : `Prices are the ${esc(W.book.as_of)} close. The ${esc(L.goal || "range edge").toLowerCase()} is the edge of the model's 5-day 50% price range, so it applies only until the date shown (about a coin flip of being reached); the ${esc(L.stop || "exit level").toLowerCase()} is 2 average daily moves from the price. Click a stock for the reasons.`}</p>`;
}

/* ----- the paper account page ----- */
async function loadPaper() {
  if (paper || paperLoading) return; paperLoading = true;
  const get = f => ctx.getJSON("aladin2/" + f, false).catch(() => null);
  const [live, hist, mv, small] = await Promise.all([get("paper_live.json"), get("paper_backtest.json"), ctx.getJSON("aladin_movers.json", false).catch(() => null), get("paper_live_small.json")]); paper = { live, hist, small }; movers = mv; paperLoading = false;
  if (root && st.page === "paper") paintPaper();
}
const rupee = v => v == null ? "--" : (v < 0 ? "-" : "") + "₹" + inr(Math.abs(v), 0);
const sgn = (v, d = 1, suf = "%") => v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(d) + suf;
const cls = v => v == null ? "" : v >= 0 ? "up" : "down";
const kpi = (label, val, sub, c = "") => `<div class="sg-stat"><span>${esc(label)}</span><b class="${c}">${val}</b><small>${sub || ""}</small></div>`;
function tradesTable(list) {
  if (!list || !list.length) return '<p class="note">No closed trades yet.</p>';
  const nm = { stop: "stop", time: "5-day limit", goal: "goal", "no data": "no data" };
  return `<div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>Stock</th><th>In</th><th>Out</th><th class="r">Price in → out</th><th class="r">Net P/L</th><th>Why out</th></tr></thead><tbody>${list.slice(-40).reverse().map(t => `<tr><td class="sg-st"><b>${esc(t.sym)}</b><small>${t.qty} shares</small></td><td>${esc(t.entry_date)}</td><td>${esc(t.exit_date)}</td><td class="r"><b>${inr(t.entry)} → ${inr(t.exit)}</b></td><td class="r"><b class="${cls(t.net)}">${rupee(t.net)}</b><small class="${cls(t.ret_pct)}">${sgn(t.ret_pct, 2)}</small></td><td>${esc(nm[t.reason] || t.reason)}</td></tr>`).join("")}</tbody></table></div>`;
}
/* The weekly ranking (scripts/aladin_movers.py, data/aladin_movers/latest.json): every stock ranked by its expected 5-day move, recorded before Monday's open,
   checked against real prices, and run as a shadow of the paper bot. Pure: doc = aladin_movers.json, n = rows shown per side. Gates that failed are shown as failed. */
export function moversHtml(doc, n = 15) {
  if (!doc) return '<p class="note">The weekly ranking is not published yet. The first one is written after the close on Friday.</p>';
  const B = doc.book, F = doc.forward || {}, S = doc.shadow || {}, T = doc.backtest || {}, G = T.gates || {};
  const pct = (v, d = 1) => v == null ? "--" : (v * 100).toFixed(d) + "%";
  const row = r => `<tr tabindex="0" data-sym="${esc(r.sym)}"><td class="sg-st"><b>${esc(r.sym)}</b><small>${esc(r.name || r.sector || "")}</small></td>
    <td class="r ${cls(r.exp_move)}"><b>${sgn(r.exp_move * 100, 2)}</b></td><td class="r">${pct(r.p_up, 0)}</td><td class="r">±${(r.size * 100).toFixed(1)}%</td>
    <td>${r.results_this_week ? '<span class="sg-flag">Results due</span>' : ""}</td></tr>`;
  const table = (title, rows, sub) => `<div class="sg-card"><h4>${title}</h4><p class="note">${sub}</p><div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>Stock</th><th class="r">Expected move</th><th class="r">Chance up</th><th class="r">Typical size</th><th></th></tr></thead><tbody>${rows.slice(0, n).map(row).join("")}</tbody></table></div></div>`;
  const book = B ? `<div class="sg-stats sg-kp">${kpi("Ranking for the week after", dmy(B.friday), B.counted ? "written before Monday's open: counts" : "written late: shown, not counted")}${kpi("Stocks ranked", String(B.n), `top and bottom tenth: ${B.k} each`)}${kpi("Finished weeks", `${F.done || 0} of ${S.promote_after_weeks || 26}`, "before the record is judged")}${kpi("Paper top tenth", rupee(F.equity), `all stocks equally: ${rupee(F.equity_all_stocks)}`)}</div>
    <div class="sg-split">${table("Highest expected move", B.top, `The top tenth. This is the shadow paper portfolio for the week: equal amounts, Monday open to Friday close, 0.30% costs.`)}
    ${table("Lowest expected move", B.bottom, `The bottom tenth, kept to check that the ranking separates: the top should do better than these.`)}</div>`
    : `<div class="sg-empty"><b>No ranking written yet.</b><span>The first one is written after the close on Friday and recorded before Monday's open.</span></div>`;
  const done = (F.weeks || []).filter(w => w.status === "done");
  const weeks = (F.weeks || []).length ? `<ol class="sg-wks">${F.weeks.map(w => `<li class="sg-wk ${w.status === "done" ? "in-time" : "waiting"}"><b>${dmy(w.friday)}</b><span>${w.status === "done" ? "finished" : "running"}</span>${w.status === "done" ? `<small>top <i class="${cls(w.top)}">${sgn(w.top, 2)}</i> · bottom <i class="${cls(w.bottom)}">${sgn(w.bottom, 2)}</i> · all ${sgn(w.all, 2)}</small>` : ""}</li>`).join("")}</ol>` : "";
  const prog = Math.min(1, (S.weeks || 0) / (S.promote_after_weeks || 26));
  const shadow = `<div class="sg-card"><h4>Shadow of the paper bot · same ₹10 lakh, same weeks</h4>
    <div class="sg-prog" role="img" aria-label="${S.weeks || 0} of ${S.promote_after_weeks || 26} finished weeks"><i style="width:${(prog * 100).toFixed(1)}%"></i></div>
    <table class="sg-mini"><thead><tr><td></td><td>Weekly ranking</td><td>Current paper bot</td></tr></thead><tbody>
      <tr><td>Return over the same weeks${S.from ? ` (${dmy(S.from)} to ${dmy(S.to)})` : ""}</td><td class="${cls(S.movers_return_pct)}">${sgn(S.movers_return_pct, 2)}</td><td class="${cls(S.bot_return_pct)}">${sgn(S.bot_return_pct, 2)}</td></tr>
      <tr><td>Finished weeks</td><td>${S.weeks || 0}</td><td>same weeks</td></tr></tbody></table>
    <p class="note">${S.promoted ? `<b>Switched on ${esc(String(S.promoted.ts).slice(0, 10))}</b> after ${S.promoted.weeks} weeks: the ranking returned ${sgn(S.promoted.movers_return_pct, 2)} against the bot's ${sgn(S.promoted.bot_return_pct, 2)}. It is now the paper bot; this is never reversed automatically.`
      : `The rule, written before the first week: after ${S.promote_after_weeks || 26} finished weeks, if the ranking's return beats the bot's over exactly those weeks AND the top tenth beat the bottom tenth on average after costs, it replaces the bot. Checked every week, decided once.`}</p>${weeks}</div>`;
  const gate = (ok, name, txt) => `<tr><td><b>${name}</b></td><td><span class="sg-flag ${ok ? "ok" : "no"}">${ok == null ? "not measured" : ok ? "passed" : "did not pass"}</span></td><td>${txt}</td></tr>`;
  const dec = T.deciles_expected_move || [], mx = Math.max(0.0001, ...dec.map(d => Math.abs(d.mean_r5)));
  const bars = dec.length ? `<h4 style="margin-top:12px">Average 5-day return by tenth of the ranking (2016 to 2026, before costs)</h4><ul class="sg-bars">${dec.map((d, i) => `<li><span>${i === 0 ? "Lowest tenth" : i === dec.length - 1 ? "Highest tenth" : `Tenth ${i + 1}`}</span><div><i class="${d.mean_r5 >= 0 ? "up" : "down"}" style="width:${(Math.abs(d.mean_r5) / mx * 100).toFixed(0)}%"></i></div><em>${sgn(d.mean_r5 * 100, 2)}</em></li>`).join("")}</ul>` : "";
  const back = `<div class="sg-card"><h4>What the 10-year test showed (every year out of sample)</h4><table class="sg-mini"><tbody>
    ${gate(G.size, "How big", `Telling big movers (over 5% either way) from quiet ones: score ${T.auc_big ?? "--"}, only a little better than the stock's own recent volatility (${T.auc_big_recent_volatility ?? "--"}). The gate needed 0.70. Not shown as a forecast on its own.`)}
    ${gate(G.direction, "Which way", `Calling up or down: score ${T.auc_up ?? "--"}, where 0.50 is a coin toss. The gate needed 0.53. Not shown as a forecast on its own.`)}
    ${gate(G.ranking, "Ranking", `Top tenth minus bottom tenth: ${sgn(T.ranking_top_minus_bottom_weekly_pct_after_costs, 3)} a week after costs; positive in ${T.years_positive_after_costs ?? "--"} of 11 years, top ahead of bottom in ${T.years_top_beats_bottom ?? "--"} of 11.`)}
    </tbody></table>${bars}<p class="note">So the ranking as a whole separated stocks over ten years, while a single stock's forecast is weak. ${T.rows ? `${inr(T.rows, 0)} stock-weeks, ${inr(T.stocks, 0)} stocks. ` : ""}The years were looked at twice (round 2 after round 1 failed), and the test uses stocks listed today, so it is flattered. That is why it runs forward before anything changes.</p></div>`;
  return `<div class="sg-banner">${esc(doc.label || "")}</div>${book}${shadow}${back}
    <p class="note">${esc(doc.method || "")} Educational simulation, not advice. Updated ${doc.updated_utc ? new Date(doc.updated_utc).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) + " IST" : "--"}.</p>`;
}
/* The live account's complete trade book: every position it has ever taken, open ones first, with the money each one used and why it was that size.
   Pure: doc = paper/live.json, view = "all" | "open" | "closed". Fields the bot has not recorded yet show "--", never a guess (capital = shares x entry price is exact). */
const SIZED = { "risk per trade": "risk to the stop", "max position size": "per-stock cap", "liquidity": "daily volume cap", "fractional Kelly (edge too small)": "small-edge cap", "cash left": "cash left" };
export function tradeBookRows(doc) {
  const capOf = t => t.capital ?? t.qty * t.entry;
  const open = (doc.open || []).map(o => ({ ...o, status: "open", capital: capOf(o), value: o.value_now ?? o.qty * o.last, costs: o.cost_in ?? null, net: o.pnl, ret: o.pnl != null ? o.pnl / capOf(o) * 100 : null }));
  const closed = (doc.trades || []).map(t => ({ ...t, status: "closed", capital: capOf(t), value: t.exit_value ?? t.qty * t.exit, net: t.net, ret: t.ret_pct })).reverse();
  return open.concat(closed);
}
export function tradeBookHtml(doc, view = "all") {
  const all = tradeBookRows(doc), R = doc.rules || {}, eqr = (doc.equity || []).slice(-1)[0];
  if (!all.length) return "";
  const rows = all.filter(r => view === "all" || r.status === view), open = all.filter(r => r.status === "open"), closed = all.filter(r => r.status === "closed");
  const acct = eqr ? eqr[1] : null, invested = open.reduce((a, r) => a + r.value, 0), costs = all.some(r => r.costs == null) ? null : all.reduce((a, r) => a + r.costs, 0);
  const avgCap = all.reduce((a, r) => a + r.capital, 0) / all.length, big = all.reduce((m, r) => r.capital > m.capital ? r : m, all[0]);
  const realised = closed.reduce((a, r) => a + r.net, 0), unreal = open.reduce((a, r) => a + (r.net || 0), 0);
  const pctAcc = r => r.pct_of_account != null ? `${r.pct_of_account.toFixed(1)}% of account` : acct ? `about ${(r.capital / acct * 100).toFixed(0)}% of today's account` : "";
  const tr = r => `<tr tabindex="0" data-sym="${esc(r.sym)}"><td class="sg-st"><b>${esc(r.sym)}</b><small>${esc([r.sector && r.sector !== "Unknown" && r.sector !== "?" ? r.sector : "", r.as_of ? `list of ${dmy(r.as_of)}` : ""].filter(Boolean).join(" · "))}</small></td>
    <td class="r"><b>${dmy(r.entry_date)}</b><small>₹${inr(r.entry, 2)}</small></td><td class="r">${inr(r.qty, 0)}</td>
    <td class="r"><b>${rupee(r.capital)}</b><small>${pctAcc(r)}</small></td>
    <td>${r.sized_by ? `<span class="sg-flag">${esc(SIZED[r.sized_by] || r.sized_by)}</span>` : '<span class="sg-nm" title="Recorded from tonight’s run">--</span>'}${r.risk_to_stop != null ? `<small class="sg-sub">${rupee(r.risk_to_stop)} to the exit level</small>` : ""}</td>
    <td class="r">${r.status === "open" ? `<b>₹${inr(r.last, 2)} now</b><small>out ${r.exit_due ? dmy(r.exit_due) : `in ${r.days_left} days`}</small>` : `<b>₹${inr(r.exit, 2)}</b><small>${dmy(r.exit_date)} · ${esc(r.reason === "time" ? "5-day limit" : r.reason)}</small>`}</td>
    <td class="r">${r.costs != null ? rupee(r.costs) : "--"}</td>
    <td class="r"><b class="${cls(r.net)}">${rupee(r.net)}</b><small class="${cls(r.ret)}">${sgn(r.ret, 2)}</small></td>
    <td><span class="sg-flag ${r.status === "open" ? "" : r.net >= 0 ? "ok" : "no"}">${r.status === "open" ? `open · day ${r.days_held}` : r.net >= 0 ? "profit" : "loss"}</span></td></tr>`;
  const chip = (v, label, n) => `<button type="button" class="sg-chip ${view === v ? "on" : ""}" data-tb="${v}" aria-pressed="${view === v}">${label} (${n})</button>`;
  const sk = (doc.skipped || []).map(s => `<li><b>${esc(s.sym)}</b> <span>${esc(String(s.why).replace(/^size 0 \((.*)\) or no cash\/sector room$/, (m, w) => `size came out at zero (${SIZED[w] || w})`))}</span> <small>list of ${dmy(s.as_of)}</small></li>`).join("");
  return `<div class="sg-card sg-book"><h4>Trade book · every position since ${dmy(doc.stats && doc.stats.from)}</h4>
    <div class="sg-stats sg-kp">${kpi("In stocks now", rupee(invested), acct ? `${(invested / acct * 100).toFixed(0)}% of ${rupee(acct)} account · ${open.length} positions` : `${open.length} positions`)}
      ${kpi("Cash and liquid fund", acct ? rupee(acct - invested) : "--", "idle money earns the call-money rate")}
      ${kpi("Average capital per trade", rupee(avgCap), `largest ${esc(big.sym)} ${rupee(big.capital)}`)}
      ${kpi("Costs paid", costs == null ? "--" : rupee(costs), costs == null ? "entry costs are recorded from tonight's run" : "brokerage, STT, stamp duty, exchange and GST")}</div>
    <div class="sg-stats sg-kp">${kpi("Positions taken", String(all.length), `${open.length} open · ${closed.length} closed`)}${kpi("Realised P/L", closed.length ? rupee(realised) : "--", closed.length ? `${closed.filter(r => r.net > 0).length} of ${closed.length} in profit` : "nothing closed yet", cls(closed.length ? realised : null))}
      ${kpi("Open P/L (after entry costs)", rupee(unreal), "marked at the last close", cls(unreal))}${kpi("Names on the lists not taken", String((doc.skipped || []).length), "reasons below")}</div>
    <p class="note">How each trade is sized: at most ${R.risk_per_trade_pct ?? "--"}% of the account lost if the price fell to the exit level, at most ${R.max_position_pct ?? "--"}% of the account in one stock, at most ${R.adv_participation_max != null ? (R.adv_participation_max * 100).toFixed(0) : "--"}% of the stock's daily volume, at most ${R.max_open ?? "--"} positions and ${R.max_sector_pct ?? "--"}% in one sector, and a cap from the size of the edge. The smallest of these wins; the "Sized by" column names it.</p>${R.dp_charge_per_sale_inr != null ? `<p class="note"><b>Small account (₹${inr(R.budget_inr, 0)}):</b> the same rules on the same lists from the list of ${dmy(R.first_list)}. Whole shares only, so a stock whose one share costs more than ${R.max_position_pct ?? 20}% of the account (about ₹${inr((R.budget_inr || 0) * (R.max_position_pct ?? 20) / 100, 0)}) cannot be held, and every sale pays a ₹${R.dp_charge_per_sale_inr} depository charge. On small positions fixed charges weigh far more.</p>` : ""}
    <div class="sg-bar"><div class="sg-chips" role="group" aria-label="Trades shown">${chip("all", "All", all.length)}${chip("open", "Open", open.length)}${chip("closed", "Closed", closed.length)}</div><button type="button" class="sg-chip" id="tb-csv">Download CSV</button></div>
    <div class="sg-tablewrap"><table class="sg-table sg-ledger"><thead><tr><th>Stock</th><th class="r">Entered</th><th class="r">Shares</th><th class="r">Capital used</th><th>Sized by</th><th class="r">Exit / now</th><th class="r">Costs</th><th class="r">Net P/L</th><th>Status</th></tr></thead>
    <tbody>${rows.length ? rows.map(tr).join("") : `<tr><td colspan="9" class="note">No ${view} positions.</td></tr>`}</tbody></table></div>
    ${sk ? `<details class="sg-skip"><summary>On the lists but not taken (${(doc.skipped || []).length})</summary><ul>${sk}</ul></details>` : ""}
    <p class="note">Simulated money on real prices. Entry at the open after each Friday list, exit at the open five trading days later. Costs are charged on both legs; open P/L already includes the entry costs.</p></div>`;
}
export function tradeBookCsv(doc) {
  const cols = ["status", "sym", "sector", "as_of", "entry_date", "entry", "qty", "capital", "pct_of_account", "sized_by", "risk_to_stop", "exit_date", "exit", "last", "reason", "costs", "net", "ret"];
  const q = v => v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
  return [cols.join(",")].concat(tradeBookRows(doc).map(r => cols.map(c => q(c === "capital" || c === "net" || c === "ret" ? (r[c] == null ? null : Math.round(r[c] * 100) / 100) : r[c])).join(","))).join("\n");
}
/* The continuous front test: a heartbeat, the week-by-week strip from the forward clock, progress to the judging point, live vs history. doc = paper/live.json. */
const dmy = d => d ? new Date(d + "T00:00:00Z").toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" }) : "--";
export function frontTestHtml(doc) {
  const T = doc && doc.timeline; if (!T) return "";
  const S = doc.stats || {}, E = T.expect_from_history || {}, nm = { "in time": "counted", late: "late, not counted", missed: "no list written", waiting: "waiting" };
  const ran = doc.created_utc ? new Date(doc.created_utc).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) + " IST" : "--";
  const weeks = T.weeks.length ? T.weeks.map(w => `<li class="sg-wk ${w.status.replace(" ", "-")}"><b>${dmy(w.friday)}</b><span>${esc(nm[w.status] || w.status)}</span><small>${[w.names != null ? `${w.names} names` : "", w.closed ? `${w.wins}/${w.closed} profitable · <i class="${cls(w.net)}">${rupee(w.net)}</i>` : w.open ? `${w.open} open` : w.status === "in time" ? `enters ${dmy(w.entry_day)}` : ""].filter(Boolean).join(" · ")}</small></li>`).join("") : '<li class="sg-wk waiting"><b>--</b><span>no Friday yet</span></li>';
  const live = (v, d) => v == null ? "--" : d(v);
  return `<div class="sg-card sg-ft"><h4>Front test · running every trading day since ${dmy(T.start)}</h4>
    <p class="sg-beat"><i class="sg-dot" aria-hidden="true"></i><span>Day ${T.days_running} · last run ${esc(ran)} · prices up to ${dmy(doc.last_price_date)} · next list after the close on ${dmy(T.next_book)}, the bot enters at the open on ${dmy(T.next_entry)}</span></p>
    <div class="sg-prog" role="img" aria-label="${T.closed_trades} of ${T.judge_after_trades} closed trades"><i style="width:${(T.progress * 100).toFixed(1)}%"></i></div>
    <p class="note">${T.closed_trades} of ${T.judge_after_trades} closed trades before the live record can be judged.</p>
    <ol class="sg-wks">${weeks}</ol>
    <table class="sg-mini"><thead><tr><td></td><td>Live so far</td><td>13-year history</td></tr></thead><tbody>
      <tr><td>Trades ending in profit</td><td>${live(S.win_rate, v => (v * 100).toFixed(0) + "%")}</td><td>${E.win_rate != null ? (E.win_rate * 100).toFixed(0) + "%" : "--"}</td></tr>
      <tr><td>Profit factor (wins ÷ losses)</td><td>${live(S.profit_factor, v => v.toFixed(2))}</td><td>${E.profit_factor ?? "--"}</td></tr></tbody></table>
    <p class="note">Only lists written before the next open count. Every night the job replays the whole live record from the ledger, so nothing can be edited afterwards.</p></div>`;
}
/* Today, during market hours: what the live account holds right now, from the delayed prices the desk already loads (t/quotes.json, about 15 minutes late).
   Before tonight's run records the fills, the Friday list is shown as PROVISIONAL entries at today's open; afterwards the recorded open positions are marked to the live price.
   Pure: doc = paper/live.json, book = weekly.json's book, quotes = {SYM: {p, o, d}}, today = "YYYY-MM-DD" (IST). Nothing here is saved or counted. */
export function liveTodayHtml(doc, book, quotes, today) {
  const q = s => { const x = quotes && quotes[s]; return x && x.d === today ? x : null; };
  const open = (doc && doc.open) || [];
  if (open.length) {
    let tot = 0, n = 0;
    const rows = open.map(o => { const x = q(o.sym), last = x ? x.p : null, pl = last != null ? o.qty * (last - o.entry) : null; if (pl != null) { tot += pl; n++; }
      return `<tr><td><b>${esc(o.sym)}</b></td><td class="r">₹${inr(o.entry, 2)}</td><td class="r">${last != null ? "₹" + inr(last, 2) : '<span class="sg-nm">no live price</span>'}</td><td class="r ${cls(pl)}">${pl != null ? rupee(pl) + " · " + sgn((last / o.entry - 1) * 100, 2) : "--"}</td></tr>`; }).join("");
    return `<div class="sg-card sg-today"><h4>Right now · open positions marked to the live price</h4><div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>Stock</th><th class="r">Bought at</th><th class="r">Live price</th><th class="r">P/L so far</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">${n ? `Together ${rupee(tot)} on ${n} of ${open.length} positions. ` : ""}Delayed prices (about 15 minutes). This is a live mark only; the account's official numbers are written after the close each night.</p></div>`;
  }
  const wk = book && doc && doc.timeline && (doc.timeline.weeks || []).find(w => w.friday === book.as_of);
  if (!wk || wk.entry_day !== today || wk.status !== "in time" || !(book.bull || []).length) return "";
  let sum = 0, n = 0;
  const rows = book.bull.map(b => { const x = q(b.sym), ch = x && x.o ? (x.p / x.o - 1) * 100 : null; if (ch != null) { sum += ch; n++; }
    return `<tr><td><b>${esc(b.sym)}</b></td><td class="r">${x && x.o ? "₹" + inr(x.o, 2) : '<span class="sg-nm">no live price</span>'}</td><td class="r">${x ? "₹" + inr(x.p, 2) : "--"}</td><td class="r ${cls(ch)}">${sgn(ch, 2)}</td></tr>`; }).join("");
  return `<div class="sg-card sg-today"><h4>Today · the bot enters ${book.bull.length} stocks at the open (provisional)</h4><div class="sg-tablewrap sg-short"><table class="sg-table"><thead><tr><th>Stock</th><th class="r">Today's open (entry)</th><th class="r">Live price</th><th class="r">Since entry</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note">${n ? `Average since the open ${sgn(sum / n, 2)} across ${n} names. ` : ""}PROVISIONAL: the list was written before today's open, so these entries count. Quantities and the official fills are recorded after today's close by the nightly run; until then this is a live view from delayed prices (about 15 minutes), not the account's record.</p></div>`;
}
function paperHtml() {
  if (!paper) return '<p class="note">Loading the paper account…</p>';
  const doc = st.pmode === "live" ? (st.acct === "small" ? paper.small : paper.live) : paper.hist, seg = `<div class="sg-chips" role="group" aria-label="Paper account view"><button type="button" class="sg-chip ${st.pmode === "live" ? "on" : ""}" data-pm="live" aria-pressed="${st.pmode === "live"}">Live front test</button><button type="button" class="sg-chip ${st.pmode === "hist" ? "on" : ""}" data-pm="hist" aria-pressed="${st.pmode === "hist"}">History 2013 to 2026</button><button type="button" class="sg-chip ${st.pmode === "movers" ? "on" : ""}" data-pm="movers" aria-pressed="${st.pmode === "movers"}">Weekly ranking (forward test)</button></div>${st.pmode === "live" ? `<div class="sg-chips" role="group" aria-label="Account size"><button type="button" class="sg-chip ${st.acct === "big" ? "on" : ""}" data-acct="big" aria-pressed="${st.acct === "big"}">₹10 lakh account</button><button type="button" class="sg-chip ${st.acct === "small" ? "on" : ""}" data-acct="small" aria-pressed="${st.acct === "small"}">₹10,000 account</button></div>` : ""}`;
  if (st.pmode === "movers") return `<div class="sg-bar">${seg}</div>${moversHtml(movers)}`;
  if (!doc) return `<div class="sg-bar">${seg}</div><p class="note">This part of the paper account is not published yet.</p>`;
  const S = doc.stats || {}, R = doc.rules || {}, hist = st.pmode === "hist";
  const rulesCard = `<div class="sg-card"><h4>The bot's written rules</h4><dl class="sg-dl"><div><dt>Budget</dt><dd>${rupee(R.budget_inr)}, simulated</dd></div><div><dt>Which signals</dt><dd>${esc(R.books || "")}</dd></div><div><dt>Entry</dt><dd>${esc(R.entry || "")}</dd></div><div><dt>Exit</dt><dd>${esc(R.exit_order || "")}</dd></div><div><dt>Size</dt><dd>${R.risk_per_trade_pct}% of the account at risk to the stop, at most ${R.max_position_pct}% in one stock, at most ${(R.adv_participation_max * 100).toFixed(0)}% of its daily volume, at most ${R.max_open} stocks at once</dd></div><div><dt>Costs</dt><dd>${esc(R.costs || "")}</dd></div>${R.idle_cash ? `<div><dt>Idle cash</dt><dd>${esc(R.idle_cash)}</dd></div>` : ""}</dl>
    ${(doc.rule_history || []).length ? `<h4 style="margin-top:12px">Rule history (kept in the open)</h4><ul class="sg-hist">${doc.rule_history.map(x => `<li><b>v${x.v}</b> · ${esc(x.exits)} · ${esc(x.why_dropped || x.why || "")}${x.backtest_return_pct != null ? ` (history result ${sgn(x.backtest_return_pct)})` : ""}</li>`).join("")}</ul>` : ""}</div>`;
  const ft = hist ? "" : liveTodayHtml(doc, W && W.book, ctx.S.quotes, new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })) + frontTestHtml(doc);
  if (!S.started) return `<div class="sg-bar">${seg}</div><div class="sg-banner">${esc(doc.label || "")}</div><div class="sg-empty"><b>No live trade yet.</b><span>${esc(doc.note || "")} Budget ${rupee(R.budget_inr)}.</span></div>${ft}${rulesCard}`;
  const bench = hist && doc.benchmark ? compound(doc.benchmark.weekly, S.start_equity) : null, ex = (S.avg_invested_pct || 0) / 100, matched = bench && ex > 0 && ex < 1 ? compound(doc.benchmark.weekly.map(([d, r]) => [d, r * ex]), S.start_equity) : null;
  const chart = lineChart([{ name: "Paper account (after all costs)", pts: doc.equity.map(r => [r[0], r[1]]), cls: "a" }].concat(matched ? [{ name: `Market with the same ${(ex * 100).toFixed(0)}% in stocks, rest cash (the fair comparison)`, pts: matched, cls: "c" }] : []).concat(bench ? [{ name: "Market, all money in the liquid stocks every week, before costs", pts: bench, cls: "b" }] : []), { base: S.start_equity, label: "Paper account value over time", fmt: v => rupee(v) });
  const yrs = S.by_year_pct ? Object.entries(S.by_year_pct) : [], mx = Math.max(1, ...yrs.map(([, v]) => Math.abs(v)));
  const ab = hist && doc.ablation ? `<div class="sg-card"><h4>Rule versions compared (same signals, same history)</h4><table class="sg-mini"><thead><tr><td></td><td>Return</td><td>Per year</td><td>Worst fall</td><td>Profit factor</td></tr></thead><tbody>${Object.entries(doc.ablation).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${sgn(v.return_pct, 0)}</td><td>${sgn(v.cagr_pct, 1)}</td><td>${sgn(v.max_drawdown_pct, 0)}</td><td>${v.profit_factor ?? "--"}</td></tr>`).join("")}</tbody></table><p class="note">v1 (an order to leave at the price goal) lost money; v2 (stop + time) was replaced the same day by v3, the owner's choice, before any live trade. v3 was picked after its history was seen, so the live record is what decides. The price goal and exit level stay on the page as information.</p></div>` : "";
  const book = hist ? "" : tradeBookHtml(doc, st.tb);
  return `<div class="sg-bar">${seg}</div><div class="sg-banner">${esc(doc.label || "")}</div>${ft}${book}
    <div class="sg-stats sg-kp">${kpi("Budget", rupee(S.start_equity), `from ${esc(S.from)}`)}${kpi("Account value", rupee(S.end_equity), `to ${esc(S.to)}`)}${kpi("Profit or loss", rupee(S.pnl), sgn(S.return_pct) + (S.cagr_pct != null ? ` · ${sgn(S.cagr_pct)} a year` : ""), cls(S.pnl))}${kpi("Worst fall from a peak", sgn(S.max_drawdown_pct), "the deepest drop of the account value", "down")}</div>
    <div class="sg-stats sg-kp">${kpi("Trades", String(S.trades), `${(S.win_rate * 100).toFixed(0)}% ended in profit`)}${kpi("Average win · loss", `${sgn(S.avg_win_pct, 2)} · ${sgn(S.avg_loss_pct, 2)}`, `profit factor ${S.profit_factor ?? "--"}`)}${kpi("Costs paid", rupee(S.costs_paid), "brokerage, taxes, charges, spread")}${kpi("Money at work", S.avg_invested_pct != null ? S.avg_invested_pct.toFixed(0) + "%" : "--", `average share of the account in stocks; exits: ${Object.entries(S.exits || {}).filter(([, n]) => n).map(([k, n]) => k + " " + n).join(", ")}`)}</div>
    <div class="sg-card"><h4>Account value over time</h4>${chart}${hist && matched ? `<p class="note">The bot trades only the best-ranked 1%, so on average just ${(ex * 100).toFixed(0)}% of the account is in stocks; the rest sits in a liquid fund at the India call-money rate minus fund costs. The fair comparison is the market held at the same share (middle line). The top dashed line has all its money in stocks every week, so it also carries about twice the worst fall.</p>` : ""}</div>
    <div class="sg-card"><h4>Return by year</h4><ul class="sg-bars">${yrs.map(([y, v]) => `<li><span>${esc(y)}</span><div><i class="${v >= 0 ? "up" : "down"}" style="width:${(Math.abs(v) / mx * 100).toFixed(0)}%"></i></div><em>${sgn(v, 1)}</em></li>`).join("")}</ul></div>
    ${ab}${hist ? `<div class="sg-card"><h4>Most recent trades</h4>${tradesTable(doc.recent_trades)}</div>` : ""}${rulesCard}
    <p class="note">${hist ? "History: ALADIN 1's out-of-sample scores replayed week by week on real prices, stocks listed today (flatters the positive signals), the price goal in the history is a volatility stand-in, idle cash earns the liquid-fund rate, no tax on gains. It shows how the rules behave; it is not a forecast and not live trading." : "Live: simulated trades on real prices from the forward clock. The first weeks prove nothing: judge it after months."} Simulated money, no broker, no real trade. Educational analysis only, not investment advice.</p>`;
}
function paintPaper() {
  const el = root && root.querySelector("#sg-p2"); if (!el) return; el.innerHTML = paperHtml();
  el.querySelectorAll("[data-pm]").forEach(b => b.onclick = () => { st.pmode = b.dataset.pm; paintPaper(); });
  el.querySelectorAll("[data-acct]").forEach(b => b.onclick = () => { st.acct = b.dataset.acct; st.tb = "all"; paintPaper(); });
  el.querySelectorAll("[data-tb]").forEach(b => b.onclick = () => { st.tb = b.dataset.tb; paintPaper(); });
  const csv = el.querySelector("#tb-csv"); const cur = paper && (st.acct === "small" ? paper.small : paper.live); if (csv && cur) csv.onclick = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([tradeBookCsv(cur)], { type: "text/csv" })); a.download = `paper-trades-${st.acct === "small" ? "10k" : "10L"}-${cur.last_price_date || "live"}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); };
  el.querySelectorAll("tr[data-sym]").forEach(tr => { const go = () => { ctx.openSec(tr.dataset.sym); ctx.go("terminal"); }; tr.onclick = go; tr.onkeydown = e => { if (e.key === "Enter") go(); }; });
}
function showPage(p) {
  st.page = p; root.querySelectorAll("[data-page]").forEach(b => { const on = b.dataset.page === p; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  const a = root.querySelector("#sg-p1"), b = root.querySelector("#sg-p2"); if (a) a.hidden = p !== "signals"; if (b) b.hidden = p !== "paper";
  if (p === "paper") { paintPaper(); loadPaper(); }
}

/* How often the rule was right on years it was never chosen on (2021 to 2026), from the weekly study. the positive side carries a weak-evidence warning (owner's choice A, 2026-10-09). */
export function heldOutHtml(rec, bull) {
  const h = rec && rec.held_out; if (!h) return "";
  const ci = h.excess_ci95_bps ? ` (95% range ${h.excess_ci95_bps[0]} to ${h.excess_ci95_bps[1]} bps)` : "";
  const line = `<p class="note">On ${esc(h.years)}, years the rule was not picked on: ${esc(h.right_means)} in <b>${pct0(h.right_rate)}</b> of ${h.n.toLocaleString("en-IN")} stock-weeks, ${h.excess_bps >= 0 ? "+" : ""}${h.excess_bps} bps a week on average${ci}.</p>`;
  return bull && rec.evidence === "weak" ? `<p class="sg-warn"><b>Weak evidence.</b> This side is close to a coin flip after costs; its average could be luck. Size small or skip.</p>${line}` : line;
}
/* ----- the sheet (detail) ----- */
function meter(label, v, ci, n) {
  if (v == null) return `<div class="sg-meter"><div class="sg-ml"><span>${esc(label)}</span><b>not measured</b></div></div>`;
  const lo = ci ? ci[0] : v, hi = ci ? ci[1] : v, pos = x => Math.max(0, Math.min(100, (x - 0.3) / 0.4 * 100));
  return `<div class="sg-meter"><div class="sg-ml"><span>${esc(label)}</span><b>${pct0(v)}</b></div><div class="sg-track" role="img" aria-label="${esc(label)} ${pct0(v)}${ci ? ", 95% range " + pct0(lo) + " to " + pct0(hi) : ""}"><i class="sg-ci" style="left:${pos(lo)}%;width:${Math.max(1, pos(hi) - pos(lo))}%"></i><i class="sg-half" style="left:${pos(0.5)}%"></i><i class="sg-mk" style="left:${pos(v)}%"></i></div>
    <small>${ci ? `95% range ${pct0(lo)} to ${pct0(hi)}` : ""}${n ? ` · ${n.toLocaleString("en-IN")} past stock-weeks` : ""} · the thin line is a coin flip (50%)</small></div>`;
}
function summaryHtml(r) {
  const L = lab(), b = r.book; if (!b) return holdSummary(r);
  const c = b.chance, bull = r.sig === "bull", rec = b.record;
  const tile = (name, big, sub, cls = "") => `<div class="sg-tile ${cls}"><span>${esc(name)}</span><b>${big}</b><small>${sub}</small></div>`;
  const rrText = r.rr == null ? "" : r.rr < 1 ? `<p class="sg-warn">The ${esc((L.goal || "range edge").toLowerCase())} is closer than the ${esc((L.stop || "exit level").toLowerCase())} (reward ${r.rr.toFixed(2)} for each 1 of risk): one win is smaller than one loss, so this only pays if it wins often enough. The chances below say how often it has.</p>` : `<p class="sg-ok">Reward ${r.rr.toFixed(2)} for each 1 of risk.</p>`;
  return `<div class="sg-tiles">${tile(L.signal || "Signal", badge(r.sig), `${bull ? "enter at the next open" : "exit if you hold it; do not add it"} · ${W.book.horizon_trading_days} trading days`)}
      ${tile(L.goal || "Range edge", r.goal != null ? `${inr(r.goal)} <em class="${r.goalPct >= 0 ? "up" : "down"}">${pct(r.goalPct, 1)}</em>` : '<span class="sg-nm">not measured</span>', esc(b.goal_basis || ""))}
      ${tile(L.stop || "Stop loss", r.stop != null ? `${inr(r.stop)} <em class="${r.stopPct >= 0 ? "up" : "down"}">${pct(r.stopPct, 1)}</em>` : '<span class="sg-nm">not measured</span>', esc(b.stop_basis || ""))}</div>${rrText}
    <div class="sg-card"><h4>Chance, from 13 years of out-of-sample history</h4>${c ? meter("Closes higher in 5 trading days", c.closes_higher, c.closes_higher_ci95, c.n_stock_weeks) + meter("Beats the market in 5 trading days", c.beats_market, c.beats_market_ci95, c.n_stock_weeks) : '<p class="note">Not measured for this rank.</p>'}</div>
    <div class="sg-card"><h4>What to do</h4><p>${esc(b.what_to_do)}</p>${bull && b.entry_zone ? `<dl class="sg-dl"><div><dt>Entry zone</dt><dd>${inr(b.entry_zone[0])} to ${inr(b.entry_zone[1])}</dd></div><div><dt>Exit</dt><dd>${esc(b.exit)}</dd></div><div><dt>Round trip cost</dt><dd>${esc(String(b.round_trip_cost_bps))} bps</dd></div>${b.size_for_capital ? `<div><dt>Size for ₹${b.size_for_capital.capital.toLocaleString("en-IN")}</dt><dd>${b.size_for_capital.qty.toLocaleString("en-IN")} shares, ₹${b.size_for_capital.capital_at_risk.toLocaleString("en-IN")} at risk</dd></div>` : ""}</dl>` : ""}</div>
    ${rec ? `<div class="sg-card"><h4>The same signal in the past (history, not live)</h4><dl class="sg-dl"><div><dt>Stock-weeks</dt><dd>${rec.n.toLocaleString("en-IN")}</dd></div><div><dt>Closed higher</dt><dd>${pct0(rec.share_closing_up)}</dd></div>${bull ? `<div><dt>After costs, vs the market</dt><dd>${rec.net_bps >= 0 ? "+" : ""}${rec.net_bps} bps a week</dd></div><div><dt>Years positive</dt><dd>${esc(rec.years_positive_net || "--")}</dd></div>` : `<div><dt>Vs the market, before costs</dt><dd>${rec.gross_excess_bps} bps a week</dd></div><div><dt>Years below the market</dt><dd>${esc(rec.years_below_market || "--")}</dd></div>`}</dl>${heldOutHtml(rec, bull)}</div>` : ""}`;
}
function holdSummary(r) {
  const L = lab(), none = r.sig === "none";
  return `<div class="sg-tiles">${`<div class="sg-tile"><span>${esc(L.signal || "Signal")}</span><b>${badge(r.sig)}</b><small>${none ? "not in the best 1% or worst 5% of the week's ranking" : "too thinly traded to rank for a weekly call"}</small></div>`}
    <div class="sg-tile"><span>${esc(L.goal || "Range edge")}</span><b><span class="sg-nm">--</span></b><small>no signal, no levels</small></div><div class="sg-tile"><span>${esc(L.stop || "Exit level")}</span><b><span class="sg-nm">--</span></b><small>no signal, no levels</small></div></div>
    ${none && r.pu != null ? `<div class="sg-card"><h4>For a typical stock at this rank (${(r.rank * 100).toFixed(0)}th percentile)</h4>${meter("Closes higher in 5 trading days", r.pu, null, null)}${meter("Beats the market in 5 trading days", r.pb, null, null)}<p class="note">Near the middle, the chances are close to a coin flip: that is why ALADIN stays out.</p></div>` : '<p class="note">No weekly call for this stock.</p>'}`;
}
function howHtml(r) {
  const b = r.book, L = lab(), a = ctx.S.aladin && ctx.S.aladin.stocks && ctx.S.aladin.stocks[r.sym];
  const N = W.book.universe.toLocaleString("en-IN"), c = b && b.chance;
  const steps = r.rank == null ? [] : [
    ["Score", `ALADIN 1 gives the stock a 5-day score: a ${pct0(r.book ? r.book.p5 : (a && a.t && a.t.p && a.t.p["5"]))} model chance of closing higher. The rule only compares stocks with each other, so a score under 50% can still be the best of the week.`],
    ["Rank", `Among ${N} liquid stocks it ranks at the ${(r.rank * 100).toFixed(2)}th percentile (higher is better).`],
    ["Rule", r.sig === "bull" ? `It is inside the best 1%, so the signal is ${esc(L.bull)}.` : r.sig === "bear" ? `It is inside the worst 5%, so the signal is ${esc(L.bear)}.` : `It is not in the best 1% or worst 5%, so the signal is ${esc(L.none)}.`],
    ["Chance", c ? `Stocks at this rank closed higher ${pct0(c.closes_higher)} of the time and beat the market ${pct0(c.beats_market)} of the time over 5 trading days.` : `Measured chance for this rank: not measured.`],
    ["Levels", b ? `The ${esc((L.goal || "range edge").toLowerCase())} is the ${esc(b.goal_basis || "not measured")}; the ${esc((L.stop || "exit level").toLowerCase())} is 2 average daily moves from the price.` : "No levels: no signal."],
    ["Cost", b ? `Trading it costs about ${b.round_trip_cost_bps} bps round trip; the signal only counts if the edge is bigger than that.` : "No position, so no cost."]];
  const names = (ctx.S.aladin && ctx.S.aladin.model && ctx.S.aladin.model.names) || {}, nice = n => names[n] || ({ dom: "day of the month", moy: "month of the year", dow: "day of the week" })[n] || n, drv = a && a.t && a.t.drv ? a.t.drv.slice(0, 6).map(([n, v]) => [nice(n), v]) : null, mx = drv ? Math.max(...drv.map(d => Math.abs(d[1])), 1e-9) : 1;
  const inputs = [["Prices and volume (ALADIN 1 technical score)", "In the rule", a && a.t ? `score ${pct0(a.t.p && a.t.p["5"])}` : "not measured"], ["Company fundamentals", "Shown, not in the rule", a && a.f ? `fundamental score ${a.f.sc ?? "not measured"}` : "not measured"],
    ["News sentiment", "Shown, not in the rule", b && b.evidence && b.evidence.sentiment_level ? esc(b.evidence.sentiment_level) : "not measured"], ["Revenue dependencies (NEXUS)", "Shown, not in the rule yet", a && a.x && a.x.i != null ? `impact ${a.x.i}` : "see the next tabs"]];
  return `<div class="sg-card"><h4>The steps</h4><ol class="sg-steps">${steps.map(([t, x], i) => `<li><span>${i + 1}</span><div><b>${esc(t)}</b><p>${x}</p></div></li>`).join("") || '<li><div><p>This stock is not ranked.</p></div></li>'}</ol></div>
    ${drv ? `<div class="sg-card"><h4>What pushed ALADIN 1's score (for this stock)</h4><ul class="sg-bars">${drv.map(([n, v]) => `<li><span>${esc(n)}</span><div><i class="${v >= 0 ? "up" : "down"}" style="width:${(Math.abs(v) / mx * 100).toFixed(0)}%"></i></div><em>${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}</em></li>`).join("")}</ul><p class="note">Longer bar, bigger push. Green pushed the chance up, red pushed it down.</p></div>` : ""}
    <div class="sg-card"><h4>Which inputs are in the rule</h4><table class="sg-mini"><tbody>${inputs.map(([n, s, v]) => `<tr><td>${esc(n)}</td><td><span class="sg-tag ${s === "In the rule" ? "on" : ""}">${esc(s)}</span></td><td>${v}</td></tr>`).join("")}</tbody></table>
      <p class="note">Only the price-and-volume score decides the signal. Fundamentals, sentiment and dependencies were tested against the weekly result and did not improve it (and the dependency data is too new to test properly), so they are shown as context, not used in the rule. When they pass a proper test they will be added.</p></div>`;
}
function rangeHtml(r) {
  if (!A2.loaded(r.sym)) A2.ready(r.sym).then(() => { if (st.sel === r.sym && st.tab === "range") paintSheet(); });
  setTimeout(() => { const el = root.querySelector("#a2-brief"); if (el) A2.bind(el, r.sym); }, 0);
  return `<div class="sg-card a2-embed">${A2.wrap(r.sym)}</div><p class="note">The chart on the Terminal tab draws the same range to the right of the last candle.</p>`;
}
function depsHtml(r) {
  if (!graph) { loadGraph(); return '<p class="note">Loading the dependency graph…</p>'; }
  const d = dependenciesOf(graph, r.sym);
  if (!d || graph.missing) return '<p class="note">The dependency graph is not published yet.</p>';
  const q = s => ctx.S.quotes && ctx.S.quotes[s], row = x => {
    const o = x.other, pq = o.sym ? q(o.sym) : null, u = o.sym && ctx.S.map ? ctx.S.map.get(o.sym) : null;
    return `<li><div class="sg-dh"><b>${esc(x.text)}</b>${x.share != null ? `<span class="sg-tag on">${esc(shareText({ w: x.w, wb: x.wb, wd: x.wd }))}</span>` : '<span class="sg-tag">share not disclosed</span>'}</div>
      <small>${esc(x.period || "period not stated")} · confidence ${x.conf != null ? Math.round(x.conf * 100) + "%" : "n/a"}${pq ? ` · ${esc(o.sym)} ${pct(pq.pct, 1)} today${u && u.r1m != null ? `, ${pct(u.r1m, 1)} in a month` : ""}` : ""}</small>
      ${x.quote ? `<blockquote>“${esc(x.quote)}”</blockquote>` : ""}${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">Filing${x.page ? ", page " + x.page : ""} ↗</a>` : ""}</li>`;
  };
  return `<div class="sg-card"><h4>Who ${esc(r.sym)} depends on, and who depends on it</h4>${d.rows.length ? `<ul class="sg-deps">${d.rows.slice(0, 8).map(row).join("")}</ul>${d.rows.length > 8 ? `<p class="note">${d.rows.length - 8} more in NEXUS.</p>` : ""}`
      : `<p class="note">${d.read ? "The filings were read and no dependency was disclosed." : "Not measured: the filings for this company have not been read yet. NEXUS has read " + (d.done ?? "some") + " of " + (d.total ?? "all") + " listed companies so far."}</p>`}
    <div class="sg-actions"><button type="button" class="btn-ink" id="sg-nx">Open the full supply-chain view →</button></div>
    <p class="note">Every link carries its filing, page and a verbatim quote. A move in a linked stock is an association, not proof of cause. Dependencies are not part of the signal rule yet: see "How it was made".</p></div>`;
}

function sheetHtml(r) {
  const tab = TABS.find(t => t[0] === st.tab) ? st.tab : "summary", b = r.book;
  const body = tab === "summary" ? summaryHtml(r) : tab === "how" ? howHtml(r) : tab === "range" ? rangeHtml(r) : depsHtml(r);
  return `<div class="sg-back" data-close="1"></div><aside class="sg-sheet" role="dialog" aria-modal="true" aria-label="${esc(r.sym)} details">
    <header><div><h3>${esc(r.sym)} ${badge(r.sig)}</h3><p>${esc(r.name || "")}${r.sector ? " · " + esc(r.sector) : ""} · close ${inr(r.close)}</p></div><div class="sg-hbtns"><button type="button" class="btn-line sm" id="sg-chart">Open chart</button><button type="button" class="sg-x" data-close="1" aria-label="Close">×</button></div></header>
    <nav class="sg-tabs" role="tablist">${TABS.map(([k, t]) => `<button type="button" role="tab" data-t="${k}" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}">${esc(t)}</button>`).join("")}</nav>
    <div class="sg-body">${body}</div><footer>${DISCLAIMER}</footer></aside>`;
}
function currentRow() {
  const { rows } = buildRows(W, ctx.S.uni ? ctx.S.uni.stocks : [], { q: st.sel, filter: "all", limit: 5 });
  return rows.find(r => r.sym === st.sel) || null;
}
function paintSheet() {
  const host = root && root.querySelector("#sg-sheet-host"); if (!host) return;
  const r = st.sel && W ? currentRow() : null;
  if (!r) { host.innerHTML = ""; document.documentElement.classList.remove("sg-lock"); return; }
  const keep = host.querySelector(".sg-body"), top = keep ? keep.scrollTop : 0;
  host.innerHTML = sheetHtml(r); document.documentElement.classList.add("sg-lock");
  const nb = host.querySelector(".sg-body"); if (nb) nb.scrollTop = top;
  host.querySelectorAll("[data-close]").forEach(b => b.onclick = close);
  host.querySelectorAll("[data-t]").forEach(b => b.onclick = () => { st.tab = b.dataset.t; if (nb) nb.scrollTop = 0; paintSheet(); });
  const ch = host.querySelector("#sg-chart"); if (ch) ch.onclick = () => { const s = st.sel; close(); ctx.openSec(s); ctx.go("terminal"); };
  const nx = host.querySelector("#sg-nx"); if (nx) nx.onclick = () => { import("./desk-nexus.js").then(m => m.openNexus({ type: "company", id: st.sel })); };
  const sheet = host.querySelector(".sg-sheet"); if (sheet) { sheet.focus?.(); }
}
function open(sym, tab) { st.sel = sym; st.tab = tab || "summary"; paintSheet(); const x = root.querySelector(".sg-x"); if (x) x.focus(); root.querySelectorAll("#sg-list tbody tr").forEach(tr => tr.classList.toggle("on", tr.dataset.sym === sym)); }
function close() { st.sel = null; paintSheet(); root.querySelectorAll("#sg-list tbody tr.on").forEach(tr => tr.classList.remove("on")); }

function paintList() {
  const el = root.querySelector("#sg-list"); if (!el) return; el.innerHTML = listHtml();
  el.querySelectorAll("tbody tr").forEach(tr => { tr.onclick = () => open(tr.dataset.sym); tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(tr.dataset.sym); } }; });
}
function bind() {
  root.querySelectorAll("[data-page]").forEach(b => b.onclick = () => showPage(b.dataset.page));
  const q = root.querySelector("#sg-q"); if (q) q.oninput = () => { st.q = q.value; paintList(); };
  if (q) q.onkeydown = e => { if (e.key === "Enter") { const tr = root.querySelector("#sg-list tbody tr"); if (tr) open(tr.dataset.sym); } };
  root.querySelectorAll("[data-f]").forEach(b => b.onclick = () => { st.filter = b.dataset.f; root.querySelectorAll("[data-f]").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); }); paintList(); });
}
export async function mount() {
  root = document.getElementById("signals"); if (!root) return;
  if (!document.__sgKey) { document.__sgKey = true; document.addEventListener("keydown", e => { if (e.key === "Escape" && st.sel && root && root.isConnected) close(); }); }
  if (!W) { root.innerHTML = '<p class="note">Loading…</p>'; await load(); }
  const q0 = root.querySelector("#sg-q"), had = q0 && q0.value;
  root.innerHTML = shell(); bind(); paintList(); if (st.page === "paper") showPage("paper"); if (had) root.querySelector("#sg-q").value = had; paintSheet();
}
export const _test = { reset: () => { W = null; graph = null; failed = false; loading = null; st.q = ""; st.filter = "all"; st.sel = null; st.tab = "summary"; }, set: (w, g) => { W = w; graph = g; } };
