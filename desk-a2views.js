/* ALADIN 2.0 pages: Scoreboard, Market map, Sector rotation, Forecast board, Learning journal, Learning curve.
   Data (all published nightly, lazy, a few KB to a few hundred KB): aladin2/index.json, scoreboard.json, market_map.json, journal.json. Nothing is estimated in the browser except what is named here
   (sector rotation is computed from the return columns the desk already holds). Charts are inline SVG or plain HTML with existing colour tokens, keyboard reachable, with a numbers fallback.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. */
import { esc, inr, pct } from "./desk-aladin2.js";

let ctx = null, root = null;
const D = { index: null, score: null, map: null, journal: null, method: null, weekly: null }, loading = new Set();
const st = { tab: "weekly", colour: "state", q: "", sector: "", sort: "w20", limit: 50, kind: "" };
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results.";
const TABS = [["weekly", "Weekly signals"], ["score", "Scoreboard"], ["map", "Market map"], ["rot", "Sector rotation"], ["board", "Forecast board"], ["journal", "Learning journal"], ["curve", "Learning curve"], ["method", "Method"]];
const FILES = { index: "aladin2/index.json", score: "aladin2/scoreboard.json", map: "aladin2/market_map.json", journal: "aladin2/journal.json", method: "aladin2/method.json", weekly: "aladin2/weekly.json" };

export function init(c) { ctx = c; }

/* ---------- pure helpers (tests/js/a2views.test.mjs) ---------- */
export const median = a => { const s = a.filter(x => x != null && isFinite(x)).sort((x, y) => x - y); return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null; };

/* Squarified treemap (Bruls, Huizing, van Wijk). items: [{key, value}] with value > 0; returns [{key, value, x, y, w, h}] filling the rectangle, areas proportional to values. */
export function squarify(items, x, y, w, h) {
  const list = items.filter(i => i.value > 0).sort((a, b) => b.value - a.value), total = list.reduce((s, i) => s + i.value, 0), out = [];
  if (!list.length || w <= 0 || h <= 0) return out;
  const scale = (w * h) / total, nodes = list.map(i => ({ ...i, a: i.value * scale }));
  let rx = x, ry = y, rw = w, rh = h, row = [];
  const worst = (r, side) => { const s = r.reduce((t, n) => t + n.a, 0), mx = Math.max(...r.map(n => n.a)), mn = Math.min(...r.map(n => n.a)); return Math.max(side * side * mx / (s * s), s * s / (side * side * mn)); };
  const place = r => {
    const s = r.reduce((t, n) => t + n.a, 0);
    if (rw >= rh) { const cw = s / rh; let cy = ry; for (const n of r) { const hh = n.a / cw; out.push({ key: n.key, value: n.value, x: rx, y: cy, w: cw, h: hh }); cy += hh; } rx += cw; rw -= cw; }
    else { const ch = s / rw; let cx = rx; for (const n of r) { const ww = n.a / ch; out.push({ key: n.key, value: n.value, x: cx, y: ry, w: ww, h: ch }); cx += ww; } ry += ch; rh -= ch; }
  };
  for (const n of nodes) {
    const side = Math.min(rw, rh);
    if (!row.length || worst([...row, n], side) <= worst(row, side)) row.push(n); else { place(row); row = [n]; }
  }
  if (row.length) place(row);
  return out;
}

/* Sector rotation from the return columns the desk already holds: x = 3-month return of the sector's median stock minus the market median, y = 1-month return minus the market median.
   Quadrants: Leading (x>0, y>0), Weakening (x>0, y<=0), Improving (x<=0, y>0), Lagging (x<=0, y<=0). Needs >= 5 stocks in a sector. No trails: they would need daily history. */
export function sectorRotation(stocks) {
  const m1 = median(stocks.map(s => s.r1m)), m3 = median(stocks.map(s => s.r3m)), by = new Map();
  for (const s of stocks) { if (!s.ind || s.r1m == null || s.r3m == null) continue; if (!by.has(s.ind)) by.set(s.ind, []); by.get(s.ind).push(s); }
  return [...by].filter(([, a]) => a.length >= 5).map(([sector, a]) => {
    const x = median(a.map(s => s.r3m)) - m3, y = median(a.map(s => s.r1m)) - m1;
    return { sector, n: a.length, x, y, quad: x > 0 ? (y > 0 ? "Leading" : "Weakening") : (y > 0 ? "Improving" : "Lagging") };
  }).sort((a, b) => b.x - a.x);
}

