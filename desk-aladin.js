/* TOOLS tab / ALADIN: probability model view.
   Data (aladin.json, sentiment.json, paper.json, houses.json, aladin_method.json) is fetched by this module: a few seconds after the
   desk starts (preload(), for the Details rail and Brief card) or when the tab first opens, never at page start.
   P(up) in the table is recomputed in the browser with combine(): the nightly Technical and Fundamental scores plus the CURRENT
   sentiment and, while the local tick feed runs, the live sweep score. Price, change and P(up) cells of the visible rows are patched in
   place (textContent only) when ticks arrive.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. */
import { onTick } from "./desk-ticks.js";

let ctx = null, opened = false, filterSym = null, loading = null, failed = null;
const st = { h: 10, view: "up", board: "All", sector: "", house: "", sent: "", conf: "", q: "", sort: null, limit: 50 };
const expanded = new Set();
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice.";
const LEVELS = ["BAD", "POOR", "NEUTRAL", "GOOD", "EXCELLENT"];
const MATCH = { symbol: "symbol", name: "company name", group: "business group" };
const FETCHED = { aladin: 0, sentiment: 0 };

/* The ALADIN combiner. Identical to combine_py() in scripts/aladin_model.py: both must pass tests/fixtures/combiner_cases.json.
   logit(p) = logit(p_tech) + wF F/100 + wS S/100 + wSweep S_sweep/100. A missing front (null/undefined) contributes 0. p is clipped to [0.02, 0.98].
   confidence: Low if |p-0.5| < 0.03, Medium if < 0.07, else High.
   agreement: of the AVAILABLE fronts (F, T, S) how many lean the same way as p (a front leans up above +10, down below -10, with 1e-9 of slack so
   floating-point noise like 200*(0.55-0.5) = 10.000000000000009 does not count as "above 10"): "k/n". */
export function combine(pTech, F, S, sSweep, w) {
  w = w || { wF: 0.20, wS: 0.12, wSweep: 0.18 };
  const T = Math.max(-100, Math.min(100, 200 * (pTech - 0.5)));
  const q = Math.min(0.999999, Math.max(1e-6, pTech));
  const z = Math.log(q / (1 - q)) + w.wF * (F ?? 0) / 100 + w.wS * (S ?? 0) / 100 + w.wSweep * (sSweep ?? 0) / 100;
  const p = Math.min(0.98, Math.max(0.02, 1 / (1 + Math.exp(-z))));
  const fronts = [F, T, S].filter(x => x !== null && x !== undefined);
  const up = p > 0.5, EPS = 1e-9, k = fronts.filter(x => (x > 10 + EPS && up) || (x < -10 - EPS && !up)).length, d = Math.abs(p - 0.5);
  return { p: Math.round(p * 1e4) / 1e4, q: Math.round((1 - p) * 1e4) / 1e4, T: Math.round(T * 10) / 10,
    conf: d < 0.03 ? "Low" : d < 0.07 ? "Medium" : "High", agree: `${k}/${fronts.length}`, agree_k: k, agree_n: fronts.length };
}

export function init(c) {
  ctx = c;
  onTick(onBatch);
  document.addEventListener("click", e => {                                           // "Open in ALADIN →" links in the Details rail
    const a = e.target.closest && e.target.closest("[data-aladin]");
    if (a) { e.preventDefault(); setAladinFilter(a.dataset.aladin); ctx.go("lab"); }
  });
}

/* ---------- data ---------- */
const files = () => ctx.S.deskMan || {};
async function fetchInto(key, file, bust = true) {
  if (!files()[key]) return null;
  try { const j = await ctx.getJSON(file, bust); ctx.S[key] = j; return j; } catch (e) { return null; }
}
export async function preload() {
  if (!ctx || !files().aladin) return null;
  loading = loading || Promise.all([
    ctx.S.aladin ? 0 : fetchInto("aladin", "aladin.json").then(() => { FETCHED.aladin = Date.now(); }),
    ctx.S.sentiment ? 0 : fetchInto("sentiment", "sentiment.json").then(() => { FETCHED.sentiment = Date.now(); }),
    ctx.S.paper ? 0 : fetchInto("paper", "paper.json"),
    ctx.S.method ? 0 : fetchInto("method", "aladin_method.json", false),
  ]).catch(e => { failed = e.message; }).finally(() => { loading = null; });
  await loading;
  return ctx.S.aladin || null;
}
export async function refresh() {                                                       // called by the page's 1-minute poll once the data has been loaded
  if (!ctx || !ctx.S.aladin) return;
  const now = Date.now();
  const sent = files().sentiment ? await ctx.getJSON("sentiment.json").catch(() => null) : null;
  let changed = false;
  if (sent && sent.generated_utc !== (ctx.S.sentiment || {}).generated_utc) { ctx.S.sentiment = sent; changed = true; }
  if (files().aladin && now - FETCHED.aladin > 30 * 60000) {                            // the model file changes once a night: check twice an hour at most
    FETCHED.aladin = now;
    const a = await ctx.getJSON("aladin.json").catch(() => null);
    if (a && a.generated_utc !== ctx.S.aladin.generated_utc) { ctx.S.aladin = a; changed = true; }
    const p = files().paper ? await ctx.getJSON("paper.json").catch(() => null) : null;
    if (p && p.meta && p.meta.updated_utc !== ((ctx.S.paper || {}).meta || {}).updated_utc) { ctx.S.paper = p; changed = true; }
  }
  if (changed) { if (document.getElementById("v-lab").classList.contains("on")) draw(); ctx.renderRegimeBrief && ctx.renderRegimeBrief(); }
}
async function loadHouses() {
  if (ctx.S.houses || !files().houses) return;
  try { ctx.S.houses = await ctx.getJSON("houses.json", false); } catch (e) { /* house filter simply stays empty */ }
}

