"""Portfolio study: benchmarks, blends and the bootstrap (synthetic data only)."""

import numpy as np
import pandas as pd
import pytest

from trading_os import portfolio_study as ps


def days(n, start="2020-01-01"):
    return pd.bdate_range(start, periods=n)


def test_curve_stats_cagr_and_drawdown():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-07-01", "2021-01-01"])
    stats = ps.curve_stats(pd.Series([1.0, 0.5, 1.21], index=idx))
    assert stats["max_dd_pct"] == pytest.approx(-50)
    assert stats["cagr_pct"] == pytest.approx(100 * (1.21 ** (1 / (366 / 365.25)) - 1), rel=1e-6)


def test_index_curve_holds_or_follows_the_trend_with_yesterdays_close():
    d = days(8)
    close = pd.Series([10, 11, 12, 13, 9, 8, 8, 8], index=d, dtype=float)
    cash = pd.Series(100 * 1.001 ** np.arange(8), index=d)
    held = ps.index_curve(close)
    assert held.iloc[-1] == pytest.approx(0.8)
    trend = ps.index_curve(close, cash, trend=2, switch_cost_pct=0)
    # the 13 -> 9 drop (day 4) is still held: the signal at day 3's close was "above"
    assert trend.loc[d[4]] / trend.loc[d[3]] == pytest.approx(9 / 13)
    # day 5 is decided at day 4's close (9 < 11): cash
    assert trend.loc[d[5]] / trend.loc[d[4]] == pytest.approx(1.001)


def test_momentum_picks_the_strongest_eligible_stocks_monthly():
    d = days(80)
    up = np.linspace(10, 30, 80)
    flat = np.full(80, 10.0)
    cheap = np.linspace(1, 4, 80)  # strongest, but under the price floor
    close = pd.DataFrame({"UP": up, "FLAT": flat, "CHEAP": cheap}, index=d)
    dvol = pd.DataFrame(1e9, index=d, columns=close.columns)
    equity, picks = ps.momentum_curve(close, dvol, top=1, lookback=10, skip=2, min_price=5)
    assert set(picks["ticker"]) == {"UP"}
    assert equity.iloc[-1] > 1.5  # rode UP, less the costs


def test_idle_cash_earns_the_index():
    d = days(5)
    strat = pd.Series([1.0, 1.01, 1.02, 1.03, 1.04], index=d)
    index = pd.Series(1.0 * 1.01 ** np.arange(5), index=d)
    none = ps.with_idle_cash_in(strat, pd.Series(1.0, index=d), index)
    assert none.iloc[-1] == pytest.approx(strat.pct_change().fillna(0).add(1).prod())
    idle = ps.with_idle_cash_in(pd.Series(1.0, index=d), pd.Series(0.0, index=d), index)
    assert idle.iloc[-1] == pytest.approx(index.iloc[-1])


def test_blend_and_bootstrap():
    d = days(300)
    rng = np.random.default_rng(1)
    a = pd.Series(np.cumprod(1 + rng.normal(0.0005, 0.01, 300)), index=d)
    b = pd.Series(np.cumprod(1 + rng.normal(0.0010, 0.01, 300)), index=d)
    mix = ps.blend({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
    assert a.iloc[-1] < mix.iloc[-1] < b.iloc[-1] or b.iloc[-1] < mix.iloc[-1] < a.iloc[-1]
    out = ps.bootstrap(pd.DataFrame({"a": a, "b": b}).pct_change().dropna(), draws=200)
    assert out.loc["a", "p_beats_first"] == 0
    assert out.loc["a", "max_dd_p5"] <= out.loc["a", "max_dd_p50"] <= out.loc["a", "max_dd_p95"]
    assert out.loc["a", "cagr_p5"] <= out.loc["a", "cagr_p95"]


def test_a_cap_per_grade_leaves_room_for_the_better_grades():
    from trading_os import portfolio_sim as sim

    sessions = list(pd.bdate_range("2021-01-04", periods=30).date)
    tickers = ["B1", "B2", "B3", "A1"]
    closes = np.full((30, 4), 10.0)
    rows = [  # three B trades at 10:00, an A trade at 15:45, the same day
        {"ticker": t, "grade": g, "entry_minute": m, "priority": 0.0}
        for t, g, m in (("B1", "B", 600), ("B2", "B", 600), ("B3", "B", 600), ("A1", "A", 945))
    ]
    trades = pd.DataFrame(rows).assign(
        session_date=sessions[0],
        trade_id=range(4),
        side=1,
        price=10.0,
        stop=9.0,
        frac_1=1.0,
        days_1=5,
        r_1=1.0,
        cost_pct=0.0,
        strategy="x",
    )
    base = {"risk_pct": {"A": 0.5, "B": 0.5}, "max_positions": 3}
    _, taken = sim.simulate(trades, closes, sessions, tickers, sim.Rules(**base))
    assert "A1" not in set(taken["ticker"])  # the B trades came first and filled the slots
    capped = sim.Rules(**base, max_by_grade={"B": 2})
    _, taken = sim.simulate(trades, closes, sessions, tickers, capped)
    assert set(taken["ticker"]) == {"B1", "B2", "A1"}
