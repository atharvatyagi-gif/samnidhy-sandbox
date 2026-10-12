/* Simple / Pro view, shared by every redesigned page.
   - A first-time visitor starts in Simple: plain words, the few numbers that matter, and "Show details" expanders (<details class="pro-more">)
     that open the professional detail in place. Nothing is hidden for good: every detail is one click away.
   - The switch (HyperUI toggle, MIT) moves to Pro: every expander opens, .pro-only blocks appear, .simple-only explanations step aside.
   - The choice is remembered in this browser only (localStorage, wrapped in try/catch: private windows simply start in Simple each time).
   The page sets <html data-ui-mode> before it paints with the one-line snippet in its <head>; this file wires the switch and the expanders. */
(function () {
  var KEY = "samnidhy-ui-mode", root = document.documentElement;
  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function save(m) { try { localStorage.setItem(KEY, m); } catch (e) { /* not remembered */ } }
  function apply(m) {
    root.setAttribute("data-ui-mode", m);
    document.querySelectorAll("details.pro-more").forEach(function (d) { d.open = m === "pro"; });
    document.querySelectorAll("[data-ui-switch]").forEach(function (box) { box.checked = m === "pro"; box.setAttribute("aria-checked", String(m === "pro")); });
    document.querySelectorAll("[data-ui-label]").forEach(function (el) { el.textContent = m === "pro" ? "Pro view" : "Simple view"; });
    try { window.dispatchEvent(new CustomEvent("uimodechange", { detail: m })); } catch (e) { /* old browser */ }
  }
  function init() {
    var first = !saved();
    if (first) root.setAttribute("data-first-visit", "");
    apply(saved() === "pro" ? "pro" : "simple");
    document.querySelectorAll("[data-ui-switch]").forEach(function (box) {
      box.addEventListener("change", function () { var m = box.checked ? "pro" : "simple"; save(m); apply(m); });
    });
    window.uiMode = function () { return root.getAttribute("data-ui-mode") || "simple"; };
    window.uiModeApply = function () { apply(window.uiMode()); };          // pages call this after they draw new expanders
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
