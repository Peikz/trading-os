"""Strategy history: long/short outcome arithmetic and an end-to-end replay on hand-built bars."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import strategy_history as sh
from trading_os.config import load_config


def arrays(closes, highs=None, lows=None, opens=None):
    c = np.array(closes, dtype=float)
    h = np.array(highs if highs is not None else c + 0.5, dtype=float)
    lo = np.array(lows if lows is not None else c - 0.5, dtype=float)
    o = np.array(opens if opens is not None else c, dtype=float)
    mas = {w: np.full(len(c), np.nan) for w in sh.TRAILS}
    return o, h, lo, c, mas


def test_long_outcome_with_a_gap_through_the_stop():
    o, h, lo, c, mas = arrays([10, 11, 12, 9, 9, 9, 9])
    o[3] = 8.5  # opens under the stop at 9.5
    lo[3] = 8.4
    row = sh.outcomes(o, h, lo, c, mas, 0, 10.0, 9.5, side=1)
    assert row["pnl_1d"] == pytest.approx(10.0)
    assert row["stop_hit_5d"] and row["r_5d"] == pytest.approx((8.5 - 10) / 0.5)
    assert row["best_5d"] == pytest.approx((12.5 / 10 - 1) * 100)


def test_short_outcome_profits_when_it_falls_and_stops_above():
    o, h, lo, c, mas = arrays([20, 19, 18, 17, 16, 15])
    row = sh.outcomes(o, h, lo, c, mas, 0, 20.0, 21.0, side=-1)
    assert row["pnl_5d"] == pytest.approx(25.0)  # 20 -> 15 short
    assert not row["stop_hit_5d"] and row["r_5d"] == pytest.approx(5.0)
    # A squeeze that opens at 22, over the 21 stop: filled at the open, -2R.
    o2, h2, lo2, c2, mas2 = arrays([20, 22, 18, 17, 16, 15])
    row2 = sh.outcomes(o2, h2, lo2, c2, mas2, 0, 20.0, 21.0, side=-1)
    assert row2["stop_hit_1d"] and row2["r_1d"] == pytest.approx(-(22.0 - 20) / 1.0)


def test_no_stop_means_returns_only():
    o, h, lo, c, mas = arrays([10, 11, 12, 13, 14, 15])
    row = sh.outcomes(o, h, lo, c, mas, 0, 10.0, None, side=1)
    assert row["pnl_5d"] == pytest.approx(50.0) and np.isnan(row["r_5d"])


def synthetic_bars():
    days = list(pd.bdate_range("2025-01-02", periods=240).date)
    rows = []
    for name, move in (("UPX", 1.06), ("DNX", 0.94), ("FLT", 1.0)):
        for i, day in enumerate(days):
            close = 20.0 * (move if i >= 200 else 1.0)  # one burst, then flat
            vol = 1_500_000 if i == 200 else 800_000
            high = close * 1.002 if name == "UPX" and i == 200 else close * 1.01
            low = close * 0.99
            rows.append(
                {"session_date": day, "ticker": name, "open": close, "high": high}
                | {"low": low, "close": close, "volume": vol}
            )
    return pd.DataFrame(rows), days


def test_replay_runs_the_live_scans_and_measures_both_sides():
    bars, days = synthetic_bars()
    found = sh.find(bars, days, load_config(), caps={})
    mb = found[found["strategy"].isin(["mb_up", "mb_down"])].set_index("strategy")
    assert mb.loc["mb_up", "ticker"] == "UPX" and mb.loc["mb_up", "side"] == "long"
    assert mb.loc["mb_down", "ticker"] == "DNX" and mb.loc["mb_down", "side"] == "short"
    assert mb.loc["mb_up", "session_date"] == days[200]
    # Flat after the burst: no profit either way, and the stops sit beyond the signal bar.
    assert mb.loc["mb_up", "pnl_5d"] == pytest.approx(0.0, abs=1e-4)
    assert mb.loc["mb_down", "stop"] > mb.loc["mb_down", "entry"]
    table = sh.summary(found).set_index("strategy")
    assert table.loc["mb_up", "events"] == 1


def test_fridays_are_the_last_session_of_each_week():
    days = [dt.date(2026, 10, d) for d in (12, 13, 14, 15, 16, 19, 20)]
    assert sh._fridays(days) == {dt.date(2026, 10, 16), dt.date(2026, 10, 20)}
