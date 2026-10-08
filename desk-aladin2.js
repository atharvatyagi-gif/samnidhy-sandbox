/* ALADIN 2.0 brief: the block at the top of the Details rail for the open stock.
   Verdict strip (product state, signal, why), forecast fan chart (inline SVG, existing colour tokens only), range table, strategy panel, risk panel, reliability and coverage,
   "What does this mean?" disclosures. Data: aladin2/stock/<SYM>.json (one small file, fetched when a stock opens), aladin2/scoreboard.json (once). Nothing is estimated here:
   every number is read from a file the engine wrote, and a missing input says "not measured" with its reason.
   All wording comes from the labels dictionary the engine publishes (index.json / scoreboard.json), so switching the signal vocabulary is a one-line config change.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. */

let ctx = null, onReady = null;
const cache = new Map(), pending = new Map();
let board = null, boardP = null, failed = new Set(), regimeD = null, regimeP = null;
const ui = { layers: { 95: true, 80: true, 50: true } };
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results.";
const LS = "aladin2.risk";

export function init(c, ready) { ctx = c; onReady = ready; }

/* Weekdays after a date (exchange holidays are not known here, so dates are approximate by up to a day or two over long horizons). */
export function addBusinessDays(dateStr, n) {
  const d = new Date(dateStr + "T00:00:00Z"); let k = 0;
  while (k < n) { d.setUTCDate(d.getUTCDate() + 1); const w = d.getUTCDay(); if (w !== 0 && w !== 6) k++; }
  return d.toISOString().slice(0, 10);
}
/* The lines the main chart draws to the right of the last bar for the open stock: [{id, tone, points:[[time, price]]}], honouring the layer toggles. null until the shard has loaded. */
export function fanLines(sym) {
  const d = cache.get(sym); if (!d || !d.bands || !d.bands.length) return null;
  const mk = (id, tone, f) => ({ id, tone, points: [[d.as_of, d.close], ...d.bands.map(b => [addBusinessDays(d.as_of, b.H), f(b)])] }), out = [];
  if (ui.layers[95]) out.push(mk("lo95", "edge", b => b.lo95), mk("hi95", "edge", b => b.hi95));
  if (ui.layers[80]) out.push(mk("lo80", "edge", b => b.lo80), mk("hi80", "edge", b => b.hi80));
  if (ui.layers[50]) out.push(mk("lo50", "acc", b => b.lo50), mk("hi50", "acc", b => b.hi50), mk("med", "acc", b => (b.lo50 + b.hi50) / 2));
  return { sym, lines: out };
}
/* Market-stress ribbon data {d: [...], p: [...]} once aladin2/regime.json has loaded (it is one small file for the whole market), else null. */
export function regime() {
  if (regimeD) return regimeD.missing ? null : regimeD;
  if (!regimeP && ctx) { regimeP = ctx.getJSON("aladin2/regime.json", false).then(d => { regimeD = d; }).catch(() => { regimeD = { missing: true }; }).finally(() => { if (onReady) onReady("*"); }); }
  return null;
}

/* ---------- pure helpers (tested in tests/js/aladin2.test.mjs) ---------- */
export const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const inr = (v, dp = 2) => v == null || !isFinite(v) ? "--" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });
export const pct = (v, dp = 1) => v == null || !isFinite(v) ? "--" : (v >= 0 ? "+" : "") + v.toFixed(dp) + "%";

