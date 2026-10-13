import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_movers as M  # noqa: E402


def ist(s):
    return pd.Timestamp(s).tz_localize(M.IST)


def test_a_book_is_made_only_after_the_week_closes_and_counts_only_before_monday_open():
    fri = pd.Timestamp("2026-10-09")
    assert not M.book_due(ist("2026-10-09 15:00"), fri)            # market still open
    assert M.book_due(ist("2026-10-09 19:30"), fri) and M.book_due(ist("2026-10-11 10:00"), fri)
    assert not M.book_due(ist("2026-10-12 10:00"), fri)            # Monday: too late to make last week's book
    assert not M.book_due(ist("2026-10-17 10:00"), fri)            # a stale bar from the week before is never booked as this week's
    d = M.entry_deadline("2026-10-09")
    assert d == ist("2026-10-12 09:15")


def test_the_event_features_use_only_meetings_intimated_by_the_friday():
    import numpy as np
    ev = np.array([[pd.Timestamp("2024-01-20"), pd.Timestamp("2024-01-10"), 1], [pd.Timestamp("2024-01-25"), pd.Timestamp("2024-01-24"), 0]], dtype=object)
    out = M.event_features([pd.Timestamp("2024-01-19")], ev)
    assert out[0, 0] == 1 and out[0, 1] == 1 and out[0, 3] == 0
