/* fx.js: small, dependency-free effects, switched on per element with data-fx="...".
   reveal | stagger | split | count | draw | tilt | magnetic | spotlight | marquee | parallax | progress
   - Progressive enhancement: with reduced motion or without JS everything stays visible; "count" still shows the real value.
   - One shared requestAnimationFrame loop; effects pause off-screen and while the tab is hidden.
   - Idempotent: FX.init(root) can run twice. One failing effect never stops the others.
   Add a new effect: FX.register("name", el => { ...; return cleanup? }) and put data-fx="name" on the element. */
(function () {
  "use strict";
  var root = document.documentElement;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  if (!reduce) root.classList.add("motion");

  var effects = {}, loop = [], raf = 0;
  function frame(t) {
    raf = 0;
    if (document.hidden) return;
    for (var i = 0; i < loop.length; i++) { try { loop[i](t); } catch (e) { /* one bad effect must not stop the rest */ } }
    if (loop.length) raf = requestAnimationFrame(frame);
  }
  function addTick(fn) { if (loop.indexOf(fn) < 0) loop.push(fn); if (!raf) raf = requestAnimationFrame(frame); }
  function dropTick(fn) { var i = loop.indexOf(fn); if (i >= 0) loop.splice(i, 1); }
  document.addEventListener("visibilitychange", function () { if (!document.hidden && loop.length && !raf) raf = requestAnimationFrame(frame); });

  var io = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      var el = e.target, cb = el.__fxIn;
      if (e.isIntersecting) { if (cb) cb(true); if (el.__fxOnce) io.unobserve(el); } else if (cb && !el.__fxOnce) cb(false);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 }) : null;
  function watch(el, cb, once) { el.__fxIn = cb; el.__fxOnce = !!once; if (io) io.observe(el); else cb(true); }
  function enter(el) { el.classList.remove("fx-pre"); el.classList.add("fx-in"); }
  function below(el) { var r = el.getBoundingClientRect(); return r.top > window.innerHeight * 0.92; }

  function reveal(el) { if (reduce) return; if (below(el)) el.classList.add("fx-pre"); watch(el, function () { enter(el); }, true); }
  effects.reveal = reveal;
  effects.stagger = function (el) { if (reduce) return; Array.prototype.forEach.call(el.children, function (c, i) { c.style.setProperty("--i", i); }); reveal(el); };

  effects.split = function (el) {
    if (el.__fxSplit) return; el.__fxSplit = true;
    var text = el.textContent.trim(); if (!text) return;
    el.setAttribute("aria-label", text);
    el.textContent = "";
    text.split(/\s+/).forEach(function (w, i) {
      var o = document.createElement("span"), n = document.createElement("span");
      o.className = "fx-w"; o.setAttribute("aria-hidden", "true"); o.style.setProperty("--i", i);
      n.textContent = w; o.appendChild(n); el.appendChild(o); el.appendChild(document.createTextNode(" "));
    });
    reveal(el);
  };

  effects.count = function (el) {
    var to = parseFloat(el.getAttribute("data-count")); if (!isFinite(to)) return;
    var dec = parseInt(el.getAttribute("data-decimals") || "0", 10), pre = el.getAttribute("data-prefix") || "", suf = el.getAttribute("data-suffix") || "";
    var fmt = function (v) { return pre + v.toLocaleString("en-IN", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + suf; };
    el.textContent = fmt(to);                       // the real value is always what is in the page
    if (reduce) return;
    watch(el, function () {
      var t0 = 0, dur = 1100;
      var step = function (t) {
        if (!t0) t0 = t; var p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
        el.textContent = fmt(to * e);
        if (p >= 1) { el.textContent = fmt(to); dropTick(step); }
      };
      addTick(step);
    }, true);
  };

  effects.draw = function (el) {
    if (reduce || !el.getTotalLength) return;
    try { el.style.setProperty("--len", Math.ceil(el.getTotalLength())); } catch (e) { return; }
    if (below(el)) el.classList.add("fx-pre");
    watch(el, function () { enter(el); }, true);
  };

  effects.tilt = function (el) {
    if (reduce || !fine) return;
    var max = parseFloat(el.getAttribute("data-tilt")) || 4;
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      el.classList.add("fx-live");
      el.style.transform = "perspective(900px) rotateX(" + (-y * max).toFixed(2) + "deg) rotateY(" + (x * max).toFixed(2) + "deg)";
    });
    el.addEventListener("pointerleave", function () { el.classList.remove("fx-live"); el.style.transform = ""; });
  };

  effects.magnetic = function (el) {
    if (reduce || !fine) return;
    var pull = parseFloat(el.getAttribute("data-magnetic")) || 8;
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect(), x = (e.clientX - r.left - r.width / 2) / r.width, y = (e.clientY - r.top - r.height / 2) / r.height;
      el.classList.add("fx-live"); el.style.transform = "translate(" + (x * pull).toFixed(1) + "px," + (y * pull).toFixed(1) + "px)";
    });
    el.addEventListener("pointerleave", function () { el.classList.remove("fx-live"); el.style.transform = ""; });
  };

  effects.spotlight = function (el) {
    if (!fine) return;
    el.addEventListener("pointermove", function (e) { var r = el.getBoundingClientRect(); el.style.setProperty("--mx", (e.clientX - r.left) + "px"); });
  };

  effects.marquee = function (el) {
    if (el.__fxMq) return; el.__fxMq = true;
    var track = el.querySelector(".fx-marquee-track"); if (!track) return;
    Array.prototype.slice.call(track.children).forEach(function (c) { var k = c.cloneNode(true); k.setAttribute("aria-hidden", "true"); track.appendChild(k); });
    var secs = parseFloat(el.getAttribute("data-speed")); if (secs) el.style.setProperty("--fx-speed", secs + "s");
    if (reduce) { el.classList.add("fx-off"); return; }
    watch(el, function (on) { el.classList.toggle("fx-off", !on); }, false);
  };

  effects.parallax = function (el) {
    if (reduce) return;
    var k = parseFloat(el.getAttribute("data-speed")) || 0.15, on = false;
    var tick = function () { if (!on) return; var r = el.parentNode.getBoundingClientRect(); el.style.transform = "translate3d(0," + ((r.top + r.height / 2 - innerHeight / 2) * -k).toFixed(1) + "px,0)"; };
    watch(el, function (v) { on = v; if (v) addTick(tick); else dropTick(tick); }, false);
  };

  effects.progress = function (el) {
    var tick = function () { var h = root.scrollHeight - innerHeight; el.style.transform = "scaleX(" + (h > 0 ? Math.min(1, scrollY / h) : 0).toFixed(4) + ")"; };
    addEventListener("scroll", tick, { passive: true }); addEventListener("resize", tick, { passive: true }); tick();
  };

  function init(scope) {
    scope = scope || document;
    Array.prototype.forEach.call(scope.querySelectorAll("[data-fx]"), function (el) {
      if (el.__fxDone) return;
      el.__fxDone = true;
      (el.getAttribute("data-fx") || "").split(/\s+/).forEach(function (name) {
        var fn = effects[name]; if (!fn) return;
        try { fn(el); } catch (e) { if (window.console && console.warn) console.warn("fx:", name, e.message); }
      });
    });
  }
  window.FX = { init: init, register: function (n, f) { effects[n] = f; }, tick: addTick, untick: dropTick, reduced: reduce };

  function start() { init(document); root.classList.add("fx-ready"); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