/* ---------- small helpers ---------- */
const W = () => { const w = (ctx.S.aladin || {}).weights; return w ? { wF: w.wF, wS: w.wS, wSweep: w.wSweep } : undefined; };
const sentOf = sym => ((ctx.S.sentiment || {}).stocks || {})[sym] || null;
const sweepOf = sym => ((ctx.S.sweep || {})[sym]);
const pctTxt = v => v == null ? "—" : Math.round(v * 100) + "%";
function reasonNoProb(u) { return u.etf ? "ETF: no probability needed here" : "Not enough price history (fewer than 250 daily bars) or no recent trading"; }
function fundText(u, a) {
  if (u.board === "SME") return { t: "not covered", why: "SME stocks have no fundamental coverage" };
  if (u.etf) return { t: "n/a", why: "Not applicable to an ETF" };
  if (a && a.f && a.f.sc != null) return null;
  return { t: "—", why: "No Yahoo statements loaded for this stock yet (they rotate in about 400 a night)" };
}

/* the combined view of one stock for the chosen horizon */
function calc(sym, h) {
  const a = (ctx.S.aladin || {}).stocks && ctx.S.aladin.stocks[sym];
  if (!a || !a.t || !a.t.p || a.t.p[h] == null) return null;
  const F = a.f && a.f.sc != null ? a.f.sc : null, sn = sentOf(sym), S = sn ? sn.sc : null, sw = sweepOf(sym);
  const r = combine(a.t.p[h], F, S, sw == null ? null : sw, W());
  return { ...r, F, S, sw, Th: r.T };
}

function gauge(sc, why) {
  if (sc == null) return `<span class="mut al-na" title="${ctx.esc(why || "Not measured")}">—</span>`;
  const v = Math.max(-100, Math.min(100, sc));
  return `<span class="al-g" title="${v > 0 ? "+" : ""}${Math.round(v)} on a scale of -100 to +100"><i class="mid"></i><b class="${v > 5 ? "up" : v < -5 ? "down" : "flat"}" style="left:${50 + v / 2}%"></b></span><span class="al-gv ${ctx.ud(v)}">${v > 0 ? "+" : ""}${Math.round(v)}</span>`;
}
function dots(k, n) { return n ? "●".repeat(k) + "○".repeat(n - k) : "—"; }
function covHtml(a) {
  if (!a) return "";
  const c = a.cov || {};
  const part = (l, v, why) => `<b class="${v ? "" : "off"}" title="${ctx.esc(why)}">${l}</b>`;
  return `<span class="al-cov">${part("T", c.t, "Technical view")}${part("F", c.f, c.f ? `Fundamental view, ${Math.round(c.f * 100)}% of its parts present` : "Fundamental view not available")}${part("S", c.s, c.s ? "Sentiment view" : "No headline in the last 72 hours")}</span>`;
}
function sweepHtml(sym) {
  const sc = sweepOf(sym);
  if (sc == null || Math.abs(sc) < 1) return "—";
  const ev = (ctx.S.sweepEv || []).filter(e => e.sym === sym).slice(-1)[0];
  return `${sc > 0 ? "▲" : "▼"} ${Math.abs(Math.round(sc))}${ev ? (ev.confirmed ? " confirmed" : " forming") : ""}`;
}

/* ---------- sentiment bar (markup as specified) ---------- */
function sentHtml(sym, compact, open) {
  const e = sentOf(sym), esc = ctx.esc, lvl = e ? e.lvl : "NO NEWS";
  const segs = "<i></i>".repeat(5);
  const sum = e ? `+${Math.round(e.sc)}`.replace("+-", "−") : "";
  let list;
  if (!e) list = `<li class="mut">No headline named this company in the last 72 hours, so there is no sentiment score. It is not treated as neutral.</li>`;
  else {
    const p = e.parts || {}, fmt = v => v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(Math.round(v * 100));
    list = (e.items || []).map(([t, u, src, age, s, m]) => `<li><span class="al-chip ${ctx.ud(s)}">${s >= 0 ? "+" : "−"}${Math.abs(Math.round(s * 100))}</span><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(t)}</a><span class="mut"> · ${esc(src || "")} · ${esc(ctx.agoTxt(age))} · matched by ${esc(MATCH[m] || m)}</span></li>`).join("")
      + `<li class="mut">news ${fmt(p.news)} · retail ${fmt(p.retail)}${e.rn ? ` (${e.rn} authors)` : ""} · flow ${fmt(p.flow)}</li>`
      + `<li class="mut">Geopolitical adjustment ${e.geo ? (e.geo > 0 ? "+" : "−") + Math.abs(Math.round(e.geo * 100)) + " points" : "none"}</li>`;
  }
  const head = e ? `${sum} · ${e.n} headline${e.n === 1 ? "" : "s"}` : "no headline in 72 h";
  return `<details class="sent${compact ? " compact" : ""}" data-lvl="${esc(lvl)}"${open ? " open" : ""}><summary><span class="sent-bar">${segs}</span><b class="sent-lbl">${esc(lvl)}</b><span class="mut">${esc(head)}</span></summary><ul class="sent-list">${list}</ul></details>`;
}

