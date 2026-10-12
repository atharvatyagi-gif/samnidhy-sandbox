/* Home page data: the four market numbers (live.json), when the data last updated (status.json), when the screen last ran (screener.json),
   and the phone menu. Every value is the published one; a missing value stays "--" with the reason, nothing is guessed. */
(function () {
  var up = "text-green-400", down = "text-red-400";
  function get(f) { return fetch(f, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(f + " " + r.status); return r.json(); }); }
  function fmt(v, unit) {
    if (v == null || isNaN(v)) return "--";
    var d = unit === "pts" && v > 1000 ? 0 : 2;
    return Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function ago(iso) {
    var m = (Date.now() - new Date(iso).getTime()) / 60000;
    if (!isFinite(m)) return "";
    return m < 2 ? "just now" : m < 90 ? Math.round(m) + " minutes ago" : m < 48 * 60 ? Math.round(m / 60) + " hours ago" : Math.round(m / 1440) + " days ago";
  }

  get("live.json").then(function (L) {
    var byT = {}; (L.markets || []).forEach(function (m) { byT[m.ticker] = m; });
    document.querySelectorAll("[data-mkt]").forEach(function (el) {
      var m = byT[el.getAttribute("data-mkt")], v = el.querySelector("[data-v]"), c = el.querySelector("[data-c]");
      if (!m || m.value == null) { v.textContent = "--"; c.textContent = "not available right now"; return; }
      v.textContent = fmt(m.value, m.unit);
      if (m.change_pct != null) {
        var p = m.change_pct, s = (p > 0 ? "▲ +" : p < 0 ? "▼ " : "") + p.toFixed(2) + "%";
        c.textContent = s; c.className = "block text-base font-semibold " + (p > 0 ? up : p < 0 ? down : "text-gray-400");
        c.setAttribute("aria-label", (p >= 0 ? "up " : "down ") + Math.abs(p).toFixed(2) + " percent since the previous close");
      }
    });
    var t = document.getElementById("mkt-asof");
    if (t) t.textContent = "Prices as of " + (L.generated_ist || "--") + (L.generated_utc ? " (" + ago(L.generated_utc) + ")" : "") + ". Market " + (L.market || "status unknown") + ".";
  }).catch(function () {
    var t = document.getElementById("mkt-asof"); if (t) t.textContent = "The latest prices could not be loaded. Please try again in a minute.";
  });

  get("status.json").then(function (s) {
    var el = document.getElementById("data-fresh");
    if (el && s.last_success_ist) el.textContent = "Last full update: " + s.last_success_ist + (s.session_date ? " · trading day " + s.session_date : "") + ".";
  }).catch(function () { /* the line simply stays empty */ });

  get("screener.json").then(function (s) {
    var el = document.getElementById("screen-asof");
    if (el && s.generated_ist) el.textContent = "Last screen run: " + s.generated_ist + " · " + ((s.picks || []).length) + " companies.";
  }).catch(function () { /* optional */ });

  var btn = document.getElementById("MenuButton"), menu = document.getElementById("MobileMenu");
  if (btn && menu) btn.addEventListener("click", function () {
    var open = menu.classList.toggle("hidden") === false; btn.setAttribute("aria-expanded", String(open));
  });
})();
