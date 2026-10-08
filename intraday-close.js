/* The delayed intraday feed (Yahoo 5-minute candles) stops at about 15:10 to 15:15 IST, so the last 15 to 20 minutes of every session are missing from the intraday charts.
   After the close, NSE's official end-of-day row for the SAME session is real data: it gives the closing price, the day's high and low and the full-day volume.
   From it ONE closing candle is completed and labelled "close (NSE official)". The rest of the chart is untouched, nothing is smoothed, and the daily chart never uses this.
   - the close is NSE's official close;
   - the volume is NSE's full-day volume minus what the feed already counted;
   - the high / low are NOT taken from NSE's day range (the feed and NSE differ by a few paise on the morning's high, which would draw a false spike): they only cover the move from the last price the feed saw to the official close.
   bars: [{time (IST wall clock as UTC seconds), o, h, l, c, v, day, lbl}] sorted; u: the stock's NSE end-of-day row; meta: the live-quote metadata; s: candle length in seconds. */
export function withOfficialClose(bars, u, meta, s) {
  const last = bars && bars[bars.length - 1];
  if (!u || !last || !meta || meta.market !== "closed" || u.date !== meta.session_date || u.c == null || !(s > 0) || s >= 3600) return bars;
  const day = new Date(last.time * 1000).toISOString().slice(0, 10); if (day !== u.date) return bars;
  const today = bars.filter(b => b.day === day);
  const slot = Math.floor(last.time / 86400) * 86400 + (15 * 60 + 30) * 60 - s;                 // the last candle slot of the session
  const seen = today.reduce((a, b) => a + (b.v || 0), 0), rest = Math.max(0, (u.v || 0) - seen), c = u.c;
  if (last.time >= slot) {
    if (last.c === c && !rest) return bars;
    const b = { ...last, c, h: Math.max(last.h, c), l: Math.min(last.l, c), v: (last.v || 0) + rest };
    if (!String(b.lbl || "").includes("NSE official")) b.lbl = (b.lbl || "") + " · close (NSE official)";
    return [...bars.slice(0, -1), b];
  }
  const o = last.c, t = new Date(slot * 1000).toISOString();
  return [...bars, { time: slot, o, h: Math.max(o, c), l: Math.min(o, c), c, v: rest, day, lbl: `${t.slice(0, 10)} ${t.slice(11, 16)} · close (NSE official)` }];
}
