/* ALADIN, model E (aladin-e-1): the single public model. Momentum with a daily risk check (aladin-audit/SPEC_ALADIN_E.md).
   Panels: market state, the portfolio and a search for any stock (rank, state, the measured record of its rank group with a 95% range),
   "why" in plain words, model health, the paper account, alerts. Data: aladin_e.json (scripts/aladin_e.py, nightly). No price level to aim for is
   ever shown; every percentage comes with its measured range. Pure helpers are exported for tests/js/aladin_e.test.mjs.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis on paper only, not investment advice. */

let ctx = null, root = null, D = null, loading = null, failed = false;
const st = { q: "", open: null, capital: null };
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis on paper only, not investment advice. Past results do not predict future results.";
const CAP_KEY = "aladin.e.capital";

export function setQuery(sym) { st.q = sym ? String(sym).toUpperCase() : ""; st.open = st.q || null; }   // ALADIN SYM from the command line: that stock's row, opened
export function init(c) { ctx = c; try { st.capital = Number(localStorage.getItem(CAP_KEY)) || null; } catch { /* none */ } }

/* ---------- pure helpers ---------- */
const pc = (v, dp = 1) => v == null || !isFinite(v) ? "--" : (v >= 0 ? "+" : "") + v.toFixed(dp) + "%";
const pp = v => v == null ? "--" : (v * 100).toFixed(1) + "%";
export function groupOf(rankPct, cal) {
  for (const b of (cal && cal.buckets) || []) if (rankPct >= b.from && rankPct < b.to + (b.to >= 1 ? 1e-9 : 0)) return b;
  return null;
}
/* Round-trip cost of one position of `value` rupees: STT both sides, stamp, exchange, SEBI, GST, slippage both sides, the DP charge on the way out. */
export function roundTripPct(value, c) {
  if (!c || !value) return null;
  const ch = 2 * (c.exchange_txn_pct + c.sebi_fee_pct + c.brokerage_pct) * (1 + c.gst_pct_on_brokerage_and_charges / 100);
  return c.stt_entry_pct + c.stt_exit_pct + c.stamp_duty_entry_pct + ch + 2 * c.slippage_pct.adv_ge_20cr + 100 * c.dp_charge_per_scrip_exit_inr / value;
}
/* The plain reasons for one stock (3 to 5 lines). row = [rank, rankPct, r126, inPortfolio]. */
export function reasons(sym, row, doc) {
  const [rank, pct, r126, inP] = row, n = doc.universe_size, k = doc.portfolio_size, g = groupOf(pct, doc.calibration), out = [];
  const cut = (doc.portfolio && doc.portfolio.length) ? doc.portfolio[doc.portfolio.length - 1].r126 : null;
  out.push(`${r126 >= 0 ? "Up" : "Down"} ${Math.abs(r126 * 100).toFixed(1)}% over the last 6 months (126 trading sessions).`);
  out.push(inP ? `That ranks ${rank} of the ${n} most-traded stocks, inside the best ${k}, so it is in the portfolio.`
    : `That ranks ${rank} of the ${n} most-traded stocks. The portfolio takes the best ${k}${cut != null ? ` (the ${k}th is ${pc(cut * 100)})` : ""}, so: no signal.`);
  if (g) out.push(`Stocks ranked like this (${g.label}) beat the average stock ${pp(g.beat_market)} of the time over the next quarter (range ${pp(g.beat_market_ci95[0])} to ${pp(g.beat_market_ci95[1])}); on average they led by ${pc(g.mean_excess_pct)} (range ${pc(g.mean_excess_ci95_pct[0])} to ${pc(g.mean_excess_ci95_pct[1])}). The typical one trailed (${pc(g.median_excess_pct)}): a few large winners lift the average.`);
  const r = doc.risk || {};
  if (r.risk_on != null) out.push(`Market risk check: the NIFTY 500 is ${r.risk_on ? "above" : "below"} its 200-day average, so the model is ${Math.round((r.invested_share || 0) * 100)}% invested${r.risk_on ? "" : " (half its normal size)"}.`);
  if (doc.next_rebalance_in_sessions != null) out.push(`The portfolio changes about every 63 sessions; the next change is due in ${doc.next_rebalance_in_sessions} session${doc.next_rebalance_in_sessions === 1 ? "" : "s"}.`);
  return out;
}
export function search(doc, q, names) {
  const ql = String(q || "").trim().toUpperCase(); if (!ql || !doc || !doc.stocks) return [];
  return Object.keys(doc.stocks).filter(s => s.startsWith(ql) || s.includes(ql) || String((names && names.get(s)) || "").toUpperCase().includes(ql)).sort((a, b) => doc.stocks[a][0] - doc.stocks[b][0]).slice(0, 12);
}
export function alerts(doc) {
  const a = [];
  if (!doc) return a;
  if (doc.status === "degraded") a.push(["down", `Data is late (${doc.degraded_reason || "prices are stale"}): signals are hidden until fresh prices arrive.`]);
  if (doc.risk && doc.risk.kill) a.push(["down", `Kill switch: ${doc.risk.kill.reason}. No new positions until the owner reviews it.`]);
  if (doc.health && doc.health.alarm) a.push(["warn", `Accuracy alarm: ${doc.health.alarm}.`]);
  if (doc.risk && doc.risk.pause_entries_next_open) a.push(["warn", "The paper account fell more than 4% today: no new positions at the next open."]);
  return a;
}

