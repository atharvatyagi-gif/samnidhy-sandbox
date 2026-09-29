/* B-LAB chart indicators: the maths and the list shown in the Indicators dialog.
   Every function takes bars [{o,h,l,c,v,day}] and returns arrays aligned to the bars (null = not enough data yet).
   Formulas follow the standard definitions (and TradingView's built-ins where they differ, e.g. RSI uses
   Wilder's smoothing, Supertrend/ATR use RMA). */

// ---------------- building blocks ----------------
export function smaA(a, n) {
  const o = Array(a.length).fill(null); let s = 0, c = 0;
  for (let i = 0; i < a.length; i++) {
    const v = a[i];
    if (v == null) { s = 0; c = 0; continue; }
    s += v; c++;
    if (c > n) { s -= a[i - n]; c = n; }
    if (c === n) o[i] = s / n;
  }
  return o;
}
export function emaA(a, n, alpha) {
  const k = alpha ?? 2 / (n + 1), o = Array(a.length).fill(null); let e = null, s = 0, c = 0;
  for (let i = 0; i < a.length; i++) {
    const v = a[i];
    if (v == null) continue;
    if (e === null) { s += v; c++; if (c === n) { e = s / n; o[i] = e; } }
    else { e = v * k + e * (1 - k); o[i] = e; }
  }
  return o;
}
export const rmaA = (a, n) => emaA(a, n, 1 / n);
export function wmaA(a, n) {
  const o = Array(a.length).fill(null), d = n * (n + 1) / 2;
  for (let i = n - 1; i < a.length; i++) {
    let s = 0, ok = true;
    for (let j = 0; j < n; j++) { const v = a[i - j]; if (v == null) { ok = false; break; } s += v * (n - j); }
    if (ok) o[i] = s / d;
  }
  return o;
}
function stdevA(a, n) {
  const m = smaA(a, n), o = Array(a.length).fill(null);
  for (let i = 0; i < a.length; i++) {
    if (m[i] == null) continue;
    let s = 0; for (let j = i - n + 1; j <= i; j++) s += (a[j] - m[i]) ** 2;
    o[i] = Math.sqrt(s / n);
  }
  return o;
}
function rollA(a, n, f) {
  const o = Array(a.length).fill(null);
  for (let i = n - 1; i < a.length; i++) { let r = a[i - n + 1]; for (let j = i - n + 2; j <= i; j++) r = f(r, a[j]); o[i] = r; }
  return o;
}
const hiA = (a, n) => rollA(a, n, Math.max), loA = (a, n) => rollA(a, n, Math.min);
const trA = b => b.map((x, i) => i ? Math.max(x.h - x.l, Math.abs(x.h - b[i - 1].c), Math.abs(x.l - b[i - 1].c)) : x.h - x.l);
const sub = (a, b) => a.map((v, i) => v == null || b[i] == null ? null : v - b[i]);
export const SOURCES = { close: "Close", open: "Open", high: "High", low: "Low", hl2: "(H+L)/2", hlc3: "(H+L+C)/3", ohlc4: "(O+H+L+C)/4" };
const SRC = { close: b => b.c, open: b => b.o, high: b => b.h, low: b => b.l, hl2: b => (b.h + b.l) / 2, hlc3: b => (b.h + b.l + b.c) / 3, ohlc4: b => (b.o + b.h + b.l + b.c) / 4 };
const src = (bars, s) => bars.map(SRC[s] || SRC.close);

export function rsiA(c, n) {
  const up = c.map((v, i) => i ? Math.max(v - c[i - 1], 0) : null), dn = c.map((v, i) => i ? Math.max(c[i - 1] - v, 0) : null);
  const ru = rmaA(up, n), rd = rmaA(dn, n);
  return ru.map((u, i) => u == null || rd[i] == null ? null : rd[i] === 0 ? 100 : 100 - 100 / (1 + u / rd[i]));
}
export function macdA(c, f, s, g) {
  const m = sub(emaA(c, f), emaA(c, s)), sig = emaA(m, g);
  return { m, sig, h: sub(m, sig) };
}
export function stochA(b, n, sk, d) {
  const hh = hiA(b.map(x => x.h), n), ll = loA(b.map(x => x.l), n);
  const raw = b.map((x, i) => hh[i] == null ? null : hh[i] === ll[i] ? 50 : 100 * (x.c - ll[i]) / (hh[i] - ll[i]));
  const k = smaA(raw, sk); return { k, d: smaA(k, d) };
}
export function adxA(b, n) {
  const pdm = b.map((x, i) => { if (!i) return null; const u = x.h - b[i - 1].h, dn = b[i - 1].l - x.l; return u > dn && u > 0 ? u : 0; });
  const mdm = b.map((x, i) => { if (!i) return null; const u = x.h - b[i - 1].h, dn = b[i - 1].l - x.l; return dn > u && dn > 0 ? dn : 0; });
  const tr = rmaA(trA(b).map((v, i) => i ? v : null), n), p = rmaA(pdm, n), m = rmaA(mdm, n);
  const pdi = p.map((v, i) => v == null || !tr[i] ? null : 100 * v / tr[i]), mdi = m.map((v, i) => v == null || !tr[i] ? null : 100 * v / tr[i]);
  const dx = pdi.map((v, i) => v == null || mdi[i] == null ? null : (v + mdi[i]) === 0 ? 0 : 100 * Math.abs(v - mdi[i]) / (v + mdi[i]));
  return { adx: rmaA(dx, n), pdi, mdi };
}
export function cciA(b, n) {
  const tp = b.map(SRC.hlc3), m = smaA(tp, n);
  return tp.map((v, i) => { if (m[i] == null) return null; let md = 0; for (let j = i - n + 1; j <= i; j++) md += Math.abs(tp[j] - m[i]); md /= n; return md ? (v - m[i]) / (0.015 * md) : 0; });
}
export function willrA(b, n) {
  const hh = hiA(b.map(x => x.h), n), ll = loA(b.map(x => x.l), n);
  return b.map((x, i) => hh[i] == null ? null : hh[i] === ll[i] ? -50 : -100 * (hh[i] - x.c) / (hh[i] - ll[i]));
}
function supertrendA(b, n, f) {
  const atr = rmaA(trA(b), n), up = Array(b.length).fill(null), dn = Array(b.length).fill(null);
  let pu = null, pd = null, trend = 1;
  for (let i = 0; i < b.length; i++) {
    if (atr[i] == null) continue;
    const hl2 = (b[i].h + b[i].l) / 2;
    let u = hl2 - f * atr[i], d = hl2 + f * atr[i];
    if (pu !== null) { u = b[i - 1].c > pu ? Math.max(u, pu) : u; d = b[i - 1].c < pd ? Math.min(d, pd) : d;
      trend = trend === -1 && b[i].c > pd ? 1 : trend === 1 && b[i].c < pu ? -1 : trend; }
    pu = u; pd = d;
    if (trend === 1) up[i] = u; else dn[i] = d;
  }
  return { up, dn };
}
function psarA(b, step, max) {
  const o = Array(b.length).fill(null); if (b.length < 3) return o;
  let up = b[1].c >= b[0].c, af = step, ep = up ? b[0].h : b[0].l, sar = up ? b[0].l : b[0].h;
  for (let i = 1; i < b.length; i++) {
    sar += af * (ep - sar);
    const p1 = b[i - 1], p2 = b[Math.max(0, i - 2)];
    if (up) {
      sar = Math.min(sar, p1.l, p2.l);
      if (b[i].l < sar) { up = false; sar = ep; ep = b[i].l; af = step; } else if (b[i].h > ep) { ep = b[i].h; af = Math.min(af + step, max); }
    } else {
      sar = Math.max(sar, p1.h, p2.h);
      if (b[i].h > sar) { up = true; sar = ep; ep = b[i].h; af = step; } else if (b[i].l < ep) { ep = b[i].l; af = Math.min(af + step, max); }
    }
    o[i] = sar;
  }
  return o;
}
function vwapA(b) {
  const o = []; let pv = 0, vv = 0, day = null;
  for (const x of b) { if (x.day !== day) { pv = 0; vv = 0; day = x.day; } pv += (x.h + x.l + x.c) / 3 * (x.v || 0); vv += x.v || 0; o.push(vv ? pv / vv : null); }
  return o;
}
function mfiA(b, n) {
  const tp = b.map(SRC.hlc3), o = Array(b.length).fill(null);
  for (let i = n; i < b.length; i++) {
    let pos = 0, neg = 0;
    for (let j = i - n + 1; j <= i; j++) { const mf = tp[j] * (b[j].v || 0); if (tp[j] > tp[j - 1]) pos += mf; else if (tp[j] < tp[j - 1]) neg += mf; }
    o[i] = neg === 0 ? 100 : 100 - 100 / (1 + pos / neg);
  }
  return o;
}
export function heikinAshi(b) {
  const o = []; let po = null, pc = null;
  for (const x of b) {
    const c = (x.o + x.h + x.l + x.c) / 4, op = po === null ? (x.o + x.c) / 2 : (po + pc) / 2;
    o.push({ ...x, o: op, h: Math.max(x.h, op, c), l: Math.min(x.l, op, c), c }); po = op; pc = c;
  }
  return o;
}

