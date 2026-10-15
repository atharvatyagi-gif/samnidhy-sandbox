"""Shock primitives: each one edits a ShockState, the set of day-by-day multipliers and additions the generator applies.

A primitive never looks at prices; it only describes the scenario. Days count from the start of the evaluated year (offset added by the caller).
Ranges [a, b] in the config are drawn once per seed by scenarios/library.py before they reach here.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

REGIMES = {  # used by the regime chain: (annual drift, vol multiplier, idio multiplier, spread multiplier)
    "bull": (0.25, 0.8, 1.0, 1.0),
    "chop": (0.0, 1.0, 1.0, 1.0),
    "bear": (-0.25, 1.4, 1.1, 1.3),
    "crash_lite": (-0.60, 2.5, 0.6, 2.0),
    "flat": (0.0, 0.35, 0.4, 1.3),
}


@dataclass
class ShockState:
    """Everything a scenario changes, one value per day (T days, warm-up included)."""
    T: int
    mkt_add: np.ndarray = None            # extra market log return per day (the shock part, unforeseeable)
    drift_override: np.ndarray = None     # NaN = normal drift; a number replaces the daily market drift
    mkt_vol: np.ndarray = None            # market volatility multiplier
    idio_mult: np.ndarray = None          # stock-specific volatility multiplier (low = correlations near 1)
    spread_mult: np.ndarray = None        # bid-ask spread / slippage multiplier
    haircut: np.ndarray = None            # share of an order that does NOT fill (liquidity)
    volume_mult: np.ndarray = None
    chop: list = field(default_factory=list)          # (start, end, band, half_life): mean-reverting market level
    sector_add: dict = field(default_factory=dict)    # sector -> extra log return per day
    extra_add: dict = field(default_factory=dict)     # asset (oil, gold, ...) -> extra log return per day
    gaps: list = field(default_factory=list)          # (day, market gap log size) applied at the open, all stocks by beta
    flash: list = field(default_factory=list)         # (day, low, close, rebound_days)
    single_gap: list = field(default_factory=list)    # (day, size, target rule)

    def __post_init__(self) -> None:
        T = self.T
        self.mkt_add = np.zeros(T); self.drift_override = np.full(T, np.nan)
        self.mkt_vol = np.ones(T); self.idio_mult = np.ones(T); self.spread_mult = np.ones(T)
        self.haircut = np.zeros(T); self.volume_mult = np.ones(T)

    def add_sector(self, sector: str) -> np.ndarray:
        return self.sector_add.setdefault(sector, np.zeros(self.T))

    def add_extra(self, asset: str) -> np.ndarray:
        return self.extra_add.setdefault(asset, np.zeros(self.T))


def _span(st: ShockState, start: int, length: int) -> slice:
    a = max(0, min(st.T, start)); return slice(a, max(a, min(st.T, a + max(1, int(length)))))


def crash(st: ShockState, start: int, length: int, depth: float, recovery: float = 0.0) -> None:
    """The market loses `depth` (e.g. -0.4) over `length` days, then wins back `recovery` of the log loss over twice as long."""
    s = _span(st, start, length); n = s.stop - s.start
    if n <= 0:
        return
    loss = math.log1p(depth); st.mkt_add[s] += loss / n
    if recovery > 0:
        r = _span(st, s.stop, 2 * n); m = r.stop - r.start
        if m > 0:
            st.mkt_add[r] += -recovery * loss / m


def drift(st: ShockState, start: int, length: int, total: float) -> None:
    """Replace the normal market drift so that the drift alone adds up to `total` over the span."""
    s = _span(st, start, length); st.drift_override[s] = math.log1p(total) / max(1, s.stop - s.start)


def vol(st: ShockState, start: int, length: int, mult: float, idio_mult: float | None = None) -> None:
    s = _span(st, start, length); st.mkt_vol[s] *= mult
    if idio_mult is not None:
        st.idio_mult[s] *= idio_mult


def corr_spike(st: ShockState, start: int, length: int, idio_mult: float, mkt_vol_mult: float) -> None:
    """Correlations towards 1: stock-specific noise shrinks while the market's grows."""
    s = _span(st, start, length); st.idio_mult[s] *= idio_mult; st.mkt_vol[s] *= mkt_vol_mult


def liquidity(st: ShockState, start: int, length: int, spread_mult: float = 1.0, fill_haircut: float = 0.0, volume_mult: float = 1.0) -> None:
    s = _span(st, start, length); st.spread_mult[s] *= spread_mult
    st.haircut[s] = np.maximum(st.haircut[s], fill_haircut); st.volume_mult[s] *= volume_mult


def gaps(st: ShockState, start: int, length: int, n: int, size: float, rng: np.random.Generator) -> None:
    """`n` overnight gap-downs of `size` on random days inside the span (all stocks, scaled by beta). The gaps are PART of the move, not
    added to it: the same total is taken back evenly from the span's other days, so a crash keeps its configured depth."""
    s = _span(st, start, length); days = rng.choice(np.arange(s.start, s.stop), size=min(n, s.stop - s.start), replace=False)
    g = [(int(d), math.log1p(size)) for d in sorted(days)]; st.gaps += g
    st.mkt_add[s] -= sum(x for _, x in g) / max(1, s.stop - s.start)


def flash(st: ShockState, day: int, low: float, close: float, rebound_days: int) -> None:
    st.flash.append((day, low, close, rebound_days)); st.mkt_add[day] += math.log1p(close)
    r = _span(st, day + 1, rebound_days)
    if r.stop > r.start:
        st.mkt_add[r] += -0.7 * math.log1p(close) / (r.stop - r.start)          # partial rebound


def sector(st: ShockState, name: str, start: int, length: int, move: float) -> None:
    s = _span(st, start, length); st.add_sector(name)[s] += math.log1p(move) / max(1, s.stop - s.start)


def extra(st: ShockState, asset: str, start: int, length: int, move: float) -> None:
    s = _span(st, start, length); st.add_extra(asset)[s] += math.log1p(move) / max(1, s.stop - s.start)


def chop(st: ShockState, start: int, length: int, band: float, half_life: float) -> None:
    s = _span(st, start, length); st.chop.append((s.start, s.stop, band, half_life)); st.drift_override[s] = 0.0


def single_gap(st: ShockState, day: int, size: float, target: str) -> None:
    st.single_gap.append((day, math.log1p(size), target))


def regime_chain(st: ShockState, start: int, length: int, block: list, regimes: list, rng: np.random.Generator) -> list:
    """Random blocks of random regimes (each 30-60 days by default). Returns the chain for the record."""
    t, end, chain = start, start + length, []
    while t < end:
        n = int(rng.integers(block[0], block[1] + 1)); name = str(rng.choice(regimes)); d, vm, im, sm = REGIMES[name]
        s = _span(st, t, min(n, end - t))
        if name == "chop":
            chop(st, s.start, s.stop - s.start, 0.05, 8)
        else:
            st.drift_override[s] = math.log1p(d) / 252
        st.mkt_vol[s] *= vm; st.idio_mult[s] *= im; st.spread_mult[s] *= sm
        chain.append((s.start, s.stop, name)); t += n
    return chain