/* ---------- row building, filtering, sorting ---------- */
function allRows() {
  const A = ctx.S.aladin;
  return ctx.S.uni.stocks.map(u => ({ u, sym: u.s, a: A && A.stocks ? A.stocks[u.s] : null }));
}
function houseSet() {
  const h = ((ctx.S.houses || {}).houses || []).find(x => x.id === st.house);
  return h ? new Set(h.symbols) : null;
}
function visibleRows() {
  const hs = st.house ? houseSet() : null, q = st.q.trim().toUpperCase();
  let rows = allRows();
  rows = rows.filter(r => {
    const u = r.u;
    if (st.board === "NIFTY 500" && !u.n500) return false;
    if (st.board === "Main" && (u.board !== "Main" || u.etf)) return false;
    if (st.board === "SME" && u.board !== "SME") return false;
    if (st.board === "ETFs" && !u.etf) return false;
    if (st.sector && u.ind !== st.sector) return false;
    if (hs && !hs.has(r.sym)) return false;
    if (q && !(r.sym.includes(q) || (u.n || "").toUpperCase().includes(q))) return false;
    return true;
  });
  rows.forEach(r => { r.c = calc(r.sym, st.h); r.sn = sentOf(r.sym); });
  if (st.sent) rows = rows.filter(r => st.sent === "NO NEWS" ? !r.sn : r.sn && r.sn.lvl === st.sent);
  if (st.conf) rows = rows.filter(r => r.c && r.c.conf === st.conf);
  const withP = rows.filter(r => r.c), noP = rows.filter(r => !r.c);
  const by = (f, dir = 1) => (a, b) => dir * ((f(a) ?? -1e9) - (f(b) ?? -1e9));
  const keys = { sym: r => r.sym, n: r => r.u.n, last: r => (ctx.q(r.sym) || {}).p, chg: r => (ctx.q(r.sym) || {}).pct, pup: r => r.c && r.c.p, pdn: r => r.c && r.c.q, F: r => r.c && r.c.F,
    T: r => r.c && r.c.T, S: r => r.c && r.c.S, sw: r => sweepOf(r.sym), agree: r => r.c && r.c.agree_k, conf: r => r.c && ({ Low: 0, Medium: 1, High: 2 })[r.c.conf], cov: r => r.a && ((r.a.cov.f || 0) + (r.a.cov.t || 0) + (r.a.cov.s || 0)) };
  let list;
  if (st.sort) {
    const [k, d] = st.sort, f = keys[k];
    list = (k === "sym" || k === "n") ? withP.concat(noP).sort((a, b) => d * String(f(a) || "").localeCompare(String(f(b) || ""))) : withP.sort(by(f, d)).concat(noP);
  } else if (st.view === "up") list = withP.sort(by(r => r.c.p, -1));
  else if (st.view === "down") list = withP.sort(by(r => r.c.p, 1));
  else if (st.view === "agree") list = withP.sort((a, b) => b.c.agree_k - a.c.agree_k || Math.abs(b.c.p - 0.5) - Math.abs(a.c.p - 0.5));
  else list = withP.sort(by(r => r.c.p, -1)).concat(noP);
  return list;
}

function rowHtml(r, i) {
  const { esc, inr, sg, ud } = ctx, u = r.u, x = ctx.q(r.sym), c = r.c, a = r.a, ft = fundText(u, a);
  const open = expanded.has(r.sym);
  const tag = (u.board === "SME" ? ' <span class="tag warn">SME</span>' : "") + (u.etf ? ' <span class="tag">ETF</span>' : "");
  const pup = c ? ctx.probBar(c.p) : `<span class="mut" title="${esc(reasonNoProb(u))}">no probability</span>`;
  const first = `<tr class="al-r${open ? " on" : ""}" data-s="${esc(r.sym)}"><td class="mut">${i + 1}</td><td class="sym"><button class="al-tg" aria-expanded="${open}" aria-label="${open ? "Hide" : "Show"} details for ${esc(r.sym)}">${open ? "▾" : "▸"}</button> ${esc(r.sym)}${tag}</td><td class="co al-hide2">${esc(u.n || "")}</td>
    <td class="num al-last">${x ? inr(x.p) : "—"}</td><td class="num al-chg ${x ? ud(x.pct) : "mut"}">${x && x.pct != null ? sg(x.pct) + "%" : "—"}</td>
    <td class="num al-pup">${pup}</td><td class="num al-pdn al-hide">${c ? pctTxt(c.q) : "—"}</td>
    <td class="al-gc">${ft ? `<span class="mut" title="${esc(ft.why)}">${esc(ft.t)}</span>` : gauge(a.f.sc)}</td><td class="al-gc">${c ? gauge(c.T) : '<span class="mut">—</span>'}</td>
    <td class="al-sc">${sentHtml(r.sym, true)}</td><td class="al-sw al-hide">${sweepHtml(r.sym)}</td><td class="al-ag al-hide" title="How many of the available views lean the same way as P(up)">${c ? dots(c.agree_k, c.agree_n) : "—"}</td>
    <td class="al-hide">${c ? `<span class="tag${c.conf === "High" ? " acc" : ""}">${c.conf}</span>` : "—"}</td><td class="al-hide">${covHtml(a)}</td></tr>`;
  return first + (open ? `<tr class="al-x"><td colspan="14">${detailHtml(r)}</td></tr>` : "");
}

