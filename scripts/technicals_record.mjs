/* Track record of the stock page's Technicals gauge (chart-indicators.js technicals()): does its label forecast anything?
   For model E's 500 most-traded stocks, every 5th session from the first with 400 sessions of history, the label is worked
   out with the page's own code on the prices up to that close, then the stock's change over the next 10 and 63 sessions is
   compared with the average of all sampled stocks on the same day (excess return; this removes the market's own move).
   Errors are clustered by day (one value per label per day). Companies listed today only (survivorship), before costs.

     node scripts/technicals_record.mjs [--force]  -> data/config/technicals_record.json
   Re-runs itself at most once every 28 days (the daily job calls it every evening). */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { technicals } from "../chart-indicators.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "data", "config", "technicals_record.json");
const LABELS = ["Strongly bearish", "Bearish", "Neutral", "Bullish", "Strongly bullish"];
const STEP = 5, WIN = 400, H = [10, 63];
const key = s => [...s].map(c => /[A-Za-z0-9]/.test(c) ? c : "_" + c.charCodeAt(0).toString(16)).join("");

export function summarise(samples) {
  /* samples: [{day, label, f10, f63}] -> per label and horizon: n, days, mean excess %, 95% interval, share beating the day's average */
  const out = {};
  for (const h of H) {
    const byDay = new Map();
    for (const s of samples) if (s["f" + h] != null) (byDay.get(s.day) || byDay.set(s.day, []).get(s.day)).push(s);
    const per = Object.fromEntries(LABELS.map(l => [l, { ex: [], beat: 0, n: 0 }]));
    for (const rows of byDay.values()) {
      if (rows.length < 50) continue;
      const avg = rows.reduce((a, r) => a + r["f" + h], 0) / rows.length;
      const g = {};
      for (const r of rows) { (g[r.label] ||= []).push(r["f" + h] - avg); }
      for (const [l, xs] of Object.entries(g)) { per[l].ex.push(xs.reduce((a, b) => a + b, 0) / xs.length); per[l].n += xs.length; per[l].beat += xs.filter(x => x > 0).length; }
    }
    out[h] = Object.fromEntries(LABELS.map(l => {
      const xs = per[l].ex, m = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
      const sd = xs.length > 1 ? Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1)) : null;
      const se = sd == null ? null : sd / Math.sqrt(xs.length) * Math.sqrt(h / STEP > 1 ? h / STEP : 1);   // overlapping windows: widen by sqrt(overlap)
      const r = v => v == null ? null : Math.round(v * 10000) / 100;
      return [l, { n: per[l].n, days: xs.length, mean_excess_pct: r(m), ci95_pct: se == null ? null : [r(m - 1.96 * se), r(m + 1.96 * se)], beat_avg_pct: per[l].n ? Math.round(per[l].beat / per[l].n * 1000) / 10 : null }];
    }));
  }
  return out;
}

export function verdict(rec) {
  /* Plain reading per label at 10 sessions: is the label's 95% interval clear of zero? */
  return Object.fromEntries(LABELS.map(l => {
    const x = rec[10][l];
    if (!x || !x.ci95_pct) return [l, "not measured"];
    if (x.ci95_pct[0] > 0) return [l, "did better than the average stock"];
    if (x.ci95_pct[1] < 0) return [l, "did worse than the average stock"];
    return [l, "no measurable difference from the average stock"];
  }));
}

function main() {
  const force = process.argv.includes("--force");
  try { const old = JSON.parse(fs.readFileSync(OUT, "utf8")); if (!force && Date.now() - Date.parse(old.created) < 28 * 864e5) { console.log(`technicals_record: fresh (${old.created}); nothing done`); return; } } catch (e) { /* none yet */ }
  const E = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "aladin_e", "latest.json"), "utf8"));
  const samples = []; let used = 0, first = null, last = null;
  for (const s of Object.keys(E.stocks || {})) {
    let d; try { d = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "terminal", "daily", key(s) + ".json"), "utf8")).d; } catch (e) { continue; }
    if (!d || d.length < WIN + 70) continue;
    used++;
    const bars = d.map(r => ({ o: r[1], h: r[2], l: r[3], c: r[4], v: r[5] }));
    for (let t = WIN - 1; t < d.length - 10; t += STEP) {
      const T = technicals(bars.slice(t - WIN + 1, t + 1)); if (!T) continue;
      const c0 = d[t][4]; if (!(c0 > 0)) continue;
      const f = h => t + h < d.length && d[t + h][4] > 0 ? d[t + h][4] / c0 - 1 : null;
      const f10 = f(10), f63 = f(63);
      if (Math.abs(f10) > 1.5 || (f63 != null && Math.abs(f63) > 3)) continue;     // a split or data error, not a market move
      samples.push({ day: d[t][0], label: T.all.label, f10, f63 });
      if (!first || d[t][0] < first) first = d[t][0]; if (!last || d[t][0] > last) last = d[t][0];
    }
  }
  if (!samples.length) { console.log("technicals_record: no price history on disk; nothing done"); return; }
  const rec = summarise(samples);
  const doc = { what: "Track record of the stock page's Technicals gauge: change over the next 10 and 63 trading days compared with the average sampled stock on the same day, by the gauge's label.",
    method: `model E's ${used} stocks with at least ${WIN + 70} sessions of prices; the label from the page's own code (chart-indicators.js) on the last ${WIN} sessions up to each close, every ${STEP}th session; 95% intervals from day-level averages, widened for overlapping windows. Before costs; companies listed today only.`,
    from: first, to: last, samples: samples.length, record: rec, verdict_10: verdict(rec), created: new Date().toISOString() };
  fs.writeFileSync(OUT, JSON.stringify(doc, null, 1));
  console.log(`technicals_record: ${samples.length} samples, ${used} stocks, ${first} to ${last}`);
  for (const l of LABELS) console.log(`  ${l.padEnd(17)} 10d ${JSON.stringify(rec[10][l])}  63d ${JSON.stringify(rec[63][l])}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
