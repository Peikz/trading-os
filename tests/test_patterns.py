"""High tight flag and pocket pivot on hand-built bars (synthetic data only)."""

import copy
import datetime as dt

import numpy as np
import pandas as pd
import pytest
import yaml

from trading_os import patterns
from trading_os.config import DEFAULT_PATH, ConfigError, load_config, parse_config

CFG = load_config()
A = "".join(["H", "T", "Q"])


def days(n, start=dt.date(2025, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def grid(close, high, low, volume):
    g = {"open": close, "high": high, "low": low, "close": close, "volume": volume}
    return {k: np.asarray(v, dtype=float)[:, None].copy() for k, v in g.items()}


def failing(found) -> set:
    return {k for k, v in found["rules"].items() if not v[-1, 0]}


# --- grid helpers ---


def test_last_extreme_gives_the_value_and_sessions_since_the_earliest_extreme():
    a = np.array([[1.0], [5], [3], [5], [2]])
    value, since = patterns.last_extreme(a, 4, "max")
    assert value[4, 0] == 5 and since[4, 0] == 3  # rows 1-4: the first 5 is 3 sessions back
    assert np.isnan(value[2, 0])  # no full window yet
    low, low_since = patterns.last_extreme(a, 3, "min")
    assert low[4, 0] == 2 and low_since[4, 0] == 0


def test_offsets_and_windows_per_cell():
    a = np.arange(10.0)[:, None]
    back = np.full((10, 1), 2.0)
    assert patterns.at_offset(a, back)[5, 0] == 3 and np.isnan(patterns.at_offset(a, back)[1, 0])
    low = np.array([[4.0], [2], [6], [5], [7]])
    start, end = np.full((5, 1), 3.0), np.full((5, 1), 1.0)  # rows t-3 .. t-1
    assert patterns.min_since(low, start, end, 4)[4, 0] == 2
    rows = np.arange(5.0)[:, None]
    assert patterns.mean_between(low, rows - 2, rows)[4, 0] == 6  # rows 2-4


# --- high tight flag ---


def htf(pole_to=21.0, flag_days=20, depth=0.12, flag_volume=1e6, before=10.0):
    """Quiet at `before` (60 sessions, then a slide to 10 over 10 if it is higher), a 20-
    session pole from 10 to `pole_to`, then a flag drifting `depth` under the pole's high."""
    head = [before] * 50 + list(np.linspace(before, 10.0, 10))
    pole = list(np.linspace(10.0, pole_to, 21)[1:])
    close = np.array(head + pole)
    high, low = close * 1.02, close * 0.98
    volume = np.concatenate([np.full(60, 1e6), np.full(20, 3e6)])
    pivot = pole_to * 1.02
    flag = [pivot * (0.97 - depth * 0.6 * np.sin(np.pi * k / flag_days)) for k in range(flag_days)]
    flag_low = [c * 0.99 for c in flag]
    flag_low[flag_days // 2] = pivot * (1 - depth)  # the flag's deepest point
    close = np.append(close, flag)
    high = np.append(high, [c * 1.01 for c in flag])
    low = np.append(low, flag_low)
    volume = np.append(volume, np.full(flag_days, flag_volume))
    return grid(close, high, low, volume)


def test_a_doubled_stock_flagging_for_four_weeks_is_a_high_tight_flag():
    g = htf()
    found = patterns.htf_rules(g, CFG.htf)
    assert failing(found) == set()
    pivot = found["pivot"][-1, 0]
    assert np.isclose(pivot, 21.0 * 1.02) and found["flag_days"][-1, 0] == 20
    assert found["pole_pct"][-1, 0] >= 100 and found["pole_days"][-1, 0] <= 40
    assert np.isclose(found["flag_depth_pct"][-1, 0], 12.0)
    assert np.isclose(found["flag_volume_ratio"][-1, 0], 1 / 3)
    stop = max(g["low"][-5:, 0].min(), pivot * 0.92)
    assert np.isclose(found["order_stop"][-1, 0], stop)
    hits = patterns.find(g, pd.Index([A]), days(len(g["close"])), CFG)
    flags = hits[hits["strategy"] == "htf"]
    assert flags["pivot_date"].nunique() == 1 and flags["day_in_setup"].iloc[-1] == len(flags)


def test_a_smaller_pole_is_no_high_tight_flag():
    assert failing(patterns.htf_rules(htf(pole_to=15.0), CFG.htf)) == {"pole"}


def test_a_flag_needs_three_weeks():
    assert failing(patterns.htf_rules(htf(flag_days=10), CFG.htf)) == {"flag_length"}


def test_a_flag_over_six_weeks_old_has_no_pole_left():
    # the pole's high drops out of the window: the flag's own high is no new high
    assert "pole_top" in failing(patterns.htf_rules(htf(flag_days=36), CFG.htf))


def test_a_deep_flag_is_no_high_tight_flag():
    assert failing(patterns.htf_rules(htf(depth=0.30), CFG.htf)) == {"flag_depth"}


def test_a_flag_on_pole_volume_is_no_high_tight_flag():
    assert failing(patterns.htf_rules(htf(flag_volume=3e6), CFG.htf)) == {"flag_volume"}


def test_a_rebound_to_under_an_old_high_is_no_pole():
    assert failing(patterns.htf_rules(htf(before=25.0), CFG.htf)) == {"pole_top"}


# --- pocket pivot ---


def uptrend(n=150):
    """Three up days (+1 %, light volume) and two down days (-0.8 %, heavier), repeated."""
    steps = [1.01, 1.01, 1.01, 0.992, 0.992] * (n // 5)
    close = 10 * np.cumprod(steps)
    volume = np.array([0.8e6, 0.8e6, 0.8e6, 1.0e6, 1.0e6] * (n // 5))
    return close, volume


def with_day(close, volume, chg=1.01, day_volume=1.2e6, low=0.99, high=1.01):
    c = close[-1] * chg
    closes = np.append(close, c)
    highs = np.append(close * 1.01, c * high)
    lows = np.append(close * 0.99, c * low)
    return grid(closes, highs, lows, np.append(volume, day_volume))


def test_an_up_day_off_the_10_day_beating_every_down_volume_is_a_pocket_pivot():
    close, volume = uptrend()
    g = with_day(close, volume)
    found = patterns.pocket_pivot_rules(g, CFG.pocket_pivot)
    assert failing(found) == set()
    assert found["pivot_ma"][-1, 0] == 10 and found["down_volume_max"][-1, 0] == 1e6
    assert np.isclose(found["volume_vs_down"][-1, 0], 1.2)
    assert (
        found["order_stop"][-1, 0] == g["low"][-1, 0] and found["pivot"][-1, 0] == g["high"][-1, 0]
    )
    hits = patterns.find(g, pd.Index([A]), days(len(g["close"])), CFG)
    assert days(len(g["close"]))[-1] in set(
        hits.loc[hits["strategy"] == "pocket_pivot", "session_date"]
    )


def test_volume_under_a_down_day_is_no_pocket_pivot():
    close, volume = uptrend()
    found = patterns.pocket_pivot_rules(
        with_day(close, volume, day_volume=0.95e6), CFG.pocket_pivot
    )
    assert failing(found) == {"volume"}


def test_a_down_day_is_no_pocket_pivot():
    close, volume = uptrend()
    found = patterns.pocket_pivot_rules(with_day(close, volume, chg=0.999), CFG.pocket_pivot)
    assert "up_day" in failing(found)  # (and the volume rule needs an up day)


def test_an_extended_gap_up_is_no_pocket_pivot():
    close, volume = uptrend()
    g = with_day(close, volume, chg=1.06, low=0.99)  # low 5 % over yesterday's close
    assert failing(patterns.pocket_pivot_rules(g, CFG.pocket_pivot)) == {"near_ma"}


def test_a_pivot_under_the_10_day_off_the_50_day_is_a_base_pocket_pivot():
    close, volume = uptrend()
    close = np.concatenate([close, close[-1] * np.cumprod([0.99] * 5)])  # pull back ...
    volume = np.append(volume, np.full(5, 0.9e6))  # ... on lighter volume
    found = patterns.pocket_pivot_rules(with_day(close, volume, chg=1.012), CFG.pocket_pivot)
    assert failing(found) == set() and found["pivot_ma"][-1, 0] == 50
    assert found["low_vs_ma_adr"][-1, 0] < 0 < found["close_vs_ma_adr"][-1, 0]  # undercut, reclaim


def test_a_pocket_pivot_under_a_declining_50_day_is_improper():
    down = 20 * np.cumprod([0.995] * 100)
    close, volume = uptrend(15)
    close = np.concatenate([down, down[-1] * close / close[0] * 1.1])
    volume = np.concatenate([np.full(100, 1e6), volume])
    found = patterns.pocket_pivot_rules(with_day(close, volume), CFG.pocket_pivot)
    assert failing(found) == {"above_rising_ma50"}


def test_the_study_sections_are_checked_like_every_other():
    with open(DEFAULT_PATH, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    for section, key, value, error in (
        ("htf", "pole_min", 100, "unknown keys"),
        ("qm_surf", "adr_min_pct", "4%", "expected a number"),
        ("pocket_pivot", "touch_adr", None, "missing keys"),
    ):
        bad = copy.deepcopy(raw)
        if value is None:
            del bad[section][key]
        else:
            bad[section][key] = value
        with pytest.raises(ConfigError, match=error):
            parse_config(bad)