/* Position size: identical rules to signals.position_size() in Python (tests/aladin2/test_signals.py has the same numbers). */
export function riskCalc({ capital, riskPct, entry, stop, advShares, mu, sd }, limits = { maxPosPct: 10, advPart: 0.05, kelly: 0.25 }) {
  const per = entry - stop;
  if (!(per > 0) || !(entry > 0) || !(capital > 0)) return { qty: 0, binding: "invalid inputs", capitalAtRisk: 0 };
  const eps = 1e-9, kel = mu > 0 && sd > 0 ? mu / (sd * sd) : 0;
  const caps = { "risk per trade": Math.floor(capital * riskPct / 100 / per), "max position size": Math.floor(capital * limits.maxPosPct / 100 / entry), "liquidity": Math.floor(limits.advPart * (advShares || 0)),
    "fractional Kelly (edge too small)": Math.floor(capital * Math.min(1, kel * limits.kelly) / entry + eps) };
  const binding = Object.keys(caps).reduce((a, b) => caps[b] < caps[a] ? b : a), qty = caps[binding];
  return { qty, binding, caps, capitalAtRisk: qty * per, positionValue: qty * entry };
}
export function lossLadder(entry, atr, qty) { return [-1, -2, -3].map(k => ({ k, price: entry + k * atr, loss: qty * -k * atr })); }

/* Fan geometry: history closes on the left, forecast bands to the right at each horizon (x proportional to sqrt of the horizon so short horizons stay readable). */
export function fanGeometry(d, w = 320, h = 150, pad = { l: 44, r: 8, t: 8, b: 18 }) {
  const c = d.series.c, n = c.length, Hs = d.horizons, maxH = Hs[Hs.length - 1];
  const lo = Math.min(...c, ...d.bands.map(b => b.lo95)), hi = Math.max(...c, ...d.bands.map(b => b.hi95)), span = hi - lo || 1, ymin = lo - span * 0.04, ymax = hi + span * 0.04;
  const histW = (w - pad.l - pad.r) * 0.45, fanW = (w - pad.l - pad.r) - histW, x0 = pad.l + histW;
  const y = v => pad.t + (h - pad.t - pad.b) * (1 - (v - ymin) / (ymax - ymin));
  const xh = H => x0 + fanW * Math.sqrt(H / maxH), xi = i => pad.l + histW * (i / Math.max(n - 1, 1));
  const hist = c.map((v, i) => [xi(i), y(v)]), last = d.close;
  const band = (lo, hi) => [[x0, y(last)], ...d.bands.map(b => [xh(b.H), y(b[hi])])].concat([...d.bands].reverse().map(b => [xh(b.H), y(b[lo])]), [[x0, y(last)]]);
  const med = [[x0, y(last)], ...d.bands.map(b => [xh(b.H), y((b.lo50 + b.hi50) / 2)])];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => { const v = ymin + (ymax - ymin) * f; return { y: y(v), v }; });
  return { w, h, hist, band50: band("lo50", "hi50"), band80: band("lo80", "hi80"), band95: band("lo95", "hi95"), med, ticks, xh, x0, y, last };
}
const pts = a => a.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");

/* ---------- data ---------- */
function load(sym) {
  if (cache.has(sym) || pending.has(sym) || failed.has(sym) || !ctx) return;
  const p = ctx.getJSON(`aladin2/stock/${encodeURIComponent(sym)}.json`, false).then(d => { cache.set(sym, d); }).catch(() => { failed.add(sym); }).finally(() => { pending.delete(sym); if (onReady) onReady(sym); });
  pending.set(sym, p);
}
function loadBoard() {
  if (board || boardP || !ctx) return;
  boardP = ctx.getJSON("aladin2/scoreboard.json", false).then(d => { board = d; }).catch(() => { board = { missing: true }; }).finally(() => { boardP = null; if (onReady) onReady(null); });
}
export function settings() { try { return Object.assign({ capital: 1000000, riskPct: 1 }, JSON.parse(localStorage.getItem(LS) || "{}")); } catch { return { capital: 1000000, riskPct: 1 }; } }
function saveSettings(s) { try { localStorage.setItem(LS, JSON.stringify(s)); } catch { /* private window: fine */ } }

/* ---------- HTML ---------- */
const STATE_NOTE = { Learning: "ALADIN has not yet found enough evidence for this stock. It is still learning what works.", Provisional: "Some evidence, not enough to trust: ranges shown, no trade plan.",
  Validated: "Enough live and out-of-sample evidence.", Suspended: "ALADIN switched itself off here because its own live record broke its limits." };