/* ---------- row expansion ---------- */
function zbar(label, z, note) {
  if (z == null) return `<div class="al-z"><span>${label}</span><span class="mut">not measured</span></div>`;
  const v = Math.max(-3, Math.min(3, z));
  return `<div class="al-z"><span>${label}</span><span class="al-zt"><i class="mid"></i><b class="${z > 0.15 ? "up" : z < -0.15 ? "down" : "flat"}" style="left:${50 + v / 6 * 100}%"></b></span><b class="${ctx.ud(z)}">${z > 0 ? "+" : ""}${z.toFixed(2)}</b></div>${note ? `<div class="al-zn mut">${note}</div>` : ""}`;
}
const num = (v, d = 2) => v == null || !isFinite(v) ? "—" : Number(v).toFixed(d);
const pc1 = v => v == null ? "—" : (v * 100).toFixed(1) + "%";
function detailHtml(r) {
  const { esc } = ctx, a = r.a, u = r.u;
  if (!a) return `<p class="note">${esc(reasonNoProb(u))}. This row stays searchable but is left out of the rankings.</p>${actions(r.sym)}`;
  const f = a.f, t = a.t, c = r.c;
  const raw = (f && f.raw) || {}, d = f && f.dist, al = (f && f.alt) || {}, nl = f && f.nlp;
  const fund = !f ? `<p class="mut">${esc(fundText(u, a)?.why || "No fundamental data for this stock.")}</p>`
    : `${zbar("Value", f.v, `EBIT/EV ${pc1(raw.ebit_ev)} · FCF/mcap ${pc1(raw.fcf_mcap)} · book/price ${num(raw.book_price)}`)}${zbar("Quality", f.q, `ROIC ${pc1(raw.roic)} · ROE ${pc1(raw.roe)} · accruals ${pc1(raw.accrual)}`)}${zbar("Momentum", f.m, `Revenue acceleration ${pc1(raw.rev_acc)} · margin change ${pc1(raw.opm_chg)}`)}
      <div class="sec-t">Distress</div>${d ? `<p>${esc(d.band)} · distance to default ${num(d.dd, 1)} · default probability ${d.pd == null ? "—" : (d.pd * 100).toFixed(2) + "%"} · Altman Z″ ${num(d.z2, 1)}</p>` : `<p class="mut">Not applicable (${f.fin ? "financial company" : "no debt"})</p>`}
      <div class="sec-t">Filings</div>${nl ? `<p>Tone ${nl.tone > 0 ? "+" : ""}${num(nl.tone)} · hedging ${nl.hedge == null ? "—" : Math.round(nl.hedge * 100) + "%"}${nl.qa != null ? ` · Q&amp;A gap ${nl.qa > 0 ? "+" : ""}${num(nl.qa)}` : ""} · ${nl.n} announcements${nl.src ? ` · <a href="${esc(nl.src)}" target="_blank" rel="noopener noreferrer">transcript</a>` : ""}</p>` : `<p class="mut">No announcements scored</p>`}
      <div class="sec-t">Delivery and deals</div><p>Delivery % (20-day vs 120-day) ${al.deliv == null ? "—" : (al.deliv > 0 ? "+" : "") + (al.deliv * 100).toFixed(1) + "%"} · bulk/block deals, 30-day net ${al.bulk_cr == null ? "—" : "₹" + num(al.bulk_cr, 1) + " Cr"}</p>`;
  const nm = ((ctx.S.method || {}).not_measured || [["Satellite imagery", "No free source."], ["Card-spend data", "No free source."], ["Job postings", "The sites' terms forbid scraping."], ["ESG scores", "No free source."]])
    .map(([n, w]) => `<li class="mut">${esc(n)}: not measured. ${esc(w)}</li>`).join("");
  const A = ctx.S.aladin, ph = Object.keys(t.p).sort((x, y) => x - y).map(h => `${h}D <b>${pctTxt(t.p[h])}</b>`).join(" · ");
  const jp = t.jump;
  const tech = `<p>${ph}</p>
      <p>Market-factor residual z ${t.pca_z == null ? "—" : num(t.pca_z)} · market turbulence ${pctTxt(t.hmm)}</p>
      <p>${t.coint ? `Peer ${esc(t.coint.peer)}: spread z ${num(t.coint.z)} · half-life ${t.coint.hl == null ? "—" : num(t.coint.hl, 1) + " d"} · Kalman β ${num(t.coint.beta)}` : '<span class="mut">No cointegrated peer found</span>'}</p>
      <p>${jp ? `Jumps: ${num(jp.lam, 1)} a year · average ${(jp.mj * 100).toFixed(1)}% · spread ${(jp.sj * 100).toFixed(1)}% · last ${jp.last == null ? "none in 250 days" : jp.last + " days ago"} · variance share ${jp.bv == null ? "—" : Math.round(jp.bv * 100) + "%"}` : '<span class="mut">Jump statistics not available</span>'}</p>
      <p class="mut">LSTM: not tried in this build</p><div class="sec-t">What moved it most</div><div>${ctx.driversHtml(t.drv, 5) || '<span class="mut">—</span>'}</div>`;
  const evs = (ctx.S.sweepEv || []).filter(e => e.sym === r.sym).slice(-5).reverse();
  const sent = `${sentHtml(r.sym, false, true)}
      <div class="sec-t">Liquidity sweeps</div>${evs.length ? evs.map(e => `<p>${e.dir > 0 ? "▲" : "▼"} ${esc(e.lvl)} at ${num(e.px)} · volume ${num(e.rvol, 1)}× normal · wick ${Math.round(e.wick * 100)}% · ${e.confirmed ? "confirmed" : "forming"} · score ${e.score > 0 ? "+" : ""}${e.score}</p>`).join("") : `<p class="mut">No sweep seen. Needs the local tick program; the free feed covers only index levels and NSE's movers lists.</p>`}`;
  return `<div class="al-x3"><div><div class="sec-t">Fundamental</div>${fund}<ul class="al-nm">${nm}</ul></div><div><div class="sec-t">Technical · ${st.h}D</div>${tech}</div><div><div class="sec-t">Sentimental</div>${sent}</div></div>${actions(r.sym)}`;
}
function actions(sym) {
  const on = ctx.loadWatch().includes(sym);
  return `<div class="al-act"><button class="btn-line sm" data-open="${ctx.esc(sym)}">Open chart</button> <button class="btn-line sm${on ? " on" : ""}" data-wl="${ctx.esc(sym)}">${on ? "✓ In watchlist" : "+ Watchlist"}</button></div>`;
}

