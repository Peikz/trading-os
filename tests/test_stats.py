import datetime as dt

import pandas as pd
import pytest

from trading_os import stats


def data():
    ids = [f"s{i}" for i in range(6)]
    candidates = pd.DataFrame(
        {"signal_id": ids, "tier": ["alert"] * 5 + ["log"], "pushed": [True] * 5 + [False]}
    )
    outcomes = pd.DataFrame(
        {
            "signal_id": ids,
            "scan": "ep_day",
            "horizon": 5,
            "close_ret_pct": [10.0, -5.0, 3.0, 8.0, -2.0, 50.0],
            "max_gain_pct": [15.0, 2.0, 6.0, 12.0, 1.0, 60.0],
            "max_drawdown_pct": [-3.0, -9.0, -2.0, -1.0, -6.0, -5.0],
            "hit_order_stop": pd.array([pd.NA] * 6, dtype="boolean"),
            "r_hypothetical": [float("nan")] * 6,
        }
    )
    return candidates, outcomes


def test_summary_per_scan_tier_horizon():
    table = stats.summarize(*data(), min_signals=5)
    assert len(table) == 1  # the single log-tier signal is below min_signals
    row = table.iloc[0]
    assert (row["scan"], row["tier"], row["horizon"], row["signals"]) == ("ep_day", "alert", 5, 5)
    assert row["win_rate_pct"] == pytest.approx(60.0)  # 3 of 5 positive
    assert row["median_ret_pct"] == pytest.approx(3.0)
    assert row["mean_ret_pct"] == pytest.approx(14 / 5)
    assert pd.isna(row["stop_hit_pct"]) and pd.isna(row["mean_r"])


def test_markdown_and_empty_cases():
    table = stats.summarize(*data(), min_signals=5)
    text = stats.to_markdown(table, dt.date(2026, 11, 1), 6, 5)
    assert "| EP-Day | alert | 5d | 5 | 60 | +3.0 | +2.8 |" in text
    empty = stats.to_markdown(pd.DataFrame(), dt.date(2026, 11, 1), 0, 5)
    assert "_Not enough outcomes yet._" in empty
    assert stats.summarize(pd.DataFrame(), pd.DataFrame(), 5).empty


def test_all_groups_too_small_is_empty_not_an_error():
    assert stats.summarize(*data(), min_signals=50).empty
