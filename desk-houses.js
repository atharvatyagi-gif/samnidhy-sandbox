/* HOUSES tab: business-house market-cap league.
   Data: houses.json (group -> symbols, loaded on first open, never at page load), live prices through ctx.q(), share
   counts from t/fund.json (Yahoo, refreshed by scripts/terminal_fund.py). Group market cap = shares x last price for
   each listed member, summed. Cross-holdings and promoter stakes are NOT netted out. A member with no share count
   stays in the group (shown with a dash) but adds nothing to the totals, and the row says how many are missing.
   Returns (1W / 1M / YTD) are market-cap-weighted from the split-adjusted daily files, loaded only when a row opens. */
let ctx = null, cfg = null, loading = null, failed = null;
let sortKey = "mcap", query = "";
const open = new Set(), hist = new Map(), histLoading = new Map();
const CR = 1e7;

export function init(c) { ctx = c; }

const dkey = s => [...s].map(c => /[A-Za-z0-9]/.test(c) ? c : "_" + c.charCodeAt(0).toString(16)).join("");
const crTxt = v => v == null ? "—" : Math.abs(v) >= 1e5 ? (v / 1e5).toFixed(2) + " L cr" : Math.round(v).toLocaleString("en-IN");
const pctTxt = v => v == null || !isFinite(v) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2) + "%";
const cls = v => v == null || !isFinite(v) ? "mut" : v > 0 ? "up" : v < 0 ? "down" : "flat";

/* ---------- numbers ---------- */
export function members(house, getQ, fund, uni) {
  return house.symbols.map(s => {
    const u = uni.get(s), x = u ? getQ(s) : null, f = fund[s] || {};
    const sh = f.sh > 0 ? f.sh : null;
    const p = x ? x.p : null, pc = x && x.pc != null ? x.pc : (x && x.chg != null ? x.p - x.chg : null);
    return { s, n: u ? u.n : s, p, pc, pct: x ? x.pct : null, sh, n500: !!(u && u.n500),
      mcap: sh && p != null ? sh * p : null, prev: sh && pc != null ? sh * pc : null, fundAt: f.at || null };
  });
}

export function summarise(rows) {
  const have = rows.filter(r => r.mcap != null && r.prev != null);
  const mcap = have.reduce((a, r) => a + r.mcap, 0), prev = have.reduce((a, r) => a + r.prev, 0);
  const priced = rows.filter(r => r.pct != null);
  const up = priced.filter(r => r.pct > 0).length, down = priced.filter(r => r.pct < 0).length;
  const best = priced.length ? priced.reduce((a, r) => r.pct > a.pct ? r : a) : null;
  const worst = priced.length ? priced.reduce((a, r) => r.pct < a.pct ? r : a) : null;
  return { n: rows.length, counted: have.length, missing: rows.length - have.length, mcap, prev, dayCr: have.length ? (mcap - prev) / CR : null,
    dayPct: have.length && prev ? (mcap / prev - 1) * 100 : null, up, down, flat: priced.length - up - down, best, worst };
}

/* market-cap-weighted return between now and the close on/before `refDate` ("YYYY-MM-DD"); only stocks that have both prices count */
export function weightedReturn(rows, histories, refDate) {
  let now = 0, then = 0, n = 0;
  for (const r of rows) {
    const h = histories.get(r.s); if (!h || r.sh == null || r.p == null) continue;
    let ref = null; for (let i = h.length - 1; i >= 0; i--) { if (h[i][0] <= refDate) { ref = h[i][4]; break; } }
    if (ref == null || !(ref > 0)) continue;
    now += r.sh * r.p; then += r.sh * ref; n++;
  }
  return n ? { pct: (now / then - 1) * 100, n } : null;
}

export function refDates(todayIso) {
  const d = new Date(todayIso + "T00:00:00Z"), iso = x => x.toISOString().slice(0, 10);
  const w = new Date(d); w.setUTCDate(w.getUTCDate() - 7);
  const m = new Date(d); m.setUTCMonth(m.getUTCMonth() - 1);
  const y = new Date(Date.UTC(d.getUTCFullYear(), 0, 1)); y.setUTCDate(y.getUTCDate() - 1);   // last close before 1 Jan
  return { "1W": iso(w), "1M": iso(m), YTD: iso(y) };
}