/* ---------- the tab ---------- */
function methodText() {
  const M = ctx.S.method;
  if (!M) return '<p class="note">The methodology text could not be loaded.</p>';
  return M.sections.map(s => `<h6>${ctx.esc(s.h)}</h6>${s.p.map(p => `<p class="note">${ctx.esc(p)}</p>`).join("")}`).join("")
    + `<h6>Not measured, and why</h6><ul class="al-nm">${M.not_measured.map(([n, w]) => `<li class="mut">${ctx.esc(n)}: ${ctx.esc(w)}</li>`).join("")}</ul>`;
}
function modelCard() {
  const A = ctx.S.aladin, { esc } = ctx, o = (A.oos || {})[st.h];
  if (!o) return `<p class="note">No out-of-sample record for the ${st.h}-day horizon.</p>`;
  const m = o.metrics, P = ctx.S.paper || {}, dc = P.decile || {};
  const yrs = (o.years || []).map(y => `<tr><td>${y.year}</td><td class="num">${y.auc == null ? "—" : y.auc.toFixed(3)}</td><td class="num">${pctTxt(y.acc)}</td><td class="num">${pctTxt(y.base)}</td><td class="num">${pctTxt(y.top_hit)}</td><td class="num">${pctTxt(y.bot_hit)}</td></tr>`).join("");
  const cal = (o.calibration || []).map(c => `<div class="cal-b" title="Predicted ${pctTxt(c.pred)} → actually ${pctTxt(c.actual)} (${c.n.toLocaleString("en-IN")} cases)"><i class="pr" style="height:${Math.round(c.pred * 100)}%"></i><i class="ac" style="height:${Math.round(c.actual * 100)}%"></i><span>${pctTxt(c.pred)}</span></div>`).join("");
  const w = A.weights, nAll = ctx.S.uni.stocks.length, nP = Object.keys(A.stocks).length;
  const live = dc.matured_days ? `${pctTxt(dc.top_hit)} up in top decile` : "—";
  const edge = m.accuracy - m.base_rate;
  return `<div class="ol-grid">
      <div class="ol-stat"><b>${pctTxt(m.accuracy)}</b><span>right on unseen years<br><small>base rate (share that went up): ${pctTxt(m.base_rate)} · ${edge >= 0 ? "+" : "−"}${Math.abs(edge * 100).toFixed(1)} points</small></span></div>
      <div class="ol-stat"><b>${m.auc.toFixed(3)}</b><span>AUC out of sample<br><small>0.500 = no skill</small></span></div>
      <div class="ol-stat"><b>${m.brier.toFixed(4)}</b><span>Brier score<br><small>forecasting the base rate: ${m.brier_base.toFixed(4)} (lower is better)</small></span></div>
      <div class="ol-stat"><b>${pctTxt(m.top_decile_hit)}</b><span>top 10% went up<br><small>bottom 10%: ${pctTxt(m.bottom_decile_hit)}</small></span></div>
      <div class="ol-stat"><b>${live}</b><span>live track record<br><small>${dc.matured_days ? `${dc.matured_days} days scored, spread ${(dc.spread * 100).toFixed(2)}% (top minus bottom 10%)` : "first results about two weeks after the nightly run starts saving predictions"}</small></span></div>
    </div>
    <p class="note">${nAll.toLocaleString("en-IN")} securities · ${nP.toLocaleString("en-IN")} with a probability. Weights: <b>${esc(w.mode)}</b> (Fundamental ${w.wF}, Sentiment ${w.wS}, sweeps ${w.wSweep}${w.sweep_validated ? "" : ", sweep weight unvalidated"}). Regime blend: ${m.regime && m.regime.used ? "used" : m.regime && m.regime.tested ? "tested, not better, not used" : "not tested"}. Model data as of ${esc(A.as_of)} · ${esc(A.model.features)} inputs · trained on ${A.model.trained_stocks} stocks.</p>
    <details class="ol-more"><summary>How good is this model? (tested ${esc(m.from)} → ${esc(m.to)}, ${m.n.toLocaleString("en-IN")} predictions it never saw) and how it works</summary>
      <div class="ol-two"><div><h6>By year (each year predicted by models trained only on earlier years)</h6>
        <table class="tbl sm"><thead><tr><th>Year</th><th class="r">AUC</th><th class="r">Right</th><th class="r">Base rate</th><th class="r">Top 10% up</th><th class="r">Bottom 10% up</th></tr></thead><tbody>${yrs}</tbody></table></div>
        <div><h6>Calibration: 10 equal groups from lowest to highest probability. Predicted (dark) vs what happened (bright)</h6><div class="cal">${cal}</div>
        <p class="note">Information coefficient ${m.ic_mean} (t ${m.ic_t}). Years where the "Right" figure is below the base rate are years the model did worse than always saying "up".</p></div></div>
      ${methodText()}</details>`;
}
function paperLog() {
  const P = ctx.S.paper, { esc, inr } = ctx;
  if (!P) return "";
  const s = P.stats || {}, dc = P.decile || {}, n = (P.meta || {}).signals_today;
  const row = (x, closed) => `<tr data-s="${esc(x.sym)}"><td class="sym">${esc(x.sym)}</td><td>${esc(x.entry_date)}</td><td class="num">${inr(x.entry_px)}</td><td class="num">${pctTxt(x.p_up)}</td>${closed ? `<td>${esc(x.exit_date)}</td><td class="num">${inr(x.exit_px)}</td><td class="num ${ctx.ud(x.net_ret)}">${ctx.sg(x.net_ret * 100)}%</td><td class="num ${ctx.ud(x.excess)}">${x.excess == null ? "—" : ctx.sg(x.excess * 100) + "%"}</td>` : `<td>${esc(x.due_date)}${x.due_estimated ? " (est.)" : ""}</td>`}</tr>`;
  const open = (P.open || []).map(x => row(x, false)).join("") || '<tr><td colspan="5" class="empty">No open positions.</td></tr>';
  const closed = (P.closed || []).slice().reverse().slice(0, 30).map(x => row(x, true)).join("") || '<tr><td colspan="8" class="empty">No closed trades yet.</td></tr>';
  const pend = (P.pending || []).length ? `<p class="note">Waiting for the next session's open: ${(P.pending || []).map(p => esc(p.sym)).join(", ")}</p>` : "";
  return `<div class="sec-t" style="margin-top:26px">Paper log</div>
    <p class="note"><b>Simulated. Not real trades.</b> Costs of 0.5% round trip assumed. Signals need 10-day P(up) above 60%, High confidence and 3 of 3 views agreeing; the bar is not lowered. ${n === 0 ? "No stock qualified on the latest run." : n != null ? `${n} stock${n === 1 ? "" : "s"} qualified on the latest run.` : ""}</p>
    <div class="ol-grid al-pstats"><div class="ol-stat"><b>${s.open ?? 0}</b><span>open</span></div><div class="ol-stat"><b>${s.closed ?? 0}</b><span>closed</span></div>
      <div class="ol-stat"><b>${s.net_win_rate == null ? "—" : pctTxt(s.net_win_rate)}</b><span>net win rate</span></div><div class="ol-stat"><b class="${ctx.ud(s.mean_excess)}">${s.mean_excess == null ? "—" : ctx.sg(s.mean_excess * 100) + "%"}</b><span>average excess vs NIFTY 50</span></div>
      <div class="ol-stat"><b>${dc.matured_days ? ctx.sg(dc.spread * 100) + "%" : "—"}</b><span>decile spread<br><small>${dc.matured_days ? `${dc.matured_days} days of saved predictions` : "not yet measured"}</small></span></div></div>${pend}
    <div class="ol-two"><div class="tablecard"><table class="tbl sm"><thead><tr><th>Open</th><th>Entry</th><th class="r">Entry px</th><th class="r">P(up)</th><th>Exit due</th></tr></thead><tbody>${open}</tbody></table></div>
      <div class="tablecard"><table class="tbl sm"><thead><tr><th>Closed</th><th>Entry</th><th class="r">In</th><th class="r">P(up)</th><th>Exit</th><th class="r">Out</th><th class="r">Net</th><th class="r">Excess</th></tr></thead><tbody>${closed}</tbody></table></div></div>
    <p class="note">As of ${esc(P.meta.updated_utc ? ctx.istUtc(P.meta.updated_utc) : "—")} · model data ${esc(P.meta.aladin_as_of || "—")}</p>`;
}

