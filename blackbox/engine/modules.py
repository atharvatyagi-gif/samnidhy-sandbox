"""Per-module checks: do the terminal's scoring tools have an edge in each scenario, and do its risk indicators turn BEFORE a drawdown or after it?

  price signals   scripts/live_technicals.py analyse() lines 81-145: above the 200-day average, 50/200 golden cross, 12-1 momentum, nearness to the
                  52-week high, low 1-year volatility. Measured: rank correlation with the next 20 days' return across stocks (IC), averaged over the year,
                  and the hit rate of "above the 200-day average" (share of stocks above it that then rose, minus the same share for stocks below it).
  ALADIN stand-in the 10-day probability used by the paper trader (strategies/paper_trader_v1.py): calibration (predicted vs realised share of up moves,
                  by decile) and hit rate of the top decile. It is a stand-in with the calibrated skill, so this measures how much a model of that skill
                  degrades when shocks dominate, not the real LightGBM model.
  geo_tension     scripts/geo_tension.py score_region() (imported and run as is) fed synthetic headline rates and tone that follow the scenario's news
                  pressure (config `news`; news reacts on the shock day unless `lead_days` says otherwise: an ASSUMPTION, real news can lead or lag).
  flow_score      scripts/aladin_sentiment_engine.py flow_score() (imported and run as is) fed synthetic FII/DII net flows that move with the same day's market
                  return (FII sell into falls). Contemporaneous by construction, so it can only lag: the test measures how much its 5-day averaging adds.
Lead/lag: drawdown onset = first evaluated day the market index is 5% below its running peak; indicator onset = first day from 30 days before that on
which the indicator reads risk-off (geo score >= 65 "High"; flow score <= -0.5). Negative = the indicator turned FIRST.
"""
from __future__ import annotations

import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
_GT = _SE = None


def _terminal_modules():
    """Import the terminal's own geo_tension and sentiment engine (pure functions only are called)."""
    global _GT, _SE
    if _GT is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import geo_tension as gt
            _GT = gt
        except Exception as e:  # noqa: BLE001
            log.warning("geo_tension could not be imported: %s", e); _GT = False
        try:
            import aladin_sentiment_engine as se
            _SE = se
        except Exception as e:  # noqa: BLE001
            log.warning("aladin_sentiment_engine could not be imported: %s", e); _SE = False
    return _GT, _SE


def _rank_ic(x: np.ndarray, y: np.ndarray) -> float:
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 20:
        return np.nan
    a = pd.Series(x[ok]).rank().values; b = pd.Series(y[ok]).rank().values
    return float(np.corrcoef(a, b)[0, 1])


def price_signals(panel, step: int = 5, horizon: int = 20) -> dict:
    """IC of each live_technicals signal against the next `horizon` days' return, over the evaluated year."""
    c, h, l = panel.c, panel.h, panel.l
    s50 = pd.DataFrame(c).rolling(50, min_periods=50).mean().values; s200 = pd.DataFrame(c).rolling(200, min_periods=200).mean().values
    hi52 = pd.DataFrame(h).rolling(252, min_periods=200).max().values
    vol1y = pd.DataFrame(np.diff(np.log(c), axis=0, prepend=np.nan)).rolling(252, min_periods=200).std().values
    ics = {k: [] for k in ("above_200", "golden_cross", "mom_12_1", "near_52w_high", "low_vol")}; hit = []
    for t in range(panel.eval_start, panel.T - horizon, step):
        fwd = c[t + horizon] / c[t] - 1
        mom = c[t - 21] / c[t - 252] - 1 if t >= 252 else np.full(panel.N, np.nan)
        sig = {"above_200": (c[t] > s200[t]).astype(float), "golden_cross": (s50[t] > s200[t]).astype(float), "mom_12_1": mom,
               "near_52w_high": c[t] / hi52[t], "low_vol": -vol1y[t]}
        for k, v in sig.items():
            ics[k].append(_rank_ic(v, fwd))
        a = c[t] > s200[t]
        if a.any() and (~a).any():
            hit.append(float(np.mean(fwd[a] > 0) - np.mean(fwd[~a] > 0)))
    out = {f"ic_{k}": float(np.nanmean(v)) if len(v) else np.nan for k, v in ics.items()}
    out["hit_above_200"] = float(np.mean(hit)) if hit else np.nan
    return out


def standin_calibration(panel, ic: float, prob_scale: float = 0.035, horizon: int = 10) -> dict:
    """Paper-trader probability (0.52 + scale x stand-in score): expected calibration error over deciles and the top decile's hit rate."""
    pr = 0.52 + prob_scale * panel.score(horizon, ic); c = panel.c; P, Y = [], []
    for t in range(panel.eval_start, panel.T - horizon, 5):
        P.append(pr[t]); Y.append((c[t + horizon] > c[t]).astype(float))
    P, Y = np.concatenate(P), np.concatenate(Y); ok = np.isfinite(P) & np.isfinite(Y); P, Y = P[ok], Y[ok]
    q = np.quantile(P, np.linspace(0, 1, 11)); b = np.clip(np.searchsorted(q, P, side="right") - 1, 0, 9)
    ece = sum(abs(P[b == k].mean() - Y[b == k].mean()) * (b == k).mean() for k in range(10) if (b == k).any())
    top = b == 9
    return {"standin_ece": float(ece), "standin_top_hit": float(Y[top].mean()) if top.any() else np.nan, "standin_base_up": float(Y.mean()),
            "standin_top_edge": float(Y[top].mean() - Y.mean()) if top.any() else np.nan}


