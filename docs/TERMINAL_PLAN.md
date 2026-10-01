# B-LAB TERMINAL v2 — plan

Branch: `terminal-v2`. Not merged to `main` by this plan or by any commit on this branch — ends in a PR for review, per the brief.

## Status
- **(a) Visual system + chrome + command line — done.** Black/amber Bloomberg-genre palette (every existing
  screen re-themed via shared CSS variables, no per-component rewrites needed), square corners, reduced-motion
  respected, light theme kept as an accessibility option. Always-visible command line (`SYMBOL FUNCTION`
  grammar, fuzzy autocomplete, history, hash-sync), 17 function codes with honest "not built yet" messaging
  for the ones without a screen yet, F1-F8 function-key bar, HELP directory, freshness lights (real ages,
  reusing `renderAsOf()`), scrolling ticker tape + headline crawl (real data, CSS-only marquee). Market status
  was already real (`livechip`) - no change needed there. Tested against the full regression suite
  (click_all, replay, timeframes, globe) at every step; zero new failures. One real bug found and fixed by the
  tests, not assumed away: blurring the command line after a command left a stray `Esc` falling through to
  the pre-existing "nothing open -> go back to B-Lab" handler, silently navigating away.
- **(b) MAP** — not started. Next.
- **(c) remaining functions, (d) data additions** — not started.

## 1. Current state (what exists today, verified by reading the actual files, not assumed)

- **Shell**: `expert-terminal.html` (tab bar: Brief/Terminal/Movers/Sectors/World/Outlook/News/Globe/Watchlist), `terminal.js` (~1,500 lines), `terminal.css`, behind Firebase sign-in (`auth-check.js`). `#v=<view>&s=<SYMBOL>` hash already drives navigation (`go()`, `terminal.js:190`) — the command-line grammar in this plan extends that, it doesn't replace it.
- **Chart**: `chart-engine.js` + `chart-indicators.js` on Lightweight Charts — candles/line/heikin/bars/area/baseline, 24 timeframes, 67 indicators including VWAP (`chart-indicators.js:158`), drawing tools, replay mode, compare overlay, PNG snapshot. This is already professional-grade; `CH` and `ID` reuse it directly.
- **Globe/MAP**: `globe-map.js` (Leaflet 1.9.4, Esri World Dark Gray) — 7 chokepoints, live OpenSky flights with a full telemetry popup, GDELT news, a Brief-style real-data summary panel, real NSE sector-exposure tags. This is the base section 4 extends, not a rebuild.
- **Outlook**: `renderOutlook()` (`terminal.js:1152`) already shows walk-forward accuracy, live track record, and confidence-bucketed accuracy from `predict.json` — `OUT` already meets the "measured accuracy" requirement; mainly needs wiring into the new function-code shell.
- **Data already in repo**: `t/universe.json`, `t/quotes.json`, `t/fund.json`, `t/h/*`, `t/i/*`, `screener.json`, `institutional.json`, `news.json`, `predict.json`, `globe.json` — all auto-updated by `.github/workflows/` on the `market-clock` heartbeat (now every 5 minutes for live prices, hourly for Globe, 3x/day for the NSE end-of-day update).
- **Not present today**: command line / fuzzy autocomplete, function-key bar, panel tiling, amber-on-black visual system, CSV export, a treemap, a correlation matrix, multiple named watchlists with alerts, a two-pane news reader, a dedicated peer-comparison table, a searchable help directory.

## 2. Data sources — verified for real from a GitHub Actions runner

Script: `scripts/verify_terminal_v2_sources.py`. Workflow: `.github/workflows/verify-terminal-v2-sources.yml` (one-off, delete once this branch ships). Run on GitHub's own infrastructure specifically — **not** the local sandbox — because this project already has one confirmed real case (OpenSky, 30 Sep 2026) of a source working from a developer machine and failing from GitHub's shared runner IPs. Full machine-readable results: `data/terminal_v2/source_verification.json` (committed by the Action itself, run at 2026-10-01T04:55:41Z).

