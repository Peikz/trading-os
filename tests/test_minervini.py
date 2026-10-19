"""Minervini's Trend Template and VCP on hand-built bars (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd

from trading_os import minervini
from trading_os.config import load_config

CONF = load_config().minervini
A = "".join(["M", "V", "Q"])


def sessions(n, start=dt.date(2024, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def test_rs_rating_ranks_each_day_across_stocks():
    close = np.vstack([np.full(3, 10.0)] * 126 + [np.array([20.0, 10.0, 5.0])])
    rs = minervini.rs_rating(close)
    assert rs[-1, 0] > rs[-1, 1] > rs[-1, 2] and rs[-1, 0] == 99


def test_contractions_run_from_each_swing_high_to_the_next():
    high = np.array([10, 9, 8, 9.5, 9.6, 9.0, 9.2, 9.3, 9.1, 9.35])
    low = high - 0.1
    found = minervini.contractions(high, low, 2, 1.0)
    assert [round(d, 1) for _, _, d in found] == [21.0, 7.3]
    assert found[-1][0] == 9.6  # the last contraction started from 9.6: the pivot


def vcp_stock(n=420):
    """A stage-2 uptrend, then a base of shrinking pullbacks on drying volume."""
    up = np.linspace(20, 60, n - 60)
    base = np.concatenate(
        [
            60 - np.concatenate([np.linspace(0, 12, 10), np.linspace(12, 2, 10)]),  # -20 %
            60 - np.concatenate([np.linspace(2, 7, 8), np.linspace(7, 1, 8)]),  # ~-10 %
            60 - np.concatenate([np.linspace(1, 3.5, 6), np.linspace(3.5, 0.8, 6)]),  # ~-5 %
            [59.6, 59.7, 59.8, 59.9],
        ]
    )
    close = np.concatenate([up, base])
    volume = np.concatenate([np.full(len(close) - 15, 2e6), np.full(15, 1e6)])
    return close, volume


def test_vcp_on_a_trend_template_stock_breaks_out_at_the_pivot():
    close, volume = vcp_stock()
    n = len(close)
    days = sessions(n + 1)
    close = np.append(close, 61.5)  # the breakout day
    volume = np.append(volume, 4e6)
    g = {
        "open": close.copy(),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close.copy(),
        "volume": volume,
    }
    g = {k: v[:, None] for k, v in g.items()}
    g["open"][-1, 0] = 59.9
    rs = np.full_like(g["close"], 90.0)
    hits = minervini.find(g, pd.Index([A]), days, CONF, rs)
    vcp = hits[hits["strategy"] == "vcp_breakout"]
    assert days[-1] in set(vcp["session_date"])
    row = vcp[vcp["session_date"] == days[-1]].iloc[0]
    assert row["contractions"] >= 2 and row["last_depth_pct"] <= CONF["last_contraction_max_pct"]
    assert row["vol_ratio"] > 1.4 and row["pivot"] <= g["high"][-1, 0]
    assert "minervini_tt" in set(hits["strategy"])


def test_weak_rs_fails_the_trend_template():
    close, volume = vcp_stock()
    g = {"close": close[:, None], "high": close[:, None] * 1.01, "low": close[:, None] * 0.99}
    assert minervini.trend_template(g, np.full_like(g["close"], 90.0), CONF)[-1, 0]
    assert not minervini.trend_template(g, np.full_like(g["close"], 50.0), CONF)[-1, 0]
