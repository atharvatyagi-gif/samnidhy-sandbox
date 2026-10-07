/* advanced-fx.js: interaction layer for the Advanced page. Presentation only: it never changes a number, table, filter or fetch.
   The page re-renders parts of itself every minute, so everything here watches the regions and re-applies itself (idempotent).
   - Funnel: each step is focusable; hover / focus says how many stocks that step removed; click jumps to the matching rule or the shortlist.
   - Scrollspy on the top menu, scroll reveals on static blocks.
   - Price ticks: when a re-render changes a price, the cell flashes up / down (flat fill, sign and colour, never colour alone).
   - Matrix rows stay keyboard- and mouse-selectable exactly as before. */
(function () {
  "use strict";
  var reduce = window.FX ? window.FX.reduced : false;
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function safe(fn) { return function () { try { fn.apply(null, arguments); } catch (e) { if (window.console && console.warn) console.warn("advanced-fx:", e.message); } }; }
  function watchEl(el, fn) { if (!el || !window.MutationObserver) return; new MutationObserver(safe(fn)).observe(el, { childList: true, subtree: true }); fn(); }

  /* ---- funnel ---- */
  var cap;
  function funnel() {
    var box = $("#funnel"); if (!box) return;
    if (!cap) { cap = document.createElement("p"); cap.className = "f-cap"; cap.setAttribute("aria-live", "polite"); cap.textContent = "Hover or focus a step to see what it removes. Click to jump to its rule."; box.parentNode.insertBefore(cap, box.nextSibling); }
    var rows = $$(".f-row", box);
    rows.forEach(function (row, i) {
      if (row.__fx) return; row.__fx = true;
      var count = parseInt((row.querySelector(".f-count") || {}).textContent.replace(/[^0-9]/g, ""), 10);
      var step = (row.querySelector(".f-label") || {}).textContent || "";
      row.tabIndex = 0; row.setAttribute("role", "button");
      var say = function () {
        var prevRow = rows[i - 1], prev = prevRow ? parseInt(prevRow.querySelector(".f-count").textContent.replace(/[^0-9]/g, ""), 10) : null;
        cap.textContent = prev == null ? "Start: " + count + " stocks in the index." : (prev - count) + " dropped at this step (" + count + " remain): " + step + ".";
      };
      var go = function () {
        var target = i === rows.length - 1 ? $("#signals") : /F-Score/i.test(step) ? $(".rules .rule") : /Magic|rank/i.test(step) ? $$(".rules .rule")[1] : $(".rules");
        if (target) target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      };
      row.addEventListener("pointerenter", say); row.addEventListener("focus", say); row.addEventListener("click", go);
      row.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
  }

  /* ---- scrollspy for the top menu ---- */
  function spy() {
    var links = $$(".topnav a[href^='#']"), secs = links.map(function (a) { return $(a.getAttribute("href")); });
    if (!links.length || !window.IntersectionObserver) return;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) links.forEach(function (a) { var on = a.getAttribute("href") === "#" + e.target.id; if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); }); });
    }, { rootMargin: "-30% 0px -60% 0px" });
    secs.forEach(function (s) { if (s) io.observe(s); });
  }

  /* ---- price ticks on the shortlist table and the watch list ---- */
  var seen = {};
  function ticks() {
    $$("#matrix tbody tr[data-s]").forEach(function (tr) {
      var cell = tr.children[2]; if (!cell) return;
      var key = tr.dataset.s, now = cell.textContent.replace(/[^0-9.]/g, ""), was = seen[key];
      seen[key] = now;
      if (reduce || !was || was === now || !now) return;
      var up = parseFloat(now) > parseFloat(was);
      cell.classList.add(up ? "fx-tick-up" : "fx-tick-down");
      cell.setAttribute("title", (up ? "Up from " : "Down from ") + was);
      setTimeout(function () { cell.classList.remove("fx-tick-up", "fx-tick-down"); }, 1400);
    });
  }

  /* ---- reveals on static blocks ---- */
  function reveals() {
    if (!window.FX) return;
    $$(".block-head, .block-intro, .rules .rule, .climate > .card").forEach(function (n) { if (!n.hasAttribute("data-fx")) n.setAttribute("data-fx", "reveal"); });
    window.FX.init(document.body);
  }

  function start() {
    safe(reveals)(); safe(spy)();
    watchEl($("#funnel"), funnel);
    watchEl($("#matrix tbody"), ticks);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
