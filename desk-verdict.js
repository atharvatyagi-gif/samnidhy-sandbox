/* "Three questions" box at the top of a stock's ALADIN & signals section (2026-11-15).
   The page used to stack verdicts that answer different questions over different time spans (the Technicals gauge, ALADIN 1's
   10-day chance of a rise, model E's 3-month rank), so a stock could read "Strongly bearish" next to "likely to rise". Here each
   view says what it answers, over what span, and how it did when tested; a view counts as a lean only when its tested record
   is measurably different from the average stock. Pure: inputs in, HTML out (tests/js/verdict.test.mjs). */

const pct1 = v => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
const pc0 = p => Math.round(p * 100) + "%";

/* Technicals gauge: its label and the record of that label (data/config/technicals_record.json, scripts/technicals_record.mjs). */
export function techLean(label, rec) {
  if (!label) return { lean: null, text: "Needs at least 60 days of prices." };
  const r = rec && rec.record && rec.record[10] && rec.record[10][label];
  if (!r || !r.ci95_pct) return { lean: null, label, text: `${label}. Its track record is not measured yet.` };
  const lean = r.ci95_pct[0] > 0 ? 1 : r.ci95_pct[1] < 0 ? -1 : 0;
  const what = lean > 0 ? "did slightly better than" : lean < 0 ? "did slightly worse than" : "did about the same as";
  return { lean, label, text: `Tested ${rec.from.slice(0, 4)}–${rec.to.slice(0, 4)}: stocks labelled "${label}" ${what} the average stock over the next 10 trading days (${pct1(r.mean_excess_pct)}, range ${pct1(r.ci95_pct[0])} to ${pct1(r.ci95_pct[1])}).` };
}

/* ALADIN 1 (earlier model): chance of a rise in h days and where it ranks today. A lean only in its top or bottom 10%, whose tested hit rates differ from normal. */
export function tenDayLean(v) {
  if (!v) return { lean: null, text: "Earlier model not loaded." };
  const tested = v.top != null && v.bottom != null && v.base != null
    ? ` Tested: in its top 10%, ${pc0(v.top)} rose; in its bottom 10%, ${pc0(v.bottom)}; any stock, ${pc0(v.base)}.` : "";
  if (v.rank == null) return { lean: null, text: `${pc0(v.p)} chance of a rise in ${v.h} days.${tested}` };
  const lean = v.rank >= 90 ? 1 : v.rank <= 10 ? -1 : 0;
  const where = lean > 0 ? "in its top 10% today" : lean < 0 ? "in its bottom 10% today" : `higher than ${v.rank}% of stocks today, outside its top and bottom 10%: no clear lean, about as likely to rise as any stock`;
  return { lean, text: `${pc0(v.p)} chance of a rise in ${v.h} days, ${where}.${tested}` };
}

/* Model E: rank and its rank group's tested 3-month record. The lean uses the group's AVERAGE lead over the average stock (the
   same yardstick as the Technicals record): every group beats the average stock less than half the time, because a few large
   gains carry the average, so "how often" alone would call even the best group negative. */
export function eLean(row, group, universe) {
  if (!row) return { lean: null, text: `Not ranked (model E ranks the ${universe || 500} most-traded stocks).` };
  const held = row[3] ? "In the portfolio" : "Not in the portfolio";
  const ci = group && group.mean_excess_ci95_pct;
  if (!ci || group.mean_excess_pct == null) return { lean: null, text: `${held}, rank ${row[0]} of ${universe}. Its group's record is not measured.` };
  const lean = ci[0] > 0 ? 1 : ci[1] < 0 ? -1 : 0;
  const what = lean > 0 ? "better than" : lean < 0 ? "worse than" : "about the same as";
  return { lean, text: `${held}, rank ${row[0]} of ${universe}. Tested 2010–2026: its rank group, ${group.label}, did ${what} the average stock over 3 months (${pct1(group.mean_excess_pct)} on average, range ${pct1(ci[0])} to ${pct1(ci[1])}), though it beat the average only ${pc0(group.beat_market)} of the time: a few large gains carry the average.` };
}

/* One plain sentence from the leans. views: [{name, span, lean}] with lean 1, -1, 0 or null (not measured). */
export function together(views) {
  const on = views.filter(v => v.lean === 1 || v.lean === -1);
  const word = l => l > 0 ? "a positive lean" : "a negative lean";
  if (!on.length) return "None of these shows a measurable lean today: treat it as an average stock for now.";
  if (on.every(v => v.lean === on[0].lean)) {
    const rest = views.filter(v => !on.includes(v) && v.lean === 0).map(v => v.name);
    return `${on.map(v => `${v.name} (${v.span})`).join(" and ")} show${on.length === 1 ? "s" : ""} ${word(on[0].lean)}${rest.length ? `; ${rest.join(" and ")} show${rest.length === 1 ? "s" : ""} none` : ""}.`;
  }
  const up = on.filter(v => v.lean > 0), dn = on.filter(v => v.lean < 0);
  return `They point different ways because they cover different time spans: ${up.map(v => `${v.name} (${v.span})`).join(" and ")} lean${up.length === 1 ? "s" : ""} positive, ${dn.map(v => `${v.name} (${v.span})`).join(" and ")} lean${dn.length === 1 ? "s" : ""} negative. Both can be true: a move over days and a trend over months can go opposite ways. ALADIN's main tested signal is model E (3 months).`;
}

export function verdictHtml({ sym, tech, techRec, e, ten }, esc) {
  const T = techLean(tech, techRec), X = tenDayLean(ten), E = e ? eLean(e.row, e.group, e.universe) : { lean: null, text: "Loading…" };
  const views = [
    { name: "the trend so far", span: "next 2 weeks", lean: T.lean, q: "Trend so far", sub: "Technicals gauge · describes the last 10–200 days", head: tech || "Not measured", t: T.text },
    { name: "ALADIN 1", span: "10 days", lean: X.lean, q: "Next 10 days", sub: "ALADIN 1 (earlier model) · chance the price rises", head: ten ? pc0(ten.p) : "Not loaded", t: X.text },
    { name: "model E", span: "3 months", lean: E.lean, q: "Next 3 months", sub: "Model E (ALADIN) · rank by 6-month gain", head: e && e.row ? (e.row[3] ? "In the portfolio" : "No signal") : "Not ranked", t: E.text },
  ];
  const cls = l => l > 0 ? "up" : l < 0 ? "down" : "";
  const tag = l => l === 1 ? "lean +" : l === -1 ? "lean −" : l === 0 ? "no lean" : "not measured";
  return `<div class="vx" data-sym="${esc(sym)}"><div class="sec-t">Three questions, three answers</div>
    <p class="note">These views answer different questions over different time spans, so they can disagree without either being wrong.</p>
    <div class="vx-rows">${views.map(v => `<div class="vx-r"><div class="vx-q"><b>${esc(v.q)}</b><small>${esc(v.sub)}</small></div>
      <div class="vx-a"><b class="${cls(v.lean)}">${esc(v.head)}</b><span class="vx-tag ${cls(v.lean)}">${tag(v.lean)}</span><p class="note">${esc(v.t)}</p></div></div>`).join("")}</div>
    <p class="vx-sum"><b>Read together:</b> ${esc(together(views))}</p>
    <p class="note">A lean means the view's tested record differs measurably from the average stock; it is small and often wrong. Educational analysis, not investment advice.</p></div>`;
}
