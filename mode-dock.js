/* Always-visible shortcuts to the Advanced page and Expert Mode (landing page, main page, Advanced page).
   Paths are worked out from this script's own address, so it also works from the days/ archive pages. */
(function () {
  const me = document.currentScript, base = me ? me.src.replace(/mode-dock\.js(\?.*)?$/, "") : "";
  const here = location.pathname.split("/").pop() || "index.html";
  const css = `
  .mdock { position: fixed; right: 18px; bottom: 18px; z-index: 9990; display: flex; gap: 10px; font-family: "JetBrains Mono", ui-monospace, Consolas, monospace; }
  .mdock a { display: inline-flex; align-items: center; gap: 8px; height: 46px; padding: 0 18px; border-radius: 6px; text-decoration: none; font-weight: 700;
    font-size: 14px; letter-spacing: 0.03em; transition: background-color .15s ease; }
  .mdock a:hover { background: #a1a1aa; }
  .mdock .adv { background: #fafafa; color: #09090b; border: 1px solid #27272a; }
  .mdock .exp { background: #121214; color: #fafafa; border: 1px solid #27272a; }
  .mdock a.here { outline: 1px solid #52525b; outline-offset: 0; }
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
