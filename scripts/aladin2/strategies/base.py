"""Strategy contract. A strategy is a pure function of data up to day t: fn(ctx, params) -> Series in {0, 1} (long-only: cash-equity delivery cannot be shorted;
a bearish reading means "no position"). `ctx` carries px (cleaned daily bars), F (causal features), nifty (close Series or None), deliv (delivery % Series or None).
Declared per strategy: family, params, lookback_needed (bars), holding_rule, features_used. `group`/`rank` place it on a one-dimensional parameter grid so the
evaluator can test that neighbouring settings are not much worse (parameter plateau)."""
from dataclasses import dataclass, field
from hashlib import sha1
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Strategy:
    id: str
    family: str
    group: str
    rank: int
    params: dict
    rule: dict
    lookback_needed: int
    features_used: tuple
    fn: object = field(compare=False, repr=False)
    baseline: bool = False

    @property
    def hash(self):
        """Stable identity of the rule + parameters + holding rule: the same rule is never counted twice in the multiple-testing tally."""
        return sha1(json.dumps([self.family, self.group, self.params, self.rule], sort_keys=True).encode()).hexdigest()[:12]

    def signal(self, ctx):
        s = self.fn(ctx, self.params)
        return s.reindex(ctx.px.index).fillna(0.0).astype(float)


def latch(entry, exit_):
    """State machine as a vector: 1 from an entry event until an exit event, else 0."""
    entry, exit_ = entry.fillna(False), exit_.fillna(False)
    s = pd.Series(np.nan, index=entry.index); s[entry] = 1.0; s[exit_ & ~entry] = 0.0
    return s.ffill().fillna(0.0)


def make_ctx(px, F, nifty=None, deliv=None):
    return SimpleNamespace(px=px, F=F, nifty=nifty, deliv=deliv)