export const SIGNAL_NOTE = "Educational paper-trading signals from a student-built model, shown so you can follow the paper account. Not investment advice. The authors are not SEBI-registered research analysts. Real trades are your own decision and risk.";
/* Buy and sell signals: the paper account's own orders for the next open and what it holds (owner, 2026-11-13). No stop price: the stop-loss test failed. */
export function signalsHtml(sg, esc) {
  if (!sg) return "";
  const n = (v, dp = 2) => v == null || !isFinite(v) ? "--" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const chg = v => v == null ? "--" : `<span class="${v >= 0 ? "up" : "down"}">${pc(v * 100)}</span>`;
  const rng = r => r ? `${n(r.low)} · <b>${n(r.typical)}</b> · ${n(r.high)}<small>${pc(r.pct[0], 0)} · ${pc(r.pct[1], 0)} · ${pc(r.pct[2], 0)}</small>` : "--";
  const sells = (sg.sell || []).map(s => `<tr><td><span class="ae-sig sell">Sell${s.part ? " part" : ""}</span></td><td><b>${esc(s.sym)}</b></td><td class="r">${s.shares ?? "--"}</td><td class="r">${n(s.ref_price)}</td><td class="r">${n(s.entry_px)}</td><td class="r">${chg(s.change_since_entry)}</td><td>${esc(s.why)}</td></tr>`).join("");
  const buys = (sg.buy || []).map(b => `<tr><td><span class="ae-sig ${b.state === "held" ? "hold" : "buy"}">${b.state === "held" ? "Holding" : "Buy"}</span><small>${b.state === "held" ? "since " + esc(b.entry_date) : "at the next open"}</small></td>
    <td><b>${esc(b.sym)}</b><small>rank ${b.rank ?? "--"}</small></td><td class="r">${b.shares ?? "--"}</td><td class="r">${n(b.ref_price)}<small>${b.state === "held" ? "paid" : "last close"}</small></td>
    <td class="r">${b.state === "held" ? `${n(b.last_close)}<small>${b.change_since_entry == null ? "" : pc(b.change_since_entry * 100)}</small>` : "--"}</td><td class="r ae-rng">${rng(b.range)}</td></tr>`).join("");
  const done = (sg.sold_recently || []).slice(0, 8).map(t => `<li>${esc(t.date)}: sold ${t.shares} <b>${esc(t.sym)}</b> at ${n(t.px)}, ${t.net_return == null ? "" : chg(t.net_return) + " after costs, "}${esc(t.why)}</li>`).join("");
  const ex = sg.exits || {};
  return `<div class="sg-card ae-signals"><h4>Buy and sell signals <small>for the next open, after the ${esc(sg.as_of)} close</small></h4>
    <p class="ae-alert">${esc(SIGNAL_NOTE)}</p>
    <h5>Sell at the next open</h5>
    ${sells ? `<div class="tablecard"><table class="tbl sm"><thead><tr><th>Signal</th><th>Stock</th><th class="r">Shares</th><th class="r">Last close</th><th class="r">Bought at</th><th class="r">Change</th><th>Why</th></tr></thead><tbody>${sells}</tbody></table></div>` : `<p class="note">No sell signal for the next open.</p>`}
    <h5>Buy and holding</h5>
    ${buys ? `<div class="tablecard"><table class="tbl sm"><thead><tr><th>Signal</th><th>Stock</th><th class="r">Shares (₹1 lakh account)</th><th class="r">Entry price</th><th class="r">Last close</th><th class="r">Expected range in about 3 months: low · typical · high</th></tr></thead><tbody>${buys}</tbody></table></div>` : `<p class="note">No buy signal and no holding.</p>`}
    <p class="note">${esc(sg.range_note)}</p>
    <div class="ae-two"><dl class="ae-dl"><div><dt>Next quarterly rebalance</dt><dd>${ex.next_rebalance_in_sessions == null ? "--" : `in ${ex.next_rebalance_in_sessions} sessions`}<small> (stocks that leave the best 5% are sold)</small></dd></div>
      <div><dt>Daily market check</dt><dd>${esc(ex.risk_check || "")}</dd></div><div><dt>Kill switch</dt><dd>${esc(ex.kill_switch || "")}</dd></div>
      <div><dt>Stop-loss</dt><dd>${esc(sg.stop_loss || "")}</dd></div></dl>
      <div>${done ? `<h5>Sold recently</h5><ul class="ae-why ae-sold">${done}</ul>` : `<p class="note">Nothing sold yet. Entries and sells are filled at the open of the next session; the paper account below shows every fill and charge.</p>`}</div></div></div>`;
}

