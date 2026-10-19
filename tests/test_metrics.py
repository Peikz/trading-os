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
            "pm_price": [10.5],
            "pm_volume": [200_000.0],
            "adr14_usd_tv": [0.5],
            "perf_1m_tv": [10.0],
            "perf_3m_tv": [20.0],
            "perf_6m_tv": [30.0],
            "high_52w": [12.5],
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
    assert row["pm_dollar_volume"] == 2_100_000  # 10.50 × 200,000
    assert row["adr20_pct"] == pytest.approx(5.0)  # 0.50 / 10.00 × 100
    assert row["dist_ma10_adr"] == pytest.approx(2.0)  # (10 − 9) / 0.50
    assert (row["ret_22"], row["ret_63"], row["ret_126"]) == (10.0, 20.0, 30.0)
    assert row["returns_basis"] == "tv:Perf.1M/Perf.3M/Perf.6M"
    assert row["pct_from_52w_high"] == pytest.approx(-20.0)  # 10 / 12.50 − 1
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


def test_yoy_growth_from_latest_first_history():
    revenue = [130, 120, 110, 100, 100, 80, 90, 95]
    assert metrics.yoy_growth(revenue, 0, abs_base=False) == pytest.approx(30.0)  # 130 vs 100
    assert metrics.yoy_growth(revenue, 1, abs_base=False) == pytest.approx(50.0)  # 120 vs 80
    eps = [0.5, 0.2, 0.1, 0.1, -0.25, 0.1]
    # Loss to profit: (0.50 − (−0.25)) / |−0.25| = 300 %
    assert metrics.yoy_growth(eps, 0, abs_base=True) == pytest.approx(300.0)
    assert metrics.yoy_growth(eps, 1, abs_base=True) == pytest.approx(100.0)  # 0.2 vs 0.1


@pytest.mark.parametrize("history", [None, [1, 2, 3, 4], [1, 2, 3, 4, 0], [None, 2, 3, 4, 5]])
def test_yoy_growth_missing_data_is_nan(history):
    assert pd.isna(metrics.yoy_growth(history, 0, abs_base=False))


def test_add_growth_metrics_drops_arrays():
    df = pd.DataFrame(
        {"revenue_q_hist": [[130, 120, 110, 100, 100, 80]], "eps_q_hist": [[1, 1, 1, 1, 1, 0.5]]}
    )
    out = metrics.add_growth_metrics(df)
    assert out["rev_growth_q_prev"].iloc[0] == pytest.approx(50.0)
    assert out["eps_growth_q_prev"].iloc[0] == pytest.approx(100.0)
    assert "revenue_q_hist" not in out.columns and "eps_q_hist" not in out.columns
