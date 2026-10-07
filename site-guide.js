/* site-guide.js: the beginner-friendly layer for the public pages (landing, main, archive days, Advanced). Presentation only: it reads what is on the page,
   never changes data, charts, tables or fetches. The expert terminal has its own version (terminal-guide.js) that shares glossary.js.
   - Plain-words tooltips: key words get a dotted underline and explain themselves on hover / focus.
   - A searchable Glossary and a short guided tour for each page (arrow keys, Esc skips).
   - On Advanced: an "In plain English" summary of the selected stock, written from the page's own data. Educational wording only, never advice. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); }, $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var G = window.BLabGlossary || [];
  var page = document.documentElement.getAttribute("data-guide") || "";
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function safe(fn) { return function () { try { return fn.apply(null, arguments); } catch (e) { if (window.console && console.warn) console.warn("site-guide:", e.message); } }; }
  var ENT = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return ENT[c]; }); }
  function gi(title) { for (var i = 0; i < G.length; i++) if (G[i][0] === title) return i; return -1; }

  /* ---------------- tooltip ---------------- */
  var tip;
  function showTip(el) {
    var i = +el.getAttribute("data-gl-i"); if (!G[i]) return;
    if (!tip) { tip = document.createElement("div"); tip.className = "sg-tip"; tip.id = "sg-tip"; tip.setAttribute("role", "tooltip"); document.body.appendChild(tip); }
    tip.innerHTML = "<b>" + esc(G[i][0]) + "</b>" + esc(G[i][2]); tip.hidden = false;
    var r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8), y = r.bottom + 8; if (y + h > innerHeight - 8) y = Math.max(8, r.top - h - 8);
    tip.style.left = x + "px"; tip.style.top = y + "px"; el.setAttribute("aria-describedby", "sg-tip");
  }
  function hideTip() { if (tip) tip.hidden = true; }
  document.addEventListener("pointerover", function (e) { var el = e.target.closest && e.target.closest("[data-gl]"); if (el) showTip(el); });
  document.addEventListener("pointerout", function (e) { if (e.target.closest && e.target.closest("[data-gl]")) hideTip(); });
  document.addEventListener("focusin", function (e) { var el = e.target.closest && e.target.closest("[data-gl]"); if (el) showTip(el); });
  document.addEventListener("focusout", hideTip); addEventListener("scroll", hideTip, { passive: true, capture: true });

  /* ---------------- marking: labels (re-scanned) and prose (first mention of each word, once) ---------------- */
  var LABELS = "th, .chip, .kv span, .tile h4, .tile .t, h4, .sub-h, .stat-label, .mb-sub, dt, .grp-chip, .pill";
  function scanLabels() {
    $$(LABELS, $("main") || document).forEach(function (el) {
      if (el.hasAttribute("data-gl") || el.closest(".sg-modal,.sg-pop")) return;
      var t = (el.textContent || "").replace(/\s+/g, " ").trim(); if (!t || t.length > 52 || /^[\d\s.,+\-−%₹:()/]+$/.test(t)) return;
      for (var i = 0; i < G.length; i++) if (G[i][1].test(t)) { el.setAttribute("data-gl", "1"); el.setAttribute("data-gl-i", i); return; }
    });
  }
  var PROSE = [[/F-Score/, "F-Score"], [/Magic Formula/, "Magic Formula (ROC and earnings yield)"], [/India VIX|\bVIX\b/, "India VIX"], [/\bFII\b|\bDII\b/, "FII / DII"], [/NIFTY 500|NIFTY 50\b/, "NIFTY 50 / NIFTY 500"],
    [/200-day (trend|average)|moving average/i, "Moving average (SMA / EMA)"], [/\bP\/E\b/, "P/E ratio"], [/market cap/i, "Market cap"], [/order book/i, "Order book"], [/bid-ask spread|\bspread\b/i, "Bid and ask (spread)"],
    [/market order/i, "Market order"], [/\bSIP\b/, "SIP"], [/compounding/i, "Compounding"], [/volatility/i, "Volatility"], [/earnings yield/i, "Magic Formula (ROC and earnings yield)"], [/momentum/i, "Momentum (12-1)"],
    [/\bliquid\b/i, "Liquidity (liquid)"], [/top gainers?/i, "Top gainers and losers"], [/closing price/i, "Closing price"], [/consensus/i, "Consensus (analysts)"], [/\bRSI\b/, "RSI"], [/diversif/i, "Diversification"], [/drawdown/i, "Risk and return"]];
  var PROSE_BOX = "main p, main li, main .block-intro, main .section-intro, main .caption, .showcase-copy h2, .pillar p, .day-list p, .try-lead, .hero-sub, .lede, .rule p";
  function markProse() {
    var done = {};
    $$(PROSE_BOX).forEach(function (box) {
      if (box.closest("a, button, dl, .glossary, .sg-modal, [data-gl], nav")) return;
      var walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT, null), nodes = [], n;
      while ((n = walker.nextNode())) { if (!n.parentNode.closest("a, button, [data-gl], script, style, b[id], span[id]")) nodes.push(n); }
      nodes.forEach(function (node) {
        PROSE.forEach(function (p) {
          var idx = gi(p[1]); if (idx < 0 || done[idx] || !node.parentNode) return;
          var m = p[0].exec(node.nodeValue); if (!m) return;
          var after = node.splitText(m.index), rest = after.splitText(m[0].length), span = document.createElement("span");
          span.setAttribute("data-gl", "1"); span.setAttribute("data-gl-i", idx); span.tabIndex = 0; span.textContent = m[0];
          after.parentNode.replaceChild(span, after); done[idx] = true;
        });
      });
    });
  }

  /* ---------------- glossary dialog ---------------- */
  var dlg;
  function buildDialog() {
    dlg = document.createElement("div"); dlg.className = "sg-modal"; dlg.hidden = true;
    dlg.innerHTML = '<div class="sg-box" role="dialog" aria-modal="true" aria-label="Glossary: what the words mean"><div class="sg-head"><b>Glossary: what the words mean</b><button type="button" class="sg-btn" data-close>Close</button></div>' +
      '<div class="sg-body"><input type="search" id="sg-q" placeholder="Search a word, e.g. P/E, volume, F-Score" aria-label="Search the glossary"><div id="sg-list"></div></div></div>';
    document.body.appendChild(dlg);
    var list = $("#sg-list", dlg), q = $("#sg-q", dlg);
    function paint() { var f = q.value.trim().toLowerCase(); list.innerHTML = G.filter(function (g) { return !f || (g[0] + " " + g[2]).toLowerCase().indexOf(f) >= 0; }).map(function (g) { return "<dl><dt>" + esc(g[0]) + "</dt><dd>" + esc(g[2]) + "</dd></dl>"; }).join("") || '<p class="sg-mut">No match. Try a shorter word.</p>'; }
    q.addEventListener("input", paint); paint();
    dlg.addEventListener("click", function (e) { if (e.target === dlg || e.target.hasAttribute("data-close")) closeDialog(); });
  }
  function openDialog(term) { if (!dlg) buildDialog(); dlg.hidden = false; var q = $("#sg-q"); q.value = term || ""; q.dispatchEvent(new Event("input")); q.focus(); }
  function closeDialog() { if (dlg) dlg.hidden = true; }
  addEventListener("keydown", function (e) { if (e.key === "Escape" && dlg && !dlg.hidden) { e.stopImmediatePropagation(); e.preventDefault(); closeDialog(); } }, true);

  /* ---------------- tours ---------------- */
  var TOURS = {
    landing: [[".hero-tape", "The market tape", "Today's values for India's main indices and a few world markers. A green ▲ means up, a red ▼ means down. Hover to pause it."],
      ["#device", "The daily screen", "Every day, India's 500 large companies pass through filters. Hover or focus a step to see how many stocks it removes."],
      ["#pillars", "What the Cohort does", "Four ways to look at the same market, from simple to advanced: Screen, Signal, Context and Terminal."],
      ["#day", "When things update", "The real times the data refreshes during the day."],
      ["#enter", "Step inside", "The main page teaches the market with six short lessons on real data. No finance knowledge needed."]],
    main: [[".site-header", "Lessons menu", "Six short lessons built from the last trading session's biggest risers and fallers. Jump to any of them."],
      ["#movers-board", "Today's movers", "The stocks that rose and fell the most in the last session, and by how much."],
      [".fx-scrub", "Travel back in time", "Every saved day is one tap away. The left and right arrow keys step through the days."],
      ["#section-1", "Lesson 1", "Try a pretend order book to see why prices move. Words with a dotted underline explain themselves."],
      ["#past", "Past sessions", "Every earlier day, with its own set of lessons."]],
    advanced: [["#weather", "Market weather", "The conditions every stock is trading in today: the overall trend, how many stocks are rising, how nervous traders are."],
      ["#funnel", "The screen", "Each row removes stocks that fail a test. Hover a row to see how many it removes; click it to jump to its rule."],
      ["#matrix", "The shortlist", "The ten stocks that came out on top, with the numbers behind each one. Click a row for a closer look."],
      ["#sg-pe", "In plain English", "A short description of the selected stock, written from the page's own numbers."],
      ["#learn", "Learn more", "The ideas behind the screen and the signals, explained simply."]]
  };
  TOURS.days = TOURS.main;
  var tour;
  function runTour() {
    var steps = (TOURS[page] || []).filter(function (s) { var e = $(s[0]); return e && e.getClientRects().length; }), i = 0; if (!steps.length) return;
    if (tour) tour.remove();
    tour = document.createElement("div"); tour.className = "sg-tour"; tour.setAttribute("role", "dialog"); tour.setAttribute("aria-modal", "true"); tour.setAttribute("aria-label", "Guided tour");
    tour.innerHTML = '<i class="sg-s sg-t"></i><i class="sg-s sg-l"></i><i class="sg-s sg-r"></i><i class="sg-s sg-b"></i><i class="sg-hole"></i><div class="sg-pop"><p class="sg-n"></p><h3></h3><p class="sg-x"></p><div class="sg-btns"><button type="button" class="sg-btn" data-a="skip">Skip</button><span class="sg-grow"></span><button type="button" class="sg-btn" data-a="back">Back</button><button type="button" class="sg-btn primary" data-a="next">Next</button></div></div>';
    document.body.appendChild(tour);
    function place() {
      var s = steps[i], el = $(s[0]); if (!el) return; var r = el.getBoundingClientRect(), pad = 6, W = innerWidth, H = innerHeight;
      var x0 = Math.max(0, r.left - pad), y0 = Math.max(0, r.top - pad), x1 = Math.min(W, r.right + pad), y1 = Math.min(H, r.bottom + pad);
      var set = function (c, st) { var n = $(c, tour); for (var k in st) n.style[k] = st[k] + "px"; };
      set(".sg-t", { left: 0, top: 0, width: W, height: y0 }); set(".sg-b", { left: 0, top: y1, width: W, height: Math.max(0, H - y1) });
      set(".sg-l", { left: 0, top: y0, width: x0, height: y1 - y0 }); set(".sg-r", { left: x1, top: y0, width: Math.max(0, W - x1), height: y1 - y0 });
      set(".sg-hole", { left: x0, top: y0, width: x1 - x0, height: y1 - y0 });
      $(".sg-n", tour).textContent = "Step " + (i + 1) + " of " + steps.length; $("h3", tour).textContent = s[1]; $(".sg-x", tour).textContent = s[2];
      $('[data-a="back"]', tour).hidden = i === 0; $('[data-a="next"]', tour).textContent = i === steps.length - 1 ? "Done" : "Next";
      var pop = $(".sg-pop", tour), pw = pop.offsetWidth, ph = pop.offsetHeight, px = Math.min(Math.max(12, x0), W - pw - 12), py = y1 + 14 + ph < H ? y1 + 14 : Math.max(12, y0 - ph - 14);
      if (y1 + 14 + ph >= H && y0 - ph - 14 < 12) py = Math.max(12, H - ph - 12);
      pop.style.left = px + "px"; pop.style.top = py + "px";
    }
    function show() { var e = $(steps[i][0]); if (e && e.scrollIntoView) e.scrollIntoView({ block: "center", behavior: "auto" }); setTimeout(function () { if (tour) { place(); $('[data-a="next"]', tour).focus(); } }, 60); }
    function go(d) { i += d; if (i < 0) i = 0; if (i >= steps.length) return end(); show(); }
    function end() { removeEventListener("keydown", key, true); removeEventListener("resize", place); removeEventListener("scroll", place, true); if (tour) tour.remove(); tour = null; var b = $("#sg-tour-btn"); if (b) b.focus(); }
    function key(e) {
      if (e.key === "Escape") { e.stopImmediatePropagation(); e.preventDefault(); end(); }
      else if (e.key === "ArrowRight" || (e.key === "Enter" && !(e.target.closest && e.target.closest('[data-a="skip"],[data-a="back"]')))) { e.stopImmediatePropagation(); e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft") { e.stopImmediatePropagation(); e.preventDefault(); go(-1); }
    }
    tour.addEventListener("click", function (e) { var a = e.target.closest("[data-a]"); if (!a) return; var k = a.getAttribute("data-a"); if (k === "next") go(1); else if (k === "back") go(-1); else end(); });
    addEventListener("keydown", key, true); addEventListener("resize", place); addEventListener("scroll", place, { passive: true, capture: true });
    show();
  }

  /* ---------------- Advanced: "In plain English" for the selected stock ---------------- */
  var peBox, peT = 0;
  function embedded(id) { var n = document.getElementById(id); try { return n ? JSON.parse(n.textContent) : null; } catch (e) { return null; } }
  function getJson(u, fallbackId) { return fetch(u + "?t=" + Date.now(), { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }).then(function (d) { return d || embedded(fallbackId); }); }
  function advPlain() {
    var anchor = $("#terminal .block-intro") || $("#terminal .block-head"); if (!anchor) return;
    if (!peBox) { peBox = document.createElement("div"); peBox.id = "sg-pe"; peBox.className = "sg-pe"; anchor.parentNode.insertBefore(peBox, anchor.nextSibling); }
    var row = $("#matrix tr.sel") || $("#watch .w-item.sel"), sym = row && row.getAttribute("data-s"); if (!sym) return;
    Promise.all([getJson("screener.json", "screener-data"), getJson("live.json", "live-data")]).then(safe(function (r) {
      var sc = r[0], lv = r[1], p = sc && (sc.picks || []).filter(function (x) { return x.symbol === sym; })[0]; if (!p) return;
      var L = lv && lv.stocks && lv.stocks[sym], bits = [], inr = function (v) { return "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
      bits.push("<b>" + esc(p.name) + "</b> is ranked <b>#" + p.magic_rank + "</b> of " + p.of + " healthy companies by the Magic Formula (the best mix of a business that earns well and a price that is cheap for its profit).");
      bits.push("Its annual reports score <b>" + p.fscore + " out of 9</b> on the health check; the screen keeps only " + (sc.rules ? sc.rules.min_fscore : 6) + " or more.");
      if (L && !L.error) {
        bits.push("It last traded at " + inr(L.price) + ", " + (L.change_pct >= 0 ? "up " : "down ") + Math.abs(L.change_pct).toFixed(2) + "% from the previous close (prices are delayed about 15 minutes).");
        if (L.trend && L.trend.gap_pct != null) bits.push("Its price is " + Math.abs(L.trend.gap_pct).toFixed(1) + "% " + (L.trend.above_200 ? "above" : "below") + " its 200-day average, " + (L.trend.above_200 ? "which is often read as an uptrend." : "which is often read as a downtrend."));
        if (L.high52 && L.high52.ratio != null) bits.push("That is " + Math.round(L.high52.ratio * 100) + "% of its highest price in the past year.");
      }
      if (p.consensus && p.analysts) bits.push("The " + p.analysts + " professional analysts who follow it lean " + p.consensus.replace(/_/g, " ") + " on average (analysts are often too optimistic).");
      var html = '<div class="sg-pe-t">In plain English</div><ul>' + bits.map(function (b) { return "<li>" + b + "</li>"; }).join("") + '</ul><p class="sg-pe-n">This describes what the numbers show. It is educational, not advice.</p>';
      if (peBox.__html !== html) { peBox.__html = html; peBox.innerHTML = html; }
    }));
  }
  function advStarter() {
    var intro = $(".intro .wrap"); if (!intro || $(".sg-start")) return;
    var s = document.createElement("section"); s.className = "sg-start"; s.setAttribute("aria-label", "New here?");
    s.innerHTML = '<div><b>New here?</b><span>Start with these. No finance knowledge needed.</span></div><div class="sg-chips"><button type="button" class="sg-btn" data-s="tour">Take the 1-minute tour</button><button type="button" class="sg-btn" data-s="gl">What do these words mean?</button><button type="button" class="sg-btn" data-s="screen">How does the screen work?</button></div>';
    var meta = $(".meta-row", intro); intro.insertBefore(s, meta || null);
    s.addEventListener("click", function (e) { var b = e.target.closest("[data-s]"); if (!b) return; var k = b.getAttribute("data-s"); if (k === "tour") runTour(); else if (k === "gl") openDialog(""); else { var t = $("#screen"); if (t) t.scrollIntoView({ behavior: reduce ? "auto" : "smooth" }); } });
  }

  /* ---------------- buttons ---------------- */
  function buttons() {
    if ($("#sg-tour-btn")) return;
    var mk = function (id, text, fn, cls) { var b = document.createElement("button"); b.type = "button"; b.id = id; b.className = cls; b.textContent = text; b.addEventListener("click", fn); return b; };
    var nav = $(".fx-nav"), lnav = $(".lnav-links");
    if (nav) { var sp = document.createElement("span"); sp.className = "fx-spacer"; nav.appendChild(sp); nav.appendChild(mk("sg-gl-btn", "Glossary", function () { openDialog(""); }, "sg-nav")); nav.appendChild(mk("sg-tour-btn", "Take the tour", runTour, "sg-nav")); }
    else if (lnav) { lnav.appendChild(mk("sg-gl-btn", "Glossary", function () { openDialog(""); }, "sg-link")); lnav.appendChild(mk("sg-tour-btn", "Tour", runTour, "sg-link")); }
  }

  function start() {
    safe(buttons)(); safe(markProse)(); safe(scanLabels)();
    if (page === "advanced") { safe(advStarter)(); safe(advPlain)(); }
    var main = $("main"); if (main && window.MutationObserver) {
      var t = 0; new MutationObserver(function () { clearTimeout(t); t = setTimeout(safe(scanLabels), 400); if (page === "advanced") { clearTimeout(peT); peT = setTimeout(safe(advPlain), 400); } }).observe(main, { childList: true, subtree: true });
    }
    setTimeout(safe(buttons), 800);              // the shared nav may be built a moment after this script
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