const SORTS = [["sym", "Symbol"], ["n", "Company"], ["last", "Last"], ["chg", "Chg %"], ["pup", "P(up)"], ["pdn", "P(down)"], ["F", "Fundamental"], ["T", "Technical"], ["S", "Sentiment"], ["sw", "Sweep"], ["agree", "Agree"], ["conf", "Conf"], ["cov", "Cov"]];

export function setAladinFilter(sym) {
  filterSym = sym || null;
  if (sym) { st.q = sym; st.view = "all"; st.sort = null; st.board = "All"; st.sector = ""; st.house = ""; st.sent = ""; st.conf = ""; expanded.add(sym); }
}
export async function renderAladin() {
  if (!ctx) return;
  const el = ctx.$("#aladin"); if (!el) return;
  if (!ctx.S.aladin) {
    if (!files().aladin) { el.innerHTML = `<p class="empty">ALADIN is not available: aladin.json has not been published yet. The model runs after each NSE close.</p>${foot()}`; return; }
    el.innerHTML = '<p class="empty">Loading ALADIN…</p>';
    await Promise.all([preload(), loadHouses()]);
    if (!ctx.S.aladin) { el.innerHTML = `<p class="empty">ALADIN could not be loaded${failed ? ": " + ctx.esc(failed) : ""}. Nothing is shown in its place.</p>${foot()}`; return; }
  }
  await loadHouses();
  opened = true;
  draw();
}
const foot = () => `<p class="note al-foot">${DISCLAIMER}</p>`;

