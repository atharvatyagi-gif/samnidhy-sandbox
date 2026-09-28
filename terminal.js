/* B-LAB TERMINAL (expert-terminal.html). Real data only:
   live.json   delayed prices, 5-min bars, world indices, headlines (refreshed ~15 min in market hours)
   screener.json   today's NIFTY 500 screen with fundamentals, holdings and analyst data
   Nothing is simulated: cells flash only when a fresh value arrives. */

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const IST = "Asia/Kolkata";
const POLL_MS = 60000;

let LIVE = {}, SCREEN = {}, sec = null, focusFn = "GP", range = "1Y";
const prevWei = {};

/* ---------------- formatting ---------------- */
const n2 = (v, d = 2) => v == null ? "--" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const inr = (v, d = 2) => v == null ? "--" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const sg = (v, d = 2) => v == null ? "--" : (v > 0 ? "+" : "") + Number(v).toFixed(d);
const ud = v => v == null ? "flat" : v > 0 ? "up" : v < 0 ? "down" : "flat";
const big = v => v == null ? "--" : v >= 1e12 ? (v / 1e12).toFixed(2) + "T" : v >= 1e9 ? (v / 1e9).toFixed(2) + "B" : v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : Math.round(v).toLocaleString("en-US");
const crore = v => v == null ? "--" : "INR " + Math.round(v).toLocaleString("en-IN") + " Cr";
const pctx = (v, d = 2) => v == null ? "--" : (v * 100).toFixed(d) + "%";
const bbg = s => `${s} IN Equity`;
const picks = () => SCREEN.picks || [];
const liveOf = s => (LIVE.stocks || {})[s] || null;
const pickOf = s => picks().find(p => p.symbol === s) || null;

/* ---------------- auth / user ---------------- */
function onReady(user) {
  $("#sys-user").textContent = user.email;
  $("#logout").addEventListener("click", async () => {
    try { await window.__expertSignOut?.(); } finally { location.replace("auth.html"); }
  });
}
document.addEventListener("expert-ready", e => { window.__expertSignOut = e.detail.signOut; onReady(e.detail.user); });
if (window.expertUser) onReady(window.expertUser);

/* ---------------- clock ---------------- */
function tick() {
  const t = new Date().toLocaleTimeString("en-GB", { timeZone: IST, hour12: false });
  $("#clock").textContent = t + " IST";
}
setInterval(tick, 1000); tick();

