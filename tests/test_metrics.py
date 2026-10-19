import datetime as dt

import pandas as pd
import pytest

from trading_os import metrics
from trading_os.config import load_config


def s(*values):
    return pd.Series(values, dtype="float64")


def test_dollar_volume():
    # 12.50 × 400,000 = 5,000,000
    assert metrics.dollar_volume(s(12.5), s(400_000)).iloc[0] == 5_000_000


def test_close_location():
    result = metrics.close_location(s(9, 10, 8, 5), s(10, 10, 10, 5), s(8, 8, 8, 5))
    assert result.iloc[0] == 0.5  # (9 − 8) / (10 − 8)
    assert result.iloc[1] == 1.0  # closed on the high
    assert result.iloc[2] == 0.0  # closed on the low
    assert pd.isna(result.iloc[3])  # no range


def test_average_excluding_today_and_rvol():
    # 59 prior sessions at 1,000,000 and today at 3,000,000:
    # 60-day mean with today = 62,000,000 / 60 = 1,033,333.33
    avg60_with_today = s(62_000_000 / 60)
    volume = s(3_000_000)
    prior = metrics.average_excluding_today(avg60_with_today, volume, 60)
    assert prior.iloc[0] == pytest.approx(1_000_000)
    assert metrics.relative_volume(volume, prior).iloc[0] == pytest.approx(3.0)
    # Using the average with today left in would read 2.90 and fail an RVOL ≥ 3 filter.
    assert (volume / avg60_with_today).iloc[0] == pytest.approx(2.903, abs=1e-3)


def test_average_excluding_today_guards_non_positive():
    assert pd.isna(metrics.average_excluding_today(s(100), s(60 * 100), 60).iloc[0])


def test_add_phase1_metrics_uses_config_proxies():
    df = pd.DataFrame(
        {
            "close": [10.0],
            "high": [11.0],
            "low": [9.0],
            "volume": [3_000_000],
            "avg_volume_60d_tv": [62_000_000 / 60],
            "avg_volume_30d_tv": [800_000.0],
            "avg_dollar_volume_30d_tv": [8_000_000.0],
            "ma10": [9.0],
            "ma20": [10.0],
            "ma50": [float("nan")],
            "ma200": [12.0],
        }
    )
    out = metrics.add_phase1_metrics(df, load_config().proxies)
    row = out.iloc[0]
    assert row["dollar_volume"] == 30_000_000
    assert row["close_loc"] == 0.5
    assert row["rvol50"] == pytest.approx(3.0)
    assert row["rvol_basis"] == "tv_avg60d_excl_today"
    assert row["avg_volume_20d"] == 800_000
    assert row["avg_dollar_volume_20d"] == 8_000_000
    # MA position: above ma10, not above an equal ma20, missing ma50 is False, below ma200.
    assert [row[f"above_ma{w}"] for w in (10, 20, 50, 200)] == [True, False, False, False]
    assert "close_loc" not in df.columns  # input untouched


def test_earnings_flag_uses_new_york_dates():
    released = pd.Series(
        pd.to_datetime(
            [
                "2026-10-16 12:30",  # 08:30 ET on the signal day (before open)
                "2026-10-15 20:05",  # 16:05 ET the session before (after close)
                "2026-10-17 01:00",  # 21:00 ET on 16 Oct, already 17 Oct in UTC
                "2026-10-13 20:05",  # too old
                None,
            ],
            utc=True,
        )
    )
    flags = metrics.earnings_flag(released, dt.date(2026, 10, 16), dt.date(2026, 10, 15))
    assert flags.tolist() == [True, True, True, False, False]
