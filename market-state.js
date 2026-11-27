/* What the price file says versus what the exchange clock says. A price file that says "closed" but is old, while NSE is open by the clock,
   means the updates stopped: the page must say prices are not updating, never "Market closed" (found 27 Nov 2026).
   Same rule is copied inline in advanced.html (a classic script cannot import this); tests/js/market_state.test.mjs covers both. */
export const STALE_MIN = 25;        // a file older than this during market hours is not "current" (the live job runs every 5-15 min)
export const OPEN_FILE_STALE_MIN = 45;
const IST = "Asia/Kolkata";

export function clockOpen(date = new Date()) {
  const n = new Date(date.toLocaleString("en-US", { timeZone: IST })), m = n.getHours() * 60 + n.getMinutes();
  return n.getDay() >= 1 && n.getDay() <= 5 && m >= 555 && m <= 930;   // 09:15-15:30 IST, Mon-Fri (holidays: the file stays fresh and says closed)
}

/** -> { state: "open" | "delayed" | "stale" | "closed" | "unknown", ageMin } */
export function priceState(file, date = new Date()) {
  const t = file && file.generated_utc ? Date.parse(file.generated_utc) : NaN;
  if (!file || Number.isNaN(t)) return { state: "unknown", ageMin: null };
  const ageMin = Math.max(0, (date.getTime() - t) / 60000);
  if (file.market === "open") return { state: ageMin < OPEN_FILE_STALE_MIN ? "open" : "delayed", ageMin };
  if (clockOpen(date) && ageMin > STALE_MIN) return { state: "stale", ageMin };
  return { state: "closed", ageMin };
}
