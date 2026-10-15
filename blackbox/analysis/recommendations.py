"""Rules-based recommendations: every change the simulated evidence supports, each with what to change, why (the number), the expected effect,
a priority and a group: (a) strategy, (b) risk control, (c) parameter defaults, (d) terminal / UI / code, (e) remove.
Transparent rules only (thresholds in config.yaml `recommend`); nothing is tuned to make a strategy look good. The terminal is NOT changed here.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

GROUPS = {"a": "Strategy changes", "b": "Risk-control changes", "c": "Parameter defaults to adopt", "d": "Terminal / UI / code changes", "e": "Things to remove"}
ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
CRASH = ("S01_systemic_crash", "S02_flash_crash", "S06_banking_stress", "S12_mixed_regimes")
QUIET = ("S08_sideways_chop", "S10_dead_flat")


def _rec(out, group, priority, what, why, effect, strategy=None, scenario=None, param=None):
    out.append({"group": group, "group_name": GROUPS[group], "priority": priority, "what": what, "why": why, "effect": effect,
                "strategy": strategy, "scenario": scenario, "param": param})


def build(summary: pd.DataFrame, gaps: pd.DataFrame, modules: pd.DataFrame, inventory: dict, cfg: dict) -> pd.DataFrame:
    R = cfg["recommend"]; out: list = []
    S = summary[~summary["strategy"].str.startswith("buy_hold")]
    for strat, g in S.groupby("strategy"):
        g = g.set_index("scenario"); n = len(g)
        lose_rand = g.index[g["p_beat_random"] < 0.5].tolist(); neg = g.index[g["sharpe"] < 0].tolist()
        if len(lose_rand) >= R["loses_to_random_min_scenarios"]:
            pr = "Critical" if len(lose_rand) >= n / 2 else "High"
            _rec(out, "a", pr, f"{strat}: redesign the signal or the rules - it does not beat random entry",
                 f"Beats a random-entry trader with the same trade count and holding period in fewer than half the seeds in {len(lose_rand)} of {n} scenarios "
                 f"({', '.join(x.split('_', 1)[1] for x in lose_rand[:5])}{'...' if len(lose_rand) > 5 else ''}).",
                 "Without an edge over random timing, its results are its market exposure plus costs.", strat)
        if len(lose_rand) >= 0.75 * n and len(neg) >= 0.66 * n:
            _rec(out, "e", "High", f"Remove {strat} (or keep it only as a documented failed experiment)",
                 f"Median Sharpe below zero in {len(neg)} of {n} scenarios and no edge over random in {len(lose_rand)}.", "Fewer moving parts; nothing of value lost.", strat)
        crash = g.loc[[c for c in CRASH if c in g.index]]
        if len(crash) and crash["max_dd"].min() < R["crash_max_dd_limit"]:
            w = crash["max_dd"].idxmin()
            _rec(out, "b", "Critical" if crash["max_dd"].min() < 1.5 * R["crash_max_dd_limit"] else "High",
                 f"{strat}: add a volatility-scaled position cap or a portfolio drawdown brake (halve new sizes when the account is 10% below its peak)",
                 f"Median maximum drawdown {crash.loc[w, 'max_dd']:.0%} in {w.split('_', 1)[1]} (limit {R['crash_max_dd_limit']:.0%}); 5th-percentile final equity "
                 f"{crash.loc[w, 'final_p5']:.2f}x.", "Smaller losses in crashes at the price of lower exposure in calm markets.", strat, w)
        if g["p_ruin"].max() > 0:
            w = g["p_ruin"].idxmax()
            _rec(out, "b", "Critical", f"{strat}: hard account-level loss limit", f"Ruin (equity below {cfg['run']['ruin_floor']:.0%} of the start) in "
                 f"{g.loc[w, 'p_ruin']:.0%} of seeds in {w.split('_', 1)[1]}.", "Caps the worst case.", strat, w)
        quiet = g.loc[[c for c in QUIET if c in g.index]]
        for sc, r in quiet.iterrows():
            share = r.get("cost_share_of_gross")
            if r["gross_ret"] > 0 and np.isfinite(share) and share > R["cost_share_limit"]:
                _rec(out, "a", "High", f"{strat}: trade less in quiet markets (widen the entry threshold or add a no-trade band)",
                     f"Costs take {share:.0%} of the gross profit in {sc.split('_', 1)[1]} (median {r['cost_drag']:.1%} of the account a year, turnover {r['turnover']:.1f}x).",
                     "Most of the cost drag removed where the edge is smallest.", strat, sc)
            elif r["gross_ret"] <= 0 and r["cost_drag"] > 0.02:
                _rec(out, "a", "Medium", f"{strat}: costs on top of no gross edge in {sc.split('_', 1)[1]}",
                     f"Gross return {r['gross_ret']:+.1%} and costs {r['cost_drag']:.1%} of the account a year.", "A regime filter that stands aside in flat markets saves the costs.", strat, sc)
        bs = g.loc["S11_black_swan_stock"] if "S11_black_swan_stock" in g.index else None
        if bs is not None and bs["largest_loss"] < 0 and strat.startswith("aladin"):
            _rec(out, "b", "Medium", f"{strat}: per-stock overnight-gap protection: cap a single position below the 20% the terminal allows",
                 f"In the single-stock -60% gap the median largest single loss was {bs['largest_loss']:,.0f} (of a {1_000_000 if 'small' not in strat else 10_000:,} account); a price stop cannot help when the price gaps.",
                 "A smaller per-stock cap limits the loss a gap can do.", strat, "S11_black_swan_stock")
    # parameters
    if gaps is not None and len(gaps):
        for _, r in gaps.iterrows():
            gain = r["best_typical_sharpe"] - r["default_typical_sharpe"]
            if r["param"] in ("ic", "cost_mult", "roundtrip_cost"):
                continue                                                                    # assumptions about the world, not settings to adopt
            if r["best_value"] != r["default"] and gain > 0.1 and r["verdict"] != "FRAGILE":
                _rec(out, "c", "High" if gain > 0.3 and r["verdict"] == "ROBUST" else "Medium", f"{r['strategy']}: set {r['param']} = {r['best_value']} (now {r['default']})",
                     f"Typical Sharpe across scenarios {r['default_typical_sharpe']:+.2f} -> {r['best_typical_sharpe']:+.2f}; at least as good in {r['wins']} of {r['scenarios']} scenarios ({r['verdict'].lower()}).",
                     "Better across market types, not just one.", r["strategy"], None, r["param"])
            if r["sensitive"]:
                _rec(out, "c", "Medium", f"{r['strategy']}: {r['param']} is fragile - test a wider range before relying on {r['default']}",
                     f"A move to the neighbouring tested value changes the typical Sharpe by {r['sensitivity']:+.2f}.", "Avoids a setting that only works by luck.", r["strategy"], None, r["param"])
        for strat in gaps["strategy"].unique():
            ic = gaps[(gaps["strategy"] == strat) & (gaps["param"] == "ic")]
            if len(ic):
                t = json.loads(ic.iloc[0]["table"]); zero = next((x for x in t if x["value"] == 0.0), None); d = ic.iloc[0]
                if zero is not None:
                    _rec(out, "a", "Medium", f"{strat}: its results depend on the model's skill - track live skill and stop the strategy if it falls",
                         f"Typical Sharpe {d['default_typical_sharpe']:+.2f} at the calibrated skill against {zero['typical']:+.2f} with no skill (score = noise).",
                         "A live skill monitor (rolling rank correlation of the score with realised returns) catches decay before the account does.", strat, None, "ic")
    # modules
    if modules is not None and len(modules):
        for key, name, path in (("geo", "Geopolitical news-attention index", "scripts/geo_tension.py"), ("flow", "Institutional flow score", "scripts/aladin_sentiment_engine.py flow_score")):
            if f"{key}_lag_days" not in modules:
                continue
            lag = modules[f"{key}_lag_days"].median(); far = modules[f"{key}_false_alarm_rate"].median()
            if (np.isfinite(lag) and lag >= R["indicator_lag_days"]) or far > 0.1:
                _rec(out, "d", "High", f"{name}: show it as information only; do not use it as a risk-off signal ({path})",
                     f"Median timing against simulated drawdowns {lag:+.0f} days (positive = after the fall started); it reads risk-off on {far:.0%} of calm days.",
                     "No false comfort from an indicator that does not lead.", None, None, key)
        for sig in ("above_200", "golden_cross", "mom_12_1", "near_52w_high", "low_vol"):
            col = f"ic_{sig}"
            if col in modules:
                m = modules.groupby("scenario")[col].mean(); pos = int((m > 0.02).sum())
                if pos <= 3:
                    _rec(out, "d", "Low", f"Advanced page signal '{sig}': label it descriptive, not predictive (scripts/live_technicals.py)",
                         f"Rank correlation with the next 20 days above 0.02 in only {pos} of {len(m)} scenarios (mean {m.mean():+.3f}).", "Honest labelling.", None, None, sig)
    for g in inventory.get("gaps", []):
        if g.get("terminal_change"):
            _rec(out, "d", g.get("priority", "Low"), g["terminal_change"], g.get("why", ""), g.get("effect", ""), None, None, g.get("name"))
    df = pd.DataFrame(out)
    if len(df):
        df["rank"] = df["priority"].map(ORDER); df = df.sort_values(["rank", "group", "strategy"], na_position="last").drop(columns="rank").reset_index(drop=True)
    return df
