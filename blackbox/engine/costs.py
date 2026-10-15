"""Costs: fees, spread, slippage that rises with volatility and falls with liquidity, borrow for shorts, partial fills in a liquidity crisis.

Mirrors the terminal's cost table (data/config/aladin2.json "costs": statutory fees in bps, slippage by liquidity decile) and adds what the
terminal does not model: scenario-driven widening (spread_mult from the scenario, vol_ratio = today's market vol / normal) and fills that fail.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CostModel:
    cfg: dict                    # config["costs"]
    spread_mult: np.ndarray      # (T,) from the scenario
    vol_ratio: np.ndarray        # (T,)
    haircut: np.ndarray          # (T,) share of an order that does not fill
    liq_decile: np.ndarray       # (N,)
    cost_mult: float = 1.0       # GAP sweep: fees x
    slip_mult: float = 1.0       # GAP sweep: spread + slippage x

    def slip_bps(self, t: int, i: int | None, kind: str = "delivery") -> float:
        """Half-spread + slippage, in bps of price, for one fill of stock i (i=None: BTC/an index) on day t."""
        c = self.cfg; sm = float(self.spread_mult[t]); vr = max(0.5, float(self.vol_ratio[t])) ** c["slippage_vol_power"]
        base = c["slippage_bps_by_liquidity"][int(self.liq_decile[i])] if i is not None else 2.0
        return (c["spread_bps"] * sm + base * vr * sm) * self.slip_mult

    def fill(self, price: float, side: int, t: int, i: int | None, kind: str = "delivery") -> float:
        """The price actually paid (side +1 = buying) or received (side -1 = selling)."""
        return price * (1 + side * self.slip_bps(t, i, kind) / 1e4)

    def fee(self, value: float, kind: str = "delivery") -> float:
        bps = {"delivery": self.cfg["delivery_fee_bps"], "futures": self.cfg["futures_fee_bps"], "crypto": self.cfg["crypto_fee_bps"]}[kind]
        return abs(value) * bps / 1e4 * self.cost_mult

    def filled_share(self, t: int) -> float:
        return 1.0 - float(self.haircut[t])

    def borrow(self, notional: float, days: int = 1) -> float:
        return abs(notional) * self.cfg["borrow_bps_ann"] / 1e4 / 252 * days

    def fund_daily(self) -> float:
        """Daily return of idle cash in a liquid fund (the terminal's paper bot)."""
        return (self.cfg["fund_rate_ann"] - self.cfg["fund_fee_ann"]) / 252


def for_panel(cfg: dict, panel, cost_mult: float = 1.0, slip_mult: float = 1.0) -> CostModel:
    return CostModel(cfg["costs"], panel.spread_mult, panel.vol_ratio, panel.haircut, panel.liq_decile, cost_mult, slip_mult)