function compute() {
  const { S, q } = ctx, uni = S.map, fund = S.fund || {};
  const list = cfg.houses.map(h => {
    const rows = members(h, q, fund, uni);
    return { h, rows, sum: summarise(rows) };
  });
  let n500Total = 0;
  for (const [s, u] of uni) if (u.n500) { const f = fund[s], x = f && f.sh ? q(s) : null; if (x && x.p != null) n500Total += f.sh * x.p; }
  const byPrev = [...list].sort((a, b) => b.sum.prev - a.sum.prev).map(g => g.h.id);
  const byNow = [...list].sort((a, b) => b.sum.mcap - a.sum.mcap).map(g => g.h.id);
  for (const g of list) {
    g.rank = byNow.indexOf(g.h.id) + 1; g.rankPrev = byPrev.indexOf(g.h.id) + 1;
    const inN500 = g.rows.filter(r => r.n500 && r.mcap != null).reduce((a, r) => a + r.mcap, 0);
    g.share = n500Total ? inN500 / n500Total * 100 : null;
  }
  return { list, n500Total };
}

const sorters = {
  mcap: (a, b) => b.sum.mcap - a.sum.mcap,
  pct: (a, b) => (b.sum.dayPct ?? -1e9) - (a.sum.dayPct ?? -1e9),
  cr: (a, b) => (b.sum.dayCr ?? -1e9) - (a.sum.dayCr ?? -1e9),
  breadth: (a, b) => (b.sum.up / (b.sum.up + b.sum.down + b.sum.flat || 1)) - (a.sum.up / (a.sum.up + a.sum.down + a.sum.flat || 1)),
};

/* ---------- loading ---------- */
async function ensureConfig() {
  if (cfg) return cfg;
  if (!ctx.S.deskMan || !ctx.S.deskMan.houses) { failed = "The group list has not been published yet."; return null; }
  loading = loading || ctx.getJSON("houses.json", false).then(j => { cfg = j; }, e => { failed = "Could not load the group list: " + e.message; });
  await loading; loading = null;
  return cfg;
}

async function loadHist(sym) {
  if (hist.has(sym)) return;
  if (!histLoading.has(sym)) histLoading.set(sym, ctx.getJSON(`t/d/${dkey(sym)}.json`, false).then(j => { hist.set(sym, j.d || []); }, () => { hist.set(sym, null); }));
  await histLoading.get(sym);
}

/* ---------- render ---------- */
export async function renderHouses() {
  if (!ctx) return;
  const el = ctx.$("#houses"); if (!el) return;
  if (!cfg) {
    el.innerHTML = '<p class="empty">Loading the business-house list…</p>';
    await ensureConfig();
    if (!cfg) { el.innerHTML = `<p class="empty">${ctx.esc(failed || "Business-house data is not available.")}</p>`; return; }
  }
  if (!ctx.S.fund) { el.innerHTML = '<p class="empty">Loading share counts…</p>'; setTimeout(() => { if (ctx.S.fund && cfg) renderHouses(); }, 1500); if (!ctx.S.fund) return; }
  draw(el);
}

