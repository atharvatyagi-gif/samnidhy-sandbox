/* terminal-guide.js: makes the terminal friendly for people who are new to markets. Presentation only: it reads what is already on screen
   and never changes data, hotkeys, charts or fetches.
   1. Plain-words tooltips: dotted-underlined labels explain themselves on hover / focus; a searchable Glossary lists them all.
   2. "In plain English": a short, honest description of the stock on screen, written from the numbers already shown.
   3. A one-minute guided tour (keyboard friendly; Esc skips) and a "New to markets?" starter row on the Brief.
   Everything here is educational wording; none of it is advice. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); }, $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function safe(fn) { return function () { try { return fn.apply(null, arguments); } catch (e) { if (window.console && console.warn) console.warn("terminal-guide:", e.message); } }; }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  /* ---------------- glossary (plain words) ---------------- */
  var G = [
    ["Last price", /^last$|last price|^ltp$/i, "The price of the most recent trade. Prices here are delayed about 15 minutes unless a row says live."],
    ["Change / Change %", /^chg$|^chg ?%$|^chg%$|change/i, "How far the price has moved since the previous close, in rupees and as a percentage. Green is up, red is down."],
    ["Volume", /^volume$/i, "How many shares changed hands. A big number means lots of people were trading it."],
    ["Value traded", /^value$/i, "Volume multiplied by price: the total rupees that changed hands."],
    ["Relative volume", /rel vol/i, "Today's trading compared with its usual pace. 2x means twice as busy as normal."],
    ["Sweep", /^sweep$/i, "Unusually large orders that clear several price levels in one go. Shown only when the optional local feed is running."],
    ["Delivery", /^delivery$/i, "The share of traded shares that were actually taken home instead of closed out the same day. Higher can mean longer-term holders."],
    ["52-week range", /52[- ]?w(eek)?( range| high| low)?/i, "The lowest and highest price over the past year. The bar shows where today's price sits between them."],
    ["Day's range", /day'?s range/i, "The lowest and highest price so far today."],
    ["NSE Live", /nse live/i, "Which of NSE's own live lists this price was picked up from."],
    ["P/E ratio", /^p\/e|\bp\/e\b/i, "Price divided by yearly profit per share. Roughly, how many rupees people pay today for one rupee of yearly profit."],
    ["Market cap", /market cap/i, "Share price times the number of shares: the stock market's total value of the company."],
    ["Moving average (SMA / EMA)", /\bsma\b|\bema\b|moving average|200-day|50-day|200dma/i, "The average closing price over the last N days. A price above its long average is often read as an uptrend, below as a downtrend."],
    ["RSI", /\brsi\b/i, "A 0 to 100 gauge of recent price strength. Above 70 is often called overheated and below 30 weak; it is a rule of thumb, not a forecast."],
    ["MACD", /macd/i, "Compares a fast and a slow average to show whether momentum is picking up or fading."],
    ["ADX", /\badx\b/i, "How strong a trend is, in either direction. Above about 25 is usually called a clear trend."],
    ["+DI / -DI", /\+di|-di/i, "Two lines that compare the pull upward with the pull downward in price."],
    ["Bollinger bands", /bollinger/i, "A band around the average price. Touching the edge means the price is unusually far from its normal."],
    ["Stochastic / CCI / Williams %R", /stochastic|\bcci\b|williams/i, "More momentum gauges. Each one asks whether the recent move has gone unusually far."],
    ["Momentum (12-1)", /momentum/i, "How much the price rose over the past year, leaving out the latest month. Stocks that rose tend to be compared with those that fell."],
    ["Volatility", /volatil/i, "How jumpy the price is. Higher means bigger swings up and down."],
    ["India VIX", /\bvix\b/i, "A gauge of how jumpy the market expects to be over the next month. Higher means more nervous."],
    ["FII / DII", /\bfii\b|\bdii\b|\bfpi\b/i, "Foreign (FII) and domestic (DII) institutions: the big funds. Net flows show whether they put money in or took it out."],
    ["Advancing / declining (breadth)", /adv ?\/ ?dec|advanc|declin|breadth/i, "How many stocks rose compared with how many fell. More risers than fallers means the rise is broad."],
    ["NIFTY 50 / NIFTY 500", /nifty|sensex|index/i, "An index is a basket of big listed companies used as a yardstick for the whole market. NIFTY 50 holds the 50 largest, NIFTY 500 the largest 500."],
    ["Candlestick", /candle/i, "Each candle is one period. The thick body runs from the opening to the closing price; the thin lines show the highest and lowest."],
    ["Log scale", /^log$/i, "A chart scale where equal distances mean equal percentage moves, useful for long histories."],
    ["Decile", /decile/i, "Stocks sorted into ten equal groups. Decile 1 is the model's top group, decile 10 its bottom."],
    ["P(up)", /p\(up\)|p\(down\)|chance it beats|chance/i, "The student model's estimated probability of the stated outcome. It is a statistic, not a promise, and it is often wrong."],
    ["Fundamental / Technical / Sentiment", /fundamental|technical|sentiment/i, "Three views of a stock: its company numbers (fundamental), its price history (technical) and the tone of recent news (sentiment)."],
    ["F-Score", /f-?score|piotroski/i, "A 0 to 9 health score built from nine yes/no questions about a company's annual reports."],
    ["Magic Formula (ROC and earnings yield)", /magic|\broc\b|earnings yield/i, "A published way of ranking companies on how well they use their money (return on capital) and how cheap their profit is (earnings yield)."],
    ["EPS", /\beps\b/i, "Earnings per share: the company's yearly profit divided by its number of shares."],
    ["Dividend yield", /dividend/i, "The yearly cash a company pays out per share, as a percentage of the share price."],
    ["ROE", /\broe\b/i, "Return on equity: profit as a percentage of the owners' money in the business."],
    ["Debt / equity", /debt/i, "How much the company has borrowed compared with the owners' money. Higher means more borrowing."],
    ["Confidence", /confidence/i, "How many of the model's views agree. More agreement means higher confidence, not certainty."],
    ["Watchlist", /watchlist/i, "A list of stocks you follow. Add the one on screen with the star button."],
    ["Bullish / bearish", /bullish|bearish/i, "Bullish means leaning toward rising prices; bearish means leaning toward falling prices. They describe a lean, not a certainty."],
    ["Replay", /replay/i, "Plays back a past trading day minute by minute using real prices."]
  ];
  var SEL = "th, .sec-t, .lbl span, .tg-top span, .statstrip span, .tag, .wl-cols span, .rail-tabs button, .cc-bar button, .cc-foot button, .kick, .regime .lbl, .tbl .r";

  /* ---------------- tooltip engine ---------------- */
  var tip;
  function ensureTip() { if (tip) return tip; tip = document.createElement("div"); tip.className = "tg-tip"; tip.setAttribute("role", "tooltip"); tip.id = "tg-tip"; tip.hidden = true; document.body.appendChild(tip); return tip; }
  function showTip(el) {
    var d = el.getAttribute("data-gl"); if (!d) return; var t = ensureTip();
    var i = +el.getAttribute("data-gl-i"); t.innerHTML = "<b>" + esc(G[i][0]) + "</b>" + esc(G[i][2]); t.hidden = false;
    var r = el.getBoundingClientRect(), w = t.offsetWidth, h = t.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8), y = r.bottom + 8; if (y + h > innerHeight - 8) y = Math.max(8, r.top - h - 8);
    t.style.left = x + "px"; t.style.top = y + "px"; el.setAttribute("aria-describedby", "tg-tip");
  }
  function hideTip() { if (tip) tip.hidden = true; }
  document.addEventListener("pointerover", function (e) { var el = e.target.closest && e.target.closest("[data-gl]"); if (el) showTip(el); });
  document.addEventListener("pointerout", function (e) { if (e.target.closest && e.target.closest("[data-gl]")) hideTip(); });
  document.addEventListener("focusin", function (e) { var el = e.target.closest && e.target.closest("[data-gl]"); if (el) showTip(el); });
  document.addEventListener("focusout", hideTip); addEventListener("scroll", hideTip, { passive: true, capture: true });

  var scanTimer = 0;
  function scan() {
    $$(SEL, $(".views") || document).forEach(function (el) {
      if (el.hasAttribute("data-gl") || el.closest("#tg-gl,.tg-pop,.modal")) return;
      var t = (el.textContent || "").replace(/\s+/g, " ").trim(); if (!t || t.length > 48 || /^[\d\s.,+\-−%₹:()/]+$/.test(t)) return;
      for (var i = 0; i < G.length; i++) if (G[i][1].test(t)) { el.setAttribute("data-gl", "1"); el.setAttribute("data-gl-i", i); return; }
    });
  }
  function scanSoon() { clearTimeout(scanTimer); scanTimer = setTimeout(safe(scan), 350); }

  /* ---------------- glossary dialog ---------------- */
  var glossary;
  function buildGlossary() {
    glossary = document.createElement("div"); glossary.className = "modal tg-modal"; glossary.id = "tg-gl"; glossary.hidden = true;
    glossary.innerHTML = '<div class="m-box" role="dialog" aria-modal="true" aria-label="Glossary: what the words mean"><div class="m-head"><b>Glossary: what the words mean</b><button type="button" class="btn-line sm" data-close>Close</button></div>' +
      '<div class="tg-gl-body"><input type="search" id="tg-gl-q" placeholder="Search a word, e.g. RSI, volume, P/E" aria-label="Search the glossary"><div id="tg-gl-list"></div></div></div>';
    document.body.appendChild(glossary);
    var list = $("#tg-gl-list", glossary), q = $("#tg-gl-q", glossary);
    function paint() { var f = q.value.trim().toLowerCase(); list.innerHTML = G.filter(function (g) { return !f || (g[0] + " " + g[2]).toLowerCase().indexOf(f) >= 0; }).map(function (g) { return "<dl><dt>" + esc(g[0]) + "</dt><dd>" + esc(g[2]) + "</dd></dl>"; }).join("") || '<p class="mut">No match. Try a shorter word.</p>'; }
    q.addEventListener("input", paint); paint();
    glossary.addEventListener("click", function (e) { if (e.target === glossary || e.target.hasAttribute("data-close")) closeGlossary(); });
  }
  function openGlossary(term) { if (!glossary) buildGlossary(); glossary.hidden = false; var q = $("#tg-gl-q"); q.value = term || ""; q.dispatchEvent(new Event("input")); q.focus(); }
  function closeGlossary() { if (glossary) glossary.hidden = true; }

  /* ---------------- "In plain English" strip ---------------- */
  function num(s) { var m = String(s || "").replace(/[,₹\s]/g, "").replace(/−/g, "-").match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; }
  var peBox, peTimer = 0;
  function plain() {
    var head = $("#cc-head"); if (!head) return;
    var sym = (($(".sym", head) || {}).textContent || "").trim(), name = (($(".name", head) || {}).textContent || "").trim(), pxEl = $(".px", head), chgEl = $(".chg", head);
    if (!peBox) { peBox = document.createElement("div"); peBox.id = "pe"; peBox.className = "pe"; head.parentNode.insertBefore(peBox, head.nextSibling); }
    if (!sym || !pxEl) { peBox.hidden = true; return; }
    var px = num(pxEl.textContent.replace(/[^\d.,−-]/g, "")), pct = chgEl ? num((chgEl.textContent.match(/\(([^)]*)%\)/) || [])[1]) : null;
    var det = ($("#details") || {}).innerText || "", bits = [];
    var inr = function (v) { return "₹" + v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    if (px != null && pct != null) bits.push("<b>" + esc(name || sym) + "</b> last traded at " + inr(px) + ", " + (pct === 0 ? "unchanged" : (pct > 0 ? "up " : "down ") + Math.abs(pct).toFixed(2) + "%") + " from the previous close.");
    var rb = $$(".rbar", $("#details") || document).filter(function (r) { return /52-week range/i.test(r.textContent); })[0];
    if (rb && px != null) {
      var lbls = $$(".lbl", rb), ns = $$("span", lbls[lbls.length - 1]).map(function (s) { return num(s.textContent); }).filter(function (v) { return v != null; });
      if (ns.length >= 2 && ns[1] > ns[0]) {
        var pos = Math.min(1, Math.max(0, (px - ns[0]) / (ns[1] - ns[0])));
        bits.push("Over the past year it has ranged from " + inr(ns[0]) + " to " + inr(ns[1]) + "; today it sits " + (pos < 0.2 ? "near the bottom" : pos > 0.8 ? "near the top" : "around the middle") + " of that range (" + Math.round(pos * 100) + "% of the way up).");
      }
    }
    var tm = det.match(/Summary\s+([A-Za-z ]+?)\s+(\d+) bearish · (\d+) neutral · (\d+) bullish/);
    if (tm) bits.push("Of " + (+tm[2] + +tm[3] + +tm[4]) + " common chart signals, " + tm[2] + " lean bearish, " + tm[3] + " are neutral and " + tm[4] + " lean bullish (" + tm[1].trim().toLowerCase() + ").");
    var om = det.match(/Chance it beats NIFTY 50\s+(\d+)%/);
    if (om) bits.push("The students' model puts the chance of beating the NIFTY 50 over the next 20 trading days at " + om[1] + "% (50% is a coin flip). It is often wrong.");
    if (!bits.length) { peBox.hidden = true; return; }
    var open = store("tg-pe") !== "0";
    peBox.hidden = false; peBox.classList.toggle("shut", !open);
    var html = '<button type="button" class="pe-t" aria-expanded="' + open + '"><span>In plain English</span><i>' + (open ? "Hide" : "Show") + "</i></button>" +
      (open ? "<ul>" + bits.map(function (b) { return "<li>" + b + "</li>"; }).join("") + '</ul><p class="pe-n">This describes what the numbers show. It is educational, not advice.</p>' : "");
    if (peBox.__html !== html) { peBox.__html = html; peBox.innerHTML = html; }          // only touch the DOM when the words changed (the observer watches this area)
    $(".pe-t", peBox).onclick = function () { store("tg-pe", open ? "0" : "1"); plain(); };
  }
  function plainSoon() { clearTimeout(peTimer); peTimer = setTimeout(safe(plain), 300); }

  /* ---------------- guided tour ---------------- */
  var STEPS = [
    ["#cmdline", "Search for anything", "Type a company name such as Reliance, or press Ctrl+K from anywhere. Press Enter to open its chart."],
    ["#tabs", "Move between sections", "Brief is the quick summary. Terminal is the price chart. Movers shows what rose and fell today. More opens world markets, news and the globe."],
    [".chartcard", "The price chart", "Each bar is one day. Hover to read the prices, scroll to zoom in or out, and drag to move through time."],
    ["#rg-grp", "How far back to look", "1M means one month, 1Y one year, All the whole history. Try a few to see the bigger picture."],
    ["#pe", "In plain English", "A short description of the stock on screen, written from the live numbers. Hide it any time."],
    [".rail-watch", "Your watchlist", "Stocks you want to keep an eye on. Click the star above the chart to add the one you are viewing."],
    ["#details", "More numbers, explained", "Words with a dotted underline explain themselves when you hover them. The Glossary button lists every word."]
  ];
  var tour;
  function startTour() {
    var btn = $('#tabs [data-go="terminal"]'); if (btn) btn.click();
    if ($(".term.focus") && $("#fs")) $("#fs").click();
    setTimeout(safe(function () { plain(); runTour(); }), 450);
  }
  function runTour() {
    var steps = STEPS.filter(function (s) { var e = $(s[0]); return e && e.offsetParent !== null; }), i = 0;
    if (!steps.length) return;
    if (tour) tour.remove();
    tour = document.createElement("div"); tour.className = "tg-tour"; tour.setAttribute("role", "dialog"); tour.setAttribute("aria-modal", "true"); tour.setAttribute("aria-label", "Guided tour");
    tour.innerHTML = '<i class="tg-s tg-t"></i><i class="tg-s tg-l"></i><i class="tg-s tg-r"></i><i class="tg-s tg-b"></i><i class="tg-hole"></i><div class="tg-pop"><p class="tg-n"></p><h3></h3><p class="tg-x"></p>' +
      '<div class="tg-btns"><button type="button" class="btn-line sm" data-a="skip">Skip</button><span class="grow"></span><button type="button" class="btn-line sm" data-a="back">Back</button><button type="button" class="btn-ink" data-a="next">Next</button></div></div>';
    document.body.appendChild(tour);
    function place() {
      var s = steps[i], el = $(s[0]), r = el.getBoundingClientRect(), pad = 6, W = innerWidth, H = innerHeight;
      var x0 = Math.max(0, r.left - pad), y0 = Math.max(0, r.top - pad), x1 = Math.min(W, r.right + pad), y1 = Math.min(H, r.bottom + pad);
      var set = function (c, st) { var n = $(c, tour); for (var k in st) n.style[k] = st[k] + "px"; };
      set(".tg-t", { left: 0, top: 0, width: W, height: y0 }); set(".tg-b", { left: 0, top: y1, width: W, height: H - y1 });
      set(".tg-l", { left: 0, top: y0, width: x0, height: y1 - y0 }); set(".tg-r", { left: x1, top: y0, width: W - x1, height: y1 - y0 });
      set(".tg-hole", { left: x0, top: y0, width: x1 - x0, height: y1 - y0 });
      $(".tg-n", tour).textContent = "Step " + (i + 1) + " of " + steps.length; $("h3", tour).textContent = s[1]; $(".tg-x", tour).textContent = s[2];
      $('[data-a="back"]', tour).hidden = i === 0; $('[data-a="next"]', tour).textContent = i === steps.length - 1 ? "Done" : "Next";
      var pop = $(".tg-pop", tour), pw = pop.offsetWidth, ph = pop.offsetHeight;
      var px = Math.min(Math.max(12, x0), W - pw - 12), py = y1 + 14 + ph < H ? y1 + 14 : Math.max(12, y0 - ph - 14);
      if (y1 + 14 + ph >= H && y0 - ph - 14 < 12) { py = Math.max(12, H - ph - 12); px = Math.min(Math.max(12, W - pw - 12), W - pw - 12); }
      pop.style.left = px + "px"; pop.style.top = py + "px";
    }
    function go(d) { i += d; if (i < 0) i = 0; if (i >= steps.length) return end(true); var e = $(steps[i][0]); e.scrollIntoView({ block: "nearest" }); place(); $('[data-a="next"]', tour).focus(); }
    function end(done) { removeEventListener("keydown", key, true); removeEventListener("resize", place); tour.remove(); tour = null; store("tg-tour", "1"); if (done) { var b = $("#tg-tour-btn"); if (b) b.focus(); } }
    function key(e) {
      if (e.key === "Escape") { e.stopImmediatePropagation(); e.preventDefault(); end(); }
      else if (e.key === "ArrowRight" || e.key === "Enter") { if (e.target.closest && e.target.closest('[data-a="skip"],[data-a="back"]')) return; e.stopImmediatePropagation(); e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft") { e.stopImmediatePropagation(); e.preventDefault(); go(-1); }
    }
    tour.addEventListener("click", function (e) { var a = e.target.closest("[data-a]"); if (!a) return; var k = a.getAttribute("data-a"); if (k === "next") go(1); else if (k === "back") go(-1); else end(); });
    addEventListener("keydown", key, true); addEventListener("resize", place);
    go(0); i = 0; place(); $('[data-a="next"]', tour).focus();
  }

  /* ---------------- buttons, starter row, glue ---------------- */
  function install() {
    var tabs = $("#tabs"), grow = tabs && $(".grow", tabs);
    if (tabs && grow && !$("#tg-tour-btn")) {
      var t = document.createElement("button"); t.type = "button"; t.id = "tg-tour-btn"; t.className = "tab-side"; t.textContent = "Take the tour"; t.addEventListener("click", startTour);
      var g = document.createElement("button"); g.type = "button"; g.id = "tg-gl-btn"; g.className = "tab-side"; g.textContent = "Glossary"; g.addEventListener("click", function () { openGlossary(""); });
      grow.after(g); grow.after(t);
    }
    var stats = $("#brief-stats");
    if (stats && !$(".tg-start")) {
      var s = document.createElement("section"); s.className = "tg-start"; s.setAttribute("aria-label", "New to markets?");
      s.innerHTML = '<div><b>New to markets?</b><span>Start here, no finance knowledge needed.</span></div><div class="tg-chips">' +
        '<button type="button" class="btn-line" data-s="tour">Take the 1-minute tour</button><button type="button" class="btn-line" data-s="gl">What do these words mean?</button>' +
        '<button type="button" class="btn-line" data-s="movers">See what moved today</button><button type="button" class="btn-line" data-s="chart">Open a chart (Reliance)</button></div>';
      stats.parentNode.insertBefore(s, stats);
      s.addEventListener("click", function (e) {
        var b = e.target.closest("[data-s]"); if (!b) return; var k = b.getAttribute("data-s");
        if (k === "tour") startTour(); else if (k === "gl") openGlossary("");
        else if (k === "movers") { var m = $('#tabs [data-go="movers"]'); if (m) m.click(); }
        else { var c = $("#cmd"); if (c) { c.value = "RELIANCE"; c.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); } }
      });
    }
  }
  addEventListener("keydown", function (e) {              // Esc closes the glossary first; terminal.js would otherwise treat it as "leave the desk"
    if (e.key === "Escape" && glossary && !glossary.hidden) { e.stopImmediatePropagation(); e.preventDefault(); closeGlossary(); }
  }, true);

  function start() {
    safe(install)(); safe(scan)(); safe(plain)();
    var v = $(".views"); if (v && window.MutationObserver) new MutationObserver(function () { scanSoon(); plainSoon(); safe(install)(); }).observe(v, { childList: true, subtree: true });
    var h = $("#cc-head"); if (h && window.MutationObserver) new MutationObserver(plainSoon).observe(h, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