| Source | Status | Real finding |
|---|---|---|
| OpenSky `/states/all` | **OK** | Already in production use (Globe tab). |
| IMF PortWatch: chokepoints, Daily_Chokepoints_Data, disruptions, ports, Daily_Ports_Data | **OK**, all 5 | Real, current data: Suez Canal transits for 2026-09-27 (37 vessels, by type), 37 Indian ports with port-call data through 2026-09-25. This genuinely replaces the Globe tab's "no ship data" note with real daily vessel-type counts. |
| Shipping lanes (`newzealandpaul/Shipping-Lanes`) | **OK** | 1.14 MB GeoJSON — needs simplification before shipping to the browser (see §4). |
| TeleGeography submarine cables + landing points | **OK** | 730 cables, 1,925 landing points. |
| WRI Global Power Plant Database | **OK** | 1,589 India rows in an 11.4 MB CSV — filter to India + ≥100 MW before using. |
| USGS earthquakes M4.5+ | **OK** | 128 events in the last 7 days globally. |
| NASA EONET v3 | **OK** | 7,197 *open* events — far too many to show as-is; needs filtering (category + date + maybe India/Asia-Pacific bounding box) before it's usable, not a straight dump. |
| GDACS | **OK** | 89 current events. |
| Wikidata SPARQL (company → facility) | **OK, but** | The endpoint works, but a real test query for Reliance Industries' facilities returned **zero results**. Wikidata's facility-level coverage for Indian-listed companies looks sparse. Plan: ship this layer best-effort with the spec's own required honesty ("No mapped assets on Wikidata") — expect it to be empty for most NIFTY 500 names, not just Reliance; do not treat a 200 response as a guarantee of data. |
| GDELT DOC 2.0 | **FAIL — confirmed** | HTTP 429 from the Actions runner, same as the user's report. This is now independently verified, not just claimed. |
| Google News RSS (fallback) | **OK** | Real RSS, 172 KB response for one query. Use this as the primary chokepoint-news source going forward; keep GDELT as an opportunistic extra, never load-bearing. |
| Yahoo Finance (`yfinance`) — USDINR, Brent, gold, silver, copper, nat gas | **OK** | Real prices pulled in one call. |
| RBI reference-rate / policy pages | **OK** (HTTP) | Reachable; still need to write + test the actual scraper against the page's real HTML structure (not done by this script — it only confirms the page loads). |
| MOSPI release calendar | **OK** (HTTP) | Same caveat — page reachable, scraper not yet written. |
| World Bank API | **OK** | Real India GDP figure returned. |
| IMF DataMapper API | **OK** | Real data returned. |
| NSE corporate announcements | **FAIL — confirmed** | Times out from GitHub Actions too (not just locally) — consistent with this project's existing, established finding that NSE hardens several endpoints beyond the ones `scripts/nse_live_poll.py` already uses successfully (`allIndices`, live-analysis-*). Treat as unavailable; do not build `ECO`/corporate-actions on it without a different source. |
| aisstream.io (live ship AIS) | **NEEDS KEY** | Free, but needs the user to register and hand over `AISSTREAM_KEY` as a GitHub secret. Not called yet. |
| ACLED (conflict events) | **NEEDS KEY** | Free, needs `ACLED_KEY` + `ACLED_EMAIL`. Not called yet. |
| FRED | **NEEDS KEY (optional)** | Not called; marked optional in the brief, skipped unless the user wants it. |

**Action needed from the user before those three layers can ship:** register free accounts at aisstream.io and acleddata.com (and optionally FRED) and provide the keys as GitHub repo secrets. Everything else in the plan needs no key from the user.

## 3. Function-by-function plan

Reuse/refactor existing renderers wherever they exist; the command-line + panel shell dispatches to the same functions regardless of which panel or symbol it's running on.