// ---------------- the list shown in the Indicators dialog ----------------
// pane "main" = drawn over the price; "own" = its own pane below.  outs: what gets drawn.
const P = (k, label, def, min = 1, max = 500, step = 1) => ({ k, label, def, min, max, step });
const S = { k: "src", label: "Source", def: "close", opts: SOURCES };
const UPC = "rgba(0,224,96,0.30)", DNC = "rgba(224,160,96,0.32)";
export const INDICATORS = [
  { id: "vol", name: "Volume", group: "Volume", pane: "main", scale: "vol", params: [P("ma", "MA length (0 = off)", 20, 0, 200)],
    outs: [{ k: "v", name: "Vol", color: "#83795f", type: "hist" }, { k: "ma", name: "MA", color: "#4fd1c5", w: 1 }],
    label: p => "Vol", calc: (b, p) => ({ v: b.map(x => x.v || 0), v_color: b.map(x => x.c >= x.o ? UPC : DNC), ma: p.ma ? smaA(b.map(x => x.v || 0), p.ma) : b.map(() => null) }) },
  { id: "sma", name: "Moving Average (SMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 50), S], outs: [{ k: "v", name: "SMA", color: "#f0c674", w: 2 }],
    label: p => `SMA ${p.len}${p.src !== "close" ? " " + p.src : ""}`, calc: (b, p) => ({ v: smaA(src(b, p.src), p.len) }) },
  { id: "ema", name: "Exponential Moving Average (EMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 20), S], outs: [{ k: "v", name: "EMA", color: "#4fd1c5", w: 2 }],
    label: p => `EMA ${p.len}${p.src !== "close" ? " " + p.src : ""}`, calc: (b, p) => ({ v: emaA(src(b, p.src), p.len) }) },
  { id: "wma", name: "Weighted Moving Average (WMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 20), S], outs: [{ k: "v", name: "WMA", color: "#a78bfa", w: 2 }],
    label: p => `WMA ${p.len}`, calc: (b, p) => ({ v: wmaA(src(b, p.src), p.len) }) },
  { id: "vwap", name: "VWAP (intraday, resets daily)", group: "Moving averages", pane: "main", params: [], outs: [{ k: "v", name: "VWAP", color: "#f0a0ff", w: 2 }],
    intradayOnly: true, label: () => "VWAP", calc: b => ({ v: vwapA(b) }) },
  { id: "bb", name: "Bollinger Bands", group: "Bands & channels", pane: "main", params: [P("len", "Length", 20), P("mult", "StdDev", 2, 0.1, 10, 0.1), S],
    outs: [{ k: "u", name: "Upper", color: "#6fa8ff", w: 1 }, { k: "m", name: "Basis", color: "#e0a060", w: 1 }, { k: "l", name: "Lower", color: "#6fa8ff", w: 1 }],
    fill: ["u", "l", "rgba(111,168,255,0.07)"], label: p => `BB ${p.len} ${p.mult}`,
    calc: (b, p) => { const s = src(b, p.src), m = smaA(s, p.len), d = stdevA(s, p.len); return { m, u: m.map((v, i) => v == null ? null : v + p.mult * d[i]), l: m.map((v, i) => v == null ? null : v - p.mult * d[i]) }; } },
  { id: "kc", name: "Keltner Channels", group: "Bands & channels", pane: "main", params: [P("len", "Length", 20), P("mult", "Multiplier", 2, 0.1, 10, 0.1)],
    outs: [{ k: "u", name: "Upper", color: "#4fd1c5", w: 1 }, { k: "m", name: "Basis", color: "#4fd1c5", w: 1 }, { k: "l", name: "Lower", color: "#4fd1c5", w: 1 }],
    fill: ["u", "l", "rgba(79,209,197,0.06)"], label: p => `KC ${p.len} ${p.mult}`,
    calc: (b, p) => { const m = emaA(b.map(x => x.c), p.len), r = emaA(trA(b), p.len); return { m, u: m.map((v, i) => v == null || r[i] == null ? null : v + p.mult * r[i]), l: m.map((v, i) => v == null || r[i] == null ? null : v - p.mult * r[i]) }; } },
  { id: "dc", name: "Donchian Channels", group: "Bands & channels", pane: "main", params: [P("len", "Length", 20)],
    outs: [{ k: "u", name: "Upper", color: "#6fa8ff", w: 1 }, { k: "m", name: "Basis", color: "#e0a060", w: 1 }, { k: "l", name: "Lower", color: "#6fa8ff", w: 1 }],
    fill: ["u", "l", "rgba(111,168,255,0.06)"], label: p => `DC ${p.len}`,
    calc: (b, p) => { const u = hiA(b.map(x => x.h), p.len), l = loA(b.map(x => x.l), p.len); return { u, l, m: u.map((v, i) => v == null ? null : (v + l[i]) / 2) }; } },
  { id: "st", name: "Supertrend", group: "Trend", pane: "main", params: [P("len", "ATR length", 10), P("f", "Factor", 3, 0.1, 20, 0.1)],
    outs: [{ k: "up", name: "Up trend", color: "#00e060", w: 2 }, { k: "dn", name: "Down trend", color: "#ff6b6b", w: 2 }],
    label: p => `Supertrend ${p.len} ${p.f}`, calc: (b, p) => supertrendA(b, p.len, p.f) },
  { id: "psar", name: "Parabolic SAR", group: "Trend", pane: "main", params: [P("step", "Step", 0.02, 0.001, 1, 0.001), P("max", "Maximum", 0.2, 0.01, 1, 0.01)],
    outs: [{ k: "v", name: "SAR", color: "#f0c674", type: "dots" }], label: p => `SAR ${p.step} ${p.max}`, calc: (b, p) => ({ v: psarA(b, p.step, p.max) }) },
  { id: "rsi", name: "Relative Strength Index (RSI)", group: "Oscillators", pane: "own", params: [P("len", "Length", 14), S], outs: [{ k: "v", name: "RSI", color: "#a78bfa", w: 2 }],
    levels: [70, 50, 30], band: [70, 30, "rgba(167,139,250,0.08)"], label: p => `RSI ${p.len}`, calc: (b, p) => ({ v: rsiA(src(b, p.src), p.len) }) },
  { id: "macd", name: "MACD", group: "Oscillators", pane: "own", params: [P("f", "Fast length", 12), P("s", "Slow length", 26), P("g", "Signal smoothing", 9), S],
    outs: [{ k: "h", name: "Histogram", color: "#83795f", type: "hist" }, { k: "m", name: "MACD", color: "#6fa8ff", w: 2 }, { k: "sig", name: "Signal", color: "#e0a060", w: 2 }],
    levels: [0], label: p => `MACD ${p.f} ${p.s} ${p.g}`,
    calc: (b, p) => { const r = macdA(src(b, p.src), p.f, p.s, p.g);
      r.h_color = r.h.map((v, i) => v == null ? null : v >= 0 ? (i && r.h[i - 1] != null && v < r.h[i - 1] ? "rgba(0,224,96,0.35)" : "rgba(0,224,96,0.8)") : (i && r.h[i - 1] != null && v > r.h[i - 1] ? "rgba(224,160,96,0.35)" : "rgba(224,160,96,0.85)"));
      return r; } },
  { id: "stoch", name: "Stochastic", group: "Oscillators", pane: "own", params: [P("n", "%K length", 14), P("sk", "%K smoothing", 3), P("d", "%D smoothing", 3)],
    outs: [{ k: "k", name: "%K", color: "#6fa8ff", w: 2 }, { k: "d", name: "%D", color: "#e0a060", w: 1 }], levels: [80, 20], band: [80, 20, "rgba(111,168,255,0.07)"],
    label: p => `Stoch ${p.n} ${p.sk} ${p.d}`, calc: (b, p) => stochA(b, p.n, p.sk, p.d) },
  { id: "cci", name: "Commodity Channel Index (CCI)", group: "Oscillators", pane: "own", params: [P("len", "Length", 20)], outs: [{ k: "v", name: "CCI", color: "#4fd1c5", w: 2 }],
    levels: [100, 0, -100], band: [100, -100, "rgba(79,209,197,0.07)"], label: p => `CCI ${p.len}`, calc: (b, p) => ({ v: cciA(b, p.len) }) },
  { id: "willr", name: "Williams %R", group: "Oscillators", pane: "own", params: [P("len", "Length", 14)], outs: [{ k: "v", name: "%R", color: "#a78bfa", w: 2 }],
    levels: [-20, -80], band: [-20, -80, "rgba(167,139,250,0.07)"], label: p => `%R ${p.len}`, calc: (b, p) => ({ v: willrA(b, p.len) }) },
  { id: "mfi", name: "Money Flow Index (MFI)", group: "Volume", pane: "own", params: [P("len", "Length", 14)], outs: [{ k: "v", name: "MFI", color: "#f0a0ff", w: 2 }],
    levels: [80, 20], band: [80, 20, "rgba(240,160,255,0.07)"], label: p => `MFI ${p.len}`, calc: (b, p) => ({ v: mfiA(b, p.len) }) },
  { id: "obv", name: "On Balance Volume (OBV)", group: "Volume", pane: "own", params: [], outs: [{ k: "v", name: "OBV", color: "#6fa8ff", w: 2 }],
    label: () => "OBV", calc: b => { let s = 0; return { v: b.map((x, i) => (s += !i ? 0 : x.c > b[i - 1].c ? (x.v || 0) : x.c < b[i - 1].c ? -(x.v || 0) : 0)) }; } },
  { id: "atr", name: "Average True Range (ATR)", group: "Volatility", pane: "own", params: [P("len", "Length", 14)], outs: [{ k: "v", name: "ATR", color: "#ff6b6b", w: 2 }],
    label: p => `ATR ${p.len}`, calc: (b, p) => ({ v: rmaA(trA(b), p.len) }) },
  { id: "adx", name: "ADX / Directional Movement (DMI)", group: "Trend", pane: "own", params: [P("len", "Length", 14)],
    outs: [{ k: "adx", name: "ADX", color: "#f0c674", w: 2 }, { k: "pdi", name: "+DI", color: "#00e060", w: 1 }, { k: "mdi", name: "−DI", color: "#ff6b6b", w: 1 }],
    levels: [25], label: p => `DMI ${p.len}`, calc: (b, p) => adxA(b, p.len) },
  { id: "roc", name: "Rate of Change (ROC)", group: "Oscillators", pane: "own", params: [P("len", "Length", 12)], outs: [{ k: "v", name: "ROC", color: "#4fd1c5", w: 2 }],
    levels: [0], label: p => `ROC ${p.len}`, calc: (b, p) => ({ v: b.map((x, i) => i >= p.len && b[i - p.len].c ? 100 * (x.c / b[i - p.len].c - 1) : null) }) },
];

