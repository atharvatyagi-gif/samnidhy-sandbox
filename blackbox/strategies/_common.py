"""Shared pieces of the strategy re-implementations: causal indicators and a small account book with costs."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..engine.costs import CostModel
from ..engine.metrics import Result


def cached(panel, key: str, fn):
    """Indicators are computed once per panel (they only use data up to each day)."""
    store = panel.__dict__.setdefault("_cache", {})
    if key not in store:
        store[key] = fn()
    return store[key]


def atr(panel, n: int = 14) -> np.ndarray:
    """ATR(n) as a simple mean of the true range, row t uses bars <= t (scripts/aladin2/swing.py prep(), lines 75-77)."""
    def f():
        h, l, c = panel.h, panel.l, panel.c; pc = np.vstack([c[:1], c[:-1]])
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        return pd.DataFrame(tr).rolling(n, min_periods=n).mean().values
    return cached(panel, f"atr{n}", f)


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.DataFrame(x).rolling(n, min_periods=n).mean().values


def adv_shares(panel) -> np.ndarray:
    """Average daily volume in shares over 20 days (row t uses <= t)."""
    return cached(panel, "advsh", lambda: pd.DataFrame(panel.v).rolling(20, min_periods=5).mean().values)


class Book:
    """Cash + positions; every fill goes through the cost model. Gross results (no costs) are tracked alongside."""

    def __init__(self, cash: float, cm: CostModel, kind_long: str = "delivery", kind_short: str = "futures", fund: bool = False):
        self.cash, self.cm, self.kl, self.ks, self.fund = float(cash), cm, kind_long, kind_short, fund
        self.pos: dict = {}; self.trades: list = []; self.costs = 0.0; self.traded = 0.0

    def open(self, key, side: int, qty: float, ref: float, t: int, i: int | None, **meta) -> bool:
        kind = self.kl if side > 0 else self.ks
        qty = qty * self.cm.filled_share(t)                       # part of the order fails in a liquidity crisis
        if qty <= 0 or ref <= 0:
            return False
        px = self.cm.fill(ref, side, t, i, kind); fee = self.cm.fee(qty * px, kind)
        cost = fee + qty * abs(px - ref)
        if side > 0:
            if qty * px + fee > self.cash + 1e-9:
                return False
            self.cash -= qty * px + fee
        else:
            self.cash -= fee
        self.costs += cost; self.traded += qty * px
        self.pos[key] = {"side": side, "qty": qty, "entry": px, "ref": ref, "t": t, "i": i, "cost_in": cost, "kind": kind, **meta}
        return True

    def close(self, key, ref: float, t: int, reason: str) -> None:
        p = self.pos.pop(key); s = p["side"]; px = self.cm.fill(ref, -s, t, p["i"], p["kind"]); fee = self.cm.fee(p["qty"] * px, p["kind"])
        cost_out = fee + p["qty"] * abs(px - ref)
        if s > 0:
            self.cash += p["qty"] * px - fee
        else:
            self.cash += p["qty"] * (p["entry"] - px) - fee
        self.costs += cost_out; self.traded += p["qty"] * px
        gross = p["qty"] * (ref - p["ref"]) * s; cap = p["qty"] * p["ref"]; net = gross - p["cost_in"] - cost_out
        self.trades.append({"key": key, "side": "long" if s > 0 else "short", "entry_t": p["t"], "exit_t": t, "days": t - p["t"], "pnl": net,
                            "pnl_pct": net / cap if cap else 0.0, "cost": p["cost_in"] + cost_out, "capital": cap, "reason": reason})

    def value(self, prices: dict) -> float:
        """Cash + positions marked at `prices` (key -> price)."""
        v = self.cash
        for k, p in self.pos.items():
            m = prices.get(k, p["ref"])
            v += p["qty"] * m if p["side"] > 0 else p["qty"] * (p["entry"] - m)
        return v

    def invested(self, prices: dict) -> float:
        return sum(p["qty"] * prices.get(k, p["ref"]) for k, p in self.pos.items())

    def accrue(self) -> None:
        if self.fund and self.cash > 0:
            self.cash += self.cash * self.cm.fund_daily()


def finish(book: Book, eq: list, gross_add: list, expo: list) -> Result:
    e = np.array(eq, float); return Result(equity=e, gross_equity=e + np.array(gross_add, float), trades=book.trades, exposure=np.array(expo, float), traded_value=book.traded)


def hold_value(close_row: np.ndarray, i: int, fallback: float) -> float:
    x = close_row[i]; return float(x) if np.isfinite(x) and x > 0 else fallback


def kelly_cap_value(capital: float, mu: float, sd: float, frac: float) -> float:
    """scripts/aladin2/signals.py position_size(), lines 131-132: max value = capital x min(1, mu / sd^2 x kelly_fraction_cap)."""
    k = (mu / (sd * sd)) if (mu and sd and mu > 0) else 0.0
    return capital * min(1.0, k * frac)


def floor(x: float) -> int:
    return int(math.floor(x + 1e-9)) if x > 0 else 0
