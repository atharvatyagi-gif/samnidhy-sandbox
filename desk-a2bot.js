/* ALADIN BOT console: a locked page that shows what ALADIN is doing, step by step, with graphs, and how it reaches each call.
   The data is a public but ENCRYPTED file (aladin2/bot.enc.json, AES-256-GCM, key derived from the access code with PBKDF2-SHA256, 600,000 rounds). The browser derives the key from the code you type and
   decrypts in memory; nothing readable is sent anywhere. A wrong code, or a file that was changed, fails the GCM check. This module contains no data and no code.
   Every number on the page comes from the decrypted file; results labelled "historical simulation" are out-of-sample tests on past data, not live trading and not real money.
   ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results. */
import { esc, inr } from "./desk-aladin2.js";
import { mountLive } from "./desk-a2live.js";

const FILE = "aladin2/bot.enc.json", SS = "aladin2.bot.code";
let ctx = null, root = null, blob = null, blobState = "idle", P = null, failures = 0, until = 0, live = null;
const DISCLAIMER = "ALADIN is a statistical model built by students. It is often wrong. Educational analysis only, not investment advice. Past performance does not predict future results.";

export function init(c) { ctx = c; }

/* ---------- the lock (exported for tests/js/a2bot.test.mjs, which opens a fixture produced by the Python side) ---------- */
export const normalise = c => String(c || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
export async function decrypt(b, code, subtle = globalThis.crypto && globalThis.crypto.subtle) {
  if (!subtle) throw Object.assign(new Error("no WebCrypto"), { why: "insecure" });
  const enc = new TextEncoder(), raw = s => Uint8Array.from(atob(s), ch => ch.charCodeAt(0)), n = normalise(code);
  const tryOne = async c => {
    const km = await subtle.importKey("raw", enc.encode(c), "PBKDF2", false, ["deriveKey"]);
    const key = await subtle.deriveKey({ name: "PBKDF2", salt: raw(b.salt), iterations: b.iter, hash: "SHA-256" }, km, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    return JSON.parse(new TextDecoder().decode(await subtle.decrypt({ name: "AES-GCM", iv: raw(b.iv), additionalData: enc.encode(b.aad) }, key, raw(b.ct))));
  };
  try { return await tryOne(n); }
  catch (e) { if (n.startsWith("ALADIN")) throw e; return await tryOne("ALADIN" + n); }        // the five groups typed without the leading ALADIN also open it
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
    ${missing ? "" : `<form id="a2b-form" autocomplete="off"><label class="a2b-lbl" for="botcode">Access code</label><input id="botcode" type="text" inputmode="text" autocapitalize="characters" autocomplete="off" autocorrect="off" spellcheck="false" placeholder="ALADIN-XXXX-XXXX-XXXX-XXXX-XXXX" aria-describedby="a2b-msg"><button class="btn-ink" type="submit" id="a2b-go">Unlock</button></form>`}
    <p class="note" id="a2b-msg" role="status">${esc(msg || "")}</p><p class="note">The page's data is encrypted in the browser with your code (AES-256). Without the code the file cannot be read. ${DISCLAIMER}</p></div></div>`;
}

function render(msg) {
  if (!root) return;
  if (live) { live.stop(); live = null; }
  if (P) { live = mountLive(root, P, { helpers: { barSvg }, onLock: lockNow, onOpen: sym => { if (ctx) { ctx.openSec(sym); ctx.go("terminal"); } } }); return; }
  root.innerHTML = lockScreen(msg); bind();
}
function bind() {
  const f = root.querySelector("#a2b-form");
  if (f) { f.onsubmit = e => { e.preventDefault(); unlock(root.querySelector("#botcode").value); }; const i = root.querySelector("#botcode"); if (i) i.focus(); }
}
function lockNow() { P = null; try { sessionStorage.removeItem(SS); } catch { /* fine */ } stop(); render("Locked."); }
function stop() { if (live) { live.stop(); live = null; } }

async function unlock(code) {
  const msg = root && root.querySelector("#a2b-msg"), now = Date.now();
  if (now < until) { if (msg) msg.textContent = `Wait ${Math.ceil((until - now) / 1000)} s before trying again.`; return; }
  if (!blob) { if (msg) msg.textContent = "The file is still loading."; return; }
  if (msg) msg.textContent = "Checking the code (about a second)…";
  try { P = await decrypt(blob, code); failures = 0; try { sessionStorage.setItem(SS, code); } catch { /* private window: you will be asked again */ } render(); }
  catch (e) { P = null; if (e && e.why === "insecure") { render("This browser cannot unlock here: it needs a secure (https) page."); return; } if (e && e.name === "SyntaxError") { render("The file opened but could not be read. Try again in a minute."); return; } failures++; until = Date.now() + Math.min(8000, 800 * failures); render("That code does not open the console. Check it letter by letter (no spaces needed, dashes optional)."); }
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