/* Number of strategies on trial (Probation or Active) after each journal event, from the events alone. */
export function trialCurve(events) {
  const state = new Map(), pts = [], map = { promoted_to_probation: "P", reentered: "P", capped: "P", promoted_to_active: "A", demoted: "D", retired: "R" };
  for (const e of [...events].sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0)) {
    if (!map[e.kind] || e.scope !== "universe") continue;
    state.set(e.strategy, map[e.kind]); const n = [...state.values()].filter(v => v === "P" || v === "A").length, last = pts[pts.length - 1];
    if (last && last.d === e.date) last.n = n; else pts.push({ d: e.date, n });
  }
  return pts;
}

/* ---------- data ---------- */
function need(...keys) {
  keys.forEach(k => { if (D[k] || loading.has(k) || !ctx) return; loading.add(k); ctx.getJSON(FILES[k], false).then(d => { D[k] = d; }).catch(() => { D[k] = { missing: true }; }).finally(() => { loading.delete(k); if (root && ctx) render(); }); });
  return keys.every(k => D[k] && !D[k].missing);
}
const bad = k => D[k] && D[k].missing;

/* ---------- svg helpers ---------- */
function lineSvg(series, { w = 320, h = 130, xl = d => d, yfmt = v => v.toFixed(2), ymin, ymax, ref, label = "line chart" } = {}) {
  const all = series.flatMap(s => s.pts.map(p => p[1])).concat(ref != null ? [ref] : []); if (!all.length) return "";
  const lo = ymin ?? Math.min(...all), hi = ymax ?? Math.max(...all), sp = hi - lo || 1, L = 40, R = 8, T = 8, B = 20, n = Math.max(...series.map(s => s.pts.length));
  const X = i => L + (w - L - R) * (n > 1 ? i / (n - 1) : 0.5), Y = v => T + (h - T - B) * (1 - (v - lo) / sp);
  const lines = series.map(s => `<polyline class="a2v-ln a2v-s${s.cls || 0}" points="${s.pts.map((p, i) => X(i).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ")}"/>${s.pts.map((p, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="2" class="a2v-pt a2v-s${s.cls || 0}"><title>${esc(s.name || "")} ${esc(xl(p[0]))}: ${esc(yfmt(p[1]))}</title></circle>`).join("")}`).join("");
  const refl = ref != null ? `<line x1="${L}" x2="${w - R}" y1="${Y(ref).toFixed(1)}" y2="${Y(ref).toFixed(1)}" class="a2v-ref"/>` : "";
  const ticks = [lo, (lo + hi) / 2, hi].map(v => `<text x="2" y="${(Y(v) + 3).toFixed(1)}" class="a2-ax">${esc(yfmt(v))}</text><line x1="${L - 2}" x2="${w - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="a2-grid"/>`).join("");
  const first = series[0].pts[0], last = series[0].pts[series[0].pts.length - 1];
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}" class="a2v-svg">${ticks}${refl}${lines}<text x="${L}" y="${h - 4}" class="a2-ax">${esc(xl(first[0]))}</text><text x="${w - R}" y="${h - 4}" class="a2-ax end">${esc(xl(last[0]))}</text></svg>`;
}

