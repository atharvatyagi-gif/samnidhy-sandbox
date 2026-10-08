/* ALADIN BOT console: a locked page that shows what ALADIN is doing, step by step, with graphs, and how it reaches each call.
   The data is a public but ENCRYPTED file (aladin2/bot.enc.json, AES-256-GCM, key derived from the access code with PBKDF2-SHA256, 600,000 rounds). The browser derives the key from the code you type and
   decrypts in memory; nothing readable is sent anywhere. A wrong code, or a file that was changed, fails the GCM check. This module contains no data and no code.
   Every number on the page comes from the decrypted file; results labelled "historical simulation" are out-of-sample tests on past data, not live trading and not real money.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. */
import { esc, inr } from "./desk-aladin2.js";

const FILE = "aladin2/bot.enc.json", SS = "aladin2.bot.code";
let ctx = null, root = null, blob = null, blobState = "idle", P = null, failures = 0, until = 0;
const st = { stage: "score", sym: null, step: -1, playing: null };
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results.";

export function init(c) { ctx = c; }

/* ---------- the lock (exported for tests/js/a2bot.test.mjs, which opens a fixture produced by the Python side) ---------- */
export const normalise = c => String(c || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
export async function decrypt(b, code, subtle = globalThis.crypto && globalThis.crypto.subtle) {
  const enc = new TextEncoder(), raw = s => Uint8Array.from(atob(s), ch => ch.charCodeAt(0));
  const km = await subtle.importKey("raw", enc.encode(normalise(code)), "PBKDF2", false, ["deriveKey"]);
  const key = await subtle.deriveKey({ name: "PBKDF2", salt: raw(b.salt), iterations: b.iter, hash: "SHA-256" }, km, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const pt = await subtle.decrypt({ name: "AES-GCM", iv: raw(b.iv), additionalData: enc.encode(b.aad) }, key, raw(b.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}

/* ---------- small chart helpers (inline SVG, existing colour tokens through CSS classes) ---------- */
const pc = (v, d = 0) => v == null ? "--" : (v * 100).toFixed(d) + "%";
const bps = v => v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(0) + " bps";
export function barSvg(items, { w = 340, h = 150, zero = true, fmt = v => v.toFixed(0), label = "bar chart" } = {}) {
  const vals = items.map(i => i.v), mx = Math.max(...vals, 0), mn = Math.min(...vals, 0), sp = mx - mn || 1, L = 6, B = 22, T = 10, bw = (w - L * 2) / items.length, Y = v => T + (h - T - B) * (1 - (v - mn) / sp);
  const bars = items.map((it, i) => { const y0 = Y(0), y1 = Y(it.v), x = L + i * bw + 2; return `<rect x="${x.toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" width="${(bw - 4).toFixed(1)}" height="${Math.max(1, Math.abs(y1 - y0)).toFixed(1)}" class="${it.v >= 0 ? "a2b-up" : "a2b-dn"}${it.hl ? " a2b-hl" : ""}"><title>${esc(it.t || it.l)}: ${esc(fmt(it.v))}</title></rect><text x="${(x + (bw - 4) / 2).toFixed(1)}" y="${h - 8}" class="a2-ax mid">${esc(it.l)}</text>`; }).join("");
  return `<svg viewBox="0 0 ${w} ${h}" class="a2v-svg" role="img" aria-label="${esc(label)}">${zero ? `<line x1="${L}" x2="${w - L}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" class="a2-grid"/>` : ""}${bars}</svg>`;
}
export function curveSvg(series, { w = 340, h = 150, label = "line chart", yfmt = v => v.toFixed(2), xl = null } = {}) {
  const all = series.flatMap(s => s.y); if (!all.length) return ""; const lo = Math.min(...all), hi = Math.max(...all), sp = hi - lo || 1, L = 40, R = 6, T = 8, B = 18, n = Math.max(...series.map(s => s.y.length));
  const X = i => L + (w - L - R) * i / Math.max(n - 1, 1), Y = v => T + (h - T - B) * (1 - (v - lo) / sp);
  const ln = series.map((s, k) => `<polyline class="a2b-ln a2b-c${k}" points="${s.y.map((v, i) => X(i).toFixed(1) + "," + Y(v).toFixed(1)).join(" ")}"><title>${esc(s.name)}: ${esc(yfmt(s.y[s.y.length - 1]))} at the end</title></polyline>`).join("");
  const ticks = [lo, (lo + hi) / 2, hi].map(v => `<text x="2" y="${(Y(v) + 3).toFixed(1)}" class="a2-ax">${esc(yfmt(v))}</text><line x1="${L - 2}" x2="${w - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="a2-grid"/>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" class="a2v-svg" role="img" aria-label="${esc(label)}">${ticks}${ln}${xl ? `<text x="${L}" y="${h - 4}" class="a2-ax">${esc(xl[0])}</text><text x="${w - R}" y="${h - 4}" class="a2-ax end">${esc(xl[1])}</text>` : ""}</svg>` + `<div class="a2b-leg">${series.map((s, k) => `<span class="a2b-k a2b-c${k}">${esc(s.name)}</span>`).join("")}</div>`;
}
export function histSvg(hs, { w = 340, h = 150, label = "histogram" } = {}) {
  const mx = Math.max(...hs.counts), n = hs.counts.length, L = 6, B = 22, bw = (w - 2 * L) / n, lo = hs.edges[0], hi = hs.edges[n], X = v => L + (w - 2 * L) * (v - lo) / (hi - lo);
  const bars = hs.counts.map((c, i) => { const bh = (h - B - 10) * c / mx, x0 = hs.edges[i], cls = x0 >= hs.cut_bull ? "a2b-up" : x0 + (hs.edges[1] - hs.edges[0]) <= hs.cut_bear ? "a2b-dn" : "a2b-mid"; return `<rect x="${(L + i * bw + 1).toFixed(1)}" y="${(h - B - bh).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${bh.toFixed(1)}" class="${cls}"><title>${c} stocks with a score of ${(x0 * 100).toFixed(1)}% to ${(hs.edges[i + 1] * 100).toFixed(1)}%</title></rect>`; }).join("");
  return `<svg viewBox="0 0 ${w} ${h}" class="a2v-svg" role="img" aria-label="${esc(label)}">${bars}<line x1="${X(hs.cut_bull).toFixed(1)}" x2="${X(hs.cut_bull).toFixed(1)}" y1="6" y2="${h - B}" class="a2v-ref"/><line x1="${X(hs.cut_bear).toFixed(1)}" x2="${X(hs.cut_bear).toFixed(1)}" y1="6" y2="${h - B}" class="a2v-ref"/>
    <text x="${w - 6}" y="${h - 6}" class="a2-ax end">${(hi * 100).toFixed(0)}%</text><text x="${L}" y="${h - 6}" class="a2-ax">${(lo * 100).toFixed(0)}%</text></svg>`;
}
/* the decision picture for one stock: last closes, the 5-day range if any, the entry zone, the exit level, the time limit */
export function tracePicture(t, w = 340, h = 160) {
  const c = (t.series && t.series.c) || []; if (c.length < 5) return `<p class="note">No price history for ${esc(t.sym)}.</p>`;
  const r5 = t.range5 && t.range5[0] != null ? t.range5 : null, lv = [...c, t.close, ...(r5 || []), ...(t.entry_zone || []), ...(t.invalidation ? [t.invalidation] : [])], lo = Math.min(...lv), hi = Math.max(...lv), sp = hi - lo || 1, L = 42, R = 60, T = 8, B = 16;
  const histW = (w - L - R) * 0.7, X = i => L + histW * i / (c.length - 1), Y = v => T + (h - T - B) * (1 - (v - lo) / sp), x0 = X(c.length - 1), x1 = w - R;
  const band = r5 ? `<polygon points="${x0},${Y(t.close)} ${x1},${Y(r5[1])} ${x1},${Y(r5[0])}" class="a2-b80"/>` : "";
  const zone = t.entry_zone ? `<rect x="${x0 - 4}" y="${Y(t.entry_zone[1])}" width="${x1 - x0 + 4}" height="${Math.max(1, Y(t.entry_zone[0]) - Y(t.entry_zone[1]))}" class="a2b-zone"><title>entry zone ${inr(t.entry_zone[0])}–${inr(t.entry_zone[1])}</title></rect>` : "";
  const stop = t.invalidation ? `<line x1="${x0 - 4}" x2="${x1}" y1="${Y(t.invalidation)}" y2="${Y(t.invalidation)}" class="a2b-stop"><title>exit level ${inr(t.invalidation)}</title></line><text x="${x1 + 3}" y="${Y(t.invalidation) + 3}" class="a2-ax">exit ${inr(t.invalidation, 0)}</text>` : "";
  return `<svg viewBox="0 0 ${w} ${h}" class="a2v-svg" role="img" aria-label="${esc(t.sym)}: recent closes, the 5-day range, the entry zone and the exit level"><polyline class="a2-hist" points="${c.map((v, i) => X(i).toFixed(1) + "," + Y(v).toFixed(1)).join(" ")}"/>${band}${zone}${stop}<circle cx="${x0}" cy="${Y(t.close)}" r="2.5" class="a2-dot"/>
    ${[lo, hi].map(v => `<text x="2" y="${Y(v) + 3}" class="a2-ax">${inr(v, 0)}</text>`).join("")}<text x="${x1}" y="${h - 3}" class="a2-ax end">day 5</text></svg>`;
}

/* ---------- rendering ---------- */
function lockScreen(msg) {
  const missing = blobState === "missing";
  return `<div class="a2b-lock"><div class="a2b-lock-box"><div class="a2b-logo">ALADIN <b>BOT</b></div><p>${missing ? "The console is not published yet." : "This console shows what ALADIN is doing, step by step, and how it reaches each call. It is locked. Enter the access code."}</p>
    ${missing ? "" : `<form id="a2b-form" autocomplete="off"><label class="a2b-lbl" for="botcode">Access code</label><input id="botcode" type="password" inputmode="text" autocapitalize="characters" spellcheck="false" placeholder="ALADIN-XXXX-XXXX-XXXX-XXXX-XXXX" aria-describedby="a2b-msg"><button class="btn-ink" type="submit" id="a2b-go">Unlock</button></form>`}
    <p class="note" id="a2b-msg" role="status">${esc(msg || "")}</p><p class="note">The page's data is encrypted in the browser with your code (AES-256). Without the code the file cannot be read. ${DISCLAIMER}</p></div></div>`;
}

function kpis() {
  const k = P.kpis, h = k.history, L = P.labels || {}, live = k.live_weekly || {}, n = x => x == null ? "--" : Number(x).toLocaleString("en-IN");
  const lv = (live.bull && live.bull.n) || (live.bear && live.bear.n) ? `${(live.bull.n || 0) + (live.bear.n || 0)} resolved` : "none resolved yet";
  return `<div class="a2b-kpis"><div class="a2b-kpi"><span>Forecasts made</span><b data-count="${k.forecasts_made}">${n(k.forecasts_made)}</b><small>${k.forecast_batches} nightly batch(es), price ranges at 5 horizons</small></div>
    <div class="a2b-kpi"><span>Signals this week</span><b><i class="up">${k.signals_today.bull} ${esc(L.bull || "")}</i> · <i class="down">${k.signals_today.bear} ${esc(L.bear || "")}</i></b><small>${n(k.signals_today.hold)} stocks read ${esc(L.none || "")} · ${n(k.stocks_ranked)} ranked</small></div>
    <div class="a2b-kpi"><span>Hit rate in the past (simulation)</span><b>${pc(h.bull_closed_higher)} up · ${pc(h.bear_closed_higher == null ? null : 1 - h.bear_closed_higher)} down</b><small>${esc(L.bull || "")} closed higher, ${esc(L.bear || "")} closed lower, ${n(h.stock_weeks)} stock-weeks</small></div>
    <div class="a2b-kpi"><span>${esc(L.bull || "")} vs the market (simulation)</span><b>${bps(h.bull_net_bps_per_week)} a week</b><small>after costs, 2013–2026; 95% range ${h.bull_net_ci95_bps ? h.bull_net_ci95_bps[0].toFixed(0) + " to " + h.bull_net_ci95_bps[1].toFixed(0) : "--"}; positive in ${esc(h.bull_years_positive || "--")} years. ${esc(L.bear || "")}: ${bps(h.bear_vs_market_bps_per_week)} a week, below the market in ${esc(h.bear_years_below_market || "--")} years. Not live, not real money.</small></div>
    <div class="a2b-kpi"><span>Live record</span><b>${lv}</b><small>${k.outcomes_resolved ? n(k.outcomes_resolved) + " forecasts scored" : "no forecast has reached its date yet"}</small></div></div>`;
}

function pipeline() {
  const S = P.stages, cur = S.find(s => s.id === st.stage) || S[0];
  const flow = S.map((s, i) => `<button class="a2b-st ${s.id === st.stage ? "on" : ""}" data-stage="${s.id}" aria-pressed="${s.id === st.stage}"><span class="a2b-n">${i + 1}</span>${esc(s.name.replace(/^\d+ · /, ""))}</button>${i < S.length - 1 ? '<span class="a2b-arrow" aria-hidden="true"></span>' : ""}`).join("");
  const nums = Object.entries(cur.numbers || {}).filter(([, v]) => v != null && typeof v !== "object").map(([k, v]) => `<li><span>${esc(k.replace(/_/g, " "))}</span><b>${typeof v === "number" ? v.toLocaleString("en-IN") : esc(v)}</b></li>`).join("");
  return `<div class="sec-t">What the bot does, in order</div><div class="a2b-flow" role="tablist">${flow}</div>
    <div class="a2b-detail"><div><h3>${esc(cur.name)}</h3><p><b>What:</b> ${esc(cur.what)}</p><p><b>How:</b> ${esc(cur.how)}</p><ul class="a2b-nums">${nums}</ul></div><div class="a2b-fig">${stageChart(cur.id)}</div></div>`;
}
function stageChart(id) {
  const C = P.charts;
  if (id === "score" && C.score_hist) return histSvg(C.score_hist, { label: "How many liquid stocks have each 5-day score; the lines mark the cut-offs" }) + `<p class="note">Each bar: how many stocks have that 5-day score. The two lines are the fixed cut-offs: right of the right line = best 1%, left of the left line = worst 5%.</p>`;
  if (id === "rank" && C.by_decile) return barSvg(C.by_decile.map(d => ({ l: d.decile, v: d.gross_excess_bps, t: `decile ${d.decile} (10 = best)` })), { fmt: v => bps(v), label: "Next-week return versus the market by score decile, before costs" }) + `<p class="note">Stocks grouped by score (1 = worst tenth, 10 = best). Bars: how much each group beat or trailed the market the next week, before costs, 2013–2026. The worst groups trail, the best lead: that is why a rank is useful.</p>`;
  if (id === "chance" && C.probability_curve) return curveSvg([{ name: "closes higher", y: C.probability_curve.map(b => b.p_up) }, { name: "beats the market", y: C.probability_curve.map(b => b.p_beat_market) }], { yfmt: v => pc(v), label: "Chance of closing higher and of beating the market by rank bucket, worst to best", xl: ["worst ranked", "best ranked"] }) + `<p class="note">Across: rank bucket from worst to best. Up: how often stocks in it did that over the next 5 trading days. ${C.probability_check ? `Checked on years it had not seen: calibration error ${C.probability_check.closes_higher.ece} and ${C.probability_check.beats_market.ece}.` : ""}</p>`;
  if (id === "range" && C.coverage) return barSvg(Object.entries(C.coverage).map(([h, v]) => ({ l: h + "d", v: v.coverage["80"] * 100 - 80, t: `${h}-day 80% range held ${(v.coverage["80"] * 100).toFixed(1)}%` })), { fmt: v => (v >= 0 ? "+" : "") + v.toFixed(1) + " points", label: "How far the realised coverage of the 80 percent range is from 80 percent, by horizon" }) + `<p class="note">How close the 80% price range came to holding its promise, in points from 80%, by horizon, out of sample. Near zero is honest; single stress years (2020) broke it at long horizons.</p>`;
  if (id === "learn") { const tc = trialCurveFrom(); return tc.length ? curveSvg([{ name: "strategies on trial", y: tc }], { yfmt: v => Math.round(v), label: "Number of strategies on trial over time" }) + `<p class="note">How many of the 35 rules were being paper-traded over time. It rises when rules earn a trial and falls when they fade.</p>` : ""; }
  if (id === "risk") return `<p class="note">Example: a position sized for ₹10 lakh at 1% risk is the smaller of: the money you can lose divided by the distance to the exit level, 10% of capital, 5% of the day's volume, and a fraction of the Kelly size computed from the measured edge. The smallest cap wins.</p>`;
  return `<p class="note">${esc((P.stages.find(s => s.id === id) || {}).how || "")}</p>`;
}
function trialCurveFrom() { return (P.charts.trial_curve || []).map(p => p.n); }

function evidence() {
  const C = P.charts, w = C.weekly_curves;
  const eq = w && w.dates ? curveSvg([{ name: "positive signals, summed weekly excess after costs", y: w.bull_cumulative_net_excess }], { yfmt: v => (v * 100).toFixed(0) + "%", label: "Weekly return of the positive signals above the market after costs, added up week by week, 2013 to 2026", xl: [w.dates[0], w.dates[w.dates.length - 1]] }) : "";
  const avoid = w && w.dates ? curveSvg([{ name: "cumulative shortfall of the worst 5%", y: w.bear_cumulative_underperformance }], { yfmt: v => (v * 100).toFixed(0) + "%", label: "Cumulative amount by which the worst-ranked 5 percent trailed the market, week by week", xl: [w.dates[0], w.dates[w.dates.length - 1]] }) : "";
  const yr = C.by_year ? barSvg(C.by_year.flatMap(y => [{ l: String(y.year).slice(2), v: y.bull_net_bps, t: `${y.year}: positive signals after costs vs market` }]), { fmt: v => bps(v), label: "Positive signals, return versus the market after costs, by year" }) : "";
  const yr2 = C.by_year ? barSvg(C.by_year.map(y => ({ l: String(y.year).slice(2), v: y.bear_gross_bps, t: `${y.year}: negative signals vs market` })), { fmt: v => bps(v), label: "Negative signals, return versus the market, by year" }) : "";
  return `<div class="sec-t">The evidence behind it <span class="tag">historical simulation</span></div><div class="a2b-grid"><figure><figcaption>Positive signals: weekly return above the market, after costs, added up (not compounded)</figcaption>${eq}</figure><figure><figcaption>How far the worst-ranked 5% trailed the market (cumulative)</figcaption>${avoid}</figure>
    <figure><figcaption>Positive signals by year, vs market, after costs</figcaption>${yr}</figure><figure><figcaption>Negative signals by year, vs market, before costs</figcaption>${yr2}</figure></div>
    <p class="note">Every chart here is out-of-sample testing on past data with survivors to today only (this flatters the positive signals and understates the negative ones). The lines add up small weekly edges: they are not a forecast of a future balance, they ignore how much money each week's few stocks could absorb, and they are not live trading or real money.</p>`;
}

function explorer() {
  const T = P.traces; if (!T.length) return `<div class="sec-t">Watch it decide</div><p class="note">No signals this week.</p>`;
  const t = T.find(x => x.sym === st.sym) || T[0]; st.sym = t.sym; const L = P.labels || {}, steps = P.decision_steps, ch = t.chance;
  const vals = [`Score ${(t.p5 * 100).toFixed(1)}% → rank ${(t.rank_pct * 100).toFixed(1)}th percentile of ${P.kpis.stocks_ranked.toLocaleString("en-IN")} liquid stocks`, t.signal === "bull" ? `Rank is in the best 1%: inside the positive band` : `Rank is in the worst 5%: inside the negative band`,
    ch ? `Closed higher ${pc(ch.closes_higher)} of the time (95% range ${pc(ch.closes_higher_ci95[0])}–${pc(ch.closes_higher_ci95[1])}); beat the market ${pc(ch.beats_market)}` : "no measured chance", `Round trip costs about ${t.cost_bps.toFixed(0)} bps`,
    t.signal === "bull" ? `Exit level ${inr(t.invalidation)}; ${t.exit}` : `Exit if held; ${t.fno ? "futures exist, so a short is possible" : "no futures: cash shares cannot be shorted"}`, t.size ? `At ₹${t.size.capital.toLocaleString("en-IN")} capital: ${t.size.qty} shares, ₹${t.size.capital_at_risk.toLocaleString("en-IN")} at risk (limited by ${esc(t.size.binding)})` : t.signal === "bull" ? "size depends on your capital" : "no position: nothing to size"];
  const rows = steps.map((s, i) => `<li class="${i <= st.step ? "done" : ""} ${i === st.step ? "now" : ""}"><span class="a2b-n">${i + 1}</span><div><b>${esc(s)}</b><div class="a2b-val">${i <= st.step ? esc(vals[i]) : ""}</div></div></li>`).join("");
  return `<div class="sec-t">Watch it decide</div><div class="a2b-ctl"><label for="botsym" class="a2b-lbl">Stock</label><select id="botsym">${T.map(x => `<option value="${esc(x.sym)}" ${x.sym === t.sym ? "selected" : ""}>${esc(x.sym)} · ${esc(x.signal === "bull" ? L.bull : L.bear)}</option>`).join("")}</select>
    <button class="btn-ink" id="a2b-play">${st.playing ? "Stop" : "Run the decision"}</button><button class="btn-line sm" id="a2b-next">Next step</button><button class="btn-line sm" id="a2b-open" data-sym="${esc(t.sym)}">Open ${esc(t.sym)} in the terminal →</button></div>
    <div class="a2b-trace"><ol class="a2b-steps">${rows}</ol><div class="a2b-fig"><h3>${esc(t.name)} <span class="tag ${t.signal === "bull" ? "acc" : "warn"}">${esc(t.signal === "bull" ? L.bull : L.bear)}</span></h3>${tracePicture(t)}<p class="note">${esc(t.what_to_do)}</p></div></div>`;
}

function activity() {
  return `<div class="sec-t">What it did lately</div><ul class="a2b-log">${(P.activity || []).slice(0, 18).map(a => `<li><time>${esc(String(a.when || "").slice(0, 16).replace("T", " "))}</time> ${esc(a.what)}${a.historical ? ' <span class="tag">history</span>' : ""}</li>`).join("")}</ul>`;
}

function dashboard() {
  const S = P.status || {};
  return `<div class="a2b-top"><div class="a2b-logo">ALADIN <b>BOT</b> <small>console · as of ${esc(P.as_of || "?")}</small></div><div class="a2b-chips"><span class="tag ${S.engine_suspended ? "warn" : "acc"}">${S.engine_suspended ? "ENGINE SUSPENDED" : "ENGINE RUNNING"}</span><span class="tag">${esc(String(P.mode || "").toUpperCase())} WORDING</span><button class="btn-line sm" id="a2b-lockbtn">Lock</button></div></div>
    ${kpis()}${pipeline()}${explorer()}${evidence()}${activity()}<p class="note a2v-dis">${DISCLAIMER}</p>`;
}

function render(msg) {
  if (!root) return;
  root.innerHTML = P ? dashboard() : lockScreen(msg); bind();
}
function bind() {
  const f = root.querySelector("#a2b-form");
  if (f) { f.onsubmit = e => { e.preventDefault(); unlock(root.querySelector("#botcode").value); }; const i = root.querySelector("#botcode"); if (i) i.focus(); }
  root.querySelectorAll("[data-stage]").forEach(b => b.onclick = () => { st.stage = b.dataset.stage; const keep = root.scrollTop; render(); });
  const sel = root.querySelector("#botsym"); if (sel) sel.onchange = () => { st.sym = sel.value; st.step = -1; stop(); render(); };
  const nx = root.querySelector("#a2b-next"); if (nx) nx.onclick = () => { st.step = Math.min(st.step + 1, P.decision_steps.length - 1); render(); };
  const pl = root.querySelector("#a2b-play"); if (pl) pl.onclick = () => { if (st.playing) { stop(); render(); return; } st.step = -1; st.playing = setInterval(() => { st.step++; if (st.step >= P.decision_steps.length - 1) stop(); render(); }, 1100); render(); };
  const op = root.querySelector("#a2b-open"); if (op) op.onclick = () => { if (ctx) { ctx.openSec(op.dataset.sym); ctx.go("terminal"); } };
  const lk = root.querySelector("#a2b-lockbtn"); if (lk) lk.onclick = () => { P = null; try { sessionStorage.removeItem(SS); } catch { /* fine */ } stop(); render("Locked."); };
}
function stop() { if (st.playing) { clearInterval(st.playing); st.playing = null; } }

async function unlock(code) {
  const msg = root && root.querySelector("#a2b-msg"), now = Date.now();
  if (now < until) { if (msg) msg.textContent = `Wait ${Math.ceil((until - now) / 1000)} s before trying again.`; return; }
  if (!blob) { if (msg) msg.textContent = "The file is still loading."; return; }
  if (msg) msg.textContent = "Checking the code…";
  try { P = await decrypt(blob, code); failures = 0; try { sessionStorage.setItem(SS, code); } catch { /* private window: you will be asked again */ } render(); }
  catch (e) { failures++; until = Date.now() + Math.min(30000, 1500 * failures); P = null; render("That code does not open the console."); }
}

export async function mount() {
  root = document.getElementById("a2bot"); if (!root) return;
  if (!blob && blobState === "idle") {
    blobState = "loading"; render("Loading…");
    try { const r = await fetch(FILE, { cache: "no-store" }); if (!r.ok) throw new Error("missing"); blob = await r.json(); blobState = "ready"; } catch { blobState = "missing"; }
  }
  if (!P && blob) { let c = null; try { c = sessionStorage.getItem(SS); } catch { /* none */ } if (c) { try { P = await decrypt(blob, c); } catch { P = null; } } }
  render();
}
