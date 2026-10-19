"""SPEC §5 on full history, each metric against a hand-computed example."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import history_metrics as hm

START = dt.date(2026, 1, 1)


def sessions(n):
    return [START + dt.timedelta(days=i) for i in range(n)]


def bars_for(ticker, closes, *, highs=None, lows=None, opens=None, volumes=None):
    days = sessions(len(closes))
    return pd.DataFrame(
        {
            "session_date": days,
            "ticker": ticker,
            "open": opens or closes,
            "high": highs or closes,
            "low": lows or closes,
            "close": closes,
            "volume": volumes or [1000.0] * len(closes),
        }
    )


def last(metrics, ticker):
    rows = metrics[metrics["ticker"] == ticker]
    return rows.iloc[-1]


def test_adr20_constant_range():
    # high / low = 1.05 every day -> ADR(20) = 5.00 %, ADR $ = 5 % of the close.
    closes = [100.0] * 20
    bars = bars_for("A", closes, highs=[105.0] * 20, lows=[100.0] * 20)
    row = last(hm.compute(bars, sessions(20)), "A")
    assert row["adr20_pct"] == pytest.approx(5.0)
    assert row["adr20_usd"] == pytest.approx(5.0)
    # 19 days of history: no partial window.
    row19 = hm.compute(bars.iloc[:19], sessions(19)).iloc[-1]
    assert pd.isna(row19["adr20_pct"])


def test_rvol50_excludes_today():
    # 50 sessions at 1,000 shares, then 3,000: RVOL = 3,000 / 1,000 = 3.0.
    volumes = [1000.0] * 50 + [3000.0]
    bars = bars_for("A", [10.0] * 51, volumes=volumes)
    row = last(hm.compute(bars, sessions(51)), "A")
    assert row["rvol50"] == pytest.approx(3.0)
    # 20-day average includes today: (19 × 1,000 + 3,000) / 20 = 1,100.
    assert row["avg_volume_20d"] == pytest.approx(1100.0)


def test_gap_change_close_location():
    bars = bars_for("A", [10.0, 11.0], opens=[10.0, 10.5], highs=[10.0, 12.0], lows=[10.0, 10.0])
    row = last(hm.compute(bars, sessions(2)), "A")
    assert row["gap_pct"] == pytest.approx(5.0)  # 10.5 / 10 − 1
    assert row["chg_pct"] == pytest.approx(10.0)  # 11 / 10 − 1
    assert row["close_loc"] == pytest.approx(0.5)  # (11 − 10) / (12 − 10)
    assert row["dollar_volume"] == pytest.approx(11_000.0)


def test_returns():
    closes = [100.0 + i for i in range(127)]  # 100, 101, ..., 226
    row = last(hm.compute(bars_for("A", closes), sessions(127)), "A")
    assert row["ret_22"] == pytest.approx((226 / 204 - 1) * 100)
    assert row["ret_63"] == pytest.approx((226 / 163 - 1) * 100)
    assert row["ret_126"] == pytest.approx((226 / 100 - 1) * 100)


def test_ma_rising_and_distance_in_adr():
    # Closes 1..15: MA10 today = mean(6..15) = 10.5; 5 sessions ago = mean(1..10) = 5.5.
    closes = [float(i) for i in range(1, 16)]
    highs = [c * 1.1 for c in closes]
    bars = bars_for("A", closes, highs=highs)
    row = last(hm.compute(bars, sessions(15)), "A")
    assert row["ma10"] == pytest.approx(10.5)
    assert bool(row["ma10_rising"]) is True
    # ADR(20) needs 20 days, so the distance in ADR is unknown here.
    assert pd.isna(row["dist_ma10_adr"])
    assert pd.isna(row["ma20_rising"])


def test_distance_from_ma10_in_adr():
    # 20 flat days at 100 with a 2 % range, then MA10 = 100: close 104 sits 2 ADR above.
    closes = [100.0] * 20 + [104.0]
    highs = [102.0] * 20 + [104.0 * 1.02]
    lows = [100.0] * 20 + [104.0]
    row = last(hm.compute(bars_for("A", closes, highs=highs, lows=lows), sessions(21)), "A")
    ma10 = (9 * 100 + 104) / 10  # 100.4
    adr_usd = 2.0 / 100 * 104  # ADR % stays 2.00 (every day's high/low is 1.02)
    assert row["dist_ma10_adr"] == pytest.approx((104 - ma10) / adr_usd)


def test_consecutive_days():
    closes = [10, 11, 12, 11, 10, 9, 9]
    m = hm.compute(bars_for("A", [float(c) for c in closes]), sessions(7))
    assert m["consec_up"].tolist()[1:] == [1, 2, 0, 0, 0, 0]
    assert m["consec_down"].tolist()[1:] == [0, 0, 1, 2, 3, 0]  # an unchanged close ends a run
    assert pd.isna(m["consec_up"].iloc[0])


def test_parabolic_moves_within_10_days():
    # 10 → 15 over the last 10 sessions: +50 %; and the drop from the peak 15 → 10: 33.3 %.
    up = [10.0] * 10 + [11, 12, 13, 15]
    row = last(hm.compute(bars_for("A", up), sessions(14)), "A")
    assert row["gain_max_10d_pct"] == pytest.approx(50.0)
    down = [15.0] * 10 + [12, 11, 10]
    row = last(hm.compute(bars_for("B", down), sessions(13)), "B")
    assert row["drop_max_10d_pct"] == pytest.approx(100 / 3)


def test_missing_session_breaks_windows_instead_of_shifting_them():
    bars = bars_for("A", [100.0] * 20, highs=[105.0] * 20, lows=[100.0] * 20)
    gappy = bars.drop(index=5)  # the ticker has no bar on one session
    row = last(hm.compute(gappy, sessions(20)), "A")
    assert pd.isna(row["adr20_pct"])


def test_keep_limits_output_rows():
    bars = pd.concat([bars_for("A", [10.0] * 30), bars_for("B", [20.0] * 30)])
    days = sessions(30)
    out = hm.compute(bars, days, keep=[days[-1]])
    assert sorted(out["ticker"]) == ["A", "B"] and set(out["session_date"]) == {days[-1]}
