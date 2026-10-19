"""Martin Luk's setups on hand-built bars (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd

from trading_os import history_metrics as hm
from trading_os import luk, strategy_history
from trading_os.config import load_config

CONF = load_config().luk
A = "".join(["L", "K", "Q"])


def days(n, start=dt.date(2025, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def rising(n=140):
    """A leader: 10 -> 40, daily range ~6.5 % (high 6 % over, low 0.5 % under the close)."""
    close = np.linspace(10, 40, n)
    g = {
        "open": close.copy(),
        "high": close * 1.06,
        "low": close * 0.995,
        "close": close.copy(),
        "volume": np.full(n, 1e6),
    }
    return {k: v[:, None].copy() for k, v in g.items()}


def test_avwap_is_anchored_at_the_highest_high_of_the_window():
    high = np.array([[5.0], [9.0], [6.0], [6.0]])
    g = {
        "high": high,
        "low": high - 1,
        "close": high - 0.5,
        "volume": np.array([[1.0], [1], [1], [3]]),
    }
    avwap, since = luk.avwap_from_high(g, 3)
    tp = (high + high - 1 + high - 0.5) / 3
    # Last row: window rows 1-3, highest high at row 1, VWAP over rows 1..3.
    expected = (tp[1, 0] * 1 + tp[2, 0] * 1 + tp[3, 0] * 3) / 5
    assert np.isclose(avwap[3, 0], expected) and since[3, 0] == 2
    assert np.isnan(avwap[1, 0])  # no full window yet


def test_pullback_needs_the_low_at_yesterdays_ema_and_a_close_above_it():
    g = rising()
    ema9 = hm.ema(g["close"], 9)[:, 0]
    sessions = days(len(g["close"]))
    quiet = luk.find(g, pd.Index([A]), sessions, CONF)
    assert sessions[-1] not in set(quiet.loc[quiet["strategy"] == "luk_pullback", "session_date"])
    g["low"][-1, 0] = ema9[-2] - 0.05  # dips to yesterday's EMA 9 ...
    hits = luk.find(g, pd.Index([A]), sessions, CONF)
    pull = hits[(hits["strategy"] == "luk_pullback") & (hits["session_date"] == sessions[-1])]
    assert len(pull) == 1 and np.isclose(pull["level"].iloc[0], ema9[-2])
    g["close"][-1, 0] = ema9[-2] - 0.01  # ... but closes under it: no setup
    again = luk.find(g, pd.Index([A]), sessions, CONF)
    assert sessions[-1] not in set(again.loc[again["strategy"] == "luk_pullback", "session_date"])


def test_inside_day_in_a_lead_stock_keeps_its_high_as_the_pivot():
    g = rising()
    sessions = days(len(g["close"]))
    c = g["close"][-2, 0]
    g["high"][-1, 0], g["low"][-1, 0], g["close"][-1, 0] = c * 1.03, c * 1.0, c * 1.02
    hits = luk.find(g, pd.Index([A]), sessions, CONF)
    inside = hits[(hits["strategy"] == "luk_inside_day") & (hits["session_date"] == sessions[-1])]
    assert len(inside) == 1 and np.isclose(inside["pivot"].iloc[0], c * 1.03)


def test_every_strategy_gets_the_ema_exits():
    c = np.array([10, 11, 12, 13, 12, 11, 10.0])
    o, h, lo = c.copy(), c + 0.5, c - 0.5
    mas = {w: hm.rolling_mean(c[:, None], 2)[:, 0] for w in strategy_history.TRAILS}
    emas = {w: hm.ema(c[:, None], 2)[:, 0] for w in strategy_history.EMA_TRAILS}
    row = strategy_history.outcomes(o, h, lo, c, mas, 0, 10.0, 9.0, 1, emas)
    assert {"r_trail_ema9", "r_trail_ema21", "r_trail_ma20"} <= set(row)
    # EMA(2) under a falling close: the first close under it is day 4 (12 < EMA).
    assert row["days_trail_ema9"] == 4 and np.isclose(row["r_trail_ema9"], 2.0)