export function html(sym) {
  load(sym); loadBoard();
  const head = `<div class="sec-t">ALADIN 2.0 brief</div>`;
  if (failed.has(sym)) return head + `<p class="note">ALADIN has no forecast for ${esc(sym)} today (only the 500 most-traded stocks are covered). Not measured.</p>`;
  const d = cache.get(sym);
  if (!d) return head + `<p class="note">Loading the brief…</p>`;
  const lab = (board && board.labels) || { none: "NO EDGE", bull: "BULLISH SIGNAL", bear: "BEARISH SIGNAL", range: "forecast range", level: "price level likelihood", plan_level: "profit level" };
  const key = d.signal || "none", cls = key === "bull" ? "up" : key === "bear" ? "down" : "";
  const has = d.bands && d.bands.length, g = has ? fanGeometry(d) : null, s = settings(); regime();
  const verdict = `<div class="a2-verdict"><span class="tag ${d.state === "Validated" ? "acc" : d.state === "Suspended" ? "warn" : ""}" title="${esc(STATE_NOTE[d.state] || "")}">${esc(d.state.toUpperCase())}</span>
    <b class="a2-sig ${cls}">${esc(lab[key] || lab.none)}${key === "none" ? ": stand aside" : ""}</b><span class="mut">as of ${esc(d.as_of)} close</span></div>
    <p class="a2-sentence">${esc(sentence(d, lab))}</p>`;
  const chart = has ? fanSvg(d, g) : `<p class="note">No forecast range is published for ${esc(d.sym)} (ranges cover the 500 most-traded stocks).</p>`;
  const table = !has ? "" : `<details class="a2-det"><summary>Range table (${esc(lab.range)})</summary><table class="a2-tbl"><thead><tr><th>Days</th><th>50% range</th><th>80% range</th><th>95% range</th><th>Closes higher*</th></tr></thead><tbody>${d.bands.map(b =>
    `<tr><td>${b.H}</td><td>${inr(b.lo50)}–${inr(b.hi50)}</td><td>${inr(b.lo80)}–${inr(b.hi80)}</td><td>${inr(b.lo95)}–${inr(b.hi95)}</td><td>${b.p_up != null ? Math.round(b.p_up * 100) + "%" : b.base_rate != null ? "about " + Math.round(b.base_rate * 100) + "% (history; no directional information)" : "--"}</td></tr>`).join("")}</tbody></table>
    <p class="note">*For 1 and 5 days a calibrated number; for longer horizons only how often stocks like this closed higher historically. Ranges are tested out of sample: the 80% range held the price about 80% of the time.</p></details>`;
  return head + verdict + weeklyBlock(d, lab) + chart + table + (has ? attribution(d) : "") + strategyPanel(d) + riskPanel(d, s) + reliability() + what(d, lab) + `<p class="note">${DISCLAIMER}</p>`;
}

export function sentence(d, lab) {
  if (!d.bands || !d.bands.length) return d.weekly ? d.weekly.what_to_do : "No forecast range for this stock.";
  const b = d.bands.find(x => x.H === 20) || d.bands[d.bands.length - 1], p = (v) => (v / d.close - 1) * 100;
  const base = `In ${b.H} trading days ${d.sym} is likely to be between ₹${inr(b.lo80)} and ₹${inr(b.hi80)} (${pct(p(b.lo80))} to ${pct(p(b.hi80))}) about 80% of the time.`;
  return d.signal === "none" ? `${base} ALADIN sees no reliable edge in the direction: ${d.signal_why}.` : base;
}

