"""Managed exits against hand-computed trades. Entry 10 at the close of day 0, stop 9 (R = 1)."""

import numpy as np
import pytest

from trading_os import exits
from trading_os.config import load_config


def bars(closes, lows=None, highs=None, opens=None):
    c = np.array(closes, dtype=float)
    lo = np.array(lows if lows is not None else c - 0.1, dtype=float)
    h = np.array(highs if highs is not None else c + 0.1, dtype=float)
    o = np.array(opens if opens is not None else c, dtype=float)
    return o, h, lo, c


def test_partial_on_day_3_then_trail_to_a_close_under_the_ma():
    o, h, lo, c = bars([10, 11, 12, 13, 14, 15, 13.5])
    ma = np.array([np.nan, np.nan, np.nan, 12, 13, 14, 14.0])  # day 6 closes under it
    r, days = exits.partial_trail(o, h, lo, c, ma, 0, 10.0, 9.0, 1, 3, 1 / 3, 126)
    # A third at 13 (+3R), the rest at 13.5 (+3.5R).
    assert r == pytest.approx(1 / 3 * 3 + 2 / 3 * 3.5) and days == 6


def test_stopped_before_the_partial_is_a_full_loss():
    o, h, lo, c = bars([10, 9.5, 8.5, 9], lows=[9.9, 9.4, 8.4, 8.9], opens=[10, 9.5, 8.7, 9])
    ma = np.full(4, np.nan)
    r, days = exits.partial_trail(o, h, lo, c, ma, 0, 10.0, 9.0, 1, 3, 1 / 3, 126)
    assert r == pytest.approx(-1.3) and days == 2  # day 2 opens 8.7, under the stop: filled there


def test_break_even_after_the_partial():
    o, h, lo, c = bars([10, 11, 12, 12.5, 11, 10.5], lows=[9.9, 10.9, 11.9, 12.4, 10.9, 9.9])
    ma = np.full(6, np.nan)
    r, days = exits.partial_trail(o, h, lo, c, ma, 0, 10.0, 9.0, 1, 3, 1 / 3, 126)
    # A third at 12.5 (+2.5R); day 5 trades back to 10: the rest at break-even (0R).
    assert r == pytest.approx(2.5 / 3) and days == 5


def test_time_and_target_exits():
    o, h, lo, c = bars(
        [10, 10.4, 10.9, 10.6, 10.5, 10.2],
        highs=[10, 10.5, 10.95, 10.7, 10.6, 10.3],
        opens=[10, 10.3, 10.5, 10.6, 10.5, 10.2],
    )
    assert exits.time_exit(o, h, lo, c, 0, 10.0, 9.0, 1, 3) == pytest.approx(0.6)
    # +8 % = 10.8: day 2's high 10.95 reaches it.
    assert exits.target_exit(o, h, lo, c, 0, 10.0, 9.0, 1, 8, 5) == pytest.approx(0.8)
    # Not reached within 1 day: out at day 1's close.
    assert exits.target_exit(o, h, lo, c, 0, 10.0, 9.0, 1, 8, 1) == pytest.approx(0.4)


def test_short_partial_and_trail_mirror_the_long():
    o, h, lo, c = bars([20, 19, 18, 17, 16, 17.5])
    ma = np.array([np.nan, np.nan, np.nan, 18, 17, 17.0])  # day 5 closes above it
    r, days = exits.partial_trail(o, h, lo, c, ma, 0, 20.0, 21.0, -1, 3, 1 / 3, 126)
    assert r == pytest.approx(1 / 3 * 3 + 2 / 3 * 2.5) and days == 5


def test_managed_names_and_no_stop():
    rules = load_config().exits
    o, h, lo, c = bars([10, 11, 12, 13, 14, 15, 16])
    mas = {w: np.full(7, np.nan) for w in rules["trail_mas"]}
    row = exits.managed(o, h, lo, c, mas, 0, 10.0, 9.0, 1, rules)
    assert set(exits.columns(rules)) <= set(row)
    assert row["r_time5d"] == pytest.approx(5.0)
    empty = exits.managed(o, h, lo, c, mas, 0, 10.0, None, 1, rules)
    assert all(np.isnan(empty[k]) for k in exits.columns(rules))
