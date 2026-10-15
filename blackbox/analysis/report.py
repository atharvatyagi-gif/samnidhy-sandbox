"""Shareable export: results/<run>/report.html (scorecard, strategy detail, GAPs, recommendations) plus CSVs of every table."""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.io as pio

BANNER = "SIMULATED RESULTS, NOT PREDICTIONS OF REAL PERFORMANCE."
NAMES = {"S01_systemic_crash": "1 Systemic crash", "S02_flash_crash": "2 Flash crash", "S03_war": "3 War", "S11_black_swan_stock": "3b Black swan (one stock)",
         "S04_sanctions_trade_war": "4 Sanctions / trade war", "S05_rate_shock": "5 Rate shock", "S12_mixed_regimes": "5b Mixed regimes", "S06_banking_stress": "6 Banking stress",
         "S07_prolonged_bear": "7 Prolonged bear", "S08_sideways_chop": "8 Sideways chop", "S09_steady_bull": "9 Steady bull", "S10_dead_flat": "10 Dead flat"}


def label(sid: str) -> str:
    return NAMES.get(sid, sid)


def verdicts(summary: pd.DataFrame) -> pd.DataFrame:
    """One headline verdict per strategy from its medians across the ladder."""
    out = []
    S = summary[~summary["strategy"].str.startswith("buy_hold")]
    for st, g in S.groupby("strategy"):
        g = g.set_index("scenario"); crash = g.loc[[c for c in ("S01_systemic_crash", "S02_flash_crash", "S06_banking_stress") if c in g.index]]
        calm = g.loc[[c for c in ("S09_steady_bull", "S08_sideways_chop", "S10_dead_flat") if c in g.index]]
        v = []
        if (g["p_beat_random"] < 0.5).sum() >= len(g) / 2:
            v.append("Loses to random entry")
        if len(crash) and (crash["max_dd"] > -0.20).all() and (crash["total_ret"] > -0.10).all():
            v.append("Survives crashes")
        elif len(crash) and (crash["max_dd"] < -0.30).any():
            v.append("Hurt badly in crashes")
        if len(calm) and (calm["sharpe"] > 0.5).all() and len(crash) and (crash["sharpe"] < 0).any():
            v.append("Only works in calm markets")
        if (g["sharpe"] > 0).sum() >= 0.75 * len(g):
            v.append("Positive in most markets")
        if (g["sharpe"] < 0).sum() >= 0.75 * len(g):
            v.append("Negative in most markets")
        out.append({"strategy": st, "verdict": " · ".join(v) or "Mixed", "median_sharpe_all": float(g["sharpe"].median()), "worst_max_dd": float(g["max_dd"].min()),
                    "scenarios_beating_random": int((g["p_beat_random"] >= 0.5).sum()), "scenarios": len(g)})
    return pd.DataFrame(out)


def export(d: Path, summary: pd.DataFrame, gaps: pd.DataFrame, recs: pd.DataFrame, modules: pd.DataFrame) -> Path:
    d = Path(d); summary.to_csv(d / "summary.csv", index=False); gaps.to_csv(d / "gaps.csv", index=False); recs.to_csv(d / "recommendations.csv", index=False)
    if modules is not None:
        modules.to_csv(d / "modules.csv", index=False)
    v = verdicts(summary); v.to_csv(d / "verdicts.csv", index=False)
    s = summary.copy(); s["scenario_name"] = s["scenario"].map(label)
    order = [label(x) for x in sorted(s["scenario"].unique(), key=lambda z: (s[s.scenario == z]["severity"].iloc[0], z))]
    figs = []
    for metric, title, fmt in (("total_ret", "Median net return", ".0%"), ("max_dd", "Median maximum drawdown", ".0%"), ("sharpe", "Median Sharpe", ".2f")):
        piv = s.pivot_table(index="strategy", columns="scenario_name", values=metric)[order]
        figs.append(px.imshow(piv, text_auto=fmt, color_continuous_scale="RdYlGn", aspect="auto", title=title, zmin=-abs(piv.values).max() if metric != "max_dd" else -0.5,
                              zmax=abs(piv.values).max() if metric != "max_dd" else 0))
    parts = [f"<h1>Stress-Test Black Box</h1><p style='background:#7f1d1d;color:#fff;padding:10px;font-weight:700'>{BANNER}</p>",
             "<h2>Verdicts</h2>" + v.to_html(index=False, float_format=lambda x: f"{x:.2f}")]
    parts += [pio.to_html(f, include_plotlyjs="cdn" if i == 0 else False, full_html=False) for i, f in enumerate(figs)]
    parts.append("<h2>Recommendations</h2>" + (recs[["priority", "group_name", "what", "why", "effect"]].to_html(index=False) if len(recs) else "<p>None.</p>"))
    parts.append("<h2>GAPs and parameters</h2>" + (gaps[["strategy", "param", "default", "best_value", "verdict", "note"]].to_html(index=False) if len(gaps) else "<p>Not run.</p>"))
    page = ("<!doctype html><meta charset='utf-8'><title>Stress-Test Black Box report</title><style>body{font-family:Inter,system-ui,sans-serif;background:#0f172a;color:#e2e8f0;"
            "max-width:1200px;margin:auto;padding:16px}table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #334155;padding:4px 6px}</style>" + "".join(parts))
    f = d / "report.html"; f.write_text(page, encoding="utf-8"); return f
