"""Stress-Test Black Box dashboard:  streamlit run blackbox/dashboard/app.py
Five tabs: Overview, Scenario explorer, Strategy detail, GAPs & parameters, Recommendations. Reads the newest run (blackbox/results/latest.txt).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blackbox.analysis import report as RP  # noqa: E402

# validated dark palette (dataviz reference instance, dark mode): categorical slots in fixed order; status colours reserved for the scorecard
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"
SURF, INK, INK2, GRID = "#1a1a19", "#f0efec", "#c3c2b7", "#383835"

st.set_page_config(page_title="Stress-Test Black Box", layout="wide")
st.markdown(f"""<style>.stApp{{background:#0d0d0d;color:{INK}}} section[data-testid=stSidebar]{{background:{SURF}}}
.bb-banner{{background:{CRIT};color:#fff;padding:10px 14px;border-radius:6px;font-weight:700;letter-spacing:.02em;margin-bottom:10px}}</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load(d: str) -> dict:
    p = Path(d); r = {}
    for k in ("summary", "main", "paths", "gaps", "recommendations", "modules", "sweeps"):
        f = p / f"{k}.parquet"; r[k] = pd.read_parquet(f) if f.exists() else pd.DataFrame()
    return r


def latest() -> Path | None:
    f = ROOT / "blackbox" / "results" / "latest.txt"
    return Path(f.read_text(encoding="utf-8").strip()) if f.exists() else None


def layout(fig: go.Figure, title: str, h: int = 380) -> go.Figure:
    fig.update_layout(title=title, height=h, paper_bgcolor=SURF, plot_bgcolor=SURF, font=dict(color=INK2, family="Inter, system-ui"), title_font_color=INK,
                      margin=dict(l=50, r=20, t=50, b=40), legend=dict(orientation="h", y=-0.15), hovermode="x unified")
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID); fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


def status_cell(v, metric):
    if pd.isna(v):
        return ""
    if metric == "max_dd":
        c = GOOD if v > -0.15 else WARN if v > -0.30 else CRIT
    elif metric == "sharpe":
        c = GOOD if v > 0.5 else WARN if v > 0 else CRIT
    else:
        c = GOOD if v > 0.05 else WARN if v > -0.05 else CRIT
    return f"background-color:{c};color:#0b0b0b;font-weight:600"


st.markdown('<div class="bb-banner">SIMULATED RESULTS, NOT PREDICTIONS OF REAL PERFORMANCE.</div>', unsafe_allow_html=True)
d = latest()
if d is None or not (d / "summary.parquet").exists():
    st.error("No results yet. Run `python blackbox/run.py --quick` first."); st.stop()
R = load(str(d)); S, M = R["summary"], R["main"]
S["scenario_name"] = S["scenario"].map(RP.label)
scen_order = list(S.drop_duplicates("scenario").sort_values(["severity", "scenario"])["scenario"])
strats = sorted(s for s in S["strategy"].unique() if not s.startswith("buy_hold"))

with st.sidebar:
    st.header("Controls")
    sc_sel = st.selectbox("Scenario", scen_order, format_func=RP.label)
    st_sel = st.selectbox("Strategy", strats)
    seeds = int(M.groupby(["strategy", "scenario"]).size().max()) if len(M) else 0
    st.caption(f"Run: `{d.name}` · {seeds} seeds a cell · all SIMULATED")
    new_seeds = st.number_input("Seeds for a re-run", min_value=5, max_value=1000, value=seeds or 20, step=5)
    if st.button("Re-run simulation"):
        import subprocess
        import yaml
        cfg = yaml.safe_load(open(ROOT / "blackbox" / "config.yaml", encoding="utf-8")); cfg["run"]["seeds"] = int(new_seeds)
        tmp = ROOT / "blackbox" / "results" / "rerun_config.yaml"; tmp.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        with st.spinner("Simulating... (cached cells are reused)"):
            subprocess.call([sys.executable, str(ROOT / "blackbox" / "run.py"), "--no-dashboard", "--config", str(tmp)])
        st.cache_data.clear(); st.rerun()
    if st.button("Export report"):
        f = RP.export(d, S.drop(columns=["scenario_name"]), R["gaps"], R["recommendations"], R["modules"] if len(R["modules"]) else None)
        st.success(f"Written: {f} (and CSVs of every table)")

t1, t2, t3, t4, t5 = st.tabs(["Overview", "Scenario explorer", "Strategy detail", "GAPs & parameters", "Recommendations"])

with t1:
    st.subheader("Verdicts")
    st.dataframe(RP.verdicts(S), hide_index=True, use_container_width=True)
    for metric, title, fmt in (("total_ret", "Median net return", "{:+.0%}"), ("max_dd", "Median maximum drawdown", "{:.0%}"), ("sharpe", "Median Sharpe", "{:+.2f}")):
        piv = S.pivot_table(index="strategy", columns="scenario_name", values=metric)[[RP.label(x) for x in scen_order]]
        st.markdown(f"**{title}** · severity 1 (catastrophic) on the left to 10 (flat) on the right · green / amber / red with the value in every cell")
        st.dataframe(piv.style.format(fmt).map(lambda v, m=metric: status_cell(v, m)), use_container_width=True)
    if len(R["modules"]):
        st.subheader("Module checks (median over seeds)")
        mo = R["modules"]; cols = [c for c in mo.columns if c.startswith(("ic_", "hit_", "standin_", "geo_lag", "geo_false", "flow_lag", "flow_false"))]
        tab = mo.groupby("scenario")[cols].median().reindex(scen_order); tab.index = [RP.label(x) for x in tab.index]
        st.dataframe(tab.style.format("{:+.3f}", na_rep="--"), use_container_width=True)
        st.caption("ic_* = rank correlation of each Advanced-page signal with the next 20 days (0 = no edge). standin_* = the ALADIN stand-in's calibration. "
                   "geo/flow lag = days between the indicator's first 3-day risk-off reading and a 5% fall after the event (negative = it led); false = share of calm days it flagged.")

with t2:
    P = R["paths"]; pp = P[P["scenario"] == sc_sel]
    st.subheader(RP.label(sc_sel))
    mk = np.array([v for v in pp[pp["series"] == "market_index"]["values"]], dtype=object)
    if len(mk):
        A = np.vstack([np.asarray(v, float) for v in mk]); x = np.arange(A.shape[1]); q = np.nanpercentile(A, [5, 25, 50, 75, 95], axis=0)
        f = go.Figure()
        f.add_trace(go.Scatter(x=x, y=q[4], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        f.add_trace(go.Scatter(x=x, y=q[0], fill="tonexty", fillcolor="rgba(57,135,229,0.15)", line=dict(width=0), name="5-95% of seeds"))
        f.add_trace(go.Scatter(x=x, y=q[3], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        f.add_trace(go.Scatter(x=x, y=q[1], fill="tonexty", fillcolor="rgba(57,135,229,0.30)", line=dict(width=0), name="25-75%"))
        f.add_trace(go.Scatter(x=x, y=q[2], line=dict(color=SERIES[0], width=2), name="median"))
        st.plotly_chart(layout(f, f"Market index across {A.shape[0]} seeds (start = 1)"), use_container_width=True)
    pick = st.multiselect("Strategies to show", strats, default=strats[:4])
    f = go.Figure(); g = go.Figure()
    for k, s in enumerate(strats):
        if s not in pick:
            continue
        rows = [np.asarray(v, float) for v in pp[pp["series"] == s]["values"]]
        if not rows:
            continue
        n = min(len(r) for r in rows); A = np.vstack([r[:n] for r in rows]); med = np.median(A, axis=0)
        dd = np.median(A / np.maximum.accumulate(A, axis=1) - 1, axis=0); col = SERIES[strats.index(s) % len(SERIES)]
        f.add_trace(go.Scatter(y=med, name=s, line=dict(color=col, width=2))); g.add_trace(go.Scatter(y=dd, name=s, line=dict(color=col, width=2)))
    st.plotly_chart(layout(f, "Median equity curve (start = 1)"), use_container_width=True)
    st.plotly_chart(layout(g, "Median drawdown"), use_container_width=True)
    tr = np.concatenate([np.asarray(v, float) for v in pp[pp["series"] == f"{st_sel}__trades"]["values"]] or [np.array([])])
    if len(tr):
        h = go.Figure(go.Histogram(x=tr * 100, nbinsx=60, marker_color=SERIES[strats.index(st_sel) % len(SERIES)], marker_line=dict(color=SURF, width=1)))
        st.plotly_chart(layout(h, f"{st_sel}: net return per trade, %, all kept seeds ({len(tr)} trades)", 320).update_layout(hovermode="closest"), use_container_width=True)

with t3:
    g = S[S["strategy"] == st_sel].set_index("scenario").reindex(scen_order); g.index = [RP.label(x) for x in g.index]
    st.subheader(st_sel)
    cols = ["total_ret", "ann_ret", "vol", "sharpe", "sharpe_ci_lo", "sharpe_ci_hi", "sortino", "calmar", "max_dd", "dd_days", "worst_day", "worst_week", "var5", "cvar5",
            "final_p5", "final_p50", "final_p95", "p_ruin", "p_beat_bh", "p_beat_random", "gross_ret", "cost_drag", "turnover", "exposure"]
    st.markdown("**Returns and risk (median over seeds; Sharpe with its 95% bootstrap interval; final equity percentiles)**")
    st.dataframe(g[[c for c in cols if c in g]].style.format("{:+.3f}", na_rep="--"), use_container_width=True)
    tcols = ["n_trades", "avg_pnl", "avg_pnl_pct", "median_pnl_pct", "win_rate", "win_rate_ci_lo", "win_rate_ci_hi", "avg_win_pct", "avg_loss_pct", "payoff", "profit_factor",
             "expectancy_pct", "avg_hold", "max_losing_streak", "trades_per_year", "largest_loss"]
    st.markdown("**Average-trade statistics**")
    st.dataframe(g[[c for c in tcols if c in g]].style.format("{:,.3f}", na_rep="--"), use_container_width=True)
    b = go.Figure(go.Bar(x=list(g.index), y=g["sharpe"], marker_color=SERIES[0],
                         error_y=dict(type="data", symmetric=False, array=(g["sharpe_ci_hi"] - g["sharpe"]).fillna(0).values, arrayminus=(g["sharpe"] - g["sharpe_ci_lo"]).fillna(0).values, color=INK2)))
    st.plotly_chart(layout(b, "Median Sharpe by scenario (bars: 95% bootstrap interval over seeds)").update_layout(hovermode="closest"), use_container_width=True)
    sw = R["sweeps"]
    if len(sw):
        sws = sw[sw["strategy"] == st_sel]
        for prm in [p for p in sws["param"].unique() if p != "default"]:
            h = pd.concat([sws[sws["param"] == "default"].assign(value="terminal value"), sws[sws["param"] == prm]])
            piv = h.groupby(["value", "scenario"])["sharpe"].median().unstack().reindex(columns=scen_order)
            piv.columns = [RP.label(c) for c in piv.columns]
            hm = go.Figure(go.Heatmap(z=piv.values, x=list(piv.columns), y=[str(v) for v in piv.index], colorscale=[[0, "#e66767"], [0.5, "#383835"], [1, "#3987e5"]], zmid=0,
                                      text=np.where(np.isfinite(piv.values.astype(float)), np.round(piv.values.astype(float), 2).astype(str), ""), texttemplate="%{text}", hovertemplate="%{y} · %{x}: Sharpe %{z:.2f}<extra></extra>"))
            hm.update_yaxes(type="category", title=prm); hm.update_xaxes(type="category")         # "35" is a label here, not a number on an axis
            st.plotly_chart(layout(hm, f"Sensitivity: {prm} (median Sharpe; red < 0 < blue)", 160 + 34 * len(piv)).update_layout(hovermode="closest"), use_container_width=True)

with t4:
    G = R["gaps"]
    st.subheader("Every undefined or hard-coded parameter: tested range, most robust value, sensitivity")
    if len(G):
        st.dataframe(G[["strategy", "param", "default", "tested", "best_value", "verdict", "default_typical_sharpe", "best_typical_sharpe", "sensitivity", "note"]],
                     hide_index=True, use_container_width=True)
    inv = json.loads((ROOT / "blackbox" / "inventory.json").read_text(encoding="utf-8"))
    st.markdown("**GAPs found in the terminal's code (blackbox/INVENTORY.md)**")
    st.dataframe(pd.DataFrame(inv["gaps"]), hide_index=True, use_container_width=True)

with t5:
    RE = R["recommendations"]
    st.subheader(f"{len(RE)} changes the evidence supports, most severe first")
    if len(RE):
        for grp, g in RE.groupby("group_name", sort=False):
            st.markdown(f"### {grp}")
            for _, r in g.iterrows():
                st.markdown(f"**[{r['priority']}]** {r['what']}  \n*Why:* {r['why']}  \n*Expected effect:* {r['effect']}")
    st.caption("Rules: blackbox/analysis/recommendations.py (thresholds in config.yaml `recommend`). The terminal itself is not changed by the Black Box.")
