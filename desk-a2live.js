/* ALADIN BOT live console: the animated dashboard drawn after the access code has opened the encrypted file.
   Everything it draws comes from the decrypted payload (the weekly book, the 13-year test, the probability table, the activity log). It animates by REPLAYING real numbers:
   a scan across every ranked stock, the decision for each signal stock in turn, the 13-year test week by week. Nothing is simulated or invented; a missing input is shown as "not measured".
   "Past 5-day moves" are this stock's own earlier 5-day moves replayed from today's close: history, not a forecast. Test results are out-of-sample history, not live trading, not real money.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. */
import { esc, inr } from "./desk-aladin2.js";

export const FOCUS_MS = 7000;
const pc = (v, d = 0) => v == null ? "--" : (v * 100).toFixed(d) + "%";
const bpsf = v => v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(0) + " bps";
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const ease = x => 1 - Math.pow(1 - clamp(x, 0, 1), 3);

/* ---------- pure helpers (tested in tests/js/a2live.test.mjs) ---------- */
export function focusOrder(traces) {
  const b = traces.filter(t => t.signal === "bull"), r = traces.filter(t => t.signal !== "bull"), out = [];
  for (let i = 0; i < Math.max(b.length, r.length); i++) { if (b[i]) out.push(b[i]); if (r[i]) out.push(r[i]); }
  return out;
}
export function pastPaths(c, H = 5) {
  const out = [];
  for (let i = 0; i + H < c.length; i++) { const b = c[i]; if (!(b > 0)) continue; const p = [0]; for (let j = 1; j <= H; j++) p.push(c[i + j] / b - 1); out.push(p); }
  return out;
}
export function pathStats(paths) {
  if (!paths.length) return null;
  const fin = paths.map(p => p[p.length - 1]).sort((a, b) => a - b), q = f => fin[Math.min(fin.length - 1, Math.floor(f * fin.length))];
  return { n: fin.length, up: fin.filter(x => x > 0).length / fin.length, lo: q(0.1), med: q(0.5), hi: q(0.9) };
}
/* prefix counts of weeks in which the positive signals beat the market after costs, from the cumulative curve */
export function replayTable(w) {
  const s = (w && w.bull_cumulative_net_excess) || [], pos = [0];
  for (let k = 1; k < s.length; k++) pos.push(pos[k - 1] + (s[k] > s[k - 1] ? 1 : 0));
  return { pos, n: s.length };
}
export function replayAt(w, tab, i) {
  const s = w.bull_cumulative_net_excess; i = clamp(i, 0, s.length - 1);
  return { week: i + 1, date: w.dates[i], cum: s[i], hit: i > 0 ? tab.pos[i] / i : null, avoid: w.bear_cumulative_underperformance[i] };
}
export function decisionLines(t, P) {
  const ch = t.chance, N = (P.kpis.stocks_ranked || 0).toLocaleString("en-IN");
  return [`Score ${pc(t.p5, 1)} → rank ${(t.rank_pct * 100).toFixed(2)}th percentile of ${N} liquid stocks`,
    t.signal === "bull" ? "Rank is inside the best 1%: the positive band" : "Rank is inside the worst 5%: the negative band",
    ch ? `Closed higher ${pc(ch.closes_higher, 1)} of the time (${pc(ch.closes_higher_ci95[0], 1)} to ${pc(ch.closes_higher_ci95[1], 1)}); beat the market ${pc(ch.beats_market, 1)}` : "chance: not measured for this rank",
    `Round trip costs about ${Number(t.cost_bps).toFixed(0)} bps`,
    t.signal === "bull" ? `Exit level ${inr(t.invalidation)}; ${t.exit}` : `Exit if held; ${t.fno ? "futures exist, so a short is possible" : "no futures: cash shares cannot be shorted"}`,
    t.size ? `At ₹${t.size.capital.toLocaleString("en-IN")}: ${t.size.qty} shares, ₹${t.size.capital_at_risk.toLocaleString("en-IN")} at risk (limit: ${t.size.binding})` : t.signal === "bull" ? "size depends on your capital" : "no position: nothing to size"];
}
export function palette() {
  const g = typeof document !== "undefined" && typeof getComputedStyle === "function" ? getComputedStyle(document.documentElement) : null, v = n => g ? g.getPropertyValue(n).trim() : "";
  return { up: v("--up"), down: v("--down"), ink: v("--ink"), ink2: v("--ink-2"), ink3: v("--ink-3"), rule: v("--rule"), card: v("--card"), amber: v("--bot-amber"), cyan: v("--bot-cyan"), mono: v("--mono") || "monospace" };
}

