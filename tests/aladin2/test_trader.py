from scripts.aladin2 import trader as T


def st(cagr, dd, pf, n, years):
    return {"cagr_pct": cagr, "max_drawdown_pct": dd, "profit_factor": pf, "trades": n, "by_year_pct": years}


def test_the_gates_need_more_return_no_deeper_fall_quality_and_as_many_good_years():
    base = st(20.0, -27.0, 1.26, 2700, {y: (5 if y != 2022 else -2) for y in range(2013, 2026)})
    good = st(22.0, -25.0, 1.3, 2900, {y: 4 for y in range(2013, 2026)})
    assert T.judge(good, base) == ({"return": True, "risk": True, "quality": True, "stability": True}, True)
    assert T.judge({**good, "max_drawdown_pct": -30.0}, base)[0]["risk"] is False
    assert T.judge({**good, "by_year_pct": {**good["by_year_pct"], 2014: -1, 2015: -1}}, base)[0]["stability"] is False
