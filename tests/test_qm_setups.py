"""Qullamaggie's MA-surf breakout on hand-built bars (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd

from trading_os import qm_setups
from trading_os.config import load_config

CONF = load_config().qm_surf
A = "".join(["Q", "S", "F"])


def days(n, start=dt.date(2025, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def surfer(leg_to=15.0, spread=(1.04, 0.985)):
    """60 quiet sessions at 10, a 30-session leg to `leg_to` (its last high is the pivot P),
    then an 8-session base on low volume: a dip to 0.92 P, a higher low, a tight right side."""
    up, down = spread
    close = np.concatenate([np.full(60, 10.0), np.linspace(10.0, leg_to, 31)[1:]])
    g = {
        "open": close.copy(),
        "high": close * up,
        "low": close * down,
        "close": close.copy(),
        "volume": np.concatenate([np.full(60, 1e6), np.full(30, 1.5e6)]),
    }
    pivot = leg_to * up
    base = [  # (high, low, close) as fractions of the pivot
        (0.985, 0.955, 0.960),
        (0.968, 0.940, 0.955),
        (0.962, 0.920, 0.952),
        (0.966, 0.950, 0.960),
        (0.970, 0.953, 0.964),
        (0.972, 0.956, 0.966),
        (0.973, 0.958, 0.968),
        (0.974, 0.960, 0.970),
    ]
    for h, lo, c in base:
        for field, value in (("open", c), ("high", h), ("low", lo), ("close", c)):
            g[field] = np.append(g[field], value * pivot)
        g["volume"] = np.append(g["volume"], 0.6e6)
    return {k: v[:, None].copy() for k, v in g.items()}


def check(g, conf=CONF):
    found = qm_setups.rules(g, conf)
    return {k: bool(v[-1, 0]) for k, v in found["rules"].items()}, found


def failing(g, conf=CONF) -> set:
    """The rules the last session fails."""
    return {k for k, ok in check(g, conf)[0].items() if not ok}


def test_a_base_riding_the_10_day_is_a_setup_with_its_pivot_and_stop():
    g = surfer()
    rules, found = check(g)
    assert all(rules.values()), rules
    pivot, adr = found["pivot"][-1, 0], found["adr_usd"][-1, 0]
    assert np.isclose(pivot, 15.0 * 1.04)  # the leg's last high
    assert found["base_len"][-1, 0] == 9 and found["surf_ma"][-1, 0] == 10
    right_low = pivot * 0.956
    assert np.isclose(found["order_stop"][-1, 0], max(right_low, pivot - adr))
    assert np.isclose(found["max_entry"][-1, 0], g["close"][-1, 0] + adr)
    assert found["trail_ma"][-1, 0] == 20  # ADR under 5 %: the 20-day trail
    hits = qm_setups.find(g, pd.Index([A]), days(len(g["close"])), CONF)
    last = hits[hits["session_date"] == days(len(g["close"]))[-1]].iloc[0]
    assert last["pivot_date"] == days(len(g["close"]))[89]
    assert last["ma_low_adr"] < 0  # the dip undercut the 10-day intraday; its close held


def test_the_same_base_counts_its_days():
    g = surfer()
    hits = qm_setups.find(g, pd.Index([A]), days(len(g["close"])), CONF)
    assert list(hits["day_in_setup"]) == list(range(1, len(hits) + 1))
    assert hits["pivot_date"].nunique() == 1


def test_a_fast_stock_trails_the_10_day():
    _, found = check(surfer(spread=(1.07, 0.985)))
    assert found["adr_pct"][-1, 0] >= 5 and found["trail_ma"][-1, 0] == 10


def test_a_small_prior_move_is_no_setup():
    assert failing(surfer(leg_to=12.0)) == {"prior_move"}  # +27 %, low to high


def test_a_quiet_stock_is_no_setup():
    # ADR under 3 %: and the pivot, 3 % over the close, is then more than 1 ADR away
    assert failing(surfer(spread=(1.02, 0.99))) == {"adr", "reachable"}


def test_a_close_under_the_10_and_20_day_breaks_the_surf():
    g = surfer()
    g["close"][-4, 0] = g["low"][-4, 0] = 13.0  # one close far under both MAs
    assert failing(g) == {"surf", "near_ma"}  # no MA surfed, so none to be near


def test_a_close_under_the_10_day_but_on_the_20_day_surfs_the_20_day():
    g = surfer()
    g["close"][-4, 0] = g["low"][-4, 0] = 14.3  # under MA10 (~14.8), over MA20 (~14.1)
    rules, found = check(g)
    assert all(rules.values()) and found["surf_ma"][-1, 0] == 20


def test_an_extended_stock_is_not_near_its_ma():
    rules, found = check(surfer())
    assert rules["near_ma"] and 0.1 < found["surf_ma_dist_adr"][-1, 0] < 0.5
    stricter = {**CONF, "near_ma_adr_max": 0.1}  # the same close is too far over it
    assert failing(surfer(), stricter) == {"near_ma"}


def test_a_new_low_on_the_right_side_is_no_higher_low():
    g = surfer()
    g["low"][-1, 0] = 15.6 * 0.915  # under the dip's low
    assert failing(g) == {"higher_low"}


def test_a_wide_right_side_is_not_tight():
    g = surfer()
    g["high"][-2, 0] = 15.6 * 0.995  # still under the pivot, but a wide right side
    g["low"][-3, 0] = 15.6 * 0.925  # still a higher low
    assert failing(g) == {"tight"}


def test_heavy_volume_on_the_right_side_is_not_dry():
    g = surfer()
    g["volume"][-3:, 0] = 2e6
    assert failing(g) == {"dry"}


def test_a_pivot_more_than_one_adr_away_is_out_of_reach():
    g = surfer()
    g["high"][89, 0] = 15.6 * 1.06  # a spike high: the pivot moves 6 % up
    assert failing(g) == {"reachable"}


def test_a_base_needs_five_sessions():
    g = {k: v[:-5] for k, v in surfer().items()}  # 4 sessions from the leg's high
    assert failing(g) == {"base", "higher_low"}  # the dip is still the right side