| Code | Reuse | New work |
|---|---|---|
| `OV` | `renderDetails()` already has ranges, key stats, outlook snippet | Promote to a full standalone screen: description, P/E and sector from `t/fund.json`/`t/universe.json`, laid out for the new density/grid |
| `CH` | `chart-engine.js` + `chart-indicators.js`, as-is | Wire into the function/panel dispatcher; no chart-engine changes needed |
| `ID` | VWAP indicator already exists; intraday timeframes already exist | A dedicated tick-style intraday screen (current intraday view is the same chart engine, different timeframe — mostly a presentation layer) |
| `HIS` | `t/h/*` loading (`loadHist`) | New: a plain table view + **CSV export** (not present anywhere today — only PNG snapshot exists) |
| `FIN` | `S.fund` already loaded and partially shown | New: full ratios table, one sparkline per row (small canvas/SVG, reuse Lightweight Charts' sparkline mode or a tiny hand-rolled one) |
| `PEER` | `sectorStats()` already groups by industry | New: a sortable table scoped to one stock's industry, not the whole sector |
| `MOV` | `renderMovers()`, as-is | Wire into dispatcher |
| `SEC` | `renderSectors()` heat strip | Extend to true size-by-market-cap / colour-by-% grid |
| `HEAT` | sector grouping logic | New: NIFTY 500 treemap (new rendering, likely a small dependency-free treemap layout function — no need for a library) |
| `SCR` | `screener.json` already loaded and used in Brief | New: dedicated screen + saved queries (`localStorage`, wrapped in try/catch per the repo's existing pattern) |
| `FII` | `renderWorld()`'s FII/DII section | Wire into dispatcher |
| `NEWS` | `renderNews()` list view | New: second pane (reader), keep existing filter/search logic |
| `OUT` | `renderOutlook()`, as-is, already shows measured accuracy | Wire into dispatcher |
| `CORR` | `t/h/*` historical closes already loadable per symbol | New: client-side correlation matrix (Pearson over daily returns, 60/120/250-day) for the current watchlist — pure computation, no new data source |
| `WATCH` | watchlist storage (`loadWatch`/`saveWatch`) | New: multiple named lists, in-browser alert evaluation (price cross / % move) against live quotes already in `S.quotes` |
| `MAP` | `globe-map.js`, 7 chokepoints, flights, news, sector tags | Section 4 below — the largest single piece of work |
| `HELP` | — | New: static searchable directory of the function table above |

## 4. `MAP` — build plan

1. **Base map switcher**: add Esri World Imagery + Esri World Street Map as alternate `L.tileLayer`s; a small control toggles between them and the existing World Dark Gray. All three verified reachable with no key (Esri tiles already proven in production use).
2. **PortWatch layer** (replaces the "no ship data" note): extend `scripts/globe_data.py` to pull `Daily_Chokepoints_Data` for the 7 existing chokepoints by name/id match, plus the full `PortWatch_chokepoints_database` (28 points — more than today's 7; decide whether to expand the chokepoint set or keep 7 primary + show the rest as a lighter layer) and `Daily_Ports_Data` filtered to India. Popup: 90-day sparkline (needs a small history file, see §5), 7-day-avg vs prior-90-day-avg %, top industries (already in the schema as `industry_top1/2/3`), real data date (don't claim "live" — PortWatch itself lags about a week).
3. **Disruptions layer**: `portwatch_disruptions_database`, refreshed daily alongside the above.
4. **Hazard layers**: USGS (M4.5+, 7 days), EONET (**must filter** — 7,197 open events is not a map layer, it's a database; plan: last 72h + category checkboxes + the India/Indian Ocean region by default), GDACS. All free, no key, verified working.
5. **Static/slow layers** (`data/globe/layers/*.json`, regenerated only when >7 days old, per the brief): shipping lanes (simplify the 1.14 MB source — drop to a coarser line simplification, keep attribution), submarine cables + landing points (highlight India-landing cables specifically), WRI power plants (India, ≥100 MW, coloured by fuel).
6. **Company footprint layer**: Wikidata SPARQL, by NSE ticker → Wikidata item → facilities. Given the confirmed sparse coverage, ship it as genuinely best-effort with the brief's own required empty-state message, and don't promise coverage beyond "try it, it may come back empty."
7. **News**: switch the chokepoint-news source to Google News RSS as primary (GDELT's 429 from Actions is now confirmed, not assumed); keep GDELT as a secondary opportunistic call that's allowed to fail silently, exactly like today's degradation rules.
8. **Market linkage**: extend the existing `CHOKE_SECTORS` map in `terminal.js` to the new PortWatch/hazard popups, same pattern already shipped (real sector name + real live % move, click-through to `OV`).
9. **Optional, blocked on user-provided keys**: aisstream.io live AIS, ACLED conflict events. Code them so they degrade to "not configured" (not an error) when the secret is absent, same pattern as every other optional source in this repo.
10. Keep hourly JSON under ~400 KB: round coordinates to 3–4 decimals, cap EONET/GDACS/USGS to a recent window, and keep the static layers in their own files so they don't bloat the hourly payload.

## 5. Sequencing (as specified) and file-size reality check

(a) Visual system + chrome + command line → (b) `MAP` → (c) remaining functions → (d) data additions. Each step gets its own commits on this branch, tested locally with `scripts/dev_preview.py` and a headless browser before moving on — the same discipline already used for every feature shipped on `main` so far (test, verify, then commit).

Being honest about scale: this is a full redesign of a ~120 KB JS file and a ~58 KB CSS file, plus roughly a dozen new screens and ten new map layers. It will take multiple work sessions, not one. This plan is the first deliverable; (a) starts next.

## 6. What needs the user, before this can fully ship

1. A free aisstream.io account → `AISSTREAM_KEY` secret (for live ship AIS on the map).
2. A free acleddata.com account → `ACLED_KEY` + `ACLED_EMAIL` secrets (for conflict-event markers).
3. Optionally, a free FRED account → `FRED_KEY` (the brief marks this optional; can ship without it).

Everything else in this plan needs no new credentials from the user.