// ---------------- more TradingView built-ins ----------------
const sumA = (a, n) => { const o = Array(a.length).fill(null); let s = 0, c = 0; for (let i = 0; i < a.length; i++) { const v = a[i]; if (v == null) { s = 0; c = 0; continue; } s += v; c++; if (c > n) { s -= a[i - n]; c = n; } if (c === n) o[i] = s; } return o; };
const chg = (a, n = 1) => a.map((v, i) => i >= n && v != null && a[i - n] != null ? v - a[i - n] : null);
const shiftA = (a, k) => { const o = Array(a.length + Math.max(0, k)).fill(null); a.forEach((v, i) => { const j = i + k; if (j >= 0 && j < o.length) o[j] = v; }); return o; };   // k > 0 draws into the future
const mid = (b, n) => { const h = hiA(b.map(x => x.h), n), l = loA(b.map(x => x.l), n); return h.map((v, i) => v == null ? null : (v + l[i]) / 2); };
const swmaA = a => a.map((v, i) => i < 3 || v == null || a[i - 3] == null ? null : (a[i - 3] + 2 * a[i - 2] + 2 * a[i - 1] + v) / 6);
function hma(a, n) { const x = wmaA(a, Math.max(1, Math.round(n / 2))), y = wmaA(a, n); return wmaA(x.map((v, i) => v == null || y[i] == null ? null : 2 * v - y[i]), Math.max(1, Math.round(Math.sqrt(n)))); }
function linreg(a, n) { const o = Array(a.length).fill(null); for (let i = n - 1; i < a.length; i++) { let sx = 0, sy = 0, sxy = 0, sxx = 0, ok = true; for (let j = 0; j < n; j++) { const y = a[i - n + 1 + j]; if (y == null) { ok = false; break; } sx += j; sy += y; sxy += j * y; sxx += j * j; } if (!ok) continue; const sl = (n * sxy - sx * sy) / (n * sxx - sx * sx), ic = (sy - sl * sx) / n; o[i] = ic + sl * (n - 1); } return o; }
function almaA(a, n, off, sig) { const m = off * (n - 1), s = n / sig, w = [...Array(n)].map((_, i) => Math.exp(-((i - m) ** 2) / (2 * s * s))), ws = w.reduce((x, y) => x + y, 0); const o = Array(a.length).fill(null); for (let i = n - 1; i < a.length; i++) { let t = 0, ok = true; for (let j = 0; j < n; j++) { const v = a[i - n + 1 + j]; if (v == null) { ok = false; break; } t += v * w[j]; } if (ok) o[i] = t / ws; } return o; }
function mcginley(a, n) { const e = emaA(a, n), o = Array(a.length).fill(null); let m = null; for (let i = 0; i < a.length; i++) { if (m == null) { m = e[i]; o[i] = m; continue; } m = m + (a[i] - m) / (n * Math.pow(a[i] / m, 4)); o[i] = m; } return o; }
function pivotsA(b, per) {
  const key = x => per === "D" ? x.day : per === "W" ? (() => { const d = new Date(x.day + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10); })() : per === "M" ? x.day.slice(0, 7) : x.day.slice(0, 4);
  const out = { p: [], r1: [], s1: [], r2: [], s2: [], r3: [], s3: [] }; let cur = null, H = -Infinity, L = Infinity, C = null, lv = null;
  for (const x of b) {
    const k = key(x);
    if (k !== cur) { if (cur !== null) { const P = (H + L + C) / 3; lv = { p: P, r1: 2 * P - L, s1: 2 * P - H, r2: P + (H - L), s2: P - (H - L), r3: H + 2 * (P - L), s3: L - 2 * (H - P), start: true }; } cur = k; H = -Infinity; L = Infinity; }
    H = Math.max(H, x.h); L = Math.min(L, x.l); C = x.c;
    for (const f of Object.keys(out)) out[f].push(lv && !lv.start ? lv[f] : null);
    if (lv) lv.start = false;
  }
  return out;
}
function zigzag(b, dev) {
  const o = Array(b.length).fill(null); if (!b.length) return o;
  const piv = [[0, b[0].c]]; let dir = 0, ext = 0;
  for (let i = 1; i < b.length; i++) {
    const last = piv[piv.length - 1][1];
    if (dir >= 0 && b[i].h >= b[ext].h) ext = i;
    if (dir <= 0 && b[i].l <= b[ext].l) ext = i;
    if (dir >= 0 && b[i].l < b[ext].h * (1 - dev / 100) && b[ext].h > last) { piv.push([ext, b[ext].h]); dir = -1; ext = i; }
    else if (dir <= 0 && b[i].h > b[ext].l * (1 + dev / 100) && b[ext].l < last) { piv.push([ext, b[ext].l]); dir = 1; ext = i; }
  }
  piv.push([b.length - 1, dir >= 0 ? b[ext].h : b[ext].l]);
  for (let k = 1; k < piv.length; k++) { const [i0, v0] = piv[k - 1], [i1, v1] = piv[k]; for (let i = i0; i <= i1; i++) o[i] = i1 === i0 ? v1 : v0 + (v1 - v0) * (i - i0) / (i1 - i0); }
  return o;
}
const perAuto = b => { if (b.length < 2) return "M"; const gap = typeof b[1].time === "number" ? b[1].time - b[0].time : (Date.parse(b[1].time) - Date.parse(b[0].time)) / 1000; return gap < 3600 ? "D" : gap < 86400 ? "W" : gap <= 86400 * 4 ? "M" : "Y"; };
const adA = b => { let s = 0; return b.map(x => (s += x.h === x.l ? 0 : ((x.c - x.l) - (x.h - x.c)) / (x.h - x.l) * (x.v || 0))); };