function draw(el) {
  const { esc, S } = ctx, { list, n500Total } = compute();
  const q = query.trim().toLowerCase();
  const shown = list.filter(g => !q || g.h.name.toLowerCase().includes(q) || g.rows.some(r => r.s.toLowerCase().includes(q) || r.n.toLowerCase().includes(q))).sort(sorters[sortKey]);
  const tot = list.reduce((a, g) => a + g.sum.mcap, 0), totDay = list.reduce((a, g) => a + (g.sum.dayCr || 0), 0);
  const upG = list.filter(g => (g.sum.dayPct || 0) > 0).length, nSym = list.reduce((a, g) => a + g.sum.n, 0), nMiss = list.reduce((a, g) => a + g.sum.missing, 0);
  const lead = list.slice().sort(sorters.mcap)[0], top = list.filter(g => g.sum.dayPct != null).sort(sorters.pct)[0], bot = list.filter(g => g.sum.dayPct != null).sort(sorters.pct).pop();
  const allRows = list.flatMap(g => g.rows).filter(r => r.sh != null), dated = allRows.map(r => r.fundAt).filter(Boolean).sort();
  const undated = allRows.length - dated.length;
  const fetched = !dated.length ? "no fetch date recorded yet" : `fetched ${dated[0]}${dated[dated.length - 1] !== dated[0] ? " to " + dated[dated.length - 1] : ""}${undated ? `, ${undated} older figure${undated > 1 ? "s" : ""} undated` : ""}`;

  document.querySelectorAll('[data-asof="houses"]').forEach(a => {
    a.innerHTML = `Prices ${esc(S.qmeta && S.qmeta.session_date || "--")} ${esc(S.qmeta && S.qmeta.last_bar_ist || "")} IST · share counts from Yahoo Finance (${esc(fetched)}) · group list v${esc(String(cfg.version || 1))}`;
  });

  const rowsHtml = shown.map(g => {
    const s = g.sum, moved = g.rankPrev - g.rank, isOpen = open.has(g.h.id), t = s.up + s.down + s.flat || 1;
    const mv = moved > 0 ? `<span class="up" title="Up ${moved} place${moved > 1 ? "s" : ""} on yesterday's close">▲${moved}</span>` : moved < 0 ? `<span class="down" title="Down ${-moved} place${moved < -1 ? "s" : ""} on yesterday's close">▼${-moved}</span>` : '<span class="mut">–</span>';
    const miss = s.missing ? ` <span class="tag warn" title="${s.missing} listed compan${s.missing > 1 ? "ies have" : "y has"} no share count yet, so ${s.missing > 1 ? "they are" : "it is"} not in the totals">${s.missing} not counted</span>` : "";
    return `<tr class="hh-row${isOpen ? " on" : ""}" data-h="${esc(g.h.id)}" tabindex="0" aria-expanded="${isOpen}">
      <td class="num">${g.rank}</td><td>${mv}</td><td class="co"><b>${esc(g.h.name)}</b>${miss}</td>
      <td class="num hh-hide">${s.n}</td>
      <td class="num">${crTxt(s.mcap / CR)}</td><td class="num ${cls(s.dayPct)}">${pctTxt(s.dayPct)}</td><td class="num ${cls(s.dayCr)}">${s.dayCr == null ? "—" : (s.dayCr > 0 ? "+" : s.dayCr < 0 ? "−" : "") + crTxt(Math.abs(s.dayCr))}</td>
      <td><div class="b-bar" title="${s.up} up · ${s.flat} unchanged · ${s.down} down"><i style="width:${s.up / t * 100}%;background:var(--up)"></i><i style="width:${s.flat / t * 100}%;background:var(--ink-4)"></i><i style="width:${s.down / t * 100}%;background:var(--down)"></i></div></td>
      <td class="num hh-hide">${g.share == null ? "—" : g.share.toFixed(1) + "%"}</td>
      <td class="hh-hide">${s.best ? `${esc(s.best.s)} <span class="${cls(s.best.pct)}">${pctTxt(s.best.pct)}</span>` : "—"}</td>
      <td class="hh-hide">${s.worst ? `${esc(s.worst.s)} <span class="${cls(s.worst.pct)}">${pctTxt(s.worst.pct)}</span>` : "—"}</td></tr>${isOpen ? `<tr class="hh-detail"><td colspan="11">${detailHtml(g)}</td></tr>` : ""}`;
  }).join("") || '<tr><td colspan="11" class="empty">No group matches that filter.</td></tr>';

  el.innerHTML = `
    <div class="statstrip">
      <div><b>${list.length}</b><span>Groups tracked</span></div>
      <div><b>₹${(tot / 1e12).toFixed(1)} L cr</b><span>Combined market cap</span></div>
      <div><b class="${cls(totDay)}">${totDay >= 0 ? "+" : "−"}₹${crTxt(Math.abs(totDay))}</b><span>Combined move today (cr)</span></div>
      <div><b>${upG} / ${list.length - upG}</b><span>Groups up / down</span></div>
      <div><b>${lead ? esc(lead.h.name.split(" (")[0]) : "—"}</b><span>Largest by market cap</span></div>
      <div><b>${top ? esc(top.h.name.split(" (")[0]) : "—"}</b><span>Best today${bot && bot !== top ? ` · weakest ${esc(bot.h.name.split(" (")[0])}` : ""}</span></div>
    </div>
    <div class="controls">
      <div class="seg" id="hh-sort"><button data-k="mcap" class="${sortKey === "mcap" ? "on" : ""}">Market cap</button><button data-k="pct" class="${sortKey === "pct" ? "on" : ""}">Today %</button><button data-k="cr" class="${sortKey === "cr" ? "on" : ""}">Today ₹</button><button data-k="breadth" class="${sortKey === "breadth" ? "on" : ""}">Breadth</button></div>
      <input id="hh-filter" type="search" placeholder="Filter by group, symbol or company" aria-label="Filter business houses" value="${esc(query)}">
    </div>
    <div class="tablecard"><table class="tbl" id="hh-table"><thead><tr><th class="r">#</th><th>Move</th><th>Group</th><th class="r hh-hide">Companies</th><th class="r">Market cap ₹ cr</th><th class="r">Today %</th><th class="r">Today ₹ cr</th><th>Breadth</th><th class="r hh-hide">Share of NIFTY 500</th><th class="hh-hide">Best</th><th class="hh-hide">Worst</th></tr></thead><tbody>${rowsHtml}</tbody></table></div>
    <p class="note">Group market cap = shares outstanding × last price, summed over each group's listed companies. Cross-holdings and promoter stakes are not netted out, so a parent and its listed subsidiary both count. "Share of NIFTY 500" uses only the group's NIFTY 500 members. Move compares today's rank with the rank at yesterday's close. Membership is a public-information grouping that can lag demergers and ownership changes${nMiss ? ` · ${nMiss} of ${nSym} companies have no share count yet and are left out of the totals` : ""}. Click a group for its companies and 1W / 1M / YTD returns.</p>`;

  el.querySelectorAll("#hh-sort button").forEach(b => b.onclick = () => { sortKey = b.dataset.k; draw(el); });
  const f = el.querySelector("#hh-filter"); f.oninput = () => { query = f.value; const pos = f.selectionStart; draw(el); const g = el.querySelector("#hh-filter"); g.focus(); g.setSelectionRange(pos, pos); };
  el.querySelectorAll("tr.hh-row").forEach(tr => {
    const toggle = () => { const id = tr.dataset.h; open.has(id) ? open.delete(id) : open.add(id); draw(el); if (open.has(id)) loadReturns(el, id); };
    tr.onclick = toggle; tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
  });
  el.querySelectorAll("tr.hh-detail tbody tr[data-s]").forEach(tr => tr.onclick = () => { ctx.openSec(tr.dataset.s); ctx.go("terminal"); });
  void n500Total;
}