function draw() {
  const el = ctx.$("#aladin"); if (!el || !ctx.S.aladin) return;
  const A = ctx.S.aladin, { esc } = ctx;
  document.querySelectorAll('[data-asof="aladin"]').forEach(a => { a.innerHTML = `Model data <b>${esc(A.as_of)}</b> close · built ${esc(ctx.istUtc(A.generated_utc))} (${esc(ctx.agoTxt(ctx.minsAgo(A.generated_utc)))}) · sentiment ${ctx.S.sentiment ? esc(ctx.istUtc(ctx.S.sentiment.generated_utc)) : "not available"} · prices as the desk shows them`; });
  const secs = [...new Set(ctx.S.uni.stocks.map(s => s.ind).filter(Boolean))].sort();
  const houses = ((ctx.S.houses || {}).houses || []);
  const rows = visibleRows(), show = rows.slice(0, st.limit);
  const sel = (id, opts, cur) => `<select id="${id}" aria-label="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  el.innerHTML = `${modelCard()}
    <div class="controls al-controls">
      <div class="seg" id="al-h" role="group" aria-label="Horizon">${[5, 10, 20].map(h => `<button data-h="${h}" class="${st.h === h ? "on" : ""}">${h}D</button>`).join("")}</div>
      <div class="seg" id="al-v" role="group" aria-label="View">${[["up", "Most likely up"], ["down", "Most likely down"], ["agree", "Highest agreement"], ["all", "All"]].map(([v, l]) => `<button data-v="${v}" class="${st.view === v && !st.sort ? "on" : ""}">${l}</button>`).join("")}</div>
      ${sel("al-board", [["All", "All boards"], ["NIFTY 500", "NIFTY 500"], ["Main", "Main board"], ["SME", "SME"], ["ETFs", "ETFs"]], st.board)}
      ${sel("al-sector", [["", "All sectors"], ...secs.map(s => [s, s])], st.sector)}
      ${sel("al-house", [["", "All business houses"], ...houses.map(h => [h.id, h.name])], st.house)}
      ${sel("al-sent", [["", "Any sentiment"], ["EXCELLENT", "Excellent"], ["GOOD", "Good"], ["NEUTRAL", "Neutral"], ["POOR", "Poor"], ["BAD", "Bad"], ["NO NEWS", "No news"]], st.sent)}
      ${sel("al-conf", [["", "Any confidence"], ["High", "High"], ["Medium", "Medium"], ["Low", "Low"]], st.conf)}
      <input id="al-q" type="search" placeholder="Filter by symbol or name" aria-label="Filter ALADIN" value="${esc(st.q)}">
    </div>
    <div class="tablecard"><table class="tbl" id="al-table"><thead><tr><th>#</th>${SORTS.map(([k, l]) => `<th data-sort="${k}" tabindex="0" class="${["last", "chg", "pup", "pdn"].includes(k) ? "r " : ""}${st.sort && st.sort[0] === k ? "sorted " : ""}${["pdn", "sw", "agree", "conf", "cov"].includes(k) ? "al-hide " : ""}${k === "n" ? "al-hide2" : ""}" aria-sort="${st.sort && st.sort[0] === k ? (st.sort[1] > 0 ? "ascending" : "descending") : "none"}">${l}</th>`).join("")}</tr></thead>
      <tbody>${show.map((r, i) => rowHtml(r, i)).join("") || '<tr><td colspan="15" class="empty">No stocks match these filters.</td></tr>'}</tbody></table></div>
    <div class="more-row"><span class="mut" id="al-count">Showing ${show.length.toLocaleString("en-IN")} of ${rows.length.toLocaleString("en-IN")} securities</span>${rows.length > show.length ? '<button class="btn-line" id="al-more">Show 50 more</button>' : ""}</div>
    ${paperLog()}${foot()}`;
  bind(el);
  bindPatch();
}

function bind(el) {
  const rd = () => draw();
  el.querySelectorAll("#al-h button").forEach(b => b.onclick = () => { st.h = +b.dataset.h; rd(); });
  el.querySelectorAll("#al-v button").forEach(b => b.onclick = () => { st.view = b.dataset.v; st.sort = null; st.limit = 50; rd(); });
  const on = (id, k) => { const s = el.querySelector("#" + id); if (s) s.onchange = () => { st[k] = s.value; st.limit = 50; rd(); }; };
  on("al-board", "board"); on("al-sector", "sector"); on("al-house", "house"); on("al-sent", "sent"); on("al-conf", "conf");
  const q = el.querySelector("#al-q"); q.oninput = () => { st.q = q.value; st.limit = 50; const pos = q.selectionStart; rd(); const n = ctx.$("#al-q"); n.focus(); n.setSelectionRange(pos, pos); };
  const more = el.querySelector("#al-more"); if (more) more.onclick = () => { st.limit += 50; rd(); };
  el.querySelectorAll("#al-table th[data-sort]").forEach(th => { const go = () => { const k = th.dataset.sort; st.sort = st.sort && st.sort[0] === k ? [k, -st.sort[1]] : [k, ["sym", "n"].includes(k) ? 1 : -1]; rd(); }; th.onclick = go; th.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }; });
  el.querySelectorAll("tr.al-r").forEach(tr => {
    const toggle = e => {
      if (e && e.target.closest && e.target.closest(".sent")) return;
      const s = tr.dataset.s, viaKey = e && e.detail === 0;                             // detail 0 = activated from the keyboard (the row button): keep the focus there
      expanded.has(s) ? expanded.delete(s) : expanded.add(s); rd();
      if (viaKey) { const b = ctx.$(`#al-table tr.al-r[data-s="${CSS.escape(s)}"] .al-tg`); if (b) b.focus(); }
    };
    tr.onclick = toggle;
  });
  el.querySelectorAll("[data-open]").forEach(b => b.onclick = () => { ctx.openSec(b.dataset.open); ctx.go("terminal"); });
  el.querySelectorAll("[data-wl]").forEach(b => b.onclick = () => { ctx.toggleWatch(b.dataset.wl); rd(); });
  el.querySelectorAll(".tablecard tr[data-s]:not(.al-r)").forEach(tr => tr.onclick = () => { ctx.openSec(tr.dataset.s); ctx.go("terminal"); });
  if (filterSym) { const t = el.querySelector(`tr.al-r[data-s="${CSS.escape(filterSym)}"]`); if (t && t.scrollIntoView) t.scrollIntoView({ block: "center" }); filterSym = null; }
}