/* ---------- data ---------- */
async function load() {
  if (D || loading || failed) return loading;
  loading = ctx.getJSON("aladin_e.json").then(j => { D = j; }).catch(() => { failed = true; }).finally(() => { loading = null; });
  return loading;
}
export async function ready() { await load(); return D; }
export function doc() { return D; }

/* A short block for the terminal's Details panel and anywhere else a stock is open. */
export function miniHtml(sym) {
  const esc = ctx.esc;
  if (!D) { load().then(() => { if (D && ctx.onEReady) ctx.onEReady(); }); return `<div class="sec-t">ALADIN</div><p class="note">${failed ? "ALADIN is not published yet." : "Loading…"}</p>`; }
  if (D.status === "degraded") return `<div class="sec-t">ALADIN</div><p class="note">Data is late: ${esc(D.degraded_reason || "")}. Signals are hidden.</p>`;
  const row = D.stocks[sym];
  if (!row) return `<div class="sec-t">ALADIN</div><p class="note">Not ranked: ALADIN ranks the ${D.universe_size} most-traded stocks with at least a year of prices.</p>`;
  const g = groupOf(row[1], D.calibration);
  return `<div class="sec-t">ALADIN</div><p class="ae-state ${row[3] ? "on" : ""}"><b>${row[3] ? "In the portfolio" : "No signal"}</b> · rank ${row[0]} of ${D.universe_size} · ${pc(row[2] * 100)} in 6 months</p>
    ${g ? `<p class="note">Its rank group beat the average stock ${pp(g.beat_market)} of the time over a quarter (range ${pp(g.beat_market_ci95[0])}–${pp(g.beat_market_ci95[1])}); average lead ${pc(g.mean_excess_pct)}.</p>` : ""}
    <p class="note">As of the ${esc(D.as_of)} close · ${esc(D.version)} · <button class="lnk" data-go="signals">Why, and the full list →</button></p>`;
}