const MORE = [
  // moving averages
  { id: "hma", name: "Hull Moving Average", group: "Moving averages", pane: "main", params: [P("len", "Length", 9), S], outs: [{ k: "v", name: "HMA", color: "#ff9ff3", w: 2 }], label: p => `HMA ${p.len}`, calc: (b, p) => ({ v: hma(src(b, p.src), p.len) }) },
  { id: "dema", name: "Double EMA (DEMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 9), S], outs: [{ k: "v", name: "DEMA", color: "#6fa8ff", w: 2 }], label: p => `DEMA ${p.len}`, calc: (b, p) => { const e = emaA(src(b, p.src), p.len), e2 = emaA(e, p.len); return { v: e.map((v, i) => v == null || e2[i] == null ? null : 2 * v - e2[i]) }; } },
  { id: "tema", name: "Triple EMA (TEMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 9), S], outs: [{ k: "v", name: "TEMA", color: "#4fd1c5", w: 2 }], label: p => `TEMA ${p.len}`, calc: (b, p) => { const e = emaA(src(b, p.src), p.len), e2 = emaA(e, p.len), e3 = emaA(e2, p.len); return { v: e.map((v, i) => v == null || e2[i] == null || e3[i] == null ? null : 3 * v - 3 * e2[i] + e3[i]) }; } },
  { id: "smma", name: "Smoothed MA (SMMA / RMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 7), S], outs: [{ k: "v", name: "SMMA", color: "#f0c674", w: 2 }], label: p => `SMMA ${p.len}`, calc: (b, p) => ({ v: rmaA(src(b, p.src), p.len) }) },
  { id: "vwma", name: "Volume Weighted MA (VWMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 20)], outs: [{ k: "v", name: "VWMA", color: "#e0a060", w: 2 }], label: p => `VWMA ${p.len}`, calc: (b, p) => { const n = sumA(b.map(x => x.c * (x.v || 0)), p.len), d = sumA(b.map(x => x.v || 0), p.len); return { v: n.map((v, i) => v == null || !d[i] ? null : v / d[i]) }; } },
  { id: "lsma", name: "Least Squares MA (Linear Regression)", group: "Moving averages", pane: "main", params: [P("len", "Length", 25), S], outs: [{ k: "v", name: "LSMA", color: "#a78bfa", w: 2 }], label: p => `LSMA ${p.len}`, calc: (b, p) => ({ v: linreg(src(b, p.src), p.len) }) },
  { id: "alma", name: "Arnaud Legoux MA (ALMA)", group: "Moving averages", pane: "main", params: [P("len", "Length", 9), P("off", "Offset", 0.85, 0, 1, 0.01), P("sig", "Sigma", 6, 0.1, 20, 0.1)], outs: [{ k: "v", name: "ALMA", color: "#00e0c0", w: 2 }], label: p => `ALMA ${p.len}`, calc: (b, p) => ({ v: almaA(b.map(x => x.c), p.len, p.off, p.sig) }) },
  { id: "mcg", name: "McGinley Dynamic", group: "Moving averages", pane: "main", params: [P("len", "Length", 14)], outs: [{ k: "v", name: "McGinley", color: "#6fa8ff", w: 2 }], label: p => `McGinley ${p.len}`, calc: (b, p) => ({ v: mcginley(b.map(x => x.c), p.len) }) },
  { id: "macross", name: "MA Cross (two SMAs)", group: "Moving averages", pane: "main", params: [P("f", "Short", 9), P("s", "Long", 21)], outs: [{ k: "f", name: "Short", color: "#00e060", w: 2 }, { k: "s", name: "Long", color: "#ff6b6b", w: 2 }], label: p => `MA Cross ${p.f} ${p.s}`, calc: (b, p) => ({ f: smaA(b.map(x => x.c), p.f), s: smaA(b.map(x => x.c), p.s) }) },
  { id: "ribbon", name: "Moving Average Ribbon (EMA 20/50/100/200)", group: "Moving averages", pane: "main", params: [], outs: [{ k: "a", name: "20", color: "#00e060", w: 1 }, { k: "b", name: "50", color: "#f0c674", w: 1 }, { k: "c", name: "100", color: "#e0a060", w: 1 }, { k: "d", name: "200", color: "#ff6b6b", w: 1 }], label: () => "MA Ribbon", calc: b => { const c = b.map(x => x.c); return { a: emaA(c, 20), b: emaA(c, 50), c: emaA(c, 100), d: emaA(c, 200) }; } },
  { id: "alligator", name: "Williams Alligator", group: "Trend", pane: "main", params: [], outs: [{ k: "jaw", name: "Jaw", color: "#6fa8ff", w: 2 }, { k: "teeth", name: "Teeth", color: "#ff6b6b", w: 2 }, { k: "lips", name: "Lips", color: "#00e060", w: 2 }], label: () => "Alligator 13 8 5",
    calc: b => { const h = src(b, "hl2"); return { jaw: shiftA(rmaA(h, 13), 8), teeth: shiftA(rmaA(h, 8), 5), lips: shiftA(rmaA(h, 5), 3) }; } },
  { id: "ichimoku", name: "Ichimoku Cloud", group: "Trend", pane: "main", params: [P("conv", "Conversion", 9), P("base", "Base", 26), P("spanb", "Span B", 52), P("disp", "Displacement", 26)],
    outs: [{ k: "t", name: "Conversion", color: "#6fa8ff", w: 1 }, { k: "k", name: "Base", color: "#ff6b6b", w: 1 }, { k: "lag", name: "Lagging", color: "#83795f", w: 1 }, { k: "a", name: "Span A", color: "#00e060", w: 1 }, { k: "bb", name: "Span B", color: "#e0a060", w: 1 }],
    fill2: ["a", "bb", "rgba(0,224,96,0.10)", "rgba(224,160,96,0.12)"], label: p => `Ichimoku ${p.conv} ${p.base} ${p.spanb} ${p.disp}`,
    calc: (b, p) => { const t = mid(b, p.conv), k = mid(b, p.base), a = t.map((v, i) => v == null || k[i] == null ? null : (v + k[i]) / 2), sb = mid(b, p.spanb);
      return { t, k, lag: shiftA(b.map(x => x.c), -(p.disp - 1)), a: shiftA(a, p.disp - 1), bb: shiftA(sb, p.disp - 1) }; } },
  { id: "env", name: "Envelopes", group: "Bands & channels", pane: "main", params: [P("len", "Length", 20), P("pct", "Percent", 10, 0.1, 50, 0.1)], outs: [{ k: "u", name: "Upper", color: "#6fa8ff", w: 1 }, { k: "m", name: "Basis", color: "#e0a060", w: 1 }, { k: "l", name: "Lower", color: "#6fa8ff", w: 1 }],
    fill: ["u", "l", "rgba(111,168,255,0.05)"], label: p => `Env ${p.len} ${p.pct}%`, calc: (b, p) => { const m = smaA(b.map(x => x.c), p.len); return { m, u: m.map(v => v == null ? null : v * (1 + p.pct / 100)), l: m.map(v => v == null ? null : v * (1 - p.pct / 100)) }; } },
  { id: "pivots", name: "Pivot Points Standard", group: "Bands & channels", pane: "main", params: [{ k: "per", label: "Period", def: "auto", opts: { auto: "Auto", D: "Daily", W: "Weekly", M: "Monthly", Y: "Yearly" } }],
    outs: [{ k: "r3", name: "R3", color: "#ff6b6b", w: 1 }, { k: "r2", name: "R2", color: "#ff6b6b", w: 1 }, { k: "r1", name: "R1", color: "#ff6b6b", w: 1 }, { k: "p", name: "P", color: "#f0c674", w: 1 }, { k: "s1", name: "S1", color: "#00e060", w: 1 }, { k: "s2", name: "S2", color: "#00e060", w: 1 }, { k: "s3", name: "S3", color: "#00e060", w: 1 }],
    label: p => `Pivots ${p.per}`, calc: (b, p) => pivotsA(b, p.per === "auto" ? perAuto(b) : p.per) },
  { id: "zz", name: "Zig Zag", group: "Trend", pane: "main", params: [P("dev", "Deviation %", 5, 0.5, 50, 0.5)], outs: [{ k: "v", name: "ZigZag", color: "#f0c674", w: 2 }], label: p => `ZigZag ${p.dev}%`, calc: (b, p) => ({ v: zigzag(b, p.dev) }) },
  // oscillators
  { id: "stochrsi", name: "Stochastic RSI", group: "Oscillators", pane: "own", params: [P("k", "K", 3), P("d", "D", 3), P("rsi", "RSI length", 14), P("st", "Stochastic length", 14)], outs: [{ k: "k", name: "K", color: "#6fa8ff", w: 2 }, { k: "d", name: "D", color: "#e0a060", w: 1 }],
    levels: [80, 20], band: [80, 20, "rgba(111,168,255,0.07)"], label: p => `Stoch RSI ${p.k} ${p.d} ${p.rsi} ${p.st}`,
    calc: (b, p) => { const r = rsiA(b.map(x => x.c), p.rsi), hh = hiA(r, p.st), ll = loA(r, p.st), raw = r.map((v, i) => v == null || hh[i] == null ? null : hh[i] === ll[i] ? 50 : 100 * (v - ll[i]) / (hh[i] - ll[i])); const k = smaA(raw, p.k); return { k, d: smaA(k, p.d) }; } },
  { id: "ao", name: "Awesome Oscillator", group: "Oscillators", pane: "own", params: [], outs: [{ k: "v", name: "AO", color: "#83795f", type: "hist" }], levels: [0], label: () => "AO",
    calc: b => { const h = src(b, "hl2"), f = smaA(h, 5), s = smaA(h, 34), v = f.map((x, i) => x == null || s[i] == null ? null : x - s[i]); return { v, v_color: v.map((x, i) => x == null ? null : i && v[i - 1] != null && x < v[i - 1] ? "rgba(255,107,107,0.8)" : "rgba(0,224,96,0.8)") }; } },
  { id: "mom", name: "Momentum", group: "Oscillators", pane: "own", params: [P("len", "Length", 10)], outs: [{ k: "v", name: "Mom", color: "#6fa8ff", w: 2 }], levels: [0], label: p => `Mom ${p.len}`, calc: (b, p) => ({ v: chg(b.map(x => x.c), p.len) }) },
  { id: "ppo", name: "Price Oscillator (PPO)", group: "Oscillators", pane: "own", params: [P("f", "Short", 12), P("s", "Long", 26), P("g", "Signal", 9)], outs: [{ k: "h", name: "Hist", color: "#83795f", type: "hist" }, { k: "v", name: "PPO", color: "#6fa8ff", w: 2 }, { k: "sig", name: "Signal", color: "#e0a060", w: 1 }], levels: [0], label: p => `PPO ${p.f} ${p.s} ${p.g}`,
    calc: (b, p) => { const c = b.map(x => x.c), f = emaA(c, p.f), s = emaA(c, p.s), v = f.map((x, i) => x == null || s[i] == null ? null : 100 * (x - s[i]) / s[i]), sig = emaA(v, p.g); return { v, sig, h: sub(v, sig) }; } },
  { id: "tsi", name: "True Strength Index (TSI)", group: "Oscillators", pane: "own", params: [P("l", "Long", 25), P("s", "Short", 13), P("g", "Signal", 13)], outs: [{ k: "v", name: "TSI", color: "#6fa8ff", w: 2 }, { k: "sig", name: "Signal", color: "#e0a060", w: 1 }], levels: [0], label: p => `TSI ${p.l} ${p.s}`,
    calc: (b, p) => { const m = chg(b.map(x => x.c)), n = emaA(emaA(m, p.l), p.s), d = emaA(emaA(m.map(v => v == null ? null : Math.abs(v)), p.l), p.s), v = n.map((x, i) => x == null || !d[i] ? null : 100 * x / d[i]); return { v, sig: emaA(v, p.g) }; } },
  { id: "smi", name: "SMI Ergodic Indicator", group: "Oscillators", pane: "own", params: [P("l", "Long", 20), P("s", "Short", 5), P("g", "Signal", 5)], outs: [{ k: "v", name: "SMI", color: "#6fa8ff", w: 2 }, { k: "sig", name: "Signal", color: "#e0a060", w: 1 }], levels: [0], label: p => `SMIO ${p.l} ${p.s} ${p.g}`,
    calc: (b, p) => { const m = chg(b.map(x => x.c)), n = emaA(emaA(m, p.l), p.s), d = emaA(emaA(m.map(v => v == null ? null : Math.abs(v)), p.l), p.s), v = n.map((x, i) => x == null || !d[i] ? null : x / d[i]); return { v, sig: emaA(v, p.g) }; } },
  { id: "trix", name: "TRIX", group: "Oscillators", pane: "own", params: [P("len", "Length", 18)], outs: [{ k: "v", name: "TRIX", color: "#ff6b6b", w: 2 }], levels: [0], label: p => `TRIX ${p.len}`, calc: (b, p) => ({ v: chg(emaA(emaA(emaA(b.map(x => Math.log(x.c)), p.len), p.len), p.len)).map(v => v == null ? null : 10000 * v) }) },
  { id: "uo", name: "Ultimate Oscillator", group: "Oscillators", pane: "own", params: [P("a", "Fast", 7), P("b2", "Middle", 14), P("c", "Slow", 28)], outs: [{ k: "v", name: "UO", color: "#f0a0ff", w: 2 }], levels: [70, 30], label: p => `UO ${p.a} ${p.b2} ${p.c}`,
    calc: (b, p) => { const bp = b.map((x, i) => i ? x.c - Math.min(x.l, b[i - 1].c) : null), tr = b.map((x, i) => i ? Math.max(x.h, b[i - 1].c) - Math.min(x.l, b[i - 1].c) : null), av = n => { const s1 = sumA(bp, n), s2 = sumA(tr, n); return s1.map((v, i) => v == null || !s2[i] ? null : v / s2[i]); }, A = av(p.a), B = av(p.b2), C = av(p.c);
      return { v: A.map((v, i) => v == null || B[i] == null || C[i] == null ? null : 100 * (4 * v + 2 * B[i] + C[i]) / 7) }; } },
  { id: "cmo", name: "Chande Momentum Oscillator", group: "Oscillators", pane: "own", params: [P("len", "Length", 9)], outs: [{ k: "v", name: "CMO", color: "#6fa8ff", w: 2 }], levels: [50, 0, -50], label: p => `ChandeMO ${p.len}`,
    calc: (b, p) => { const m = chg(b.map(x => x.c)), u = sumA(m.map(v => v == null ? null : Math.max(v, 0)), p.len), d = sumA(m.map(v => v == null ? null : Math.max(-v, 0)), p.len); return { v: u.map((x, i) => x == null || (x + d[i]) === 0 ? null : 100 * (x - d[i]) / (x + d[i])) }; } },
  { id: "fisher", name: "Fisher Transform", group: "Oscillators", pane: "own", params: [P("len", "Length", 9)], outs: [{ k: "v", name: "Fisher", color: "#6fa8ff", w: 2 }, { k: "t", name: "Trigger", color: "#e0a060", w: 1 }], levels: [1.5, 0, -1.5], label: p => `Fisher ${p.len}`,
    calc: (b, p) => { const h = src(b, "hl2"), hh = hiA(h, p.len), ll = loA(h, p.len), v = Array(b.length).fill(null); let val = 0, f = 0;
      for (let i = 0; i < b.length; i++) { if (hh[i] == null) continue; val = 0.66 * ((hh[i] === ll[i] ? 0 : (h[i] - ll[i]) / (hh[i] - ll[i])) - 0.5) + 0.67 * val; val = Math.max(-0.999, Math.min(0.999, val)); f = 0.5 * Math.log((1 + val) / (1 - val)) + 0.5 * f; v[i] = f; }
      return { v, t: v.map((x, i) => i ? v[i - 1] : null) }; } },
  { id: "rvi", name: "Relative Vigor Index", group: "Oscillators", pane: "own", params: [P("len", "Length", 10)], outs: [{ k: "v", name: "RVGI", color: "#00e060", w: 2 }, { k: "sig", name: "Signal", color: "#ff6b6b", w: 1 }], levels: [0], label: p => `RVGI ${p.len}`,
    calc: (b, p) => { const n = sumA(swmaA(b.map(x => x.c - x.o)), p.len), d = sumA(swmaA(b.map(x => x.h - x.l)), p.len), v = n.map((x, i) => x == null || !d[i] ? null : x / d[i]); return { v, sig: swmaA(v) }; } },
  { id: "dpo", name: "Detrended Price Oscillator", group: "Oscillators", pane: "own", params: [P("len", "Length", 21)], outs: [{ k: "v", name: "DPO", color: "#6fa8ff", w: 2 }], levels: [0], label: p => `DPO ${p.len}`,
    calc: (b, p) => { const m = smaA(b.map(x => x.c), p.len), k = Math.floor(p.len / 2) + 1; return { v: b.map((x, i) => i >= k && m[i - k] != null ? x.c - m[i - k] : null) }; } },
  { id: "coppock", name: "Coppock Curve", group: "Oscillators", pane: "own", params: [P("w", "WMA length", 10), P("l", "Long ROC", 14), P("s", "Short ROC", 11)], outs: [{ k: "v", name: "Coppock", color: "#6fa8ff", w: 2 }], levels: [0], label: p => `Coppock ${p.w} ${p.l} ${p.s}`,
    calc: (b, p) => { const c = b.map(x => x.c), roc = n => c.map((v, i) => i >= n ? 100 * (v / c[i - n] - 1) : null); const L = roc(p.l), Sh = roc(p.s); return { v: wmaA(L.map((v, i) => v == null || Sh[i] == null ? null : v + Sh[i]), p.w) }; } },
  { id: "kst", name: "Know Sure Thing (KST)", group: "Oscillators", pane: "own", params: [], outs: [{ k: "v", name: "KST", color: "#00e060", w: 2 }, { k: "sig", name: "Signal", color: "#ff6b6b", w: 1 }], levels: [0], label: () => "KST 10 15 20 30",
    calc: b => { const c = b.map(x => x.c), roc = n => c.map((v, i) => i >= n ? 100 * (v / c[i - n] - 1) : null), r = [[10, 10], [15, 10], [20, 10], [30, 15]].map(([n, s]) => smaA(roc(n), s)); const v = c.map((_, i) => r.some(a => a[i] == null) ? null : r[0][i] + 2 * r[1][i] + 3 * r[2][i] + 4 * r[3][i]); return { v, sig: smaA(v, 9) }; } },
  { id: "aroon", name: "Aroon", group: "Trend", pane: "own", params: [P("len", "Length", 14)], outs: [{ k: "u", name: "Up", color: "#e0a060", w: 2 }, { k: "d", name: "Down", color: "#6fa8ff", w: 2 }], levels: [70, 30], label: p => `Aroon ${p.len}`,
    calc: (b, p) => { const u = Array(b.length).fill(null), d = Array(b.length).fill(null); for (let i = p.len; i < b.length; i++) { let hi = i, lo = i; for (let j = i - p.len; j <= i; j++) { if (b[j].h >= b[hi].h) hi = j; if (b[j].l <= b[lo].l) lo = j; } u[i] = 100 * (p.len - (i - hi)) / p.len; d[i] = 100 * (p.len - (i - lo)) / p.len; } return { u, d }; } },
  { id: "vortex", name: "Vortex Indicator", group: "Trend", pane: "own", params: [P("len", "Length", 14)], outs: [{ k: "p", name: "VI+", color: "#6fa8ff", w: 2 }, { k: "m", name: "VI−", color: "#ff6b6b", w: 2 }], levels: [1], label: p => `VI ${p.len}`,
    calc: (b, p) => { const vp = sumA(b.map((x, i) => i ? Math.abs(x.h - b[i - 1].l) : null), p.len), vm = sumA(b.map((x, i) => i ? Math.abs(x.l - b[i - 1].h) : null), p.len), tr = sumA(trA(b).map((v, i) => i ? v : null), p.len); return { p: vp.map((v, i) => v == null || !tr[i] ? null : v / tr[i]), m: vm.map((v, i) => v == null || !tr[i] ? null : v / tr[i]) }; } },
  { id: "chop", name: "Choppiness Index", group: "Trend", pane: "own", params: [P("len", "Length", 14)], outs: [{ k: "v", name: "CHOP", color: "#f0c674", w: 2 }], levels: [61.8, 38.2], band: [61.8, 38.2, "rgba(240,198,116,0.07)"], label: p => `CHOP ${p.len}`,
    calc: (b, p) => { const t = sumA(trA(b), p.len), hh = hiA(b.map(x => x.h), p.len), ll = loA(b.map(x => x.l), p.len); return { v: t.map((v, i) => v == null || hh[i] === ll[i] ? null : 100 * Math.log10(v / (hh[i] - ll[i])) / Math.log10(p.len)) }; } },
  { id: "bbp", name: "Bull Bear Power", group: "Trend", pane: "own", params: [P("len", "Length", 13)], outs: [{ k: "v", name: "BBP", color: "#83795f", type: "hist" }], levels: [0], label: p => `BBP ${p.len}`,
    calc: (b, p) => { const e = emaA(b.map(x => x.c), p.len), v = b.map((x, i) => e[i] == null ? null : (x.h - e[i]) + (x.l - e[i])); return { v, v_color: v.map(x => x == null ? null : x >= 0 ? "rgba(0,224,96,0.75)" : "rgba(255,107,107,0.75)") }; } },
  { id: "bop", name: "Balance of Power", group: "Oscillators", pane: "own", params: [P("len", "Smoothing", 14)], outs: [{ k: "v", name: "BOP", color: "#ff6b6b", w: 2 }], levels: [0], label: p => `BOP ${p.len}`, calc: (b, p) => ({ v: smaA(b.map(x => x.h === x.l ? 0 : (x.c - x.o) / (x.h - x.l)), p.len) }) },
  { id: "mass", name: "Mass Index", group: "Volatility", pane: "own", params: [P("len", "Length", 10)], outs: [{ k: "v", name: "Mass", color: "#6fa8ff", w: 2 }], levels: [27, 26.5], label: p => `Mass ${p.len}`,
    calc: (b, p) => { const r = b.map(x => x.h - x.l), e1 = emaA(r, 9), e2 = emaA(e1, 9); return { v: sumA(e1.map((v, i) => v == null || !e2[i] ? null : v / e2[i]), p.len) }; } },
  { id: "hv", name: "Historical Volatility", group: "Volatility", pane: "own", params: [P("len", "Length", 10)], outs: [{ k: "v", name: "HV %", color: "#ff6b6b", w: 2 }], label: p => `HV ${p.len}`,
    calc: (b, p) => { const r = b.map((x, i) => i ? Math.log(x.c / b[i - 1].c) : null); return { v: stdevA(r, p.len).map(v => v == null ? null : 100 * v * Math.sqrt(252)) }; } },
  { id: "stdev", name: "Standard Deviation", group: "Volatility", pane: "own", params: [P("len", "Length", 20)], outs: [{ k: "v", name: "StdDev", color: "#6fa8ff", w: 2 }], label: p => `StdDev ${p.len}`, calc: (b, p) => ({ v: stdevA(b.map(x => x.c), p.len) }) },
  { id: "bbw", name: "Bollinger BandWidth", group: "Volatility", pane: "own", params: [P("len", "Length", 20), P("mult", "StdDev", 2, 0.1, 10, 0.1)], outs: [{ k: "v", name: "BBW", color: "#6fa8ff", w: 2 }], label: p => `BBW ${p.len} ${p.mult}`,
    calc: (b, p) => { const c = b.map(x => x.c), m = smaA(c, p.len), d = stdevA(c, p.len); return { v: m.map((v, i) => v == null || !v ? null : 100 * 2 * p.mult * d[i] / v) }; } },
  { id: "bbpct", name: "Bollinger Bands %B", group: "Volatility", pane: "own", params: [P("len", "Length", 20), P("mult", "StdDev", 2, 0.1, 10, 0.1)], outs: [{ k: "v", name: "%B", color: "#6fa8ff", w: 2 }], levels: [1, 0.5, 0], band: [1, 0, "rgba(111,168,255,0.06)"], label: p => `%B ${p.len} ${p.mult}`,
    calc: (b, p) => { const c = b.map(x => x.c), m = smaA(c, p.len), d = stdevA(c, p.len); return { v: m.map((v, i) => v == null || !d[i] ? null : (c[i] - (v - p.mult * d[i])) / (2 * p.mult * d[i])) }; } },
  // volume
  { id: "ad", name: "Accumulation / Distribution", group: "Volume", pane: "own", params: [], outs: [{ k: "v", name: "A/D", color: "#6fa8ff", w: 2 }], label: () => "Accum/Dist", calc: b => ({ v: adA(b) }) },
  { id: "cmf", name: "Chaikin Money Flow", group: "Volume", pane: "own", params: [P("len", "Length", 20)], outs: [{ k: "v", name: "CMF", color: "#00e060", w: 2 }], levels: [0], label: p => `CMF ${p.len}`,
    calc: (b, p) => { const mf = sumA(b.map(x => x.h === x.l ? 0 : ((x.c - x.l) - (x.h - x.c)) / (x.h - x.l) * (x.v || 0)), p.len), v = sumA(b.map(x => x.v || 0), p.len); return { v: mf.map((x, i) => x == null || !v[i] ? null : x / v[i]) }; } },
  { id: "cho", name: "Chaikin Oscillator", group: "Volume", pane: "own", params: [P("f", "Fast", 3), P("s", "Slow", 10)], outs: [{ k: "v", name: "Chaikin", color: "#ff6b6b", w: 2 }], levels: [0], label: p => `ChaikinOsc ${p.f} ${p.s}`, calc: (b, p) => { const a = adA(b); return { v: sub(emaA(a, p.f), emaA(a, p.s)) }; } },
  { id: "efi", name: "Elder Force Index", group: "Volume", pane: "own", params: [P("len", "Length", 13)], outs: [{ k: "v", name: "EFI", color: "#ff6b6b", w: 2 }], levels: [0], label: p => `EFI ${p.len}`, calc: (b, p) => ({ v: emaA(b.map((x, i) => i ? (x.c - b[i - 1].c) * (x.v || 0) : null), p.len) }) },
  { id: "eom", name: "Ease of Movement", group: "Volume", pane: "own", params: [P("len", "Length", 14)], outs: [{ k: "v", name: "EOM", color: "#00e060", w: 2 }], levels: [0], label: p => `EOM ${p.len}`,
    calc: (b, p) => { const h = src(b, "hl2"); return { v: smaA(b.map((x, i) => i && x.v ? 10000 * (h[i] - h[i - 1]) * (x.h - x.l) / x.v : null), p.len) }; } },
  { id: "pvt", name: "Price Volume Trend", group: "Volume", pane: "own", params: [], outs: [{ k: "v", name: "PVT", color: "#6fa8ff", w: 2 }], label: () => "PVT", calc: b => { let s = 0; return { v: b.map((x, i) => (s += i && b[i - 1].c ? (x.c / b[i - 1].c - 1) * (x.v || 0) : 0)) }; } },
  { id: "nv", name: "Net Volume", group: "Volume", pane: "own", params: [], outs: [{ k: "v", name: "Net vol", color: "#83795f", type: "hist" }], label: () => "Net Volume",
    calc: b => { const v = b.map((x, i) => !i ? 0 : x.c > b[i - 1].c ? (x.v || 0) : x.c < b[i - 1].c ? -(x.v || 0) : 0); return { v, v_color: v.map(x => x >= 0 ? "rgba(0,224,96,0.7)" : "rgba(255,107,107,0.7)") }; } },
  { id: "vo", name: "Volume Oscillator", group: "Volume", pane: "own", params: [P("f", "Short", 5), P("s", "Long", 10)], outs: [{ k: "v", name: "VO %", color: "#6fa8ff", w: 2 }], levels: [0], label: p => `VolOsc ${p.f} ${p.s}`,
    calc: (b, p) => { const v = b.map(x => x.v || 0), f = emaA(v, p.f), s = emaA(v, p.s); return { v: f.map((x, i) => x == null || !s[i] ? null : 100 * (x - s[i]) / s[i]) }; } },
];
INDICATORS.push(...MORE);

export const IND = Object.fromEntries(INDICATORS.map(d => [d.id, d]));
export const defaults = id => Object.fromEntries(IND[id].params.map(p => [p.k, p.def]));

// ---------------- TradingView-style "Technicals" summary (educational rule counts) ----------------
// Moving averages: price above the MA = buy, below = sell. Oscillators: the usual overbought/oversold and
// cross rules. Score = (buys - sells) / signals: > 0.5 strong buy, > 0.1 buy, < -0.1 sell, < -0.5 strong sell.
export function technicals(b) {
  if (!b || b.length < 60) return null;
  const c = b.map(x => x.c), n = b.length - 1, last = c[n], rows = [];
  const add = (group, name, value, sig) => rows.push({ group, name, value, sig });
  for (const len of [10, 20, 30, 50, 100, 200]) {
    for (const [nm, f] of [["EMA", emaA], ["SMA", smaA]]) {
      const v = f(c, len)[n]; if (v == null) continue;
      add("ma", `${nm} ${len}`, v, last > v ? 1 : last < v ? -1 : 0);
    }
  }
  const r = rsiA(c, 14); if (r[n] != null) add("osc", "RSI (14)", r[n], r[n] < 30 && r[n] > r[n - 1] ? 1 : r[n] > 70 && r[n] < r[n - 1] ? -1 : 0);
  const st = stochA(b, 14, 3, 3); if (st.k[n] != null && st.d[n] != null) add("osc", "Stochastic %K (14, 3, 3)", st.k[n], st.k[n] < 20 && st.k[n] > st.d[n] ? 1 : st.k[n] > 80 && st.k[n] < st.d[n] ? -1 : 0);
  const cc = cciA(b, 20); if (cc[n] != null) add("osc", "CCI (20)", cc[n], cc[n] < -100 && cc[n] > cc[n - 1] ? 1 : cc[n] > 100 && cc[n] < cc[n - 1] ? -1 : 0);
  const ad = adxA(b, 14); if (ad.adx[n] != null) add("osc", "ADX (14)", ad.adx[n], ad.adx[n] > 20 && ad.pdi[n] > ad.mdi[n] && ad.adx[n] > ad.adx[n - 1] ? 1 : ad.adx[n] > 20 && ad.mdi[n] > ad.pdi[n] && ad.adx[n] > ad.adx[n - 1] ? -1 : 0);
  const mo = c[n] - c[n - 10], mo1 = c[n - 1] - c[n - 11]; add("osc", "Momentum (10)", mo, mo > mo1 ? 1 : mo < mo1 ? -1 : 0);
  const md = macdA(c, 12, 26, 9); if (md.m[n] != null && md.sig[n] != null) add("osc", "MACD (12, 26)", md.m[n], md.m[n] > md.sig[n] ? 1 : md.m[n] < md.sig[n] ? -1 : 0);
  const w = willrA(b, 14); if (w[n] != null) add("osc", "Williams %R (14)", w[n], w[n] < -80 && w[n] > w[n - 1] ? 1 : w[n] > -20 && w[n] < w[n - 1] ? -1 : 0);
  const score = list => { const bu = list.filter(x => x.sig > 0).length, se = list.filter(x => x.sig < 0).length, ne = list.length - bu - se, s = list.length ? (bu - se) / list.length : 0;
    return { buy: bu, sell: se, neutral: ne, score: s, label: s > 0.5 ? "Strong buy" : s > 0.1 ? "Buy" : s < -0.5 ? "Strong sell" : s < -0.1 ? "Sell" : "Neutral" }; };
  return { rows, ma: score(rows.filter(x => x.group === "ma")), osc: score(rows.filter(x => x.group === "osc")), all: score(rows) };
}

// ---------------- "Recommended indicators" for one stock, from its own past ----------------
// Each candidate turns an indicator into a simple long-only rule (in the market or in cash), the way the
// indicator is usually read. It is tested on the stock's daily history: a signal on a day's close is acted on
// at the next day's close, 0.1% cost per buy and per sell. Chosen on the first 70% of the history
// ("training"), then checked on the last 30% it never saw ("test"). Ranked by a robust score that needs both
// parts to hold up. Past results only: educational, not advice.
const RULES = [
  { key: "sma50_200", name: "SMA 50 / 200 trend (golden cross)", family: "Trend", add: [["sma", { len: 50 }], ["sma", { len: 200 }]], sig: b => { const c = b.map(x => x.c), f = smaA(c, 50), s = smaA(c, 200); return c.map((_, i) => f[i] != null && s[i] != null ? f[i] > s[i] : null); } },
  { key: "ema20_50", name: "EMA 20 / 50 crossover", family: "Trend", add: [["ema", { len: 20 }], ["ema", { len: 50 }]], sig: b => { const c = b.map(x => x.c), f = emaA(c, 20), s = emaA(c, 50); return c.map((_, i) => f[i] != null && s[i] != null ? f[i] > s[i] : null); } },
  { key: "ema9_21", name: "EMA 9 / 21 crossover (fast)", family: "Trend", add: [["ema", { len: 9 }], ["ema", { len: 21 }]], sig: b => { const c = b.map(x => x.c), f = emaA(c, 9), s = emaA(c, 21); return c.map((_, i) => f[i] != null && s[i] != null ? f[i] > s[i] : null); } },
  { key: "px_sma200", name: "Price above SMA 200", family: "Trend", add: [["sma", { len: 200 }]], sig: b => { const s = smaA(b.map(x => x.c), 200); return b.map((x, i) => s[i] == null ? null : x.c > s[i]); } },
  { key: "st", name: "Supertrend (10, 3)", family: "Trend", add: [["st", { len: 10, f: 3 }]], sig: b => { const r = supertrendA(b, 10, 3); return b.map((_, i) => r.up[i] != null ? true : r.dn[i] != null ? false : null); } },
  { key: "macd", name: "MACD above signal", family: "Momentum", add: [["macd", {}]], sig: b => { const r = macdA(b.map(x => x.c), 12, 26, 9); return b.map((_, i) => r.m[i] == null || r.sig[i] == null ? null : r.m[i] > r.sig[i]); } },
  { key: "donchian", name: "Donchian 20 breakout (exit 10-day low)", family: "Breakout", add: [["dc", { len: 20 }]], sig: b => { const hh = hiA(b.map(x => x.h), 20), ll = loA(b.map(x => x.l), 10); let on = false; return b.map((x, i) => { if (i < 20 || hh[i - 1] == null || ll[i - 1] == null) return null; if (!on && x.c > hh[i - 1]) on = true; else if (on && x.c < ll[i - 1]) on = false; return on; }); } },
  { key: "psar", name: "Parabolic SAR", family: "Trend", add: [["psar", {}]], sig: b => { const s = psarA(b, 0.02, 0.2); return b.map((x, i) => s[i] == null ? null : x.c > s[i]); } },
  { key: "adx", name: "ADX > 25 with +DI above −DI", family: "Trend", add: [["adx", { len: 14 }]], sig: b => { const r = adxA(b, 14); return b.map((_, i) => r.adx[i] == null ? null : r.adx[i] > 25 && r.pdi[i] > r.mdi[i]); } },
  { key: "ichimoku", name: "Ichimoku: price above cloud", family: "Trend", add: [["ichimoku", {}]], sig: b => { const t = mid(b, 9), k = mid(b, 26), sb = mid(b, 52); return b.map((x, i) => { const j = i - 25; if (j < 0 || t[j] == null || k[j] == null || sb[j] == null) return null; const a = (t[j] + k[j]) / 2; return x.c > Math.max(a, sb[j]); }); } },
  { key: "rsi_mr", name: "RSI 14: buy below 30, sell above 70", family: "Mean reversion", add: [["rsi", { len: 14 }]], sig: b => { const r = rsiA(b.map(x => x.c), 14); let on = false; return b.map((_, i) => { if (r[i] == null) return null; if (!on && r[i] < 30) on = true; else if (on && r[i] > 70) on = false; return on; }); } },
  { key: "rsi2", name: "RSI 2: buy below 10, sell above 70 (short-term)", family: "Mean reversion", add: [["rsi", { len: 2 }]], sig: b => { const r = rsiA(b.map(x => x.c), 2), s = smaA(b.map(x => x.c), 200); let on = false; return b.map((x, i) => { if (r[i] == null || s[i] == null) return null; if (!on && r[i] < 10 && x.c > s[i]) on = true; else if (on && r[i] > 70) on = false; return on; }); } },
  { key: "bb_mr", name: "Bollinger: buy below lower band, sell at the middle", family: "Mean reversion", add: [["bb", { len: 20, mult: 2 }]], sig: b => { const c = b.map(x => x.c), m = smaA(c, 20), d = stdevA(c, 20); let on = false; return c.map((v, i) => { if (m[i] == null) return null; if (!on && v < m[i] - 2 * d[i]) on = true; else if (on && v > m[i]) on = false; return on; }); } },
  { key: "stoch", name: "Stochastic: %K crosses up below 20, out above 80", family: "Mean reversion", add: [["stoch", {}]], sig: b => { const r = stochA(b, 14, 3, 3); let on = false; return b.map((_, i) => { if (r.k[i] == null || r.d[i] == null || r.k[i - 1] == null || r.d[i - 1] == null) return null; if (!on && r.k[i] < 20 && r.k[i - 1] <= r.d[i - 1] && r.k[i] > r.d[i]) on = true; else if (on && r.k[i] > 80) on = false; return on; }); } },
  { key: "cci", name: "CCI 20: in on cross above −100, out on cross below +100", family: "Mean reversion", add: [["cci", { len: 20 }]], sig: b => { const r = cciA(b, 20); let on = false; return b.map((_, i) => { if (r[i] == null || r[i - 1] == null) return null; if (!on && r[i - 1] < -100 && r[i] >= -100) on = true; else if (on && r[i - 1] > 100 && r[i] <= 100) on = false; return on; }); } },
];
function backtest(b, sig, from, to, cost = 0.001) {
  let eq = 1, peak = 1, dd = 0, pos = false, trades = 0, wins = 0, entry = 0, inDays = 0; const rets = [];
  for (let i = Math.max(from, 1); i < to; i++) {
    const r = b[i].c / b[i - 1].c - 1; let day = pos ? r : 0;
    const want = sig[i - 1] === true;                     // yesterday's signal, acted on at yesterday's close
    if (want !== pos && sig[i - 1] != null) {
      day = want ? r : 0; eq *= 1 - cost;
      if (want) { entry = b[i - 1].c; trades++; } else if (b[i - 1].c > entry) wins++;
      pos = want;
    }
    if (pos) inDays++;
    eq *= 1 + day; rets.push(day); peak = Math.max(peak, eq); dd = Math.min(dd, eq / peak - 1);
  }
  if (pos && b[to - 1].c > entry) wins++;
  const n = rets.length, mu = rets.reduce((a, x) => a + x, 0) / (n || 1), sd = Math.sqrt(rets.reduce((a, x) => a + (x - mu) ** 2, 0) / (n || 1));
  const yrs = n / 252;
  return { ret: eq - 1, cagr: yrs > 0 ? Math.pow(eq, 1 / yrs) - 1 : 0, sharpe: sd ? mu / sd * Math.sqrt(252) : 0, dd, trades, win: trades ? wins / trades : null, exposure: n ? inDays / n : 0 };
}
export function recommend(b) {
  if (!b || b.length < 400) return null;
  const n = b.length, cut = Math.floor(n * 0.7), start = 200;
  const bh = (f, t) => backtest(b, b.map(() => true), f, t, 0);
  const res = RULES.map(r => {
    let sig; try { sig = r.sig(b); } catch (e) { return null; }
    const tr = backtest(b, sig, start, cut), te = backtest(b, sig, cut, n), all = backtest(b, sig, start, n);
    const enough = tr.trades >= 2 && all.trades >= 3;
    const score = enough ? Math.min(tr.sharpe, te.sharpe) * 0.6 + all.sharpe * 0.4 : -9;
    return { ...r, tr, te, all, score, now: sig[n - 1] === true };
  }).filter(Boolean).sort((a, c) => c.score - a.score);
  const buyHold = { tr: bh(start, cut), te: bh(cut, n), all: bh(start, n) };
  const fam = {}; res.slice(0, 5).forEach(r => fam[r.family] = (fam[r.family] || 0) + 1);
  const style = Object.entries(fam).sort((a, c) => c[1] - a[1])[0]?.[0];
  return { list: res, top: res.filter(r => r.score > 0).slice(0, 3), buyHold, style, years: (n - start) / 252, from: b[start].time, to: b[n - 1].time, testFrom: b[cut].time };
}
