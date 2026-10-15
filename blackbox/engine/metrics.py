"""Statistics of one run (an equity curve + its trades) and their aggregation over seeds (percentiles, bootstrap intervals)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

PER_YEAR = 252


@dataclass
class Result:
    """What a strategy returns for one simulated market."""
    equity: np.ndarray                     # account value at each evaluated close, starting with the value before the first day
    gross_equity: np.ndarray               # the same without any costs
    trades: list = field(default_factory=list)   # dicts: entry_t, exit_t, pnl, pnl_pct, cost, capital, days, side, reason
    exposure: np.ndarray | None = None     # invested share of the account each day
    traded_value: float = 0.0
    per_year: int = PER_YEAR


def _max_dd(eq: np.ndarray) -> tuple[float, int]:
    peak = np.maximum.accumulate(eq); dd = eq / peak - 1; worst = float(dd.min())
    longest = run = 0
    for x in dd:
        run = run + 1 if x < 0 else 0; longest = max(longest, run)
    return worst, longest


RF_ANN = 0.062          # Sharpe and Sortino are measured over cash in the liquid fund (config costs: 6.5% - 0.3% fee), so holding cash earns no Sharpe


def returns_stats(eq: np.ndarray, per_year: int = PER_YEAR, rf_ann: float = RF_ANN) -> dict:
    eq = np.asarray(eq, float); r = eq[1:] / eq[:-1] - 1; n = len(r); rx = r - rf_ann / per_year
    total = float(eq[-1] / eq[0] - 1); ann = float((eq[-1] / eq[0]) ** (per_year / max(1, n)) - 1) if eq[-1] > 0 else -1.0
    vol = float(np.std(r, ddof=1) * math.sqrt(per_year)) if n > 1 else 0.0
    dn = rx[rx < 0]; dvol = float(np.sqrt(np.mean(dn ** 2)) * math.sqrt(per_year)) if len(dn) else 0.0
    mdd, ddur = _max_dd(eq); mean = float(np.mean(rx) * per_year) if n else 0.0
    wk = eq[::5]; wr = wk[1:] / wk[:-1] - 1 if len(wk) > 1 else np.array([0.0])
    q = float(np.quantile(r, 0.05)) if n else 0.0
    return {"total_ret": total, "ann_ret": ann, "vol": vol, "sharpe": mean / vol if vol > 1e-12 else 0.0, "sortino": mean / dvol if dvol > 1e-12 else 0.0,
            "calmar": ann / abs(mdd) if mdd < -1e-9 else 0.0, "max_dd": mdd, "dd_days": ddur, "worst_day": float(r.min()) if n else 0.0,
            "worst_week": float(wr.min()), "var5": q, "cvar5": float(r[r <= q].mean()) if n and (r <= q).any() else q}


def trade_stats(trades: list, n_days: int, per_year: int = PER_YEAR) -> dict:
    if not trades:
        return {"n_trades": 0, "avg_pnl": 0.0, "avg_pnl_pct": 0.0, "median_pnl_pct": 0.0, "win_rate": np.nan, "avg_win_pct": np.nan, "avg_loss_pct": np.nan,
                "payoff": np.nan, "profit_factor": np.nan, "expectancy_pct": 0.0, "avg_hold": np.nan, "max_losing_streak": 0, "trades_per_year": 0.0, "largest_loss": 0.0}
    p = np.array([t["pnl"] for t in trades]); pc = np.array([t["pnl_pct"] for t in trades]); w = pc[p > 0]; ls = pc[p <= 0]
    streak = run = 0
    for x in p:
        run = run + 1 if x <= 0 else 0; streak = max(streak, run)
    gw, gl = p[p > 0].sum(), -p[p <= 0].sum(); wr = len(w) / len(p)
    aw = float(w.mean()) if len(w) else 0.0; al = float(ls.mean()) if len(ls) else 0.0
    return {"n_trades": len(p), "avg_pnl": float(p.mean()), "avg_pnl_pct": float(pc.mean()), "median_pnl_pct": float(np.median(pc)), "win_rate": wr,
            "avg_win_pct": aw, "avg_loss_pct": al, "payoff": aw / abs(al) if al < 0 else np.nan, "profit_factor": float(gw / gl) if gl > 0 else np.nan,
            "expectancy_pct": wr * aw + (1 - wr) * al, "avg_hold": float(np.mean([t["days"] for t in trades])), "max_losing_streak": int(streak),
            "trades_per_year": len(p) * per_year / max(1, n_days), "largest_loss": float(p.min())}


def run_stats(res: Result, ruin_floor: float = 0.5) -> dict:
    """Everything for one run."""
    eq = res.equity; n = len(eq) - 1
    out = {**returns_stats(eq, res.per_year), **trade_stats(res.trades, n, res.per_year)}
    gross = float(res.gross_equity[-1] / res.gross_equity[0] - 1)
    out["gross_ret"] = gross; out["cost_drag"] = gross - out["total_ret"]
    out["cost_share_of_gross"] = (out["cost_drag"] / gross) if gross > 1e-9 else np.nan
    avg_eq = float(np.mean(eq)); out["turnover"] = res.traded_value / avg_eq * res.per_year / max(1, n) if avg_eq > 0 else 0.0
    out["exposure"] = float(np.mean(res.exposure)) if res.exposure is not None and len(res.exposure) else np.nan
    out["ruin"] = bool(eq.min() < ruin_floor * eq[0])
    return out


def bootstrap_ci(x: np.ndarray, stat=np.mean, n: int = 1000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap interval of `stat` over seeds."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 3:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed); b = np.array([stat(x[rng.integers(0, len(x), len(x))]) for _ in range(n)])
    return float(np.quantile(b, alpha / 2)), float(np.quantile(b, 1 - alpha / 2))


PCTS = (5, 25, 50, 75, 95)


def aggregate(rows: list[dict]) -> dict:
    """Over seeds: median of every statistic, percentile bands of the final equity, bootstrap CIs of Sharpe and win rate, probabilities."""
    keys = [k for k in rows[0] if isinstance(rows[0][k], (int, float, np.floating, bool, np.bool_)) and not isinstance(rows[0][k], str)]
    out = {}
    for k in keys:
        v = np.array([r[k] for r in rows], float)
        out[k] = float(np.nanmedian(v)) if np.isfinite(v).any() else np.nan
    fin = np.array([1 + r["total_ret"] for r in rows])
    for p in PCTS:
        out[f"final_p{p}"] = float(np.quantile(fin, p / 100))
    out["sharpe_ci_lo"], out["sharpe_ci_hi"] = bootstrap_ci(np.array([r["sharpe"] for r in rows]))
    out["win_rate_ci_lo"], out["win_rate_ci_hi"] = bootstrap_ci(np.array([r["win_rate"] for r in rows]))
    out["p_ruin"] = float(np.mean([r["ruin"] for r in rows]))
    for k in ("beat_bh", "beat_random"):
        if k in rows[0]:
            out[f"p_{k}"] = float(np.nanmean([r[k] for r in rows]))
    out["seeds"] = len(rows)
    return out