/* ---------- the page ---------- */
function strip(m) {
  const esc = ctx.esc, cell = (k, v, sub, cls = "") => `<div class="ae-cell ${cls}"><span>${k}</span><b>${v}</b><small>${sub}</small></div>`;
  const r = D.risk || {};
  return `<div class="ae-strip">
    ${m.nifty500 ? cell("NIFTY 500", `${pc(m.nifty500.vs_200d_pct)} vs 200-day`, `${r.risk_on ? "risk on: 70% invested" : "risk off: 35% invested"} · as of ${esc(m.nifty500.as_of)}`, r.risk_on ? "" : "warn") : cell("NIFTY 500", "not measured", "index history missing")}
    ${m.india_vix ? cell("India VIX", m.india_vix.level.toFixed(1), `higher than ${m.india_vix.higher_than_pct_of_last_year}% of the last year · ${esc(m.india_vix.as_of)}`) : cell("India VIX", "not measured", "no VIX history")}
    ${m.breadth ? cell("Breadth", `${m.breadth.share_above_200d_pct}%`, `of ${m.breadth.stocks} stocks above their 200-day average · ${esc(m.breadth.as_of)}`) : ""}
    ${m.fii_dii_20d ? cell("FII / DII, 20 sessions", `₹${Math.round(m.fii_dii_20d.fii_net_cr).toLocaleString("en-IN")} / ₹${Math.round(m.fii_dii_20d.dii_net_cr).toLocaleString("en-IN")} Cr`, `net, ${esc(m.fii_dii_20d.from)} to ${esc(m.fii_dii_20d.to)}`) : cell("FII / DII", "not measured", "no NSE report saved")}
    ${cell("Model state", D.status === "running" ? "Running" : D.status === "stopped" ? "Stopped" : "Degraded", `${esc(D.version)} · as of the ${esc(D.as_of)} close`, D.status === "running" ? "" : "down")}</div>`;
}
function rowHtml(sym, row, names) {
  const esc = ctx.esc, g = groupOf(row[1], D.calibration), open = st.open === sym;
  const cap = st.capital || (D.paper && D.paper.capital) || 100000, share = (D.risk && D.risk.invested_share) || 0.7, per = cap * share / Math.max(1, D.portfolio_size);
  const rt = roundTripPct(per, D.costs || null);
  const ev = g && rt != null ? g.mean_excess_pct - rt : null;
  return `<tr class="ae-r ${open ? "on" : ""}" data-sym="${esc(sym)}" tabindex="0"><td class="mut">${row[0]}</td><td><b>${esc(sym)}</b><small>${esc((names && names.get(sym)) || "")}</small></td>
    <td class="r ${row[2] >= 0 ? "up" : "down"}">${pc(row[2] * 100)}</td><td>${row[3] ? '<span class="ae-pill on">In the portfolio</span>' : '<span class="ae-pill">No signal</span>'}</td>
    <td class="r">${g ? `${pp(g.beat_market)} <small>${pp(g.beat_market_ci95[0])}–${pp(g.beat_market_ci95[1])}</small>` : "--"}</td>
    <td class="r">${g ? `${pc(g.mean_excess_pct)} <small>${pc(g.mean_excess_ci95_pct[0])} to ${pc(g.mean_excess_ci95_pct[1])}</small>` : "--"}</td>
    <td class="r">${row[3] && ev != null ? `${pc(ev)}<small>after about ${rt.toFixed(1)}% costs</small>` : "--"}</td>
    <td class="r">${row[3] ? `₹${Math.round(per).toLocaleString("en-IN")}` : "--"}</td></tr>
    ${open ? `<tr class="ae-x"><td colspan="8"><ul class="ae-why">${reasons(sym, row, D).map(t => `<li>${esc(t)}</li>`).join("")}</ul><button class="lnk" data-chart="${esc(sym)}">Open the chart →</button></td></tr>` : ""}`;
}
function listHtml(names) {
  const esc = ctx.esc;
  const syms = st.q ? search(D, st.q, names) : D.portfolio.map(p => p.sym);
  if (!syms.length) return `<p class="note">${st.q ? "No ranked stock matches. ALADIN ranks the most-traded stocks only." : "No portfolio yet."}</p>`;
  return `<div class="tablecard"><table class="tbl sm ae-t"><thead><tr><th>Rank</th><th>Stock</th><th class="r">6 months</th><th>State</th><th class="r">Group beat the average stock</th><th class="r">Group's average lead, a quarter</th><th class="r">Expected after costs</th><th class="r">Size at your capital</th></tr></thead>
    <tbody>${syms.map(s => rowHtml(s, D.stocks[s], names)).join("")}</tbody></table></div>
    <p class="note">${st.q ? "" : `The best ${D.portfolio_size} of ${D.universe_size} by 6-month return. `}"Group" = every stock that held a similar rank on past dates (2010–2026, companies listed today, before costs). Ranges are 95%. "Expected after costs" = the group's average lead minus the round-trip costs of one position this size, including the DP charge. Click a row for the reasons.</p>`;
}
function calibSvg(cal) {
  const b = (cal && cal.buckets) || []; if (!b.length) return "";
  const W = 520, rowH = 26, H = b.length * rowH + 24, lo = Math.min(...b.map(x => x.mean_excess_ci95_pct[0]), 0), hi = Math.max(...b.map(x => x.mean_excess_ci95_pct[1]), 0);
  const X = v => 170 + (v - lo) / (hi - lo || 1) * (W - 200);
  return `<svg viewBox="0 0 ${W} ${H}" class="ae-cal" role="img" aria-label="Average lead over the average stock for each rank group, with 95% ranges">
    <line x1="${X(0)}" x2="${X(0)}" y1="4" y2="${H - 18}" class="ae-zero"/>
    ${b.map((x, i) => { const y = 14 + i * rowH; return `<text x="4" y="${y + 4}" class="ae-lbl">${x.label}</text>
      <line x1="${X(x.mean_excess_ci95_pct[0])}" x2="${X(x.mean_excess_ci95_pct[1])}" y1="${y}" y2="${y}" class="ae-ci"/><circle cx="${X(x.mean_excess_pct)}" cy="${y}" r="4" class="${x.mean_excess_pct >= 0 ? "ae-pos" : "ae-neg"}"><title>${x.label}: ${pc(x.mean_excess_pct)} (${pc(x.mean_excess_ci95_pct[0])} to ${pc(x.mean_excess_ci95_pct[1])})</title></circle>`; }).join("")}
    <text x="${X(0)}" y="${H - 4}" class="ae-lbl mid">0 = the average stock</text></svg>`;
}
function healthHtml() {
  const esc = ctx.esc, h = D.health || {}, rate = r => r && r.n ? `${pp(r.hit_rate)} <small>of ${r.n}</small>` : `<span class="mut">not measured yet</span>`;
  return `<div class="ae-two"><div class="sg-card"><h4>Model health</h4>
      <dl class="ae-dl"><div><dt>Beat the NIFTY 500, last 20 closed positions</dt><dd>${rate(h.last_20)}</dd></div><div><dt>Last 60</dt><dd>${rate(h.last_60)}</dd></div><div><dt>Last 250</dt><dd>${rate(h.last_250)}</dd></div>
      <div><dt>Last data update</dt><dd>${esc(D.as_of)} close (published ${esc((D.generated_utc || "").replace("T", " ").slice(0, 16))} UTC)</dd></div><div><dt>Last portfolio change</dt><dd>${esc(D.last_rebalance || "not yet")}</dd></div>
      <div><dt>Status</dt><dd>${esc(D.status)}</dd></div><div><dt>Settings re-checked</dt><dd>once a year (the rule has nothing to retrain)</dd></div></dl>
      <p class="note">A closed position counts as a hit when its return after costs beat the NIFTY 500 over the same days. ${h.closed_positions ? "" : "The paper account has no closed positions yet."}</p></div>
    <div class="sg-card"><h4>Is the ranking in the right order?</h4>${calibSvg(D.calibration)}<p class="note">Average lead over the average stock in the next quarter, by rank group, with 95% ranges (2010–2026, before costs, companies listed today only, so the top groups are likely flattered). Better ranks led more on average, though every group's typical stock trailed.</p></div></div>`;
}
function paperHtml() {
  const esc = ctx.esc, p = D.paper || {}, inr = v => "₹" + Math.round(v).toLocaleString("en-IN");
  const pl = p.equity - p.capital, dd = p.drawdown || 0, limit = 0.25;
  const hold = (D.holdings || []).map(h => { const r = h.last_close ? h.last_close / h.entry_px - 1 : null; return `<tr><td><b>${esc(h.sym)}</b></td><td>${esc(h.entry_date)}</td><td class="r">${h.shares}</td><td class="r">${h.entry_px.toFixed(2)}</td><td class="r">${h.last_close != null ? h.last_close.toFixed(2) : "--"}</td><td class="r ${r >= 0 ? "up" : "down"}">${r == null ? "--" : pc(r * 100)}</td></tr>`; }).join("");
  const tr = (p.last_trades || []).slice().reverse().slice(0, 30).map(t => `<tr><td>${esc(t.date)}</td><td>${t.side === "exit" ? "Exited" : "Entered"}</td><td><b>${esc(t.sym)}</b></td><td class="r">${t.shares}</td><td class="r">${t.px.toFixed(2)}</td><td class="r">₹${t.cost.toFixed(0)}</td><td class="r ${t.net_return >= 0 ? "up" : t.net_return < 0 ? "down" : ""}">${t.net_return != null ? pc(t.net_return * 100) : ""}</td><td class="mut">${esc(t.why || "")}</td></tr>`).join("");
  const pend = p.pending && p.pending.orders && p.pending.orders.length ? `<p class="note">Queued for the next open (${esc(p.pending.reason)}): ${p.pending.orders.map(o => `${o.side === "exit" ? "exit" : "enter"} ${esc(o.sym)}`).join(", ")}.</p>` : "";
  return `<div class="sg-card"><h4>Paper account (not real money)</h4>
    <div class="ae-strip small"><div class="ae-cell"><span>Value</span><b>${inr(p.equity)}</b><small>started ${inr(p.capital)} on ${esc(p.start)}</small></div>
      <div class="ae-cell"><span>Profit / loss</span><b class="${pl >= 0 ? "up" : "down"}">${pl >= 0 ? "+" : "−"}${inr(Math.abs(pl))}</b><small>after every cost</small></div>
      <div class="ae-cell"><span>Charges paid</span><b>${inr(p.costs_paid || 0)}</b><small>STT, stamp, exchange, GST, DP, slippage</small></div>
      <div class="ae-cell ${dd <= -0.15 ? "warn" : ""}"><span>Fall from its peak</span><b>${pc(dd * 100)}</b><small>limit −25%: the kill switch</small><i class="ae-dd"><em style="width:${Math.min(100, Math.abs(dd) / limit * 100).toFixed(0)}%"></em></i></div>
      <div class="ae-cell"><span>Cash</span><b>${inr(p.cash)}</b><small>${p.positions} positions</small></div></div>
    ${pend}
    ${hold ? `<div class="tablecard"><table class="tbl sm"><thead><tr><th>Open position</th><th>Since</th><th class="r">Shares</th><th class="r">Entry</th><th class="r">Last close</th><th class="r">Change</th></tr></thead><tbody>${hold}</tbody></table></div>` : `<p class="note">No open positions yet: the first orders fill at the next open after the first run.</p>`}
    ${tr ? `<div class="tablecard"><table class="tbl sm"><thead><tr><th>Date</th><th>Action</th><th>Stock</th><th class="r">Shares</th><th class="r">Price</th><th class="r">Charges</th><th class="r">Net result</th><th>Why</th></tr></thead><tbody>${tr}</tbody></table></div>` : ""}</div>`;
}
function page() {
  const esc = ctx.esc;
  if (!D) return `<p class="note">${failed ? "ALADIN is not published yet: it runs after each evening's prices." : "Loading…"}</p>`;
  const names = ctx.S.map ? new Map([...ctx.S.map].map(([k, v]) => [k, v.n])) : null, al = alerts(D);
  const cap = st.capital || (D.paper && D.paper.capital) || 100000;
  return `<div class="sg"><div class="sg-head"><div><h2>ALADIN</h2><p>The ${D.universe_size} most-traded stocks ranked by their 6-month rise; the best ${D.portfolio_size} form the portfolio, changed about every quarter, half-sized when the market is below its 200-day average.</p></div></div>
    ${al.map(([c, t]) => `<p class="ae-alert ${c}" role="alert">${esc(t)}</p>`).join("")}
    ${strip(D.market || {})}
    ${D.status === "degraded" ? "" : signalsHtml(D.signals, esc)}
    <div class="sg-bar"><div class="sg-search"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="M14 14l4 4"/></svg><input id="ae-q" type="search" autocomplete="off" spellcheck="false" placeholder="Find any stock's rank: symbol or company name" value="${esc(st.q)}" aria-label="Find any stock's rank"></div>
      <label class="ae-cap">Your capital ₹ <input id="ae-cap" type="number" min="10000" step="10000" value="${Math.round(cap)}" aria-label="Your capital in rupees, for the size column"></label></div>
    <div id="ae-list">${D.status === "degraded" ? "" : listHtml(names)}</div>
    ${healthHtml()}${paperHtml()}
    <p class="note">How it works, the tests behind it and its limits: the model was chosen in a fair test of seven approaches on 2010–2026 data after Indian trading costs. Companies that later disappeared are missing from free data, which flatters the test; the strict check for luck was not passed; it has had losing years. ${DISCLAIMER}</p></div>`;
}
function bind() {
  const q = root.querySelector("#ae-q");
  if (q) q.oninput = () => { st.q = q.value; const names = ctx.S.map ? new Map([...ctx.S.map].map(([k, v]) => [k, v.n])) : null; root.querySelector("#ae-list").innerHTML = listHtml(names); bindRows(); };
  const c = root.querySelector("#ae-cap");
  if (c) c.onchange = () => { const v = Number(c.value); if (v >= 10000) { st.capital = v; try { localStorage.setItem(CAP_KEY, String(v)); } catch { /* fine */ } render(); } };
  bindRows();
}
function bindRows() {
  root.querySelectorAll("tr.ae-r").forEach(tr => { const f = () => { st.open = st.open === tr.dataset.sym ? null : tr.dataset.sym; render(); }; tr.onclick = f; tr.onkeydown = e => { if (e.key === "Enter") f(); }; });
  root.querySelectorAll("[data-chart]").forEach(b => b.onclick = e => { e.stopPropagation(); ctx.openSec(b.dataset.chart); ctx.go("terminal"); });
}
function render() { if (!root) return; root.innerHTML = page(); bind(); }
export async function mount() {
  root = document.getElementById("signals"); if (!root) return;
  render(); await load(); render();
}