/* ---------- pages ---------- */
function pageScore() {
  if (!need("score", "index")) return bad("score") ? `<p class="note">The scoreboard is not published yet. Not measured.</p>` : `<p class="note">Loading…</p>`;
  const S = D.score, I = D.index, H = S.historical_simulation.horizons, hs = Object.keys(H), live = S.live || {}, nLive = Object.values(live).reduce((a, v) => a + v.n, 0);
  const cards = `<div class="a2v-cards"><div class="a2v-card"><span>Live forecasts resolved</span><b>${nLive.toLocaleString("en-IN")}</b><small>${nLive ? "see the coverage table below" : `none yet: the first 5-day forecasts were made on ${esc(S.as_of)}`}</small></div>
    <div class="a2v-card"><span>Stocks by state</span><b>${Object.entries(S.state_shares).map(([k, v]) => `${Math.round(v * 100)}% ${({ L: "Learning", P: "Provisional", V: "Validated", S: "Suspended" })[k] || k}`).join(" · ")}</b><small>Validated needs 60 live days, 60 out-of-sample trades and a calibration check</small></div>
    <div class="a2v-card"><span>Engine</span><b>${S.engine_suspended ? "SUSPENDED" : "running"}</b><small>${S.engine_suspended ? esc((S.kill_reasons || []).join("; ")) : "no kill switch has fired"}</small></div></div>`;
  const barW = 22, bars = hs.map((h, i) => ["50", "80", "95"].map((b, j) => { const v = H[h].coverage[b], x = 44 + i * 120 + j * (barW + 4), y = 8 + 100 * (1 - v);
    return `<rect x="${x}" y="${y.toFixed(1)}" width="${barW}" height="${(100 * v).toFixed(1)}" class="a2v-bar"><title>${h} days, ${b}% range held ${(v * 100).toFixed(1)}% of the time (nominal ${b}%)</title></rect><line x1="${x - 2}" x2="${x + barW + 2}" y1="${(8 + 100 * (1 - +b / 100)).toFixed(1)}" y2="${(8 + 100 * (1 - +b / 100)).toFixed(1)}" class="a2v-ref"/>`; }).join("") + `<text x="${44 + i * 120 + 40}" y="126" class="a2-ax mid">${h}d</text>`).join("");
  const cov = `<div class="sec-t">Do the ranges hold what they promise? <span class="tag">historical simulation</span></div><svg viewBox="0 0 ${44 + hs.length * 120} 134" class="a2v-svg" role="img" aria-label="Realised coverage of the 50, 80 and 95 percent ranges by horizon; the short lines mark the promised share">${bars}</svg>
    <p class="note">Bars = share of out-of-sample outcomes inside the 50 / 80 / 95% range, left to right 50%, 80%, 95%; short lines = the promise. 2012–2026, survivors to today only, <b>not live results</b>.</p>`;
  const nums = `<details class="a2-det"><summary>Numbers behind these charts</summary><table class="a2-tbl"><thead><tr><th>Days</th><th>50% held</th><th>80% held</th><th>95% held</th><th>Calibration error of P(up)</th><th>Forecasts</th></tr></thead><tbody>${hs.map(h => `<tr><td>${h}</td><td>${(H[h].coverage["50"] * 100).toFixed(1)}%</td><td>${(H[h].coverage["80"] * 100).toFixed(1)}%</td><td>${(H[h].coverage["95"] * 100).toFixed(1)}%</td><td>${H[h].ece_p_up}</td><td>${H[h].rows.toLocaleString("en-IN")}</td></tr>`).join("")}</tbody></table></details>`;
  const rel = ["1", "5"].filter(h => H[h]).map(h => { const t = H[h].reliability, pts = t.map(r => [r.pred, r.actual]), lo = 0.3, hi = 0.7, w = 150, hh = 130, X = v => 30 + (w - 36) * (v - lo) / (hi - lo), Y = v => 8 + (hh - 28) * (1 - (v - lo) / (hi - lo));
    return `<div class="a2v-rel"><svg viewBox="0 0 ${w} ${hh}" class="a2v-svg" role="img" aria-label="Reliability of the probability of closing higher, ${h} day: predicted against actual"><line x1="${X(lo)}" y1="${Y(lo)}" x2="${X(hi)}" y2="${Y(hi)}" class="a2v-ref"/>${pts.map(([p, a], i) => `<circle cx="${X(Math.min(hi, Math.max(lo, p))).toFixed(1)}" cy="${Y(Math.min(hi, Math.max(lo, a))).toFixed(1)}" r="3" class="a2v-pt a2v-s0"><title>said ${(p * 100).toFixed(0)}%, happened ${(a * 100).toFixed(0)}% (n = ${t[i].n.toLocaleString("en-IN")})</title></circle>`).join("")}
      <text x="2" y="${Y(hi) + 3}" class="a2-ax">${hi * 100}%</text><text x="2" y="${Y(lo) + 3}" class="a2-ax">${lo * 100}%</text><text x="${w / 2}" y="${hh - 4}" class="a2-ax mid">said → · up = happened · ${h}-day, ECE ${H[h].ece_p_up}</text></svg></div>`; }).join("");
  const yr = `<div class="sec-t">Does the 80% range hold in every year? <span class="tag">historical simulation</span></div>` + ["5", "20"].filter(h => H[h] && H[h].coverage_80_by_year).map(h => { const ys = Object.entries(H[h].coverage_80_by_year);
    return `<div class="a2v-yr"><b>${h}-day</b>${lineSvg([{ name: "80% range held", pts: ys.map(([y, v]) => [y, v * 100]) }], { yfmt: v => v.toFixed(0) + "%", ymin: 50, ymax: 100, ref: 80, xl: d => d, label: `Share of ${h}-day outcomes inside the 80 percent range, by year; the dashed line is the 80 percent promise` })}</div>`; }).join("") + `<p class="note">The dashed line is the promise (80%). Stress years (2020) break it at longer horizons: that is why the engine widens a range automatically when its live record drifts.</p>`;
  const strat = `<div class="sec-t">Strategy records</div>` + (S.strategies || []).map(c => `<div class="a2-card"><div class="a2-card-t"><b>${esc(c.name)}</b><span class="tag ${c.state === "Active" ? "acc" : ""}">${esc(c.state.toUpperCase())}</span></div><div class="note">${esc(c.last_change)}</div></div>`).join("") + `<p class="note">${esc(S.historical_simulation.policy)}.</p>`;
  const livetbl = `<div class="sec-t">Live results</div>` + (nLive ? `<table class="a2-tbl"><thead><tr><th>Days</th><th>Resolved</th><th>50%</th><th>80%</th><th>95%</th></tr></thead><tbody>${Object.entries(live).map(([h, v]) => `<tr><td>${h}</td><td>${v.n.toLocaleString("en-IN")}</td><td>${(v.coverage["50"] * 100).toFixed(1)}%</td><td>${(v.coverage["80"] * 100).toFixed(1)}%</td><td>${(v.coverage["95"] * 100).toFixed(1)}%</td></tr>`).join("")}</tbody></table>` :
    `<p class="note">No live forecast has resolved yet. ${esc(S.live_note)} Paper-portfolio equity, drawdown, monthly returns and best and worst calls will appear here once a stock is Validated and a paper position exists: none does today.</p>`);
  const bc = S.barrier_check_20d && S.barrier_check_20d.touch_up_1sigma ? `<p class="note">Touch probabilities (20 days): predicted ${(S.barrier_check_20d.touch_up_1sigma.mean_predicted * 100).toFixed(1)}% of reaching +1 range-width, realised ${(S.barrier_check_20d.touch_up_1sigma.realised * 100).toFixed(1)}% (historical simulation; the model is 2–3 points too generous).</p>` : "";
  return asof(S.as_of + " close") + cards + cov + nums + `<div class="sec-t">Do the probabilities mean what they say? <span class="tag">historical simulation</span></div><div class="a2v-rels">${rel}</div><p class="note">Points = groups of forecasts: what ALADIN said (across) against what happened (up). On the diagonal = honest. Short horizons only: longer ones carry no directional information.</p>` + bc + yr + livetbl + strat;
}