function fanSvg(d, g) {
  const lab = (board && board.labels && board.labels.range) || "forecast range";
  const axis = g.ticks.map(t => `<text x="2" y="${t.y.toFixed(1)}" class="a2-ax">${inr(t.v, t.v < 100 ? 1 : 0)}</text><line x1="40" x2="${g.w - 8}" y1="${t.y.toFixed(1)}" y2="${t.y.toFixed(1)}" class="a2-grid"/>`).join("");
  const marks = d.bands.map(b => `<g><line x1="${g.xh(b.H).toFixed(1)}" x2="${g.xh(b.H).toFixed(1)}" y1="${g.y(b.hi95).toFixed(1)}" y2="${g.y(b.lo95).toFixed(1)}" class="a2-mk"/><text x="${g.xh(b.H).toFixed(1)}" y="${g.h - 4}" class="a2-ax mid">${b.H}d</text>
    <title>${b.H} days: 50% ${inr(b.lo50)}–${inr(b.hi50)}; 80% ${inr(b.lo80)}–${inr(b.hi80)}; 95% ${inr(b.lo95)}–${inr(b.hi95)}</title></g>`).join("");
  return `<div class="a2-fan" data-a2-fan><svg viewBox="0 0 ${g.w} ${g.h}" role="img" aria-label="${esc(lab)} for ${esc(d.sym)}: last ${d.series.c.length} closes then 50, 80 and 95 percent ranges out to ${d.horizons[d.horizons.length - 1]} days">
    ${axis}<polyline points="${pts(g.hist)}" class="a2-hist"/><polygon points="${pts(g.band95)}" class="a2-b95" data-layer="95" ${ui.layers[95] ? "" : 'style="display:none"'}/><polygon points="${pts(g.band80)}" class="a2-b80" data-layer="80" ${ui.layers[80] ? "" : 'style="display:none"'}/><polygon points="${pts(g.band50)}" class="a2-b50" data-layer="50" ${ui.layers[50] ? "" : 'style="display:none"'}/>
    <polyline points="${pts(g.med)}" class="a2-med"/><circle cx="${g.x0.toFixed(1)}" cy="${g.y(g.last).toFixed(1)}" r="2.5" class="a2-dot"/>${marks}</svg>
    <div class="a2-legend">${[95, 80, 50].map(k => `<label><input type="checkbox" data-a2-layer="${k}" ${ui.layers[k] ? "checked" : ""}> ${k}%</label>`).join("")}
    <span class="mut">line = centre of the 50% range · as of ${esc(d.as_of)} · also drawn on the chart at 1D</span></div></div>`;
}

/* Attribution waterfall: how the probability of closing higher moved from the plain base rate to the number shown. With no strategy behind a stock the ONLY step is the model's own small
   adjustment, and the chart says so. Shown for the horizons that carry a calibrated probability (1 and 5 days). */
export function attribution(d) {
  const rows = d.bands.filter(b => b.p_up != null && b.base_rate != null);
  const head = `<div class="sec-t">Where the probability came from</div>`;
  if (!rows.length) return head + `<p class="note">No probability is shown for this stock.</p>`;
  const bars = rows.map(b => { const a = b.base_rate * 100, z = b.p_up * 100, up = z >= a, W = 220, X = v => 70 + (W - 70) * (v - 40) / 20, x0 = X(Math.min(a, z)), x1 = X(Math.max(a, z));
    return `<div class="a2-wf"><span>${b.H}-day</span><svg viewBox="0 0 ${W} 22" role="img" aria-label="${b.H}-day: base rate ${a.toFixed(1)} percent, model adjustment ${(z - a).toFixed(1)} points, final ${z.toFixed(1)} percent"><line x1="${X(50)}" x2="${X(50)}" y1="0" y2="22" class="a2-grid"/><circle cx="${X(a)}" cy="11" r="3" class="a2-dot"/><rect x="${x0.toFixed(1)}" y="7" width="${Math.max(1, x1 - x0).toFixed(1)}" height="8" class="${up ? "a2-wfu" : "a2-wfd"}"/><title>base rate ${a.toFixed(1)}%, model adjustment ${(z - a).toFixed(1)} points, final ${z.toFixed(1)}%</title></svg>
      <b>${a.toFixed(0)}% → ${z.toFixed(0)}% <small>(${(z - a >= 0 ? "+" : "") + (z - a).toFixed(1)} pts)</small></b></div>`; }).join("");
  return head + bars + `<p class="note">Dot = how often stocks like this closed higher historically (the base rate); the bar = the model's own small adjustment. There are no strategy, flow, sentiment, supply-chain or regime steps because no strategy is Active for this stock: ALADIN has not found a reason to lean. Out of sample the adjustment added no skill, so treat it as noise.</p>`;
}