/* ---------- canvas plumbing ---------- */
function fit(cv) {
  const r = cv.getBoundingClientRect(), dpr = Math.min(2, (typeof devicePixelRatio === "number" && devicePixelRatio) || 1), w = Math.max(40, Math.round(r.width)), h = Math.max(40, Math.round(r.height));
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h); return { g, w, h };
}
const txt = (g, C, s, x, y, col, size = 10, align = "left", weight = "") => { g.font = `${weight} ${size}px ${C.mono}`.trim(); g.fillStyle = col; g.textAlign = align; g.fillText(s, x, y); };
const line = (g, x0, y0, x1, y1, col, wd = 1, dash = null) => { g.beginPath(); g.setLineDash(dash || []); g.lineWidth = wd; g.strokeStyle = col; g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke(); g.setLineDash([]); };
const zoneCol = (C, r) => r >= 0.99 ? C.up : r <= 0.05 ? C.down : C.ink3;

/* ---------- panels ---------- */
function drawScan(f, C, P, ts, focusSym) {
  const { g, w, h } = f, S = P.scan || []; if (!S.length) { txt(g, C, "scan: not measured (no ranked stocks in the file)", 8, 20, C.ink3); return 0; }
  const n = S.length, L = 4, B = 16, T = 6, bw = (w - 2 * L) / n, ups = S.map(r => r[2]).filter(v => v != null), lo = Math.min(...ups) - 0.02, hi = Math.max(...ups) + 0.01, sp = (ts / 9000) % 1, head = Math.floor(sp * n);
  const Y = v => T + (h - T - B) * (1 - (v - lo) / (hi - lo));
  line(g, L, Y(0.5), w - L, Y(0.5), C.rule, 1, [3, 3]); txt(g, C, "50% chance of closing higher", w - L, Y(0.5) - 3, C.ink3, 9, "right");
  let fi = -1;
  for (let i = 0; i < n; i++) {
    const r = S[i], v = r[2]; if (r[0] === focusSym) fi = i; if (v == null) continue;
    const x = L + i * bw, y = Y(v), read = i <= head; g.globalAlpha = read ? (i > head - 14 ? 1 : 0.85) : 0.18; g.fillStyle = zoneCol(C, r[1]); g.fillRect(x, y, Math.max(1, bw - (bw > 2.5 ? 0.6 : 0)), h - B - y);
  }
  g.globalAlpha = 1; const hx = L + head * bw; line(g, hx, T, hx, h - B, C.amber, 1.5);
  if (fi >= 0) { const fx = L + fi * bw; line(g, fx, T, fx, h - B, C.cyan, 1, [2, 2]); txt(g, C, focusSym, clamp(fx, 24, w - 24), T + 9, C.cyan, 10, "center", "bold"); }
  txt(g, C, "best ranked", L, h - 4, C.ink3, 9); txt(g, C, "worst ranked", w - L, h - 4, C.ink3, 9, "right"); txt(g, C, `read ${(head + 1).toLocaleString("en-IN")} of ${n.toLocaleString("en-IN")}`, w / 2, h - 4, C.amber, 10, "center");
  return head + 1;
}
function drawDial(f, C, t, ph, ts, P) {
  const { g, w, h } = f, cx = w / 2, cy = h / 2 + 6, r = Math.min(w, h) / 2 - 16, a0 = 0.75 * Math.PI, sp = 1.5 * Math.PI, e = ease(ph / 0.35), arc = (rad, fr, col, wd) => { g.beginPath(); g.lineWidth = wd; g.lineCap = "round"; g.strokeStyle = col; g.arc(cx, cy, rad, a0, a0 + sp * fr); g.stroke(); };
  g.globalAlpha = 0.5; arc(r, 1, C.rule, 9); arc(r - 14, 1, C.rule, 5); g.globalAlpha = 1;
  const z = zoneCol(C, t.rank_pct), rk = clamp(t.rank_pct, 0, 1) * e; arc(r, rk, z, 9);
  const pu = t.chance ? t.chance.closes_higher : null; if (pu != null) arc(r - 14, clamp(pu, 0, 1) * e, C.cyan, 5);
  for (const cut of [0.05, 0.99]) { const a = a0 + sp * cut; line(g, cx + Math.cos(a) * (r - 8), cy + Math.sin(a) * (r - 8), cx + Math.cos(a) * (r + 8), cy + Math.sin(a) * (r + 8), C.ink, 1.5); }
  g.save(); g.translate(cx, cy); g.rotate(ts / 6000); g.beginPath(); g.setLineDash([2, 7]); g.strokeStyle = C.ink3; g.lineWidth = 1; g.arc(0, 0, r - 28, 0, Math.PI * 2); g.stroke(); g.setLineDash([]); g.restore();
  txt(g, C, (t.rank_pct * 100 * e).toFixed(2), cx, cy + 4, C.ink, Math.max(18, r / 2.6), "center", "bold"); txt(g, C, "rank percentile", cx, cy + 20, C.ink3, 10, "center");
  txt(g, C, pu == null ? "chance: not measured" : `${(pu * 100 * e).toFixed(1)}% chance higher`, cx, cy + 36, C.cyan, 11, "center"); txt(g, C, t.sym, cx, cy - r / 2.2, z, 12, "center", "bold");
}
function drawFocus(f, C, t, ph) {
  const { g, w, h } = f, s = t.series || {}, c = s.c || []; if (c.length < 8) { txt(g, C, `No price history for ${t.sym}`, 10, 24, C.ink3); return; }
  const bars = Math.min(60, c.length), o0 = c.length - bars, fwd = 14, cols = bars + fwd, L = 46, R = 8, T = 12, B = 20, cw = (w - L - R) / cols, lc = c[c.length - 1];
  const paths = pastPaths(c), ps = pathStats(paths), r5 = t.range5 && t.range5[0] != null ? t.range5 : null;
  let lo = Infinity, hi = -Infinity; for (let i = o0; i < c.length; i++) { lo = Math.min(lo, s.l ? s.l[i] : c[i]); hi = Math.max(hi, s.h ? s.h[i] : c[i]); }
  const ex = [...(t.entry_zone || []), t.invalidation, ...(r5 || []), ps ? lc * (1 + ps.lo) : null, ps ? lc * (1 + ps.hi) : null].filter(v => v != null); for (const v of ex) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad; const Y = v => T + (h - T - B) * (1 - (v - lo) / (hi - lo)), X = i => L + (i + 0.5) * cw;
  for (const v of [lo + pad, (lo + hi) / 2, hi - pad]) { line(g, L, Y(v), w - R, Y(v), C.rule, 1); txt(g, C, inr(v, 0), L - 4, Y(v) + 3, C.ink3, 9, "right"); }
  const k = Math.ceil(bars * clamp(ph / 0.4, 0, 1)); g.lineWidth = 1;
  for (let j = 0; j < k; j++) { const i = o0 + j, o = s.o ? s.o[i] : c[i], hh = s.h ? s.h[i] : c[i], ll = s.l ? s.l[i] : c[i], up = c[i] >= o, col = up ? C.up : C.down, x = X(j); line(g, x, Y(hh), x, Y(ll), col, 1); g.fillStyle = col; g.fillRect(x - cw * 0.34, Math.min(Y(o), Y(c[i])), cw * 0.68, Math.max(1, Math.abs(Y(o) - Y(c[i])))); }
  const x0 = X(bars - 1), x1 = X(cols - 1); if (ph > 0.4) {
    const q = clamp((ph - 0.4) / 0.5, 0, 1), days = q * 5;
    if (t.entry_zone) { g.globalAlpha = 0.18; g.fillStyle = C.cyan; g.fillRect(x0, Y(t.entry_zone[1]), x1 - x0 + cw, Math.max(1.5, Y(t.entry_zone[0]) - Y(t.entry_zone[1]))); g.globalAlpha = 1; txt(g, C, "entry zone", x1 + cw, Y(t.entry_zone[1]) - 3, C.cyan, 9, "right"); }
    if (t.invalidation) { line(g, x0, Y(t.invalidation), x1 + cw, Y(t.invalidation), C.down, 1.2, [5, 3]); txt(g, C, `exit ${inr(t.invalidation, 0)}`, x1 + cw, Y(t.invalidation) + 11, C.down, 9, "right"); }
    if (r5) { g.globalAlpha = 0.16; g.fillStyle = C.ink; g.beginPath(); g.moveTo(x0, Y(lc)); g.lineTo(x1, Y(r5[1])); g.lineTo(x1, Y(r5[0])); g.closePath(); g.fill(); g.globalAlpha = 1; }
    const step = Math.max(1, Math.floor(paths.length / 70)), seg = j => Math.min(j, days), dayX = d => x0 + (x1 - x0) * d / 5;
    g.globalAlpha = 0.2; g.lineWidth = 1; g.strokeStyle = C.ink2;
    for (let pi = 0; pi < paths.length; pi += step) {
      const p = paths[pi]; g.beginPath(); g.moveTo(dayX(0), Y(lc));
      for (let d = 1; d <= 5; d++) { if (days >= d) g.lineTo(dayX(d), Y(lc * (1 + p[d]))); else { const fr = days - (d - 1); if (fr > 0) g.lineTo(dayX(days), Y(lc * (1 + p[d - 1] + (p[d] - p[d - 1]) * fr))); break; } }
      g.stroke();
    }
    g.globalAlpha = 1;
    if (ps) { const m = lc * (1 + ps.med); g.beginPath(); g.lineWidth = 2; g.strokeStyle = C.amber; g.moveTo(dayX(0), Y(lc)); g.lineTo(dayX(seg(5)), Y(lc + (m - lc) * seg(5) / 5)); g.stroke();
      txt(g, C, `${ps.n} past 5-day moves of ${t.sym}: ${pc(ps.up)} closed higher; middle 80% ${(ps.lo * 100).toFixed(1)}% to ${(ps.hi * 100).toFixed(1)}%`, L + 2, h - 5, C.amber, 9); }
  }
  txt(g, C, "history replayed from today's close, not a forecast", w - R, T - 1, C.ink3, 9, "right");
}
function drawCurve(f, C, P, t, ph) {
  const { g, w, h } = f, B = P.charts.probability_curve || []; if (!B.length) { txt(g, C, "chance table: not measured", 8, 20, C.ink3); return; }
  const L = 36, R = 8, T = 10, Bt = 18, mid = b => (b.from + b.to) / 2, vals = B.flatMap(b => [b.p_up_ci95[0], b.p_up_ci95[1], b.p_beat_market]), lo = Math.min(...vals) - 0.02, hi = Math.max(...vals) + 0.02;
  const X = r => L + (w - L - R) * r, Y = v => T + (h - T - Bt) * (1 - (v - lo) / (hi - lo));
  for (const v of [lo + 0.02, (lo + hi) / 2, hi - 0.02]) { line(g, L, Y(v), w - R, Y(v), C.rule, 1); txt(g, C, pc(v), L - 3, Y(v) + 3, C.ink3, 9, "right"); }
  g.globalAlpha = 0.16; g.fillStyle = C.cyan; g.beginPath(); B.forEach((b, i) => g[i ? "lineTo" : "moveTo"](X(mid(b)), Y(b.p_up_ci95[1]))); [...B].reverse().forEach(b => g.lineTo(X(mid(b)), Y(b.p_up_ci95[0]))); g.closePath(); g.fill(); g.globalAlpha = 1;
  const ln = (key, col) => { g.beginPath(); g.lineWidth = 1.8; g.strokeStyle = col; B.forEach((b, i) => g[i ? "lineTo" : "moveTo"](X(mid(b)), Y(b[key]))); g.stroke(); }; ln("p_up", C.cyan); ln("p_beat_market", C.amber);
  const r = clamp(t.rank_pct, 0, 1) * ease(ph / 0.4), mx = X(r); line(g, mx, T, mx, h - Bt, C.ink, 1, [3, 3]);
  const at = key => { const i = B.findIndex(b => r <= b.to); const b = B[i < 0 ? B.length - 1 : i]; return b[key]; };
  g.fillStyle = C.cyan; g.beginPath(); g.arc(mx, Y(at("p_up")), 3.5, 0, 7); g.fill(); g.fillStyle = C.amber; g.beginPath(); g.arc(mx, Y(at("p_beat_market")), 3.5, 0, 7); g.fill();
  txt(g, C, "worst ranked", L, h - 4, C.ink3, 9); txt(g, C, "best ranked", w - R, h - 4, C.ink3, 9, "right"); txt(g, C, "closes higher", L + 4, T + 8, C.cyan, 9); txt(g, C, "beats the market", L + 82, T + 8, C.amber, 9);
}
function drawReplay(f, C, P, tab, ts) {
  const { g, w, h } = f, W = P.charts.weekly_curves; if (!W || !W.dates || W.dates.length < 3) { txt(g, C, "13-year test: not measured", 8, 20, C.ink3); return null; }
  const n = W.dates.length, cyc = 16000, i = Math.min(n - 1, Math.floor(clamp((ts % cyc) / (cyc * 0.9), 0, 1) * (n - 1))), a = W.bull_cumulative_net_excess, b = W.bear_cumulative_underperformance, all = [...a, ...b];
  const L = 40, R = 8, T = 22, B = 18, lo = Math.min(0, ...all), hi = Math.max(...all) * 1.05, X = k => L + (w - L - R) * k / (n - 1), Y = v => T + (h - T - B) * (1 - (v - lo) / (hi - lo));
  for (const v of [lo, (lo + hi) / 2, hi]) { line(g, L, Y(v), w - R, Y(v), C.rule, 1); txt(g, C, (v * 100).toFixed(0) + "%", L - 3, Y(v) + 3, C.ink3, 9, "right"); }
  const draw = (s, col) => { g.beginPath(); g.lineWidth = 1.6; g.strokeStyle = col; for (let k = 0; k <= i; k++) g[k ? "lineTo" : "moveTo"](X(k), Y(s[k])); g.stroke(); g.fillStyle = col; g.beginPath(); g.arc(X(i), Y(s[i]), 3, 0, 7); g.fill(); };
  draw(b, C.down); draw(a, C.up); const st = replayAt(W, tab, i); line(g, X(i), T, X(i), h - B, C.ink3, 1, [2, 3]);
  txt(g, C, `${st.date} · week ${st.week} of ${n}`, L, 12, C.ink2, 10); txt(g, C, `positive signals ${(st.cum * 100).toFixed(0)}% added up · beat the market in ${pc(st.hit)} of weeks`, w - R, 12, C.ink, 10, "right");
  txt(g, C, "green: positive signals, after costs, added up", L + 6, T + 12, C.up, 9); txt(g, C, "red: how far the worst 5% trailed the market", L + 6, T + 24, C.down, 9);
  txt(g, C, W.dates[0].slice(0, 4), L, h - 4, C.ink3, 9); txt(g, C, W.dates[n - 1].slice(0, 4), w - R, h - 4, C.ink3, 9, "right"); return st;
}
function drawHist(f, C, P, ts) {
  const { g, w, h } = f, H = P.charts.score_hist; if (!H) { txt(g, C, "score histogram: not measured", 8, 20, C.ink3); return; }
  const n = H.counts.length, L = 4, B = 16, bw = (w - 2 * L) / n, mx = Math.max(...H.counts), step = (H.edges[1] - H.edges[0]), sp = (ts / 5000) % 1, grow = ease((ts % 5000) / 900);
  H.counts.forEach((c, i) => { const bh = (h - B - 14) * c / mx * (i / n < sp ? 1 : grow), x0 = H.edges[i], col = x0 >= H.cut_bull ? C.up : x0 + step <= H.cut_bear ? C.down : C.ink3, near = Math.abs(i / n - sp) < 0.04; g.globalAlpha = near ? 1 : 0.7; g.fillStyle = col; g.fillRect(L + i * bw + 1, h - B - bh, bw - 2, bh); }); g.globalAlpha = 1;
  const X = v => L + (w - 2 * L) * (v - H.edges[0]) / (H.edges[n] - H.edges[0]); for (const v of [H.cut_bear, H.cut_bull]) line(g, X(v), 6, X(v), h - B, C.ink, 1, [3, 3]);
  txt(g, C, (H.edges[0] * 100).toFixed(0) + "%", L, h - 3, C.ink3, 9); txt(g, C, (H.edges[n] * 100).toFixed(0) + "%", w - L, h - 3, C.ink3, 9, "right"); txt(g, C, "5-day score →", w / 2, h - 3, C.ink3, 9, "center");
}