function retTxt(g, key, ref) {
  const rows = g.rows.filter(r => r.sh != null && r.p != null);
  if (!rows.every(r => hist.has(r.s))) return null;
  return weightedReturn(rows, hist, ref);
}

function detailHtml(g) {
  const { esc } = ctx, today = (ctx.S.qmeta && ctx.S.qmeta.session_date) || (ctx.S.uni && ctx.S.uni.session_date);
  const refs = today ? refDates(today) : null, loaded = g.rows.every(r => r.sh == null || hist.has(r.s));
  const tmcap = g.sum.mcap || 0;
  const groupRet = k => {
    if (!refs) return '<td class="num mut">—</td>';
    if (!loaded) return '<td class="num mut">…</td>';
    const r = retTxt(g, k, refs[k]);
    return r ? `<td class="num ${cls(r.pct)}" title="${r.n} of ${g.sum.counted} companies had prices back to that date">${pctTxt(r.pct)}</td>` : '<td class="num mut" title="Not enough price history">—</td>';
  };
  const stockRet = (r, k) => {
    if (!refs || !hist.has(r.s)) return '<td class="num mut">' + (refs && !loaded ? "…" : "—") + "</td>";
    const h = hist.get(r.s); if (!h || r.p == null) return '<td class="num mut">—</td>';
    let ref = null; for (let i = h.length - 1; i >= 0; i--) if (h[i][0] <= refs[k]) { ref = h[i][4]; break; }
    return ref ? `<td class="num ${cls((r.p / ref - 1) * 100)}">${pctTxt((r.p / ref - 1) * 100)}</td>` : '<td class="num mut">—</td>';
  };
  const body = g.rows.slice().sort((a, b) => (b.mcap ?? -1) - (a.mcap ?? -1)).map(r => `<tr data-s="${esc(r.s)}"><td class="sym">${esc(r.s)}</td><td class="co">${esc(r.n)}</td>
    <td class="num">${r.p == null ? "—" : ctx.inr(r.p)}</td><td class="num ${cls(r.pct)}">${pctTxt(r.pct)}</td>
    <td class="num">${r.mcap == null ? '<span class="mut" title="No share count yet">—</span>' : crTxt(r.mcap / CR)}</td>
    <td class="num">${r.mcap == null || !tmcap ? "—" : (r.mcap / tmcap * 100).toFixed(1) + "%"}</td>${stockRet(r, "1W")}${stockRet(r, "1M")}${stockRet(r, "YTD")}</tr>`).join("");
  return `<div class="tablecard"><table class="tbl"><thead><tr><th>Symbol</th><th>Company</th><th class="r">Last</th><th class="r">Chg %</th><th class="r">Mcap ₹ cr</th><th class="r">Weight</th><th class="r">1W</th><th class="r">1M</th><th class="r">YTD</th></tr></thead>
    <tbody>${body}<tr class="hh-total"><td colspan="2"><b>Group, market-cap weighted</b></td><td></td><td class="num ${cls(g.sum.dayPct)}">${pctTxt(g.sum.dayPct)}</td><td class="num">${crTxt(tmcap / CR)}</td><td class="num">100%</td>${groupRet("1W")}${groupRet("1M")}${groupRet("YTD")}</tr></tbody></table></div>
    ${g.h.note ? `<p class="note">${esc(g.h.note)}</p>` : ""}<p class="note">Returns use today's share counts and split-adjusted closes, so they reflect price moves only (no buybacks, issues or dividends).</p>`;
}

async function loadReturns(el, id) {
  const g = compute().list.find(x => x.h.id === id); if (!g) return;
  await Promise.all(g.rows.filter(r => r.sh != null).map(r => loadHist(r.s)));
  if (open.has(id) && ctx.S && document.contains(el)) draw(el);
}