function pageMap() {
  if (!need("map", "index")) return bad("map") ? `<p class="note">The market map is not published yet. Not measured.</p>` : `<p class="note">Loading…</p>`;
  const rows = D.map.rows.filter(r => r[2] > 0), W = 1000, Hh = 560, sectors = new Map();
  rows.forEach(r => { if (!sectors.has(r[1])) sectors.set(r[1], []); sectors.get(r[1]).push(r); });
  const secs = squarify([...sectors].map(([k, a]) => ({ key: k, value: a.reduce((s, r) => s + r[2], 0) })), 0, 0, W, Hh), widths = rows.map(r => r[3]).sort((a, b) => a - b), q = f => widths[Math.floor(f * (widths.length - 1))] || 1;
  const tiles = secs.map(sc => { const inner = squarify(sectors.get(sc.key).map(r => ({ key: r[0], value: r[2], r })), sc.x + 2, sc.y + 12, sc.w - 4, sc.h - 14);
    return `<div class="a2v-sec" style="left:${sc.x / W * 100}%;top:${sc.y / Hh * 100}%;width:${sc.w / W * 100}%;height:${sc.h / Hh * 100}%"><span>${sc.w > 70 ? esc(sc.key) : ""}</span></div>` + inner.map(t => { const r = t.r || sectors.get(sc.key).find(x => x[0] === t.key), f = Math.min(1, Math.max(0, (r[3] - q(0.05)) / (q(0.95) - q(0.05) || 1)));
      const style = `left:${t.x / W * 100}%;top:${t.y / Hh * 100}%;width:${t.w / W * 100}%;height:${t.h / Hh * 100}%` + (st.colour === "range" ? `;background:color-mix(in srgb, var(--acc) ${Math.round((0.06 + f * 0.34) * 100)}%, var(--card))` : "");
      return `<a class="a2v-tile ${st.colour === "range" ? "rng" : ""}" tabindex="0" role="button" data-sym="${esc(t.key)}" style="${style}" title="${esc(t.key)} · ${esc(sc.key)} · ${({ L: "Learning", P: "Provisional", V: "Validated", S: "Suspended" })[r[4]]} · 20-day 80% range width ${r[3]}%">${t.w > 34 && t.h > 16 ? esc(t.key) : ""}</a>`; }).join(""); }).join("");
  return asof(D.map.as_of + " close") + `<div class="a2v-bar-c"><div class="seg" id="a2v-col"><button data-col="state" class="${st.colour === "state" ? "on" : ""}">Colour: state</button><button data-col="range" class="${st.colour === "range" ? "on" : ""}">Colour: forecast range width</button></div></div>
    <div class="a2v-map" style="aspect-ratio:${W}/${Hh}" aria-label="Market map: area is traded value, grouped by sector">${tiles}</div>
    <p class="note">Area = 20-day average traded value (market capitalisation is not available from free data), grouped by sector. <b>State</b> colouring is flat because every stock is Learning today: ALADIN has no calibrated lean to colour by. <b>Range width</b> shades by how wide the 20-day 80% range is (darker = wider = riskier). Click or press Enter on a tile to open the stock. The Forecast board has the same data as a table.</p>`;
}

