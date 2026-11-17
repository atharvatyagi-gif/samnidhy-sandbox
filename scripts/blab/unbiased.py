"""Survivorship-free market for the head-to-head (docs/blab/HEAD_TO_HEAD.md, rules written 2026-11-17 before any result).

Builds the same matrices as evolve.Market (dates x stocks: open, close, traded value, eligibility) from NSE's daily files
(scripts/bhav_history.py), so every strategy and model E run in the SAME simulator on data that includes delisted companies.
  - adjusted prices: chained daily returns, close / (last close x split or bonus factor on its ex-date), the factors from
    NSE's corporate-actions record (scripts/corp_actions.py); where the file's previous-close field already differs from the
    last close by more than 2% (NSE adjusted it), that field is used. Falls beyond 45% with no recorded action stay in.
  - renamed symbols joined by ISIN (a symbol stops, a new one with the same ISIN starts the next trading day)
  - prices from the EQ, BE (trade-to-trade) and BZ series: a company moved to BE keeps trading and can still be sold there
    (fixed 2026-11-17 after the first run counted such moves as vanished holdings); new buys only on a day it trades in EQ
  - a locked circuit (open = high = low = close) cannot be filled
  - a holding with no trade for 10 sessions in a row is treated by `vanish`: "base" sells at the last close, "stress" at zero
"""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from . import evolve as V

VANISH_SESSIONS = 10


HOLD_SERIES = ("EQ", "BE", "BZ")


def read_days(folder: Path, start="2008-01-01"):
    """-> {date: [(symbol, open, high, low, close, prevclose, value, isin, series)]}: EQ, BE and BZ rows, EQ first when a
    company has more than one the same day."""
    days = {}
    for p in sorted(Path(folder).glob("*/*.csv.gz")):
        d = p.stem[:10]
        if d < start:
            continue
        rows = []
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for r in csv.reader(f):
                if len(r) < 11 or r[2] not in HOLD_SERIES:
                    continue
                try:
                    rows.append((r[1], float(r[3] or r[6]), float(r[4] or r[6]), float(r[5] or r[6]), float(r[6]), float(r[7] or r[6]), float(r[9] or 0), r[10], r[2]))
                except ValueError:
                    continue
        rows.sort(key=lambda x: HOLD_SERIES.index(x[8]))
        if rows:
            days[d] = rows
    return days


def join_renames(days):
    """symbol -> company key: a symbol that starts the trading day after another with the same ISIN stopped continues it."""
    dates = sorted(days)
    last_seen, first_seen, isin_of = {}, {}, {}
    for d in dates:
        for s, *_x, isin, _ser in days[d]:
            first_seen.setdefault(s, d); last_seen[s] = d; isin_of.setdefault(s, isin)
    pos = {d: i for i, d in enumerate(dates)}
    key = {s: s for s in first_seen}
    by_isin = {}
    for s, i in isin_of.items():
        by_isin.setdefault(i, []).append(s)
    for isin, syms in by_isin.items():
        syms.sort(key=lambda s: first_seen[s])
        for a, b in zip(syms, syms[1:]):
            if isin and pos[first_seen[b]] - pos[last_seen[a]] <= 2:
                key[b] = key[a]
    return key


class BhavMarket(V.Market):
    """evolve.Market built from NSE's daily files. Extra: H, L (adjusted), locked (no fill), last trade index per stock."""

    def __init__(self, folder, start="2008-01-01", index_series=None):
        import numpy as np
        days = read_days(folder, start)
        ca = {}
        ca_p = Path(folder) / "corporate_actions.json"
        if ca_p.exists():
            for sym, ex, f, _subj in json.loads(ca_p.read_text())["events"]:
                ca[(sym, ex)] = ca.get((sym, ex), 1.0) * f
        self.ca_events = len(ca)
        self.dates = sorted(days)
        key = join_renames(days)
        comp = sorted(set(key.values()))
        col = {c: j for j, c in enumerate(comp)}
        T, N = len(self.dates), len(comp)
        O, H, L, C, TV = (np.full((T, N), np.nan, np.float32) for _ in range(5))
        PC = np.full((T, N), np.nan, np.float64)
        F = np.ones((T, N), np.float64)
        EQ = np.zeros((T, N), bool)
        for t, d in enumerate(self.dates):
            for s, o, h, lo, c, pc, val, _isin, ser in days[d]:
                j = col[key[s]]
                if not np.isnan(C[t, j]):
                    continue                                              # EQ came first: keep it
                O[t, j], H[t, j], L[t, j], C[t, j], TV[t, j], PC[t, j] = o, h, lo, c, val, pc
                F[t, j] = ca.get((s, d), 1.0)
                EQ[t, j] = ser == "EQ"
        # adjusted close: chain the day returns (split/bonus adjusted by NSE's previous close); scale open/high/low by the same factor
        adj = np.full((T, N), np.nan, np.float64)
        self.unexplained = []
        for j in range(N):
            idx = np.nonzero(~np.isnan(C[:, j]))[0]
            if not len(idx):
                continue
            level = float(C[idx[0], j])
            adj[idx[0], j] = level
            for a, b in zip(idx, idx[1:]):
                last, pc = float(C[a, j]), PC[b, j]
                base = pc if (np.isfinite(pc) and pc > 0 and abs(pc / last - 1) > 0.02) else last * F[b, j]
                r = float(C[b, j]) / base - 1 if base > 0 else 0.0
                if r < -0.45:
                    self.unexplained.append((comp[j], self.dates[b], round(r, 3)))
                level = level * (1 + r)
                adj[b, j] = level
        f = np.where(C > 0, adj / C, np.nan)
        self.syms = comp
        self.C = adj.astype(np.float32)
        self.O = (O * f).astype(np.float32)
        self.locked = (O == H) & (H == L) & (L == C)
        self.TV = TV
        self.last_trade = np.full(N, -1)
        for j in range(N):
            nz = np.nonzero(~np.isnan(C[:, j]))[0]
            self.last_trade[j] = nz[-1] if len(nz) else -1
        idx_map = index_series or {}
        self.n50 = np.array([idx_map.get(d, np.nan) for d in self.dates], float)
        if np.isnan(self.n50).any():
            import pandas as pd
            self.n50 = pd.Series(self.n50).ffill().bfill().to_numpy()
        self._cache = {}
        self._prep()
        self.elig &= EQ                                                   # new buys only on a day the company trades in the EQ series
