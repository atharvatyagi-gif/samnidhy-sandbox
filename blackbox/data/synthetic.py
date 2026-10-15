"""Synthetic NSE-like market: one seeded panel of daily OHLCV for a universe of stocks plus BTC, oil, gold, USD/INR and a bond, under a scenario.

Return of stock i on day t (log):
    beta_i * market_t + sector_{s(i),t} + idio_{i,t} (Student-t, stochastic vol) + jumps + scenario shocks
The market has calm/turbulent volatility regimes (Markov). A few stock pairs are cointegrated. Volume rises with volatility.
The stand-in scores for the model-driven strategies (config `oracle`) are correlated with the NORMAL part of each stock's next-k-day return:
the scenario's shocks are not in it, so no stand-in can foresee a crash. This forward-looking construction happens HERE (scenario generation)
and nowhere else; strategies only ever read the score at the close of day t.
Every panel is labelled SIMULATED.
"""
from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..scenarios import library as LIB

log = logging.getLogger(__name__)
LABEL = "SIMULATED"


@dataclass
class Panel:
    """One simulated market. Arrays are (T days x N stocks) unless noted."""
    dates: pd.DatetimeIndex
    o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray; v: np.ndarray
    sector: np.ndarray; sectors: list; beta: np.ndarray; adv_cr: np.ndarray; liq_decile: np.ndarray; fno: np.ndarray
    spread_mult: np.ndarray; haircut: np.ndarray; vol_ratio: np.ndarray       # (T,) liquidity and today's market vol / normal
    index: np.ndarray                                                          # (T,) equal-weight market index level
    extras: dict                                                               # asset -> {"o","h","l","c"} (T,)
    zfwd: dict = field(default_factory=dict)                                   # horizon -> (T x N) z-score of the normal-part forward return
    noise: dict = field(default_factory=dict)                                  # horizon -> (T x N) independent noise for the stand-in score
    news: np.ndarray = None                                                    # (T,) news pressure 0..1 for the geopolitical module
    eval_start: int = 0
    drawn: dict = field(default_factory=dict)
    label: str = LABEL

    @property
    def T(self) -> int:
        return self.c.shape[0]

    @property
    def N(self) -> int:
        return self.c.shape[1]

    def score(self, horizon: int, ic: float) -> np.ndarray:
        """Stand-in model score with correlation ~ic to the normal-part forward return (cross-section, each day)."""
        ic = float(np.clip(ic, -0.999, 0.999))
        return ic * self.zfwd[horizon] + math.sqrt(1 - ic * ic) * self.noise[horizon]


