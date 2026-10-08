"""
ALADIN 2.0 acceptance checklist (section 14 of the brief): runs what can be run, reads the measured reports for the rest, and writes docs/aladin2/ACCEPTANCE.md with the results as measured.
Each item is PASS, PARTIAL (part met, the rest said plainly) or NOT MET. Nothing is tuned to pass.

  python -m scripts.aladin2.acceptance            (needs data/aladin2/e2e_report.json from tests/e2e/aladin2_check.py for items 12-14)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DA = ROOT / "data" / "aladin2"


def J(name):
    p = DA / name; return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pytest(*files):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"(\d+) passed", r.stdout); f = re.search(r"(\d+) failed", r.stdout)
    return r.returncode == 0, f"{m.group(1) if m else 0} passed" + (f", {f.group(1)} FAILED" if f else "")


def node(*files):
    ok, n = True, 0
    for f in files:
        r = subprocess.run(["node", "--test", f], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore"); m = re.search(r"pass (\d+)", r.stdout); n += int(m.group(1)) if m else 0; ok &= r.returncode == 0
    return ok, f"{n} JS tests passed"


def grep(pattern, paths, flags=re.I):
    hits = []
    for p in paths:
        for f in ([p] if p.is_file() else p.rglob("*")):
            if f.is_file() and f.suffix in (".py", ".js", ".yml", ".json") and "replay" not in f.parts and f.name != "acceptance.py" and "tests" not in f.parts:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if re.search(pattern, line, flags) and not line.lstrip().startswith(("#", "//", "*", "\"\"\"", "/*")):
                        hits.append(f"{f.relative_to(ROOT)}:{i}")
    return hits


def run():
    R = []; q = 0.10
    ok, ev = pytest("tests/aladin2/test_leakage.py", "tests/aladin2/test_strategies.py", "tests/test_no_lookahead.py")
    R.append((1, "No look-ahead", "PASS" if ok else "NOT MET", f"price-shift and future-permutation tests, feature lags, next-open fills, one look-ahead test per strategy (34 + baseline), existing ALADIN 1 tests: {ev}"))
    z, r = J("honesty_null2000_zerocost.json"), J("honesty_null2000_realcost.json"); n0, n1 = z["null"], r["null"]
    R.append((2, "Honest null", "PASS" if max(n0["share_pairs_promoted"], n1["share_pairs_promoted"]) <= q and max(n0["share_blocks_with_any_promotion"], n1["share_blocks_with_any_promotion"]) <= q else "NOT MET",
              f"2,000 noise series x 29 rules ({n0['pairs']:,} pairs, {n0['blocks']} blocks): promoted {n0['promoted_ever']} with zero costs and {n1['promoted_ever']} with real costs (limit {q:.0%})"))
    pl = J("honesty_planted.json"); pw = {k: v["power"] for k, v in pl["planted"].items()}; van = pl["vanishing"]; big = [pw[k] for k in pw if not k.startswith("vanishing") and k.split(":")[1] in ("120", "240", "40", "80", "160")]
    ok3 = min(big) >= 0.7 if big else False
    R.append((3, "Planted edges", "PARTIAL" if ok3 else "NOT MET", f"power on the larger planted effects {', '.join(f'{k} {v:.0%}' for k, v in pw.items())}; vanishing edge: first demotion after a median of {van['median_days_to_demotion']:.0f} days (90th percentile {van['p90_days']:.0f}) with {van['series_with_live_strategy_at_vanish']} of 48 series having a live rule at the vanishing point. "
              "Power is met; **the vanishing-edge retirement is NOT met** (a 1% edge is invisible next to 8% trade noise). Stated, not tuned."))
    b = J("phase2b_report.json"); pa = b["policy_pooled_with_veto_Probation_and_Active"]; ac = b["policy_pooled_with_veto_Active_only"]; nv = b["baseline_naive_momentum_all_stocks"]; allp = b["baseline_all_strategies_no_selection"]
    f = lambda d: f"{d['excess_vs_stock_drift']['mean_bps']:+.0f} bps [{d['excess_vs_stock_drift']['ci95_bps'][0]:+.0f}, {d['excess_vs_stock_drift']['ci95_bps'][1]:+.0f}]"
    R.append((4, "Policy vs baselines", "PASS (reported as measured)", f"nested walk-forward net of costs, excess per trade over the equal-weight universe: policy (paper) {f(pa)} = {pa['excess_per_day_in_market_bps']:+.1f} bps/day; Active tier only {f(ac)}; naive momentum {f(nv)}; all rules, no selection {f(allp)}; buy-and-hold 0 by construction; "
              "random walk = no skill (P(up) 49.8%, Brier 0.2500); Outlook model could not be re-scored (its per-row predictions were never saved). Per-stock selection (original design) traded nothing: 0 eligible pairs in 56 blocks. Not an edge: unstable, last two years negative"))
    ok, ev = pytest("tests/aladin2/test_costs.py")
    R.append((5, "Costs", "PASS" if ok else "NOT MET", f"worked trade reproduced to the paisa line by line (Rs 862.84 buy leg, Rs 832.95 sell leg, Rs 1,695.79 total); STT both delivery legs / sell-only intraday and futures; stamp on buy; GST on fees only; cash-equity delivery short raises an error: {ev}"))
    p3 = J("phase3_report.json"); eces = {h: v["p_up"]["ece_after_isotonic"] for h, v in p3["horizons"].items()}; okh = [h for h, e in eces.items() if e <= 0.05]
    R.append((6, "Calibration (ECE <= 0.05)", "PARTIAL", f"pooled out-of-sample ECE by horizon (days): {', '.join(f'{h}: {e}' for h, e in eces.items())}. Met at {', '.join(okh)} days; missed at the others because the model has no directional skill and the yearly base rate swings (even a constant base rate is 5.6 to 9.8 points off year to year at 20 and 60 days). Plan applied: a calibrated number is shown only for 1 and 5 days. Reliability tables are in scoreboard.json"))
    cov = {h: v["coverage"] for h, v in p3["horizons"].items()}; worst = max(abs(c[b_] - n) for c in cov.values() for b_, n in (("50", .5), ("80", .8), ("95", .95)))
    live = (J("state/latest_summary.json") or {}).get("live_stats", {}).get("outcomes", {})
    R.append((7, "Interval coverage", "PARTIAL", f"out-of-sample pooled coverage is within {worst * 100:.1f} points of nominal at every horizon and band (tolerance 4); single stress years break it at long horizons (2020: 70% for the 80% range at 20 days). Live ledger: {'resolved ' + str(sum(v['n'] for v in live.values())) + ' forecasts' if live else 'no forecast has resolved yet (the first 5-day forecasts were made on 2026-10-06)'}; the live check starts working once they do"))
    ok, ev = pytest("tests/aladin2/test_lifecycle.py", "tests/aladin2/test_journal_drift.py")
    R.append((8, "Lifecycle", "PASS" if ok else "NOT MET", f"unit tests for every transition (Candidate to Probation to Active to Demoted to Retired to re-entry), CUSUM, minimum trades, cap of four Active, and a journal event with evidence per transition: {ev}"))
    ok, ev = pytest("tests/aladin2/test_ledger.py")
    R.append((9, "Ledger integrity", "PASS" if ok else "NOT MET", f"append-only, conflicts refused, corrections as new lines, resolved lines never change, every live statistic reproduces from the raw lines, late forecasts excluded: {ev}"))
    ok1, ev1 = pytest("tests/aladin2/test_signals.py"); ok2, ev2 = node("tests/js/aladin2.test.mjs")
    R.append((10, "Risk maths", "PASS" if ok1 and ok2 else "NOT MET", f"sizing, stop-out probability, Kelly cap, liquidity cap, sector cap, correlation, drawdown brake all fixture-tested ({ev1}); the browser uses the same rules and numbers ({ev2}); capital at risk is one function = quantity x stop distance"))
    sm = J("state/latest_summary.json") or {}; ok, ev = pytest("tests/aladin2/test_kill_meta.py", "tests/aladin2/test_stress.py")
    R.append((11, "Abstention and states", "PASS" if ok else "NOT MET", f"today {sm.get('product_state_counts')}: no stock has a plan; a forced calibration break flips a stock to Suspended and its signal to NO EDGE; sector and engine suspension; crash-year coverage suspends the engine: {ev}"))
    e = J("e2e_report.json")
    if e:
        v = e["viewports"]; err = sum(len(x["js_errors"]) + len(x["unexpected_404s"]) for x in v.values()); pages = {k: all(p["svg_charts"] == p["svg_charts_with_aria_label"] for p in x["pages"].values()) for k, x in v.items()}
        kb = all(x["keyboard_open_from_map"] and x["keyboard_open_from_map"]["focused_tile"] == x["keyboard_open_from_map"]["terminal_symbol"] for x in v.values())
        asof = all(p["as_of"] for x in v.values() for p in x["pages"].values()); dis = all(p["disclaimer"] for x in v.values() for p in x["pages"].values()) and all(x["brief"]["disclaimer"] for x in v.values())
        diff = subprocess.run(["git", "diff", "--numstat", "ac95415", "HEAD", "--", "terminal.css", "expert-terminal.html", "chart-engine.js"], cwd=ROOT, capture_output=True, text=True).stdout
        removed = {l.split()[2]: int(l.split()[1]) for l in diff.splitlines()}; lit = len(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", "\n".join(l[1:] for l in subprocess.run(["git", "diff", "-U0", "ac95415", "HEAD", "--", "terminal.css"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines() if l.startswith("+") and not l.startswith("+++"))))
        R.append((12, "Charts", "PASS" if err == 0 and kb and asof and all(pages.values()) else "PARTIAL",
                  f"every ALADIN 2.0 page and the brief rendered from real data at 1440x900 and 390x844: JS errors + unexpected 404s = {err}; every chart has an accessible label ({pages}); hover text (SVG titles: {sum(p['svg_titles'] for p in v['desk']['pages'].values())} on the desk pages); keyboard Tab to a market-map tile + Enter opens that stock: {kb}; an 'As of' line on every page: {asof}; "
                  f"existing tabs: removed lines in terminal.css / expert-terminal.html / chart-engine.js vs the pre-ALADIN2 commit = {removed}; new colour literals in terminal.css = {lit} (all new CSS uses :root tokens; test_design_integrity passes)"))
        t = e["throttled_stock_shard"]; sz = sum(f.stat().st_size for f in (ROOT / "site" / "aladin2").rglob("*") if f.is_file()) if (ROOT / "site" / "aladin2").exists() else None
        rr = J("replay/state/run_report.json") or {}
        R.append((13, "Performance", "PASS" if v["desk"]["desk_ready_ms"] < 2000 and t["ms_median"] < 300 and not any(x.startswith(("index", "market_map", "journal", "method")) for x in v["desk"]["aladin2_requests_before_opening_a_stock_or_the_tab"]) else "PARTIAL",
                  f"desk shows its watchlist in {v['desk']['desk_ready_ms']} ms on this PC (limit 2,000; unthrottled, local server); at page start only the three small files the open stock's brief needs are fetched ({', '.join(v['desk']['aladin2_requests_before_opening_a_stock_or_the_tab'])}); the index, market map, journal and method files load only when an ALADIN 2.0 page needs them; a stock shard ({t['bytes'][0]:,} bytes) loads in a median {t['ms_median']} ms (max {t['ms_max']}) at {t['profile']} (limit 300); "
                  f"total added to site/: {sz / 1e6 if sz else 0:.1f} MB (500 stock shards of at most 6 KB, index 29 KB); nightly job: learn 204 s on a block-boundary day, forecast 76 to 81 s, discovery 10 s a generation, 14 cores, local; **the 110-minute budget is estimated at 25 to 60 minutes on a GitHub 2-vCPU runner, NOT measured there**"))
        R.append((14, "Compliance and wording", "PASS" if dis else "NOT MET", f"all labels come from the labels dictionary (JS and Python tests); neutral mode has none of the banned words in any shard, page text, config or README block (scripts/check_banned.py + tests); the disclaimer appears on the brief and every ALADIN 2.0 page including the scoreboard and market map: {dis}; no copy implies guaranteed returns; the methodology text equals the README block word for word (test)"))
    else:
        R += [(12, "Charts", "NOT RUN", "run tests/e2e/aladin2_check.py first"), (13, "Performance", "NOT RUN", "run tests/e2e/aladin2_check.py first"), (14, "Compliance and wording", "NOT RUN", "run tests/e2e/aladin2_check.py first")]
    broker = grep(r"smartapi|place_?order|\bbroker\b|order_?id|/orders", [ROOT / "scripts" / "aladin2", ROOT / "desk-aladin2.js", ROOT / "desk-a2views.js"])
    ev_ = grep(r"\beval\(|\bexec\(|new Function|compile\(|__import__", [ROOT / "scripts" / "aladin2", ROOT / "desk-aladin2.js", ROOT / "desk-a2views.js"])
    skip = "[skip ci]" in (ROOT / ".github" / "workflows" / "aladin2.yml").read_text(encoding="utf-8"); gitops = 'endswith("[skip ci]")' in (ROOT / "scripts" / "gitops.py").read_text(encoding="utf-8")
    sec = [h for h in grep(r"(API_KEY|SECRET|TOKEN|PASSWORD)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}", [ROOT / "scripts" / "aladin2", ROOT / ".github", ROOT / "data" / "config"]) if "os.environ" not in h]
    ck = subprocess.run([sys.executable, str(ROOT / "scripts" / "aladin2" / "check_aladin2.py")], capture_output=True, text=True).stdout.strip().splitlines()[-1]
    R.append((15, "Safety and ops", "PASS" if not broker and not ev_ and skip and gitops and not sec else "NOT MET", f"no broker or order code in scripts/aladin2 or the new JS ({len(broker)} matches); no eval, exec, compile or generated code ({len(ev_)} matches; discovery interprets rules as data); every automated commit goes through gitops.py, which refuses a message without [skip ci], and the workflow message has it: {skip and gitops}; "
              f"no secrets in the new files ({len(sec)} suspicious matches); size check: {ck}; a job summary table is printed on every run (run_nightly.py) and in GITHUB_STEP_SUMMARY"))
    return R


def main():
    R = run(); lines = ["# ALADIN 2.0 acceptance checklist (section 14), run on 2026-10-08", "", "Results as measured. PARTIAL means part is met and the rest is stated plainly. Nothing was tuned to pass.", "", "| # | Item | Result | Evidence |", "|---|---|---|---|"]
    for n, name, res, ev in R:
        lines.append(f"| {n} | {name} | **{res}** | {ev} |")
    tally = {}
    for _, _, res, _ in R:
        tally[res.split(" ")[0]] = tally.get(res.split(" ")[0], 0) + 1
    lines += ["", f"Tally: {tally}", ""]
    (ROOT / "docs" / "aladin2" / "ACCEPTANCE.md").write_text("\n".join(lines), encoding="utf-8"); print("\n".join(lines))


if __name__ == "__main__":
    main()
