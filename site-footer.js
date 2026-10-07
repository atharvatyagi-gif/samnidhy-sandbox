/* site-footer.js: adds "Data last refreshed ..." (from status.json) to the footer a page already has.
   Paths come from this script's own URL, so it works from / , /days/ and under /samnidhy-sandbox/. Fails silently: the footer is complete without it. */
(function () {
  "use strict";
  var me = document.currentScript, src = me && me.src ? me.src : location.href;
  var base = src.replace(/[?#].*$/, "").replace(/[^/]*$/, "");
  function start() {
    var f = document.querySelector("footer"); if (!f || f.querySelector(".fx-refreshed")) return;
    fetch(base + "status.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (s) {
      if (!s || !s.last_success_ist) return;
      var n = document.createElement("span"); n.className = "fx-refreshed"; n.style.cssText = "display:block;margin-top:6px;font-variant-numeric:tabular-nums";
      n.textContent = "Data last refreshed " + s.last_success_ist; f.appendChild(n);
    }).catch(function () { /* no time shown */ });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
