/* Always-visible shortcuts to the Advanced page and Expert Mode (landing page, main page, Advanced page).
   Paths are worked out from this script's own address, so it also works from the days/ archive pages. */
(function () {
  const me = document.currentScript, base = me ? me.src.replace(/mode-dock\.js(\?.*)?$/, "") : "";
  const here = location.pathname.split("/").pop() || "index.html";
  const css = `
  .mdock { position: fixed; right: 18px; bottom: 18px; z-index: 9990; display: flex; gap: 10px; font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace; }
  .mdock a { display: inline-flex; align-items: center; gap: 8px; height: 46px; padding: 0 18px; border-radius: 12px; text-decoration: none; font-weight: 700;
    font-size: 14px; letter-spacing: 0.03em; box-shadow: 0 12px 34px rgba(0,0,0,0.45); transition: transform .15s ease, filter .15s ease; }
  .mdock a:hover { transform: translateY(-2px); filter: brightness(1.08); }
  .mdock .adv { background: #e9dcc0; color: #06170e; border: 1px solid rgba(6,23,14,0.2); }
  .mdock .exp { background: #22c55e; color: #03140a; border: 1px solid #16a34a; }
  .mdock a.here { outline: 3px solid rgba(255,255,255,0.55); outline-offset: 2px; }
  .mdock small { font-weight: 500; font-size: 11px; opacity: 0.75; }
  @media (max-width: 600px) { .mdock { left: 12px; right: 12px; bottom: 12px; } .mdock a { flex: 1; justify-content: center; height: 44px; padding: 0 10px; font-size: 13px; } .mdock small { display: none; } }
  @media print { .mdock { display: none; } }`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
  const d = document.createElement("nav"); d.className = "mdock"; d.setAttribute("aria-label", "Advanced and Expert Mode");
  d.innerHTML = `<a class="adv${here === "advanced.html" ? " here" : ""}" href="${base}advanced.html" title="Screen, live technicals, institutions, market weather">◆ Advanced <small>screen</small></a>
    <a class="exp" href="${base}auth.html" title="The B-Lab terminal: every NSE stock, TradingView-style charts">█ Expert Mode <small>terminal</small></a>`;
  const add = () => document.body.appendChild(d);
  if (document.body) add(); else document.addEventListener("DOMContentLoaded", add);
})();
