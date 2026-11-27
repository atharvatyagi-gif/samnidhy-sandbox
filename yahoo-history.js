/* Older chart history for the terminal's scroll-back, fetched when you scroll a chart back past what the site already has:
     5m = the last 60 days (Yahoo's limit for 5-minute candles) · 1h = up to 2 years · 1d = every day since listing (split-adjusted).
   Real Yahoo Finance candles (the same source the old GitHub "intraday" and "history" files were built from), passed through the
   site's own Cloudflare worker (blab-quotes) because a browser cannot call Yahoo directly. Nothing is stored; missing minutes stay missing. */
export const HIST_BASE = "https://blab-quotes.blab-cohort.workers.dev/yc/";
const ALLOWED = { "5m": ["60d"], "1h": ["730d", "365d", "180d"], "1d": ["all"] };     // must match the worker's list

export function histUrl(sym, interval, range = ALLOWED[interval]?.[0]) {
  if (!ALLOWED[interval] || !ALLOWED[interval].includes(range)) throw new Error(`not an allowed history request: ${interval} ${range}`);
  const ticker = sym.startsWith("^") ? sym : sym + ".NS";
  return `${HIST_BASE}${encodeURIComponent(ticker)}?i=${interval}&r=${range}`;
}

/** Yahoo chart reply -> [[time, o, h, l, c, v]]: time "YYYY-MM-DD HH:MM" IST (intraday, 09:15-15:29 only) or "YYYY-MM-DD" (daily). */
export function yahooRows(j, intraday) {
  const res = j && j.chart && j.chart.result && j.chart.result[0];
  const t = res && res.timestamp, q = res && res.indicators && res.indicators.quote && res.indicators.quote[0];
  if (!t || !t.length || !q) return [];
  const off = (res.meta && res.meta.gmtoffset) ?? 19800;
  let lastC = null;
  for (let i = t.length - 1; i >= 0 && lastC == null; i--) lastC = q.close[i];
  const nd = lastC != null && lastC < 1 ? 4 : 2, r = x => +x.toFixed(nd);
  const out = [], seen = new Map();
  for (let i = 0; i < t.length; i++) {
    const o = q.open[i], h = q.high[i], l = q.low[i], c = q.close[i];
    if (o == null || h == null || l == null || c == null) continue;
    const iso = new Date((t[i] + off) * 1000).toISOString(), day = iso.slice(0, 10), hm = iso.slice(11, 16);
    const row = [intraday ? `${day} ${hm}` : day, r(o), r(h), r(l), r(c), Math.round(q.volume[i] || 0)];
    if (intraday) {
      const m = +hm.slice(0, 2) * 60 + +hm.slice(3);
      if (m >= 555 && m <= 929) out.push(row);
    } else if (seen.has(day)) out[seen.get(day)] = row;              // Yahoo sends today's live row next to today's candle
    else { seen.set(day, out.length); out.push(row); }
  }
  return out;
}
