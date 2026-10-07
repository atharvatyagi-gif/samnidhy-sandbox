/* landing-fx.js: real-data scenes for the landing page (loads after fx.js and landing.js).
   Reads live.json, screener.json and days.json. Every scene keeps its static HTML as a fallback if a file is missing.
   No invented numbers: figures come from the site's own published files. */
(function () {
  "use strict";
  var reduce = window.FX ? window.FX.reduced : false;
  function $(s, r) { return (r || document).querySelector(s); }
  function get(url) { return fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(url); return r.json(); }); }
  var ENT = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return ENT[c]; }); }
  var nf = function (v, d) { return Number(v).toLocaleString("en-IN", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }); };
  function safe(fn) { return function (x) { try { fn(x); } catch (e) { if (window.console && console.warn) console.warn("landing-fx:", e.message); } }; }

  /* ---- 1. index tape (hero bottom) + the candle field, both from live.json ---- */
  var live = get("live.json").catch(function () { return null; });
  live.then(safe(function (d) {
    if (!d || !d.markets || !d.markets.length) return;
    var hero = $("#hero"), tape = document.createElement("div");
    tape.className = "fx-marquee hero-tape"; tape.setAttribute("data-fx", "marquee"); tape.setAttribute("data-speed", "70");
    tape.setAttribute("role", "region"); tape.setAttribute("aria-label", "Market tape, as of " + (d.generated_ist || ""));
    var track = document.createElement("div"); track.className = "fx-marquee-track";
    d.markets.forEach(function (m) {
      var up = m.change_pct >= 0, s = document.createElement("span"); s.className = "fx-marquee-item";
      s.innerHTML = "<b>" + esc(m.name) + "</b>" + nf(m.value, 2) + ' <span class="' + (up ? "fx-up" : "fx-down") + '">' + (up ? "▲ +" : "▼ −") + Math.abs(m.change_pct).toFixed(2) + "%</span>";
      track.appendChild(s);
    });
    var asof = document.createElement("span"); asof.className = "fx-marquee-item"; asof.textContent = "as of " + (d.generated_ist || ""); track.appendChild(asof);
    tape.appendChild(track); hero.appendChild(tape);
    if (window.FX) window.FX.init(hero);
    candleField(hero, d.markets);
  }));

  function candleField(hero, markets) {
    if (reduce || !window.FX) return;
    var cv = document.createElement("canvas"); cv.className = "hero-canvas"; cv.setAttribute("aria-hidden", "true");
    $(".layer-back", hero).appendChild(cv);
    var ctx = cv.getContext("2d"); if (!ctx) return;
    var series = markets.filter(function (m) { return m.spark && m.spark.length > 10; }).map(function (m) { return m.spark; });
    if (!series.length) return;
    var W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 1.5), px = -999, py = -999, off = 0, last = 0;
    function size() { var r = cv.getBoundingClientRect(); W = r.width; H = r.height; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); }
    size(); addEventListener("resize", size, { passive: true });
    hero.addEventListener("pointermove", function (e) { var r = cv.getBoundingClientRect(); px = e.clientX - r.left; py = e.clientY - r.top; }, { passive: true });
    hero.addEventListener("pointerleave", function () { px = py = -999; });
    var step = 26, bodyW = 8;
    var range = series.map(function (s) { return [Math.min.apply(null, s), Math.max.apply(null, s)]; });      // computed once, not per candle per frame
    function draw(t) {
      if (t - last < 42) return; last = t;                       // about 24 fps is plenty for a background
      off += 0.35;
      ctx.clearRect(0, 0, W, H);
      var n = Math.ceil(W / step) + 2, base = Math.floor(off / step);
      for (var i = 0; i < n; i++) {
        var idx = i + base, s = series[Math.floor(idx / 60) % series.length], k = idx % (s.length - 1);
        var a = s[k], b = s[k + 1], rg = range[Math.floor(idx / 60) % series.length], lo = rg[0], hi = rg[1], span = hi - lo || 1;
        var y1 = H * (0.82 - 0.55 * (a - lo) / span), y2 = H * (0.82 - 0.55 * (b - lo) / span);
        var x = i * step - (off % step), up = b >= a, dx = x - px, dy = (y1 + y2) / 2 - py, near = Math.sqrt(dx * dx + dy * dy) < 130;
        ctx.globalAlpha = near ? 0.55 : 0.2; ctx.strokeStyle = ctx.fillStyle = up ? "#22c55e" : "#ef4444";
        ctx.beginPath(); ctx.moveTo(x, Math.min(y1, y2) - 10); ctx.lineTo(x, Math.max(y1, y2) + 10); ctx.stroke();
        ctx.fillRect(x - bodyW / 2, Math.min(y1, y2), bodyW, Math.max(2, Math.abs(y2 - y1)));
      }
      ctx.globalAlpha = 1;
    }
    var start = function () { new IntersectionObserver(function (es) { if (es[0].isIntersecting) window.FX.tick(draw); else window.FX.untick(draw); }).observe(hero); };
    if (window.requestIdleCallback) requestIdleCallback(function () { setTimeout(start, 600); }, { timeout: 2500 }); else setTimeout(start, 1500);   // after the page has settled
  }

  /* ---- 2. the real funnel + a real NIFTY 50 line in the showcase device ---- */
  Promise.all([get("screener.json").catch(function () { return null; }), live]).then(safe(function (r) {
    var sc = r[0], d = r[1], box = $(".mini-funnel");
    if (sc && sc.funnel && sc.funnel.length && box) {
      var top = sc.funnel[0].count || 1, cap = $(".funnel-cap");
      box.innerHTML = "";
      sc.funnel.forEach(function (f, i) {
        var row = document.createElement("div"); row.tabIndex = 0;
        row.style.setProperty("--w", Math.max(4, Math.round(100 * f.count / top)) + "%");
        if (i === sc.funnel.length - 1) row.className = "last";
        row.innerHTML = "<b>" + nf(f.count) + "</b><span>" + esc(f.step) + "</span>";
        var show = function () { if (cap) cap.textContent = i === 0 ? "Start: " + nf(f.count) + " stocks in the index." : nf(sc.funnel[i - 1].count - f.count) + " dropped at this step: " + f.step + "."; };
        row.addEventListener("pointerenter", show); row.addEventListener("focus", show);
        box.appendChild(row);
      });
      var cards = document.querySelectorAll(".num-card b");
      if (cards[0]) { cards[0].dataset.count = sc.funnel[0].count; cards[0].textContent = nf(sc.funnel[0].count); }
      var kept = (sc.picks || []).length || sc.funnel[sc.funnel.length - 1].count;
      if (cards[1]) { cards[1].dataset.count = kept; cards[1].textContent = nf(kept); }
      if (window.ScrollTrigger) window.ScrollTrigger.refresh();
    }
    if (sc && sc.fscore_counts) trySlider(sc);
    var nifty = d && d.markets && d.markets.filter(function (m) { return m.ticker === "^NSEI"; })[0];
    if (nifty && nifty.spark && nifty.spark.length > 5) {
      var s = nifty.spark, ref = s.concat(nifty.sma200 ? [nifty.sma200] : []);
      var lo = Math.min.apply(null, ref), hi = Math.max.apply(null, ref), sp = hi - lo || 1;
      var X = function (i) { return (i / (s.length - 1) * 300).toFixed(1); }, Y = function (v) { return (110 - 100 * (v - lo) / sp).toFixed(1); };
      var line = s.map(function (v, i) { return (i ? "L" : "M") + X(i) + "," + Y(v); }).join(" ");
      var l = $(".mc-line"), a = $(".mc-area"), avg = $(".mc-avg");
      if (l) l.setAttribute("d", line);
      if (a) a.setAttribute("d", line + " L300,120 L0,120 Z");
      if (avg && nifty.sma200) avg.setAttribute("d", "M0," + Y(nifty.sma200) + " L300," + Y(nifty.sma200));
      var mc = $(".mini-chart");
      if (mc && !$(".chart-cap", mc)) { var p = document.createElement("p"); p.className = "chart-cap"; p.textContent = "Nifty 50, last " + s.length + " sessions, with its 200-day average (dashed). " + (d.generated_ist || ""); mc.appendChild(p); }
    }
  }));


  /* ---- "Try the screen": real F-Score counts from screener.json (hidden when the file does not carry them yet) ---- */
  function trySlider(sc) {
    var sec = $("#try"), range = $("#try-range"); if (!sec || !range) return;
    var counts = sc.fscore_counts, total = 0, i;
    for (i = 0; i < 10; i++) total += counts[String(i)] || 0;
    if (!total) return;
    var rule = sc.rules && sc.rules.min_fscore != null ? sc.rules.min_fscore : 6;
    range.value = rule; sec.hidden = false;
    var out = $("#try-out"), fill = $("#try-fill"), kEl = $("#try-k");
    function paint() {
      var k = +range.value, keep = 0, j;
      for (j = k; j < 10; j++) keep += counts[String(j)] || 0;
      kEl.textContent = k; fill.style.transform = "scaleX(" + (keep / total).toFixed(3) + ")";
      range.setAttribute("aria-valuetext", "minimum F-Score " + k + ": " + keep + " of " + total + " stocks stay");
      out.textContent = nf(keep) + " of " + nf(total) + " stocks stay in at an F-Score of " + k + " or more" + (k === rule ? " (the screen's own rule)." : ".");
    }
    range.addEventListener("input", paint); paint();
    if (window.ScrollTrigger) window.ScrollTrigger.refresh();
  }

  /* ---- 3. numbers: sessions saved in the archive (days.json) ---- */
  get("days.json").then(safe(function (days) {
    var n = document.querySelectorAll(".num-card")[3];
    if (!n || !days.length) return;
    var b = $("b", n); b.dataset.count = days.length; b.textContent = nf(days.length);
    $("span", n).textContent = "past sessions saved in the archive";
  })).catch(function () { /* keep the fallback card */ });

  /* ---- 4. device tilt follows the cursor (inner screen, so it never fights the scroll animation on the device) ---- */
  var scr = $(".device-screen");
  if (scr && window.FX) { scr.setAttribute("data-fx", "tilt"); scr.setAttribute("data-tilt", "2.5"); window.FX.init(scr.parentNode); }
})();
