/* transitions.js: page-to-page transitions.
   Browsers with cross-document View Transitions (site.css has @view-transition) get a short cross-fade for free.
   Others get the circular curtain growing from the click point, then the page opens.
   Never intercepts new-tab / modified clicks / downloads / hash links / other sites, never delays navigation more than 700 ms, and is off for reduced motion.
   Opt a link out with data-no-transition. */
(function () {
  "use strict";
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (window.CSSViewTransitionRule || (window.CSS && CSS.supports && CSS.supports("selector(:root)") && "onpagereveal" in window)) return;   // native cross-fade handles it
  var curtain;
  function make() { curtain = document.createElement("div"); curtain.className = "fx-curtain"; curtain.setAttribute("aria-hidden", "true"); document.body.appendChild(curtain); return curtain; }
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || a.target === "_blank" || a.hasAttribute("download") || a.hasAttribute("data-no-transition")) return;
    var u; try { u = new URL(a.href, location.href); } catch (x) { return; }
    if (u.origin !== location.origin || !/^https?:$/.test(u.protocol)) return;
    if (u.pathname === location.pathname && u.search === location.search) return;       // same page / hash link
    e.preventDefault();
    var c = curtain || make();
    c.style.setProperty("--cx", e.clientX + "px"); c.style.setProperty("--cy", e.clientY + "px");
    void c.offsetWidth; c.classList.add("go");
    var done = false, go = function () { if (done) return; done = true; location.href = a.href; };
    c.addEventListener("transitionend", go, { once: true });
    setTimeout(go, 460);                                                                  // always well under 700 ms
  });
  window.addEventListener("pageshow", function (e) { if (e.persisted && curtain) curtain.classList.remove("go"); });   // back/forward from the cache
})();