def event_day(panel) -> int | None:
    """The scenario's own event: the earliest shock start inside the evaluated year (None for bull / flat / chop and the regime chain)."""
    days = [sh.get("start", sh.get("day")) for sh in (panel.drawn or {}).get("shocks", []) if sh.get("type") not in ("drift", "chop", "regime_chain", "vol")]
    days = [d - panel.eval_start for d in days if d is not None and d > panel.eval_start]
    return min(days) if days else None


def _onsets(panel, series: np.ndarray, risk_off) -> dict:
    """Event-timed: drawdown onset = first day from the scenario's event on which the market is 5% below its level at the event; indicator onset = its
    first of 3 risk-off days IN A ROW from 10 days before the event (single noisy days are not a warning). lag = indicator - drawdown (negative = the indicator turned first). Without an event (bull, flat,
    chop, the regime chain) there is no lag, only false alarms. false_alarm_rate = share of calm days (no news pressure, market within 5% of its
    running peak) on which the indicator read risk-off anyway."""
    E = panel.eval_start; ix = panel.index[E - 1:]; dd = ix[1:] / np.maximum.accumulate(ix)[1:] - 1
    flag = np.array([bool(risk_off(x)) if x is not None and np.isfinite(x) else False for x in series[E:]])
    calm = (dd > -0.05) & ((panel.news[E:] if panel.news is not None else np.zeros(len(dd))) < 0.05)
    out = {"dd_onset": None, "ind_onset": None, "lag_days": np.nan, "false_alarm_rate": float(flag[calm].mean()) if calm.any() else np.nan}
    ev = event_day(panel)
    if ev is None:
        return out
    lvl = panel.index[E + ev - 1]; fall = np.where(panel.index[E + ev:] / lvl - 1 <= -0.05)[0]
    if not len(fall):
        return out
    on = ev + int(fall[0]); lo = max(0, ev - 10)
    sustained = flag & np.roll(flag, -1) & np.roll(flag, -2); sustained[-2:] = False         # 3 risk-off days in a row: one noisy day is not a warning
    cand = np.where(sustained[lo:])[0]; ind = int(cand[0]) + lo if len(cand) else None
    out.update({"dd_onset": on, "ind_onset": ind, "lag_days": float(ind - on) if ind is not None else np.nan})
    return out


def geo_lead_lag(panel, ncfg: dict, rng: np.random.Generator) -> dict:
    """Runs the terminal's geo_tension.score_region over synthetic headline samples (4 a day, 30-day baseline) and times its risk-off reading."""
    gt, _ = _terminal_modules()
    if not gt:
        return {"geo_wired": False}
    spd = int(ncfg["samples_per_day"]); hist: list = []; score = np.full(panel.T, np.nan); t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for t in range(panel.T):
        pr = float(panel.news[t]) if panel.news is not None else 0.0
        for k in range(spd):
            ts = t0 + timedelta(days=t, hours=6 * k)
            rate = max(0.0, ncfg["base_rate_per_hour"] * (1 + (ncfg["rate_mult_at_peak"] - 1) * pr) * (1 + rng.normal(0, ncfg["noise_rate_frac"])))
            tone = ncfg["base_tone"] + (ncfg["tone_at_peak"] - ncfg["base_tone"]) * pr + rng.normal(0, ncfg["noise_tone"])
            sc, _, _, _ = gt.score_region(rate, tone, hist)
            hist.append({"t": ts.isoformat(), "r": rate, "tone": tone}); cut = (ts - timedelta(days=gt.KEEP_DAYS)).isoformat()
            hist = [s for s in hist if s["t"] >= cut]
        score[t] = sc if sc is not None else np.nan
    out = _onsets(panel, score, lambda x: x >= 65)
    return {"geo_wired": True, **{f"geo_{k}": v for k, v in out.items()}, "geo_max": float(np.nanmax(score[panel.eval_start:])) if np.isfinite(score[panel.eval_start:]).any() else np.nan}


def flow_lead_lag(panel, rng: np.random.Generator) -> dict:
    """Runs the terminal's flow_score over synthetic FII/DII flows (FII net ~ Rs 3,000 crore per 1% market move, DII lean against it)."""
    _, se = _terminal_modules()
    if not se:
        return {"flow_wired": False}
    r = np.diff(np.log(panel.index), prepend=np.nan); r[0] = 0.0
    fii = 3000 * (r / 0.01) + rng.normal(0, 2500, panel.T); dii = -0.6 * fii + rng.normal(0, 1500, panel.T)
    days = [{"fii": {"net_cr": float(fii[t])}, "dii": {"net_cr": float(dii[t])}} for t in range(panel.T)]
    v = np.full(panel.T, np.nan)
    for t in range(panel.eval_start - 60, panel.T):
        x, _ = se.flow_score({"days": days[max(0, t - 59): t + 1]}); v[t] = x if x is not None else np.nan
    out = _onsets(panel, v, lambda x: x <= -0.5)
    return {"flow_wired": True, **{f"flow_{k}": val for k, val in out.items()}}


def run_all(panel, cfg: dict, rng: np.random.Generator) -> dict:
    out = {**price_signals(panel), **standin_calibration(panel, cfg["oracle"]["aladin1_10d"]["ic"])}
    out.update(geo_lead_lag(panel, cfg["news"], rng)); out.update(flow_lead_lag(panel, rng))
    return out
