"""Market regime filters: timing, scoring and pooling (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import regime_study as rs

D1, D2, D3 = dt.date(2022, 1, 3), dt.date(2022, 1, 4), dt.date(2022, 1, 5)


def regime():
    return pd.DataFrame(
        {
            "session_date": [D1, D2, D3],
            "qqq_trend": ["up", "down", "up"],
            "breadth_state": ["strong", "weak", "neutral"],
            "light": ["GREEN", "STOP", "YELLOW"],
            "spy_close": [10.0, 10.0, 10.0],
            "spy_sma200": [9.0, 11.0, 9.0],
            "qqq_close": [5.0, 5.0, 5.0],
            "qqq_sma50": [4.0, 6.0, 4.0],
        }
    )


def test_a_trade_gets_the_regime_known_before_its_entry():
    trades = pd.DataFrame({"session_date": [D2, D3], "ticker": ["AQ", "BQ"]})
    before = rs.known_before(trades, regime(), same_day=False)
    assert before["light"].tolist() == ["GREEN", "STOP"]  # the prior session's close
    same = rs.known_before(trades, regime(), same_day=True)
    assert same["light"].tolist() == ["STOP", "YELLOW"]  # entries at that close


def test_filters_keep_and_score_the_right_trades():
    trades = rs.known_before(
        pd.DataFrame(
            {
                "strategy": "x",
                "session_date": [D1, D2, D3],
                "r_hold_5d": [2.0, -1.0, 30.0],
            }
        ),
        regime(),
        same_day=True,
    )
    table = rs.finish(rs.score(trades, ["strategy"], ["r_hold_5d"]), ["strategy"], ["r_hold_5d"])
    by = table.set_index("filter")
    assert by.loc["all", "trades"] == 3 and by.loc["all", "R_hold_5d"] == pytest.approx(7.0)
    assert by.loc["light_green", "trades"] == 1 and by.loc["light_green", "R_hold_5d"] == 2.0
    assert by.loc["light_not_red", "R_hold_5d"] == pytest.approx(11.0)  # 30 capped at 20
    assert by.loc["spy_above_ma200", "trades"] == 2


def test_years_pool_exactly_from_their_sums():
    one = pd.DataFrame({"strategy": ["x"], "filter": ["all"], "trades": [2]})
    one = one.assign(wins_r_a=1, n_r_a=2, sum_r_a=1.0)
    two = one.assign(trades=1, wins_r_a=1, n_r_a=1, sum_r_a=4.0)
    pooled = rs.finish(pd.concat([one, two]), ["strategy"], ["r_a"]).iloc[0]
    assert pooled["trades"] == 3 and pooled["R_a"] == pytest.approx(5 / 3)


def test_compare_picks_the_best_filter_and_reports_what_it_keeps():
    table = pd.DataFrame(
        {
            "strategy": ["x"] * 3,
            "filter": ["all", "qqq_up", "light_green"],
            "trades": [1000, 600, 300],
            "R_hold_5d": [0.1, 0.3, 0.2],
        }
    )
    row = rs.compare(table, ["strategy"], "hold_5d").iloc[0]
    assert row["best_filter"] == "qqq_up" and row["kept_%"] == 60.0 and row["R_all"] == 0.1


def test_scan_count_follows_the_sunday_screen():
    n = 70
    close = np.vstack([np.linspace(10, 10, n), np.linspace(10, 20, n), np.linspace(2, 4, n)]).T
    g = {"close": close, "volume": np.full(close.shape, 1e6)}
    sc = {"price_gt": 5, "avg_volume_gt": 500_000, "perf_3m_min_pct": 50, "above_sma": 20}
    counts = rs.scan_counts(g, sc)
    assert counts[-1] == 1  # only the stock that doubled (the flat one and the $3 one fail)


def test_funds_are_tickers_never_listed_as_a_stock(tmp_path):
    path = tmp_path / "data" / "ep_enrich"
    path.mkdir(parents=True)
    pd.DataFrame(
        {"ticker": ["FQ", "SQ", "RQ", "RQ"], "type": ["ETF", "CS", "ETF", "CS"]}
    ).to_parquet(path / "tickers.parquet")
    assert rs.non_stocks(tmp_path) == {"FQ"}  # RQ was a stock at some point: kept