function pageRot() {
  const stocks = (ctx && ctx.S && ctx.S.uni ? ctx.S.uni.stocks : []).filter(s => s.n500 && !s.etf);
  if (!stocks.length) return `<p class="note">Loading…</p>`;
  const R = sectorRotation(stocks), W = 360, Hh = 280, ex = Math.max(...R.map(r => Math.abs(r.x)), 1), ey = Math.max(...R.map(r => Math.abs(r.y)), 1), X = v => W / 2 + (W / 2 - 24) * v / ex, Y = v => Hh / 2 - (Hh / 2 - 20) * v / ey;
  const dots = R.map(r => `<g tabindex="0" class="a2v-dot"><circle cx="${X(r.x).toFixed(1)}" cy="${Y(r.y).toFixed(1)}" r="${(4 + Math.min(r.n, 80) / 12).toFixed(1)}" class="a2v-q-${r.quad}"/><text x="${(X(r.x) + 7).toFixed(1)}" y="${(Y(r.y) + 3).toFixed(1)}" class="a2-ax">${esc(r.sector.split(" ").slice(0, 2).join(" ").slice(0, 16))}</text><title>${esc(r.sector)}: ${r.quad}. 3-month return ${pct(r.x)} points vs the market median, 1-month ${pct(r.y)} points (${r.n} stocks)</title></g>`).join("");
  return asof("NSE end-of-day " + ((ctx.S.uni && ctx.S.uni.session_date) || "unknown")) + `<svg viewBox="0 0 ${W} ${Hh}" class="a2v-svg" role="img" aria-label="Sector rotation quadrants"><line x1="${W / 2}" x2="${W / 2}" y1="6" y2="${Hh - 6}" class="a2-grid"/><line x1="4" x2="${W - 4}" y1="${Hh / 2}" y2="${Hh / 2}" class="a2-grid"/>
    <text x="${W - 6}" y="16" class="a2-ax end">Leading</text><text x="${W - 6}" y="${Hh - 8}" class="a2-ax end">Weakening</text><text x="6" y="16" class="a2-ax">Improving</text><text x="6" y="${Hh - 8}" class="a2-ax">Lagging</text>${dots}</svg>
    <table class="a2-tbl"><thead><tr><th>Sector</th><th>Stocks</th><th>3M vs market</th><th>1M vs market</th><th>Quadrant</th></tr></thead><tbody>${R.map(r => `<tr><td>${esc(r.sector)}</td><td>${r.n}</td><td>${pct(r.x)}</td><td>${pct(r.y)}</td><td>${r.quad}</td></tr>`).join("")}</tbody></table>
    <p class="note">Across: the sector's median 3-month return minus the market median. Up: the same for 1 month. This describes what already happened; it is not a forecast. Trails are not drawn (they need daily history). NIFTY 500 stocks only, sectors with at least 5 stocks.</p>`;
}