/* The weekly signal for this stock (or the statement that there is none): what to do, how it did in the past, what else points the same way. Every number is from the published file. */
export function weeklyBlock(d, lab) {
  const w = d.weekly, head = `<div class="sec-t">Weekly signal <span class="tag">5 trading days</span></div>`, wp = d.weekly_p;
  if (!w) return head + `<p class="note">${esc(lab.none || "HOLD")}: this stock is not in the best 1% or worst 5% of the week's ranking, so there is no weekly signal. Most stocks are not.${wp && wp.closes_higher != null ? ` For a typical stock at its rank (${(wp.rank * 100).toFixed(0)}th percentile) the chance of closing higher over 5 trading days has been ${(wp.closes_higher * 100).toFixed(0)}%, and of beating the market ${(wp.beats_market * 100).toFixed(0)}%.` : ""}</p>`;
  const r = w.record, ev = w.evidence || {}, up = w.signal === "bull";
  const hist = !r ? "" : up ? `Over 2013–2026 the best 1% each week closed higher ${(r.share_closing_up * 100).toFixed(0)}% of the time and beat the market by ${r.gross_excess_bps.toFixed(0)} bps a week before costs, ${r.net_bps.toFixed(0)} bps after costs (95% range ${r.net_ci95_bps[0].toFixed(0)} to ${r.net_ci95_bps[1].toFixed(0)}); positive after costs in ${esc(r.years_positive_net)} years.`
    : `Over 2013–2026 the worst 5% each week closed higher only ${(r.share_closing_up * 100).toFixed(0)}% of the time and fell short of the market by ${Math.abs(r.gross_excess_bps).toFixed(0)} bps a week (95% range ${r.gross_excess_ci95_bps[1].toFixed(0)} to ${r.gross_excess_ci95_bps[0].toFixed(0)}), below the market in ${esc(r.years_below_market)} years.`;
  const ch = w.chance, pc = x => (x * 100).toFixed(0) + "%", rg = c => `${(c[0] * 100).toFixed(0)}–${(c[1] * 100).toFixed(0)}%`;
  const chanceHtml = !ch ? "" : up ? `<div class="a2-chance"><div><span>Chance it closes higher in 5 trading days</span><b>${pc(ch.closes_higher)}</b><small>95% range ${rg(ch.closes_higher_ci95)}</small></div><div><span>Chance it beats the market</span><b>${pc(ch.beats_market)}</b><small>95% range ${rg(ch.beats_market_ci95)}</small></div></div>`
    : `<div class="a2-chance"><div><span>Chance it closes higher in 5 trading days</span><b>${pc(ch.closes_higher)}</b><small>95% range ${rg(ch.closes_higher_ci95)}</small></div><div><span>Chance it falls behind the market</span><b>${pc(1 - ch.beats_market)}</b><small>95% range ${rg([1 - ch.beats_market_ci95[1], 1 - ch.beats_market_ci95[0]])}</small></div></div>`;
  const chk = [["ALADIN 1 five-day technical probability", ev.aladin1_technical_p5 != null ? (ev.aladin1_technical_p5 * 100).toFixed(1) + "%" : "not measured", "the signal itself (validated)"],
    ["ALADIN 1 combined (with fundamental and sentiment)", ev.aladin1_combined_p5 != null ? (ev.aladin1_combined_p5 * 100).toFixed(1) + "% · " + esc(ev.aladin1_confidence || "") + " · views agreeing " + esc(ev.aladin1_agreement || "--") : "not measured", "context: no weekly history to test"],
    ["Outlook, beating the NIFTY over 20 days", ev.outlook_p_beat_nifty_20d != null ? (ev.outlook_p_beat_nifty_20d * 100).toFixed(0) + "%" : "not measured", "context: other horizon"],
    ["Sentiment", ev.sentiment_level || "not measured", "context: no weekly history to test"], ["Supply-chain impact (NEXUS)", ev.supply_chain_impact != null ? String(ev.supply_chain_impact) : "not measured", "context: graph too thin to validate"],
    ["Forecast range, 5 days, 80%", ev.range_5d_80pct && ev.range_5d_80pct[0] != null ? inr(ev.range_5d_80pct[0]) + "–" + inr(ev.range_5d_80pct[1]) : "not measured", "sets the risk, not the direction"], ["Strategies Active", "0", "none has passed yet"]]
    .map(([a, b, c]) => `<tr><td>${a}</td><td>${b}</td><td class="mut">${c}</td></tr>`).join("");
  return head + `<p class="a2-sentence"><b>${esc(up ? lab.bull : lab.bear)}</b> for the next 5 trading days. ${esc(w.what_to_do)}</p>${chanceHtml}<p class="note">Those chances are how often stocks at this rank did it in 2013–2026, checked out of sample (calibration error 0.015 and 0.010): the chance for a typical stock at this rank, not a promise for this one. ${hist} After a round-trip cost of about ${w.round_trip_cost_bps.toFixed(0)} bps. State: ${esc(w.state)}: ${esc(w.state_why)}.</p>
    <details class="a2-det"><summary>What else points the same way? (tested: none of it improved the weekly result)</summary><table class="a2-tbl"><tbody>${chk}</tbody></table>
    <p class="note">At the weekly horizon the 5-day score was the only input with skill; adding 5-day reversal, 3-month momentum, or a blend or stack of all three did not beat costs. Fundamental, sentiment and supply-chain views have no weekly history, so they cannot be tested.</p></details>`;
}