/* ---------- markup ---------- */
const panel = (cls, title, body, sub = "") => `<section class="a2l-p ${cls}"><h4><span>${title}</span><i ${sub ? `id="${sub}"` : ""}></i></h4>${body}</section>`;
export function markup(P, helpers = {}) {
  const k = P.kpis, h = k.history || {}, L = P.labels || {}, S = P.status || {}, chk = P.charts.probability_check, bl = esc(L.bull || "positive"), br = esc(L.bear || "negative"), n = x => x == null ? "--" : Number(x).toLocaleString("en-IN");
  const best = (P.charts.probability_curve || []).slice(-1)[0], live = k.live_weekly || {}, lv = (live.bull && live.bull.n) || (live.bear && live.bear.n) ? `${(live.bull.n || 0) + (live.bear.n || 0)} resolved` : "none resolved yet";
  const kp = (lab, val, sub, cls = "") => `<div class="a2l-k ${cls}"><span>${lab}</span><b>${val}</b><small>${sub}</small></div>`;
  const by = helpers.barSvg && P.charts.by_decile ? helpers.barSvg(P.charts.by_decile.map(d => ({ l: d.decile, v: d.gross_excess_bps, t: `decile ${d.decile} (10 = best)` })), { fmt: v => bpsf(v), label: "Next-week return versus the market by score decile, before costs" }) : "";
  const yr = helpers.barSvg && P.charts.by_year ? helpers.barSvg(P.charts.by_year.map(y => ({ l: String(y.year).slice(2), v: y.bull_net_bps, t: `${y.year}: positive signals after costs vs market` })), { fmt: v => bpsf(v), label: "Positive signals versus the market after costs, by year" }) : "";
  return `<div class="a2l">
  <header class="a2l-bar"><div class="a2l-logo">ALADIN <b>BOT</b></div><span class="a2l-live"><i></i>LIVE REPLAY</span><span class="a2l-clock" id="a2l-clock">--:--:-- UTC</span><span class="a2l-chip">DATA AS OF ${esc(P.as_of || "?")}</span><span class="a2l-chip ${S.engine_suspended ? "warn" : "ok"}">${S.engine_suspended ? "ENGINE SUSPENDED" : "ENGINE RUNNING"}</span><span class="a2l-chip">${esc(String(P.mode || "").toUpperCase())} WORDING</span>
    <span class="a2l-sp"></span><button class="btn-line sm" id="a2l-pause" aria-pressed="false">Pause</button><button class="btn-line sm" id="a2l-lockbtn">Lock</button></header>
  <div class="a2l-kpis">${kp("Signals this week", `<i class="up">${k.signals_today.bull} ${bl}</i> · <i class="down">${k.signals_today.bear} ${br}</i>`, `${n(k.signals_today.hold)} stocks read ${esc(L.none || "")} of ${n(k.stocks_ranked)} ranked`)}
    ${kp(`Best 1%: chance higher`, best ? pc(best.p_up, 1) : "--", best ? `95% range ${pc(best.p_up_ci95[0], 1)} to ${pc(best.p_up_ci95[1], 1)}; beats the market ${pc(best.p_beat_market, 1)}` : "not measured", "cy")}
    ${kp(`${bl} vs the market (history)`, `${bpsf(h.bull_net_bps_per_week)}<em> a week</em>`, `after costs, 2013 to 2026; positive in ${esc(h.bull_years_positive || "--")} years; not live, not real money`)}
    ${kp("Chance table check", chk ? `${chk.closes_higher.ece}<em> error</em>` : "--", chk ? `on years it had not seen; beats-the-market error ${chk.beats_market.ece}` : "not measured")}
    ${kp("Forecasts written", `<span id="a2l-fc" data-n="${k.forecasts_made || 0}">${n(k.forecasts_made)}</span>`, `${k.forecast_batches} nightly batch(es); live record: ${lv}`)}</div>
  <div class="a2l-grid">
    ${panel("a2l-scan", "SCANNER · every ranked stock, best to worst", `<div class="a2l-cv" style="height:236px"><canvas data-c="scan" aria-label="Chance of closing higher for every ranked stock, best ranked to worst, with a scan line"></canvas></div><p class="a2l-note">Bar height = measured chance of closing higher at that stock's rank. Green = the best 1%, red = the worst 5%.</p>`, "a2l-scan-n")}
    ${panel("a2l-dial", "RANK DIAL · stock in focus", `<div class="a2l-cv" style="height:230px"><canvas data-c="dial" aria-label="Rank percentile and chance of closing higher for the stock in focus"></canvas></div>`)}
    ${panel("a2l-focus", "DECISION · price, entry zone, exit level, past 5-day moves", `<div class="a2l-who" id="a2l-who"></div><div class="a2l-cv" style="height:300px"><canvas data-c="focus" aria-label="Candles for the stock in focus with the entry zone, exit level and its past 5-day moves"></canvas></div>`)}
    ${panel("a2l-steps", "HOW IT DECIDES · step by step", `<ol class="a2l-steplist" id="a2l-steps">${P.decision_steps.map((s, i) => `<li data-i="${i}"><span>${i + 1}</span><div><b>${esc(s)}</b><em></em></div></li>`).join("")}</ol>`)}
    ${panel("a2l-curve", "CHANCE TABLE · rank to probability", `<div class="a2l-cv" style="height:200px"><canvas data-c="curve" aria-label="Chance of closing higher and of beating the market by rank bucket, with the focus stock marked"></canvas></div>`)}
    ${panel("a2l-replay", "13-YEAR TEST · replayed week by week", `<div class="a2l-cv" style="height:200px"><canvas data-c="replay" aria-label="The 13-year test replayed week by week"></canvas></div><p class="a2l-note">Out-of-sample history with survivors to today: not live, not real money, not a forecast of a balance.</p>`)}
    ${panel("a2l-hist", "SCORE SPREAD", `<div class="a2l-cv" style="height:200px"><canvas data-c="hist" aria-label="How many liquid stocks have each 5-day score"></canvas></div>`)}
    ${panel("a2l-sig", "SIGNAL BOARD · click one to watch it decide", `<div class="a2l-cells" id="a2l-cells">${P.traces.map(t => `<button type="button" class="a2l-cell ${t.signal === "bull" ? "up" : "down"}" data-sym="${esc(t.sym)}" title="${esc(t.name)}"><b>${esc(t.sym)}</b><span>${t.chance ? pc(t.chance.closes_higher) : "--"}</span></button>`).join("") || '<p class="note">No signals this week.</p>'}</div>`)}
    ${panel("a2l-tape", "ACTIVITY TAPE", `<div class="a2l-tapebox"><ul class="a2l-tapelist">${[0, 1].map(() => (P.activity || []).slice(0, 20).map(a => `<li><time>${esc(String(a.when || "").slice(5, 16).replace("T", " "))}</time> ${esc(a.what)}${a.historical ? " (history)" : ""}</li>`).join("")).join("")}</ul></div>`)}
    ${panel("a2l-pipe", "PIPELINE · what the bot does, in order", `<div class="a2l-flow" id="a2l-flow">${P.stages.map((s, i) => `<button type="button" class="a2l-stg" data-i="${i}"><span>${i + 1}</span>${esc(s.name.replace(/^\d+ · /, ""))}</button>`).join("")}</div><div class="a2l-stgtxt" id="a2l-stgtxt"></div>`)}
    ${panel("a2l-ev1", "EVIDENCE · by score decile (before costs)", by || '<p class="note">not measured</p>')}
    ${panel("a2l-ev2", "EVIDENCE · positive signals by year (after costs)", yr || '<p class="note">not measured</p>')}
  </div>
  <p class="note a2v-dis">ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. Every animation replays real numbers from the file; nothing is simulated.</p></div>`;
}

/* ---------- the loop ---------- */
export function mountLive(root, P, { helpers = {}, onLock = null, onOpen = null } = {}) {
  root.innerHTML = markup(P, helpers);
  const C = palette(), reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches, order = focusOrder(P.traces), q = s => root.querySelector(s);
  const cvs = {}; root.querySelectorAll("canvas[data-c]").forEach(c => cvs[c.dataset.c] = c);
  const W = P.charts.weekly_curves, tab = replayTable(W), S = { i: 0, t0: null, paused: reduce, hold: 0, stage: 0, stgT: 0, last: 0, raf: 0, shown: -1, stepShown: -2, stgShown: -1 };
  const cur = () => order[S.i % Math.max(1, order.length)] || null;
  const setFocus = (sym, ts) => { const j = order.findIndex(t => t.sym === sym); if (j >= 0) { S.i = j; S.t0 = ts == null ? null : ts; S.hold = (ts || 0) + 24000; } };
  root.querySelectorAll("#a2l-cells .a2l-cell").forEach(b => b.onclick = () => setFocus(b.dataset.sym, performance.now()));
  const pb = q("#a2l-pause"); if (pb) { pb.textContent = S.paused ? "Play" : "Pause"; pb.setAttribute("aria-pressed", String(S.paused)); pb.onclick = () => { S.paused = !S.paused; pb.textContent = S.paused ? "Play" : "Pause"; pb.setAttribute("aria-pressed", String(S.paused)); }; }
  const lk = q("#a2l-lockbtn"); if (lk) lk.onclick = () => { stop(); if (onLock) onLock(); };
  const who = q("#a2l-who");
  if (who) who.onclick = e => { const b = e.target.closest("[data-open]"); if (b && onOpen) onOpen(b.dataset.open); };
  q("#a2l-flow").querySelectorAll(".a2l-stg").forEach(b => b.onclick = () => { S.stage = +b.dataset.i; S.stgT = performance.now(); S.stgShown = -1; });
  function paintFocus(t) {
    const L = P.labels || {}, up = t.signal === "bull";
    who.innerHTML = `<b>${esc(t.sym)}</b> <span class="tag ${up ? "acc" : "warn"}">${esc(up ? L.bull : L.bear)}</span> <span class="a2l-nm">${esc(t.name)} · ${esc(t.sector || "")} · close ${inr(t.close)}</span> <button type="button" class="btn-line sm" data-open="${esc(t.sym)}">Open in the terminal →</button>`;
    root.querySelectorAll("#a2l-cells .a2l-cell").forEach(b => b.classList.toggle("on", b.dataset.sym === t.sym)); const on = q("#a2l-cells .a2l-cell.on"); if (on && on.scrollIntoView) { const box = on.parentElement; box.scrollTop = Math.max(0, on.offsetTop - box.clientHeight / 2); }
  }
  function paintSteps(t, ph) {
    const lines = decisionLines(t, P), k = clamp(Math.floor(ph / 0.14), 0, lines.length), key = t.sym + k; if (S.stepShown === key) return; S.stepShown = key;
    root.querySelectorAll("#a2l-steps li").forEach((li, i) => { li.classList.toggle("done", i < k); li.classList.toggle("now", i === k - 1); li.querySelector("em").textContent = i < k ? lines[i] : ""; });
  }
  function paintStage(ts) {
    if (!S.hold || ts > S.hold) { if (ts - S.stgT > 4200) { S.stage = (S.stage + 1) % P.stages.length; S.stgT = ts; } }
    if (S.stgShown === S.stage) return; S.stgShown = S.stage; const s = P.stages[S.stage];
    root.querySelectorAll("#a2l-flow .a2l-stg").forEach((b, i) => b.classList.toggle("on", i === S.stage));
    const nums = Object.entries(s.numbers || {}).filter(([, v]) => v != null && typeof v !== "object").map(([k2, v]) => `<span>${esc(k2.replace(/_/g, " "))} <b>${typeof v === "number" ? v.toLocaleString("en-IN") : esc(v)}</b></span>`).join("");
    q("#a2l-stgtxt").innerHTML = `<p><b>What:</b> ${esc(s.what)}</p><p><b>How:</b> ${esc(s.how)}</p><div class="a2l-nums">${nums}</div>`;
  }
  const clock = q("#a2l-clock"); let lastClock = 0;
  function frame(ts) {
    S.raf = requestAnimationFrame(frame); if (!root.isConnected) { stop(); return; }
    if (!root.offsetParent || (typeof document !== "undefined" && document.hidden)) { S.last = ts; return; }
    if (S.t0 == null) S.t0 = ts; const dt = ts - (S.last || ts); S.last = ts; if (S.paused) S.t0 += dt;
    if (!reduce && ts - (S.fr || 0) < 30) return; S.fr = ts;
    if (ts - S.t0 >= FOCUS_MS) { if (order.length > 1 && !(S.hold && ts < S.hold)) { S.i++; } S.t0 = ts; }
    if (ts - lastClock > 900 && clock) { lastClock = ts; const d = new Date(), z = x => String(x).padStart(2, "0"), ist = new Date(d.getTime() + 19800000); clock.textContent = `${z(d.getUTCHours())}:${z(d.getUTCMinutes())}:${z(d.getUTCSeconds())} UTC · ${z(ist.getUTCHours())}:${z(ist.getUTCMinutes())} IST`; }
    const t = cur(), ph = reduce ? 1 : clamp((ts - S.t0) / FOCUS_MS, 0, 1), tt = S.paused ? (S.pauseTs = S.pauseTs || ts) : (S.pauseTs = null, ts);
    const ft = reduce ? 9000 : tt; let n = 0;
    if (cvs.scan) { n = drawScan(fit(cvs.scan), C, P, ft, t && t.sym); const sn = q("#a2l-scan-n"); if (sn) sn.textContent = `${n.toLocaleString("en-IN")} read`; }
    if (t) { if (S.shown !== S.i % order.length) { S.shown = S.i % order.length; paintFocus(t); } paintSteps(t, ph); if (cvs.dial) drawDial(fit(cvs.dial), C, t, ph, ft, P); if (cvs.focus) drawFocus(fit(cvs.focus), C, t, ph); if (cvs.curve) drawCurve(fit(cvs.curve), C, P, t, ph); }
    else if (who) who.textContent = "No signals this week: every stock reads as no signal.";
    if (cvs.replay) drawReplay(fit(cvs.replay), C, P, tab, ft); if (cvs.hist) drawHist(fit(cvs.hist), C, P, ft); paintStage(ts);
  }
  const fc = q("#a2l-fc"); if (fc && !reduce) { const to = +fc.dataset.n, t0 = performance.now(); (function tick() { const e = ease((performance.now() - t0) / 1600); fc.textContent = Math.round(to * e).toLocaleString("en-IN"); if (e < 1 && root.isConnected) requestAnimationFrame(tick); })(); }
  function stop() { if (S.raf) cancelAnimationFrame(S.raf); S.raf = 0; }
  S.raf = requestAnimationFrame(frame);
  return { stop, state: S };
}