function pageBoard() {
  if (!need("index")) return bad("index") ? `<p class="note">The forecast board is not published yet. Not measured.</p>` : `<p class="note">Loading…</p>`;
  const I = D.index, secs = [...new Set(I.rows.map(r => r[7]))].sort(), key = { w20: r => r[6] - r[5], w5: r => r[4] - r[3], sym: r => r[0] };
  let rows = I.rows.filter(r => (!st.sector || r[7] === st.sector) && (!st.q || r[0].toLowerCase().includes(st.q.toLowerCase())));
  rows = rows.sort((a, b) => st.sort === "sym" ? a[0].localeCompare(b[0]) : key[st.sort](b) - key[st.sort](a));
  const sig = I.rows.filter(r => r[2] !== "n").length, none = I.labels.none;
  return asof(I.as_of + " close") + `<div class="a2v-note"><b>Signal board:</b> ${sig ? sig + " signals today." : `no stock has a signal today. All ${I.rows.length} read <b>${esc(none)}</b>, and that is the usual answer: standing aside is a valid result.`} The table below is every stock's forecast range, widest first.</div>
    <div class="a2v-ctl"><input id="a2v-q" placeholder="Filter by symbol" value="${esc(st.q)}"><select id="a2v-sec"><option value="">All sectors</option>${secs.map(s => `<option ${s === st.sector ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <select id="a2v-sort"><option value="w20" ${st.sort === "w20" ? "selected" : ""}>Widest 20-day range</option><option value="w5" ${st.sort === "w5" ? "selected" : ""}>Widest 5-day range</option><option value="sym" ${st.sort === "sym" ? "selected" : ""}>Symbol</option></select></div>
    <table class="a2-tbl a2v-board"><thead><tr><th>Symbol</th><th>Sector</th><th>State</th><th>${esc(I.labels.range)} 5 days (80%)</th><th>20 days (80%)</th></tr></thead><tbody>${rows.slice(0, st.limit).map(r => `<tr tabindex="0" data-sym="${esc(r[0])}"><td><b>${esc(r[0])}</b></td><td>${esc(r[7])}</td><td>${({ L: "Learning", P: "Provisional", V: "Validated", S: "Suspended" })[r[1]]}</td><td>${pct(r[3])} to ${pct(r[4])}</td><td>${pct(r[5])} to ${pct(r[6])}</td></tr>`).join("")}</tbody></table>
    ${rows.length > st.limit ? `<button class="btn-line sm" id="a2v-more">Show more (${rows.length - st.limit} left)</button>` : ""}
    <div class="sec-t">Opportunity scatter and correlation clusters</div><p class="note">These two views plot only Validated signals (expected net return against forecast risk, and how correlated today's signals are). With no Validated stock there is nothing to plot, so they stay empty on purpose rather than showing made-up points.</p>`;
}

function pageJournal() {
  if (!need("journal")) return bad("journal") ? `<p class="note">The journal is not published yet. Not measured.</p>` : `<p class="note">Loading…</p>`;
  const ev = D.journal.events || [], kinds = [...new Set(ev.map(e => e.kind))], shown = ev.filter(e => !st.kind || e.kind === st.kind).slice(0, 120);
  const NAME = { promoted_to_probation: "Started trial", promoted_to_active: "Promoted", demoted: "Demoted", retired: "Retired", reentered: "Re-entered", capped: "Capped", candidate_tested: "Search", candidate_promoted: "New rule", drift_alarm: "Drift alarm", kill_switch: "Kill switch" };
  return asof(ev[0] ? "the latest event, " + ev[0].date : "no events yet") + `<div class="a2v-note"><b>${ev[0] && ev[0].historical ? "Latest event (a replay of history)" : "What ALADIN learned"}:</b> ${esc(ev[0] ? ev[0].text : "nothing yet")}</div><div class="seg a2v-kinds"><button data-kind="" class="${st.kind ? "" : "on"}">All</button>${kinds.map(k => `<button data-kind="${esc(k)}" class="${st.kind === k ? "on" : ""}">${esc(NAME[k] || k)}</button>`).join("")}</div>
    <ol class="a2v-tl">${shown.map(e => `<li><span class="a2v-d">${esc(e.date)}</span><span class="tag">${esc(NAME[e.kind] || e.kind)}</span>${e.historical ? '<span class="tag" title="A replay of past data, not live learning">historical simulation</span>' : ""}<div>${esc(e.text)}</div>${e.evidence && Object.keys(e.evidence).length ? `<details><summary>Evidence</summary><code>${esc(JSON.stringify(e.evidence))}</code></details>` : ""}</li>`).join("") || "<li>No events.</li>"}</ol>
    <p class="note">Every change ALADIN makes to itself is written here with its evidence. It changes weights, settings and which strategies it trusts, never its own code.</p>`;
}

function pageCurve() {
  if (!need("journal", "score")) return `<p class="note">Loading…</p>`;
  const pts = trialCurve(D.journal.events || []), c = D.score.learning_curve || [];
  return asof(pts.length ? pts[pts.length - 1].d : "no events yet") + `<div class="sec-t">Strategies on trial over time <span class="tag">from the journal</span></div>${pts.length ? lineSvg([{ name: "strategies in Probation or Active", pts: pts.map(p => [p.d, p.n]) }], { w: 360, h: 140, yfmt: v => Math.round(v), xl: d => d.slice(0, 7), ymin: 0, label: "Number of strategies in Probation or Active over time" }) : '<p class="note">No events yet.</p>'}
    <p class="note">How many of the strategies in the library were being paper-traded after each event. It rises when rules earn a trial and falls when they fade: the 2025 fade took it to zero.</p>
    <div class="sec-t">Live record, night by night</div>${c.length ? `<table class="a2-tbl"><thead><tr><th>As of</th><th>Share Validated</th><th>On trial</th><th>Live ECE</th><th>80% range held</th><th>Resolved</th></tr></thead><tbody>${c.slice(-30).reverse().map(r => `<tr><td>${esc(r.d)}</td><td>${(r.validated_share * 100).toFixed(0)}%</td><td>${r.on_trial}</td><td>${r.live_ece == null ? "--" : r.live_ece}</td><td>${r.live_cov80 == null ? "--" : (r.live_cov80 * 100).toFixed(1) + "%"}</td><td>${r.live_n}</td></tr>`).join("")}</tbody></table>` : `<p class="note">The live curve starts with the first night's run and fills in daily: the share of stocks Validated, the live calibration error, the live range coverage and net expectancy, so you can see whether ALADIN is actually improving. Nothing has resolved yet.</p>`}`;
}

function pageMethod() {
  if (!need("method")) return bad("method") ? `<p class="note">The methodology text is not published yet. Not measured.</p>` : `<p class="note">Loading…</p>`;
  const M = D.method;
  return asof("8 October 2026 (the text matches the README)") + `<p class="note"><i>${esc(M.disclaimer)}</i></p>` + M.sections.map(s => `<details class="a2-det" open><summary>${esc(s.h)}</summary>${s.p.map(p => `<p class="a2v-mp">${esc(p)}</p>`).join("")}</details>`).join("")
    + `<div class="sec-t">Not measured, and why</div><ul class="a2v-nm">${M.not_measured.map(([a, b]) => `<li><b>${esc(a)}</b>: ${esc(b)}</li>`).join("")}</ul>`;
}

const asof = t => `<p class="a2v-asof">As of ${esc(t || "unknown")}</p>`;

function pageWeekly() {
  if (!need("weekly")) return bad("weekly") ? `<p class="note">The weekly signals are not published yet. Not measured.</p>` : `<p class="note">Loading…</p>`;
  const W = D.weekly; if (!W.built) return `<p class="note">${esc(W.why || "No weekly book yet.")}</p>`;
  const B = W.book, L = W.labels, S = B.study, live = W.live_record || {}, rb = (S && D.weekly.book.bull[0] && D.weekly.book.bull[0].record) || null, rs = B.bear[0] && B.bear[0].record;
  const row = r => `<tr tabindex="0" data-sym="${esc(r.sym)}"><td><b>${esc(r.sym)}</b></td><td>${esc(r.name)}</td><td>${inr(r.close)}</td><td>${(r.rank_pct * 100).toFixed(1)}</td><td>${r.signal === "bull" ? `${inr(r.entry_zone[0])}–${inr(r.entry_zone[1])}` : "--"}</td><td>${r.signal === "bull" ? inr(r.invalidation) : "--"}</td><td>${r.chance ? (r.chance.closes_higher * 100).toFixed(0) + "%" : "--"}</td><td>${r.chance ? (r.chance.beats_market * 100).toFixed(0) + "%" : "--"}</td><td>${r.round_trip_cost_bps.toFixed(0)}</td><td>${r.fno ? "yes" : "no"}</td></tr>`;
  const hdr = `<thead><tr><th>Symbol</th><th>Company</th><th>Close</th><th>Rank (100 = best)</th><th>Entry zone</th><th>Exit early below</th><th>Chance higher</th><th>Chance beats market</th><th>Cost bps</th><th>Futures</th></tr></thead>`;
  const rec = (k, r) => !r ? "" : k === "bull" ? `<div class="a2v-card"><span>${esc(L.bull)} record, 2013–2026</span><b>${r.net_bps.toFixed(0)} bps a week after costs</b><small>${r.n.toLocaleString("en-IN")} signals · closed higher ${(r.share_closing_up * 100).toFixed(0)}% · beat the market by ${r.gross_excess_bps.toFixed(0)} bps before costs · 95% range ${r.net_ci95_bps[0].toFixed(0)} to ${r.net_ci95_bps[1].toFixed(0)} · positive in ${esc(r.years_positive_net)} years</small></div>`
    : `<div class="a2v-card"><span>${esc(L.bear)} record, 2013–2026</span><b>${r.gross_excess_bps.toFixed(0)} bps a week vs the market</b><small>${r.n.toLocaleString("en-IN")} signals · closed higher only ${(r.share_closing_up * 100).toFixed(0)}% · 95% range ${r.gross_excess_ci95_bps[1].toFixed(0)} to ${r.gross_excess_ci95_bps[0].toFixed(0)} · below the market in ${esc(r.years_below_market)} years</small></div>`;
  const lv = (k, n) => live[k] && live[k].n ? `${live[k].n} resolved, ${(live[k].share_up * 100).toFixed(0)}% closed higher, ${live[k].mean_excess_bps.toFixed(0)} bps vs market` : "none resolved yet";
  return asof(`${B.as_of} close${B.bull[0] && !B.bull[0].weekday_validated ? " (a midweek run: the 13-year test used Friday signals)" : ""}`) + `<div class="a2v-note"><b>How to use this.</b> Each signal is for the <b>next 5 trading days</b>: enter at the next open, leave at the open of the 5th trading day after, or earlier if the price closes below the exit level. ${esc(L.bear)} means <b>exit if you hold it, do not add it</b>: cash shares cannot be shorted; a short is possible only through futures, where marked. Past weekly results below are out of sample and net of costs; they are <b>not</b> a promise.</div>
    <div class="a2v-cards">${rec("bull", rb)}${rec("bear", rs)}<div class="a2v-card"><span>Live record</span><b>${esc(L.bull)}: ${lv("bull")}</b><small>${esc(L.bear)}: ${lv("bear")}. A signal counts as live only if it was published before its entry open; the first live week starts with the next nightly run. State: Provisional until 60 live days.</small></div></div>
    <div class="sec-t">${esc(L.bull)} · best ${B.rules.bull.replace(/^best /, "")} <span class="tag">${B.counts.bull}</span></div>${B.bull.length ? `<table class="a2-tbl a2v-board">${hdr}<tbody>${B.bull.map(row).join("")}</tbody></table>` : `<p class="note">No ${esc(L.bull)} this week.</p>`}
    <p class="note">The ${esc(L.bull)} side is the weak one: the best 10% of stocks do not beat their trading costs on average (about -7 bps a week); only the very best 1% do, and that result had four thresholds looked at, so treat it as the weaker claim. Size it small. The Weekly signal box in each stock's brief shows its sizing for your capital.</p>
    <div class="sec-t">${esc(L.bear)} · ${B.rules.bear} <span class="tag">${B.counts.bear}</span></div>${B.bear.length ? `<table class="a2-tbl a2v-board">${hdr}<tbody>${B.bear.map(row).join("")}</tbody></table>` : `<p class="note">No ${esc(L.bear)} this week.</p>`}
    <p class="note">${B.counts.hold.toLocaleString("en-IN")} other stocks read ${esc(L.none)}. Ranked: ${B.universe.toLocaleString("en-IN")} stocks with at least ₹2 crore a day traded. Survivorship flatters the ${esc(L.bull)} history and understates the ${esc(L.bear)} history.</p>
    <details class="a2-det"><summary>Where the rule comes from, and what did not help</summary><p class="note">${S ? `A study of ${S.rows.toLocaleString("en-IN")} stock-weeks (${S.weeks} Fridays, ${S.stocks.toLocaleString("en-IN")} stocks, ${esc(S.from)} to ${esc(S.to)}); the average round trip cost ${S.avg_round_trip_cost_bps} bps against a market that rose ${S.universe_mean_weekly_return_bps} bps a week. ` : ""}Of everything ALADIN measures, only ALADIN 1's 5-day score ranked next week's winners and losers. 5-day reversal and 3-month momentum did not pay after costs, and neither did a blend or a learned stack of all three. Fundamental, sentiment and supply-chain views have no weekly history and cannot be tested; the ALADIN 2 strategy library has no Active rule. They are shown with each signal as context.</p></details>`;
}

function render() {
  if (!root) return;
  const body = { score: pageScore, map: pageMap, rot: pageRot, board: pageBoard, journal: pageJournal, curve: pageCurve, method: pageMethod, weekly: pageWeekly }[st.tab]();
  root.innerHTML = `<div class="seg a2v-tabs" role="tablist">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-selected="${st.tab === k}" class="${st.tab === k ? "on" : ""}">${l}</button>`).join("")}</div><div class="a2v-body">${body}</div><p class="note a2v-dis">${DISCLAIMER}</p>`;
  bind();
}
function bind() {
  root.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { st.tab = b.dataset.tab; render(); });
  root.querySelectorAll("[data-col]").forEach(b => b.onclick = () => { st.colour = b.dataset.col; render(); });
  root.querySelectorAll("[data-kind]").forEach(b => b.onclick = () => { st.kind = b.dataset.kind; render(); });
  const open = el => { if (ctx && el.dataset.sym) { ctx.openSec(el.dataset.sym); ctx.go("terminal"); } };
  root.querySelectorAll("[data-sym]").forEach(el => { el.onclick = () => open(el); el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(el); } }; });
  const q = root.querySelector("#a2v-q"), sec = root.querySelector("#a2v-sec"), so = root.querySelector("#a2v-sort"), more = root.querySelector("#a2v-more");
  if (q) q.oninput = () => { st.q = q.value; st.limit = 50; const pos = q.selectionStart; render(); const n = root.querySelector("#a2v-q"); n.focus(); n.setSelectionRange(pos, pos); };
  if (sec) sec.onchange = () => { st.sector = sec.value; st.limit = 50; render(); }; if (so) so.onchange = () => { st.sort = so.value; render(); }; if (more) more.onclick = () => { st.limit += 100; render(); };
}
export function mount() { root = document.getElementById("a2v"); if (root) render(); }
