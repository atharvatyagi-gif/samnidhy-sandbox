# ALADIN 2.0, Phase 6: UI and charts, slice 1 of 3 (2026-10-08)

Branch `feature/aladin-learning`, merged to `main` slice by slice after its acceptance checks pass. This slice: the **ALADIN brief** for the open stock, the data shards behind every later chart, and the compliance wiring.

## What is in this slice
- **Data shards** (`scripts/aladin2/publish.py`, called by `scripts/build_site.py` inside a try/except so it can never break the site): `aladin2/index.json` (28 KB for 500 stocks), `aladin2/stock/<SYM>.json` (largest 6 KB; limit 80 KB), `scoreboard.json`, `journal.json`, `market_map.json`. Total added to `site/`: **3.0 MB** (500 stock shards). Built from the ledger, the strategy states and the price cache; a missing input is "not measured".
- **ALADIN brief** (`desk-aladin2.js`) at the top of the Details rail, loaded lazily (one 3-6 KB file when a stock opens; the scoreboard once):
  - verdict strip: product state chip, the signal from the labels dictionary (today: `NO EDGE: stand aside`), as-of date;
  - a plain sentence built from the numbers ("In 20 trading days TCS is likely to be between ₹1,894.28 and ₹2,295.34 (-9.3% to +10.0%) about 80% of the time");
  - **forecast fan chart** (inline SVG, existing colour tokens only): the last 150 closes, then the 50 / 80 / 95% ranges out to 60 days, hover text with the exact levels, layer toggles, accessible label, table fallback ("Range table");
  - strategy panel with a card per strategy, its state chip and the reason for its last change;
  - risk panel: capital and risk-per-trade inputs saved in the browser only; for a Validated stock it shows entry zone, invalidation level, quantity, money at risk; today it explains why there is no plan;
  - reliability and coverage table (clearly labelled "historical simulation", not live) and "What does this mean?";
  - the mandatory disclaimer. The rail re-renders every 2 seconds on ticks; the brief keeps its DOM node when its content is unchanged, so open sections, hidden layers and typed numbers survive.
- **Wording**: every label comes from the `labels` dictionary in `data/config/aladin2.json` (`signal_labels` is the one switch). `scripts/check_banned.py` now scans the new module and the neutral dictionary, exempts only `labels.directional` and the documentation block, and requires the disclaimer in the new module.
- **Theme**: unchanged. New CSS is one appended block `/* ---------- ALADIN2 ---------- */` using existing variables only (fan fills use `--acc` with `fill-opacity`); no new colour literals.

## Checks run
- Screenshots (1440x900 and 390x844, real data, `docs/aladin2/phase6/`): the brief renders in both; no console errors from ALADIN. The only 404s are three optional files this worktree does not have (`live.json`, `news.json`, `nse_live.json`); they are not part of this change.
- Tests: 6 new JS tests (risk sizing equals the Python fixtures, capital at risk = quantity x stop distance, fan geometry nests and stays in the drawing, labels and disclaimer, DOM signature); 2 new Python publish tests; the existing banned-word tests updated for the new module. Everything under `tests/` except the browser suites passes.
- Performance: the brief adds one 3-6 KB request on stock open; `build_site.py` adds the shard build (about 4 seconds locally for 500 stocks).

## Still to build in Phase 6 (next slices)
Slice 2: scoreboard page (reliability diagram, coverage trend, state shares, live vs historical, strategy records), learning journal and learning curve, market map treemap, sector-rotation chart, opportunity scatter, signal board, correlation clusters (the last three stay empty-state until a signal exists: they show "NO EDGE" honestly). Slice 3: fan chart overlay on the main price chart with signal markers and regime ribbon, attribution waterfall (needs a probability to attribute; today it will say so), loss-scenario ladder for Validated stocks, keyboard and table fallbacks on every chart, phone pass.

Honest limits of this slice: the fan chart sits in the Details rail, not yet on the main chart; the centre line is the middle of the 50% range (the ledger does not store the median yet, adding it would change a ledger line format mid-test); no stock has a trade plan because none is Validated.