function strategyPanel(d) {
  const cs = d.strategies || [];
  const rows = cs.map(c => `<div class="a2-card"><div class="a2-card-t"><b>${esc(c.name)}</b><span class="tag ${c.state === "Active" ? "acc" : ""}">${esc(c.state.toUpperCase())}</span></div><div class="note">${esc(c.last_change)}</div></div>`).join("");
  return `<div class="sec-t">Strategies ALADIN is judging</div>${rows || '<p class="note">No strategies yet.</p>'}<p class="note">Evidence is pooled across all stocks, because one stock alone has too few trades to prove anything. No strategy is Active today, so none is behind a signal for ${esc(d.sym)}.</p>`;
}

function riskPanel(d, s) {
  const head = `<div class="sec-t">Risk and position size</div>`;
  if (!d.plan) return head + `<p class="note">${esc(d.plan_why)}</p><div class="a2-risk"><label>Capital ₹ <input type="number" min="0" step="10000" value="${s.capital}" data-a2-cap></label><label>Risk per trade % <input type="number" min="0.1" max="5" step="0.1" value="${s.riskPct}" data-a2-risk></label></div>
    <p class="note">Your capital and risk limit are saved in this browser only. When a stock reaches Validated, ALADIN shows an entry zone, an invalidation level, the quantity for your numbers, the money at risk, the chance of being stopped out and a loss ladder. A stop does not always fill at its level: overnight gaps and circuit limits can go past it. Sizing reduces the risk of loss; it does not remove it.</p>`;
  const p = d.plan, r = riskCalc({ capital: s.capital, riskPct: s.riskPct, entry: p.entry, stop: p.stop, advShares: p.adv_shares, mu: p.mu, sd: p.sd }), lad = lossLadder(p.entry, p.atr, r.qty);
  return head + `<div class="stats"><div><span>Entry zone</span><b>${inr(p.zone[0])}–${inr(p.zone[1])}</b></div><div><span>Invalidation</span><b>${inr(p.stop)}</b></div><div><span>Quantity</span><b>${r.qty}</b></div><div><span>Money at risk</span><b>₹${inr(r.capitalAtRisk, 0)}</b></div></div>
    <p class="note">Limited by: ${esc(r.binding)}. Chance of being stopped out within ${p.horizon} days: ${Math.round(p.p_stop * 100)}%. Worst case if every stop is hit: ₹${inr(r.capitalAtRisk, 0)} (${(r.capitalAtRisk / s.capital * 100).toFixed(2)}% of your capital).</p>
    <table class="a2-tbl"><thead><tr><th>If the price falls to</th><th>You lose</th></tr></thead><tbody>${lad.map(l => `<tr><td>${inr(l.price)} (${l.k} ATR)</td><td>₹${inr(l.loss, 0)}</td></tr>`).join("")}<tr><td>A gap past the stop (twice the distance)</td><td>₹${inr(r.qty * 2 * (p.entry - p.stop), 0)}</td></tr></tbody></table>
    <p class="note">A stop does not always fill at its level: overnight gaps and circuit limits can go past it. Sizing reduces the risk of loss; it does not remove it.</p>`;
}