/* ---------- live patching: price, change and P(up) of the visible rows, textContent only, one animation frame per batch ---------- */
const patch = new Map();
let raf = 0; const dirtyPx = new Set(), dirtySw = new Set();
function bindPatch() {
  patch.clear();
  document.querySelectorAll("#al-table tr.al-r").forEach(tr => {
    const sym = tr.dataset.s;
    patch.set(sym, { last: tr.querySelector(".al-last"), chg: tr.querySelector(".al-chg"), pup: tr.querySelector(".al-pup .pbar"), sw: tr.querySelector(".al-sw"), ag: tr.querySelector(".al-ag") });
  });
}
function onBatch(b) {
  if (!patch.size || !b) return;
  if (b.type === "sweeps") { for (const s of b.s || []) if (patch.has(s.sym)) dirtySw.add(s.sym); for (const sym of Object.keys(b.agg || {})) if (patch.has(sym)) dirtySw.add(sym); }
  else if (b.type === "ticks") { for (const sym of Object.keys(b.q || {})) if (patch.has(sym)) dirtyPx.add(sym); }
  if (!raf && (dirtyPx.size || dirtySw.size)) raf = requestAnimationFrame(flush);
}
function flush() {
  raf = 0;
  for (const sym of dirtyPx) {
    const e = patch.get(sym), x = ctx.q(sym);
    if (!e || !x) continue;
    if (e.last) e.last.textContent = ctx.inr(x.p);
    if (e.chg) { e.chg.textContent = x.pct == null ? "—" : ctx.sg(x.pct) + "%"; e.chg.classList.remove("up", "down", "flat", "mut"); e.chg.classList.add(ctx.ud(x.pct)); }
  }
  for (const sym of dirtySw) {                                                         // P(up) is recomputed only when this symbol's sweep score changed
    const e = patch.get(sym), c = calc(sym, st.h);
    if (!e || !c) continue;
    if (e.pup) { const b = e.pup.querySelector("b"), i = e.pup.querySelector("i"); if (b) b.textContent = Math.round(c.p * 100) + "%"; if (i) i.style.width = Math.round(c.p * 100) + "%"; e.pup.classList.remove("up", "down", "flat"); e.pup.classList.add(c.p >= 0.55 ? "up" : c.p <= 0.45 ? "down" : "flat"); }
    if (e.sw) e.sw.textContent = sweepHtml(sym);
    if (e.ag) e.ag.textContent = dots(c.agree_k, c.agree_n);
  }
  dirtyPx.clear(); dirtySw.clear();
}

/* ---------- Details rail and Brief card ---------- */
export function renderAladinMini(sym) {
  if (!ctx) return "";
  const A = ctx.S.aladin, ph = (ctx.S.aladin || {}).primary || 10;
  const head = `<div class="sec-t">ALADIN · ${ph}D direction</div>`;
  if (!A) return head + `<p class="note">${files().aladin ? "ALADIN data is loading…" : "ALADIN is not available yet."}</p>`;
  const u = ctx.S.map.get(sym), c = calc(sym, ph);
  if (!c) return head + `<p class="note">${ctx.esc(sym)}: ${ctx.esc(reasonNoProb(u || {}))}.</p>`;
  const a = A.stocks[sym], ft = fundText(u || {}, a);
  const pct = Math.round(c.p * 100);
  return head + `<div class="ol-mini"><div class="tg-top"><span class="mut">P(up) in ${ph} trading days</span><b class="${c.p >= 0.55 ? "up" : c.p <= 0.45 ? "down" : ""}">${pct}%</b></div>
    <div class="tg-bar"><i style="left:calc(${pct}% - 2px)"></i></div>
    <div class="al-mini-g"><span>Fundamental ${ft ? `<span class="mut" title="${ctx.esc(ft.why)}">${ft.t}</span>` : gauge(a.f.sc)}</span><span>Technical ${gauge(c.T)}</span></div>
    <div class="al-mini-s">${sentHtml(sym, true)}</div>
    <div class="tg-n">Confidence ${c.conf} · ${c.agree} views agree</div>
    <p class="note">${DISCLAIMER} <a href="#" data-aladin="${ctx.esc(sym)}">Open in ALADIN →</a></p></div>`;
}
export function briefCard(bcard) {
  const A = ctx && ctx.S.aladin; if (!A) return "";
  const rows = ctx.S.uni.stocks.filter(u => u.n500).map(u => ({ u, c: calc(u.s, A.primary || 10) })).filter(r => r.c && r.c.conf === "High" && r.c.agree === "3/3");
  const up = rows.filter(r => r.c.p > 0.5).sort((a, b) => b.c.p - a.c.p)[0], dn = rows.filter(r => r.c.p < 0.5).sort((a, b) => a.c.p - b.c.p)[0];
  const { esc } = ctx, h = A.primary || 10;
  if (!up && !dn) return bcard("neutral", `ALADIN · ${h}D direction`, "No high-confidence 3/3 leans today", `Model data ${esc(A.as_of)}. A lean needs High confidence and all three views agreeing; the bar is not lowered.`, "Open ALADIN", 'data-go="lab"');
  const parts = [up && `${esc(up.u.s)} ${pctTxt(up.c.p)} up`, dn && `${esc(dn.u.s)} ${pctTxt(dn.c.p)} up`].filter(Boolean);
  return bcard(up ? "pos" : "neg", `ALADIN · ${h}D direction`, parts.join(" · "), `Strongest 3/3 lean up${up ? "" : " (none)"} and down${dn ? "" : " (none)"} in the NIFTY 500, model data ${esc(A.as_of)}. A statistical model that is often wrong.`, "Open ALADIN", 'data-go="lab"');
}