def _universe(m: dict, rng: np.random.Generator) -> dict:
    names = list(m["sectors"]); w = np.array([m["sectors"][k] for k in names], float); w /= w.sum()
    N = m["n_stocks"]; sec = rng.choice(len(names), size=N, p=w)
    adv = np.exp(rng.uniform(math.log(m["adv_cr_range"][0]), math.log(m["adv_cr_range"][1]), N))
    order = np.argsort(-adv); dec = np.empty(N, int); dec[order] = np.minimum(9, (np.arange(N) * 10) // N)
    fno = np.zeros(N, bool); fno[order[: int(N * m["fno_share"])]] = True
    return {"names": names, "sector": sec, "beta": rng.uniform(*m["beta"], N), "idio": rng.uniform(*m["idio_vol_ann"], N) / math.sqrt(252),
            "p0": np.exp(rng.uniform(math.log(m["price_range"][0]), math.log(m["price_range"][1]), N)), "adv": adv, "dec": dec, "fno": fno}


def _t(rng: np.random.Generator, df: float, shape) -> np.ndarray:
    """Student-t draws scaled to unit variance."""
    return rng.standard_t(df, size=shape) / math.sqrt(df / (df - 2))


def _ohlc(close_lr: np.ndarray, gap_lr: np.ndarray, sig: np.ndarray, p0, rng) -> tuple:
    """Close path from daily log returns; the open carries the overnight part; high/low from the day's volatility."""
    c = p0 * np.exp(np.cumsum(close_lr, axis=0))
    prev = np.vstack([np.atleast_2d(p0) * np.ones_like(c[:1]), c[:-1]]) if c.ndim == 2 else np.concatenate([[p0], c[:-1]])
    o = prev * np.exp(gap_lr)
    rng_hi = np.abs(rng.normal(0, 1, c.shape)) * sig * 0.8; rng_lo = np.abs(rng.normal(0, 1, c.shape)) * sig * 0.8
    h = np.maximum(o, c) * np.exp(rng_hi); l = np.minimum(o, c) * np.exp(-rng_lo)
    return o, h, l, c


def generate(cfg: dict, scenario: dict, seed: int) -> Panel:
    """The panel for one (scenario, seed). Deterministic: the same inputs give the same panel."""
    m = cfg["market"]; idx = [s["id"] for s in cfg["scenarios"]].index(scenario["id"])
    rng = np.random.default_rng([int(cfg["run"]["seed_base"]), idx, int(seed)])
    W, E = m["warmup_days"], m["eval_days"]; T = W + E
    dates = pd.bdate_range(m["start_date"], periods=T)
    U = _universe(m, np.random.default_rng([int(cfg["run"]["seed_base"]), 999, int(seed)]))   # the same universe for a seed in every scenario
    N = len(U["beta"]); st, drawn = LIB.build(cfg, scenario, T, W, rng)

    # market: regimes, fat tails, scenario drift / vol / shocks; chop pulls the level back towards where it started
    mu = math.log1p(m["drift_ann"]) / 252; sd = m["vol_ann"] / math.sqrt(252)
    reg = np.zeros(T, bool)
    for t in range(1, T):
        reg[t] = (rng.random() < m["calm_to_turbulent_p"]) if not reg[t - 1] else (rng.random() >= m["turbulent_to_calm_p"])
    mvol = sd * np.where(reg, m["turbulent_vol_mult"], 1.0) * st.mkt_vol
    eps = _t(rng, m["t_df"], T)
    drift = np.where(np.isnan(st.drift_override), mu, st.drift_override)
    mkt_base = drift + mvol * eps
    for a, b, band, hl in st.chop:
        k = 1 - 0.5 ** (1 / hl); lvl = 0.0; vol_c = band * math.sqrt(2 * k)
        for t in range(a, b):
            mkt_base[t] = -k * lvl + vol_c * eps[t]; lvl += mkt_base[t]
    mkt = mkt_base + st.mkt_add

    # sectors and stocks
    S = len(U["names"]); svol = m["sector_vol_ann"] / math.sqrt(252)
    sec_base = rng.normal(0, svol, (T, S)) * st.mkt_vol[:, None] ** 0.5
    sec_shock = np.zeros((T, S))
    for name, add in st.sector_add.items():
        if name in U["names"]:
            sec_shock[:, U["names"].index(name)] += add
    ivol = U["idio"][None, :] * np.where(reg, 1.3, 1.0)[:, None] * st.idio_mult[:, None]
    idio = _t(rng, m["t_df"], (T, N)) * ivol
    jumps = (rng.random((T, N)) < m["jumps_per_year"] / 252) * rng.normal(0, m["jump_sd"], (T, N))
    b = U["beta"][None, :]; s_ix = U["sector"]
    base = b * mkt_base[:, None] + sec_base[:, s_ix] + idio + jumps                # the part a model could learn from
    shock = b * st.mkt_add[:, None] + sec_shock[:, s_ix]
    for p in range(m["pairs"]):                                                    # cointegrated pairs: B follows A plus a mean-reverting spread
        a_, b_ = 2 * p, 2 * p + 1; spread = np.zeros(T)
        for t in range(1, T):
            spread[t] = 0.9 * spread[t - 1] + rng.normal(0, 0.01)
        base[:, b_] = base[:, a_] + np.diff(np.concatenate([[0.0], spread])); shock[:, b_] = shock[:, a_]; U["sector"][b_] = U["sector"][a_]
    gap_lr = 0.3 * (base + shock)                                                   # part of each day's move happens overnight
    for d, g in st.gaps:
        shock[d] += b[0] * g; gap_lr[d] += b[0] * g
    if any(t == "top_score" for _, _, t in st.single_gap):
        pass                                                                        # target chosen below, after the scores exist
    lr = base + shock

    # stand-in scores: z-score of the NORMAL part's forward return (cross-section each day), plus independent noise
    zfwd, noise = {}, {}
    for key, oc in cfg["oracle"].items():
        hz = int(oc["horizon"])
        if hz in zfwd:
            continue
        cs = np.vstack([np.zeros((1, N)), np.cumsum(base, axis=0)])
        f = np.full((T, N), np.nan); f[: T - hz] = cs[1 + hz: T + 1] - cs[1: T + 1 - hz]
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mu_ = np.nanmean(f, axis=1, keepdims=True); sd_ = np.nanstd(f, axis=1, keepdims=True) + 1e-12
        z = (f - mu_) / sd_; z[np.isnan(z)] = 0.0; zfwd[hz] = z; noise[hz] = rng.normal(0, 1, (T, N))
    for d, g, target in st.single_gap:                                              # the black swan hits the stock the 5-day stand-in likes most
        sc = 0.14 * zfwd[5][d - 1] + math.sqrt(1 - 0.14 ** 2) * noise[5][d - 1]
        i = int(np.argmax(sc)); lr[d, i] += g; gap_lr[d, i] += g; drawn.setdefault("black_swan", {"day": int(d), "stock": i})
    sig_day = np.sqrt(mvol[:, None] ** 2 * b ** 2 + ivol ** 2)
    o, h, l, c = _ohlc(lr, gap_lr, sig_day, U["p0"], rng)
    for d, low, close, _ in st.flash:                                               # the intraday collapse: lows far below, partly recovered by the close
        l[d] = np.minimum(l[d], o[d] * np.exp(U["beta"] * math.log1p(low)))
    vol_ratio = mvol / sd
    shares = U["adv"] * 1e7 / U["p0"]
    v = shares[None, :] * (vol_ratio[:, None] ** 1.0) * st.volume_mult[:, None] * np.exp(rng.normal(0, 0.3, (T, N)))

    index = 100 * np.exp(np.cumsum(np.log(np.mean(np.exp(lr), axis=1))))
    extras = {}
    for name, e in m["extras"].items():
        esd = e["vol_ann"] / math.sqrt(252); emu = math.log1p(e["drift_ann"]) / 252
        er = emu + e["beta"] * (mkt - drift) + _t(rng, m["t_df"], T) * esd * np.sqrt(st.mkt_vol) + st.extra_add.get(name, np.zeros(T))
        eo, eh, el, ec = _ohlc(er, 0.2 * er, np.full(T, esd), 100.0, rng)
        extras[name] = {"o": eo, "h": eh, "l": el, "c": ec}

    news = np.zeros(T); nw = scenario.get("news")
    if nw:
        lead = int(cfg["news"].get("lead_days", 0)); s0 = W + int(nw["start"]) - lead
        if nw.get("follow_drawdown"):
            dd = 1 - index / np.maximum.accumulate(index); news[W:] = np.clip(dd[W:] / 0.2, 0, 1) * nw["peak"]
        else:
            for t in range(max(0, s0), T):
                news[t] = nw["peak"] * math.exp(-(t - s0) / max(1, nw["decay_days"]))
    return Panel(dates=dates, o=o, h=h, l=l, c=c, v=v, sector=U["sector"], sectors=U["names"], beta=U["beta"], adv_cr=U["adv"], liq_decile=U["dec"],
                 fno=U["fno"], spread_mult=st.spread_mult, haircut=st.haircut, vol_ratio=vol_ratio, index=index, extras=extras, zfwd=zfwd, noise=noise,
                 news=news, eval_start=W, drawn=drawn)