function reliability() {
  if (!board) return `<div class="sec-t">Reliability and coverage</div><p class="note">Loading…</p>`;
  if (board.missing) return `<div class="sec-t">Reliability and coverage</div><p class="note">Scoreboard not available. Not measured.</p>`;
  const h = board.historical_simulation && board.historical_simulation.horizons || {};
  const rows = Object.keys(h).map(k => `<tr><td>${k}</td><td>${Math.round(h[k].coverage["80"] * 1000) / 10}%</td><td>${Math.round(h[k].coverage["95"] * 1000) / 10}%</td></tr>`).join("");
  const live = Object.keys(board.live || {}).length ? "Live results are building up: see the scoreboard." : "No live forecast has resolved yet: the live record starts with the 5-day forecasts from 6 October 2026.";
  return `<div class="sec-t">Reliability and coverage</div><table class="a2-tbl"><thead><tr><th>Days</th><th>80% range held</th><th>95% range held</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note"><b>Historical simulation</b> (out of sample, 2012–2026, survivors to today only), not live results. ${esc(live)}</p>`;
}

function what(d, lab) {
  return `<details class="a2-det"><summary>What does this mean?</summary><p class="note">The shaded fan is the ${esc(lab.range)}: the darker band holds the price about half the time, the lighter ones about 80% and 95% of the time. It is about the size of the move, not its direction.
    <b>${esc((lab.none || "NO EDGE"))}</b> means ALADIN has not found a reliable reason to expect up or down for this stock. That is the usual answer, and standing aside is a valid result. Strategies move from Probation to Active only after weeks of live paper trading, and a stock becomes Validated only after at least 60 live days, 60 out-of-sample trades and a calibration check.</p></details>`;
}

/* The block the Details rail inserts. The rail re-renders every couple of seconds while prices tick; the caller keeps the existing DOM node when `data-sig` is unchanged,
   so an opened "What does this mean?", a hidden band or a half-typed number is never thrown away. */
export function wrap(sym) {
  const h = html(sym); let x = 5381; for (let i = 0; i < h.length; i++) x = ((x << 5) + x + h.charCodeAt(i)) | 0;
  return `<div id="a2-brief" class="a2" data-sym="${esc(sym)}" data-sig="${x}">${h}</div>`;
}

/* ---------- events ---------- */
export function bind(root, sym) {
  if (!root) return;
  root.querySelectorAll("[data-a2-layer]").forEach(cb => cb.onchange = () => { ui.layers[cb.dataset.a2Layer] = cb.checked; root.querySelectorAll(`[data-layer="${cb.dataset.a2Layer}"]`).forEach(el => { el.style.display = cb.checked ? "" : "none"; }); if (onReady) onReady(sym); });
  const cap = root.querySelector("[data-a2-cap]"), rk = root.querySelector("[data-a2-risk]");
  const upd = () => { const s = settings(); s.capital = Math.max(0, +cap.value || 0); s.riskPct = Math.min(5, Math.max(0.1, +rk.value || 1)); saveSettings(s); if (onReady) onReady(sym); };
  if (cap) cap.onchange = upd; if (rk) rk.onchange = upd;
}

/* test hook: lets tests/js put data in the caches without a network */
export const _test = { put: (sym, d) => cache.set(sym, d), board: b => { board = b; }, reset: () => { cache.clear(); board = null; failed.clear(); } };