/* ---------------- data ---------------- */
async function getJSON(url) {
  const r = await fetch(url + "?t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}
async function load(first) {
  try {
    const [live, screen] = await Promise.all([getJSON("live.json"), first ? getJSON("screener.json") : Promise.resolve(SCREEN)]);
    const changed = live.generated_utc !== LIVE.generated_utc;
    LIVE = live; SCREEN = screen;
    if (first) { sec = picks()[0]?.symbol || null; renderAll(); }
    else if (changed) { renderWei(true); renderDes(); renderGp(); renderNews(); renderQr(); status(); msg("DATA UPDATED " + (LIVE.last_bar_ist || "")); }
  } catch (e) {
    if (first) { document.querySelectorAll(".pb").forEach(el => { el.innerHTML = '<div class="empty">DATA NOT AVAILABLE. PRICES COULD NOT BE LOADED; NOTHING IS SHOWN IN THEIR PLACE.</div>'; }); }
    msg("DATA REFRESH FAILED, SHOWING LAST LOADED VALUES");
  }
}

function status() {
  const m = $("#mkt");
  m.textContent = LIVE.market === "open" ? "NSE OPEN" : "NSE CLOSED";
  m.className = "tag" + (LIVE.market === "open" ? " open" : "");
  $("#st-data").textContent = LIVE.session_date ? `DATA ${LIVE.session_date} ${LIVE.last_bar_ist} IST · UPD ${LIVE.generated_ist || "--"} · SCREEN ${SCREEN.generated_ist || "--"}` : "DATA --";
}

/* ---------------- WEI ---------------- */
function renderWei(flash) {
  const rows = LIVE.indices || [];
  const tb = $("#wei tbody");
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="6" class="empty">INDEX DATA NOT AVAILABLE</td></tr>'; return; }
  let html = "", region = null;
  for (const r of rows) {
    if (r.region !== region) { region = r.region; html += `<tr class="region"><td colspan="6">${esc(region.toUpperCase())}</td></tr>`; }
    if (r.error) { html += `<tr><td class="code">${esc(r.code)}</td><td class="r dim" colspan="5">N/A</td></tr>`; continue; }
    const p = prevWei[r.code];
    const fl = flash && p != null && p !== r.value ? (r.value > p ? "flash-up" : "flash-down") : "";
    html += `<tr title="${esc(r.name)}"><td class="code">${esc(r.code)}</td>
      <td class="r ${fl}">${n2(r.value)}</td><td class="r ${ud(r.net)}">${sg(r.net)}</td><td class="r ${ud(r.pct)}">${sg(r.pct)}%</td>
      <td class="r dim">${esc(r.time)}</td><td class="r ${ud(r.ytd)}">${r.ytd == null ? "--" : sg(r.ytd) + "%"}</td></tr>`;
  }
  rows.forEach(r => { if (!r.error) prevWei[r.code] = r.value; });
  tb.innerHTML = html;
  $("#wei-asof").textContent = LIVE.generated_ist ? "UPD " + LIVE.generated_ist.replace(/^.*?, /, "") : "";
}

/* ---------------- DES ---------------- */
const reco = { strong_buy: "STRONG BUY", buy: "BUY", hold: "HOLD", underperform: "UNDERPERFORM", sell: "SELL" };
function kv(label, val, cls = "") { return `<div><span>${label}</span><b class="${cls}">${val}</b></div>`; }
function renderDes() {
  const p = pickOf(sec), L = liveOf(sec), box = $("#des");
  $("#des-sec").textContent = sec ? bbg(sec) : "";
  if (!p) { box.innerHTML = '<div class="empty">NO SECURITY LOADED</div>'; return; }
  const ok = L && !L.error;
  const up = ok && p.target_mean != null ? (p.target_mean / L.price - 1) * 100 : null;
  box.innerHTML = `<div class="des">
    <div class="des-title">${esc(bbg(p.symbol))} &nbsp; ${ok ? `<span class="${ud(L.change_pct)}">${inr(L.price)} ${sg(L.change)} (${sg(L.change_pct)}%)</span>` : ""}</div>
    <div class="des-name">${esc(p.name)} · ${esc(p.industry || p.sector || "")}${p.city ? " · " + esc(p.city) : ""}</div>
    <div class="sec-h">PRICE</div>
    <div class="kvs">
      ${kv("Last", ok ? inr(L.price) : "--")}${kv("Prev Close", ok ? inr(L.prev_close) : "--")}
      ${kv("Day High", ok ? inr(L.day_high) : "--")}${kv("Day Low", ok ? inr(L.day_low) : "--")}
      ${kv("52 Wk High", ok ? inr(L.high52.high) : "--")}${kv("52 Wk Low", ok ? inr(L.high52.low) : "--")}
      ${kv("Volume", ok ? big(L.volume) : "--")}${kv("As Of", ok ? `${L.last_bar_ist} IST` : "--")}
    </div>
    <div class="sec-h">FUNDAMENTALS (FY END ${esc(p.fy_end)})</div>
    <div class="kvs">
      ${kv("Mkt Cap", crore(p.market_cap_cr))}${kv("Shares Out", big(p.shares_out))}
      ${kv("P/E", p.pe == null ? "--" : n2(p.pe))}${kv("P/B", p.pb == null ? "--" : n2(p.pb))}
      ${kv("EPS (TTM)", p.eps == null ? "--" : inr(p.eps))}${kv("Div Yield", p.dividend_yield == null ? "--" : n2(p.dividend_yield) + "%")}
      ${kv("ROE", pctx(p.roe))}${kv("Debt/Equity", p.debt_to_equity == null ? "--" : (p.debt_to_equity / 100).toFixed(2))}
      ${kv("Beta", p.beta == null ? "--" : n2(p.beta))}${kv("Employees", p.employees == null ? "--" : Math.round(p.employees).toLocaleString("en-IN"))}
    </div>
    <div class="sec-h">B-LAB SCREEN</div>
    <div class="kvs">
      ${kv("Magic Rank", `#${p.magic_rank} / ${p.of}`, "up")}${kv("F-Score", `${p.fscore}/9`)}
      ${kv("Ret on Cap", pctx(p.roc, 1))}${kv("Earn Yield", pctx(p.earnings_yield, 1))}
      ${kv("Instit Own", pctx(p.held_institutions, 1))}${kv("Insider Own", pctx(p.held_insiders, 1))}
      ${kv("Analysts", p.analysts == null ? "--" : `${p.analysts}${p.recommendation ? " · " + (reco[p.recommendation] || p.recommendation.toUpperCase()) : ""}`)}
      ${kv("Tgt Mean", p.target_mean == null ? "--" : `${inr(p.target_mean)} ${up == null ? "" : `<span class="${ud(up)}">(${sg(up, 1)}%)</span>`}`)}
    </div>
    ${p.summary ? `<div class="sec-h">DESCRIPTION</div><p class="desc">${esc(p.summary)}</p>` : ""}
    ${p.website ? `<p class="desc dim">${esc(p.website)}</p>` : ""}
  </div>`;
}

/* ---------------- GP (SVG candles) ---------------- */
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent && parent.appendChild(e); return e; }
function renderGp() {
  document.querySelectorAll("#gp-ranges button").forEach(b => b.classList.toggle("on", b.dataset.r === range));
  const box = $("#gp"), L = liveOf(sec), leg = $("#gp-legend");
  $("#gp-title").textContent = sec ? `${bbg(sec)} · Graph Price` : "Graph Price";
  box.innerHTML = "";
  if (!L || L.error) { leg.innerHTML = ""; box.innerHTML = '<div class="empty">PRICE HISTORY NOT AVAILABLE</div>'; return; }
  const S = L.series, intraday = range === "1D";
  const n = { "1M": 21, "6M": 126, "1Y": 252 }[range] || 252;
  const bars = intraday ? S.intraday : S.daily.slice(-n);
  const s50 = intraday ? [] : S.sma50.slice(-bars.length), s200 = intraday ? [] : S.sma200.slice(-bars.length);
  if (!bars || bars.length < 2) { box.innerHTML = '<div class="empty">NOT ENOUGH DATA FOR THIS RANGE</div>'; return; }
  let hiI = 0, loI = 0;
  bars.forEach((b, i) => { if (b[2] > bars[hiI][2]) hiI = i; if (b[3] < bars[loI][3]) loI = i; });
  const last = bars[bars.length - 1];
  leg.innerHTML = `<span><i style="background:var(--up)"></i>Last Price <b class="up">${inr(L.price)}</b></span>
    <span class="dim">High on ${esc(bars[hiI][0])} <b style="color:var(--txt)">${inr(bars[hiI][2])}</b></span>
    <span class="dim">Low on ${esc(bars[loI][0])} <b style="color:var(--txt)">${inr(bars[loI][3])}</b></span>
    ${intraday ? "" : `<span><i style="background:#e8dcc3"></i>SMA(50) ${inr(s50[s50.length - 1])}</span><span><i style="background:#b5a682"></i>SMA(200) ${inr(s200[s200.length - 1])}</span>`}`;
  const W = box.clientWidth || 600, H = box.clientHeight || 300, PR = 62, PL = 4, PT = 8, PB = 18;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": `${range} price chart for ${sec}` }, box);
  let lo = Infinity, hi = -Infinity;
  bars.forEach(b => { lo = Math.min(lo, b[3]); hi = Math.max(hi, b[2]); });
  [...s50, ...s200].forEach(v => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
  const pad = (hi - lo) * 0.05 || 1; lo -= pad; hi += pad;
  const n0 = bars.length, cw = (W - PL - PR) / n0;
  const x = i => PL + cw * (i + 0.5), y = v => PT + (hi - v) / (hi - lo) * (H - PT - PB);
  for (let k = 0; k <= 5; k++) {
    const v = lo + (hi - lo) * k / 5, yy = y(v);
    svgEl("line", { x1: PL, x2: W - PR, y1: yy, y2: yy, stroke: "#b5a682", "stroke-opacity": 0.18, "stroke-dasharray": "2 3" }, svg);
    svgEl("text", { x: W - PR + 4, y: yy + 4 }, svg).textContent = inr(v, v >= 1000 ? 0 : 2);
  }
  const step = Math.ceil(n0 / 6);
  for (let i = 0; i < n0; i += step) {
    svgEl("line", { x1: x(i), x2: x(i), y1: PT, y2: H - PB, stroke: "#b5a682", "stroke-opacity": 0.12 }, svg);
    svgEl("text", { x: x(i), y: H - 5, "text-anchor": "middle" }, svg).textContent = bars[i][0];
  }
  const bw = Math.max(1, Math.min(9, cw * 0.62));
  bars.forEach((b, i) => {
    const up = b[4] >= b[1], col = up ? "#00ff00" : "#d9a066";
    svgEl("line", { x1: x(i), x2: x(i), y1: y(b[2]), y2: y(b[3]), stroke: col, "stroke-width": 1 }, svg);
    svgEl("rect", { x: x(i) - bw / 2, y: y(Math.max(b[1], b[4])), width: bw, height: Math.max(1, Math.abs(y(b[1]) - y(b[4]))),
      fill: up ? "none" : col, stroke: col, "stroke-width": 1 }, svg);
  });
  const line = (vals, col) => { let d = ""; vals.forEach((v, i) => { if (v != null) d += (d ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); }); if (d) svgEl("path", { d, fill: "none", stroke: col, "stroke-width": 1.4 }, svg); };
  line(s50, "#e8dcc3"); line(s200, "#b5a682");
  const ly = y(L.price);
  svgEl("line", { x1: PL, x2: W - PR, y1: ly, y2: ly, stroke: "#00ff00", "stroke-opacity": 0.5, "stroke-dasharray": "4 3" }, svg);
  svgEl("rect", { x: W - PR + 1, y: ly - 7, width: PR - 2, height: 14, fill: "#00ff00" }, svg);
  const t = svgEl("text", { x: W - PR + 4, y: ly + 4 }, svg); t.textContent = inr(L.price); t.setAttribute("style", "fill:#061a10;font-weight:700");
  // crosshair readout
  const tip = document.createElement("div"); tip.className = "gp-tip"; box.appendChild(tip);
  const vx = svgEl("line", { y1: PT, y2: H - PB, stroke: "#e8dcc3", "stroke-opacity": 0.5, visibility: "hidden" }, svg);
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(n0 - 1, Math.floor((px - PL) / cw))), b = bars[i];
    vx.setAttribute("x1", x(i)); vx.setAttribute("x2", x(i)); vx.setAttribute("visibility", "visible");
    tip.innerHTML = `${esc(b[0])}  O ${inr(b[1])}  H ${inr(b[2])}  L ${inr(b[3])}  C <span class="${ud(b[4] - b[1])}">${inr(b[4])}</span>` + (intraday && b[5] != null ? `  V ${big(b[5])}` : "");
  });
  svg.addEventListener("mouseleave", () => { vx.setAttribute("visibility", "hidden"); tip.textContent = ""; });
  void last;
}

/* ---------------- TOP news ---------------- */
function newsTime(iso) {
  const d = new Date(iso), now = new Date();
  const sameDay = d.toLocaleDateString("en-CA", { timeZone: IST }) === now.toLocaleDateString("en-CA", { timeZone: IST });
  return sameDay ? d.toLocaleTimeString("en-GB", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false })
                 : d.toLocaleDateString("en-GB", { timeZone: IST, day: "2-digit", month: "short" });
}
function renderNews() {
  const items = LIVE.news || [], ul = $("#news");
  if (!items.length) { ul.innerHTML = '<li class="empty">NO HEADLINES AVAILABLE</li>'; return; }
  ul.innerHTML = items.map(n => `<li><time datetime="${esc(n.time_utc)}">${newsTime(n.time_utc)}</time>
    <span>${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}
    <span class="src"> · ${esc(n.publisher || "")}</span> <span class="tk">${(n.tickers || []).map(esc).join(" ")}</span></span></li>`).join("");
}
// slow auto-scroll of the news feed; pauses while hovered
(function autoScroll() {
  const wrap = $(".news-wrap");
  let hover = false;
  wrap.addEventListener("mouseenter", () => hover = true);
  wrap.addEventListener("mouseleave", () => hover = false);
  setInterval(() => {
    if (hover || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 1) wrap.scrollTop = 0; else wrap.scrollTop += 1;
  }, 70);
})();

/* ---------------- QR tape ---------------- */
function renderQr() {
  const L = liveOf(sec), roll = $("#qr");
  $("#qr-sec").textContent = sec ? bbg(sec) + " · 5-MIN PRINTS" : "";
  if (!L || L.error || !L.series.intraday.length) { roll.className = "qr-roll"; roll.innerHTML = '<div class="empty">NO INTRADAY PRINTS</div>'; return; }
  const bars = L.series.intraday;
  const rows = bars.map((b, i) => {
    const prev = i ? bars[i - 1][4] : L.prev_close, ch = b[4] - prev;
    return `<div class="qr-row"><span class="dim">${esc(b[0])}</span><span class="r ${ud(ch)}">${inr(b[4])}</span><span class="r ${ud(ch)}">${ch > 0 ? "▲" : ch < 0 ? "▼" : "="}${inr(Math.abs(ch))}</span>
      <span class="r">${inr(b[2])}</span><span class="r">${inr(b[3])}</span><span class="r dim">${b[5] == null ? "--" : big(b[5])}</span></div>`;
  }).reverse().join("");
  roll.innerHTML = rows + rows;        // doubled so the upward roll loops seamlessly
  roll.className = "qr-roll run";
  roll.style.setProperty("--dur", Math.max(20, bars.length * 1.2) + "s");
}

/* ---------------- focus / selection ---------------- */
function focus(fn) {
  focusFn = fn;
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("focus", p.id === "p-" + fn));
  document.querySelectorAll(".fstrip button").forEach(b => b.classList.toggle("on", b.dataset.fn === fn));
  const el = document.getElementById("p-" + fn);
  if (el && matchMedia("(max-width: 900px)").matches) el.scrollIntoView({ behavior: "smooth", block: "start" });
}
function selectSec(s) {
  sec = s;
  $("#fsec").textContent = s ? `${bbg(s)} · ${pickOf(s)?.name || ""}` : "--";
  renderDes(); renderGp(); renderQr();
}
function msg(t) { $("#fmsg").textContent = t || ""; }

function renderAll() { status(); renderWei(false); selectSec(sec); renderNews(); focus(focusFn); }

/* ---------------- command line ---------------- */
const FUNCS = {
  WEI: "World Equity Indices", DES: "Security Description", GP: "Graph Price", TOP: "Top News", QR: "Quote Recap",
  HELP: "List commands", BACK: "Back to the B-Lab Advanced page", LOGOFF: "Sign out",
};
const input = $("#cli-input"), mirror = $("#cli-mirror"), sug = $("#cli-suggest");
let options = [], active = -1;

function candidates() {
  const out = [];
  for (const p of picks()) {
    for (const f of ["DES", "GP", "QR"]) out.push({ text: `${p.symbol} IN <Equity> ${f}`, note: `${p.name.slice(0, 28)} · ${FUNCS[f]}` });
  }
  for (const r of LIVE.indices || []) out.push({ text: `${r.code} <Index> WEI`, note: `${r.name} · ${FUNCS.WEI}` });
  for (const [f, d] of Object.entries(FUNCS)) out.push({ text: f, note: d });
  return out;
}
function suggest() {
  const q = input.value.trim().toUpperCase();
  mirror.textContent = input.value;
  if (!q) { closeSug(); return; }
  const toks = q.split(/\s+/);
  options = candidates().filter(c => {
    const words = c.text.toUpperCase().replace(/[<>]/g, "").split(/\s+/);
    return toks.every(t => words.some(w => w.startsWith(t.replace(/[<>]/g, ""))));
  }).slice(0, 9);
  active = options.length ? 0 : -1;
  if (!options.length) { closeSug(); return; }
  sug.innerHTML = options.map((o, i) => `<li role="option" data-i="${i}" aria-selected="${i === active}"><b>${esc(o.text)}</b><span>${esc(o.note)}</span></li>`).join("");
  sug.hidden = false; input.setAttribute("aria-expanded", "true");
}
function closeSug() { sug.hidden = true; sug.innerHTML = ""; options = []; active = -1; input.setAttribute("aria-expanded", "false"); }
function paintActive() { sug.querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", i === active)); }
sug.addEventListener("mousedown", e => {
  const li = e.target.closest("li"); if (!li) return;
  e.preventDefault(); input.value = options[+li.dataset.i].text; mirror.textContent = input.value; closeSug(); run(input.value);
});

function run(cmd) {
  const q = cmd.trim().toUpperCase().replace(/[<>]/g, " ").replace(/\s+/g, " ").trim();
  if (!q) return;
  const toks = q.split(" ");
  const fn = [...toks].reverse().find(t => t in FUNCS);
  const s = toks.find(t => picks().some(p => p.symbol === t));
  const idx = toks.find(t => (LIVE.indices || []).some(r => r.code === t));
  input.value = ""; mirror.textContent = ""; closeSug();
  if (fn === "BACK") { location.href = "advanced.html#signals"; return; }
  if (fn === "LOGOFF") { $("#logout").click(); return; }
  if (fn === "HELP") { msg("TYPE <SYMBOL> IN <Equity> DES|GP|QR, OR WEI, TOP, BACK, LOGOFF. SECURITIES = TODAY'S 10 SCREENED STOCKS."); return; }
  if (s) { selectSec(s); focus(fn && fn !== "WEI" && fn !== "TOP" ? fn : "DES"); msg(`${bbg(s)} ${fn || "DES"} <GO>`); return; }
  if (idx) { focus("WEI"); msg(`${idx} <Index> WEI <GO>`); return; }
  if (fn) { focus(fn); msg(`${fn} <GO>`); return; }
  msg(`UNKNOWN: ${q}. ONLY TODAY'S SCREENED STOCKS AND LISTED INDICES ARE LOADED. TYPE HELP <GO>.`);
}

input.addEventListener("input", suggest);
input.addEventListener("keydown", e => {
  if (e.key === "ArrowDown" && options.length) { active = (active + 1) % options.length; paintActive(); e.preventDefault(); }
  else if (e.key === "ArrowUp" && options.length) { active = (active - 1 + options.length) % options.length; paintActive(); e.preventDefault(); }
  else if (e.key === "Tab" && options.length) { input.value = options[Math.max(0, active)].text; mirror.textContent = input.value; closeSug(); e.preventDefault(); }
  else if (e.key === "Enter") { const pick = !sug.hidden && active >= 0 ? options[active].text : input.value; run(pick); e.preventDefault(); }
});
// Esc: close suggestions -> clear the line -> back to B-Lab
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (!sug.hidden) closeSug();
    else if (input.value) { input.value = ""; mirror.textContent = ""; }
    else location.href = "advanced.html#signals";
    return;
  }
  // typing anywhere goes to the command line, like a real terminal
  if (document.activeElement !== input && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) input.focus();
});
$("#cli").addEventListener("click", () => input.focus());
document.querySelectorAll(".fstrip button").forEach(b => b.addEventListener("click", () => { focus(b.dataset.fn); msg(`${b.dataset.fn} <GO>`); }));
document.querySelectorAll("#gp-ranges button").forEach(b => b.addEventListener("click", () => { if (!b.disabled) { range = b.dataset.r; renderGp(); } }));
document.querySelectorAll(".panel").forEach(p => p.addEventListener("mousedown", () => focus(p.id.slice(2))));
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(renderGp, 120); });

load(true);
setInterval(() => load(false), POLL_MS);
input.focus();
