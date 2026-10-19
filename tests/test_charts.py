import datetime as dt

import numpy as np
import pandas as pd

from trading_os import charts

DAY0 = dt.date(2026, 6, 1)


def synthetic_bars(n=150, ticker="AAA"):
    rng = np.random.default_rng(7)
    close = 20 * np.exp(np.cumsum(rng.normal(0.002, 0.02, n)))
    days = [DAY0 + dt.timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {
            "session_date": days,
            "ticker": ticker,
            "open": close * (1 + rng.normal(0, 0.005, n)),
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n).astype(float),
        }
    )


def test_before_shot_draws_once(tmp_path):
    bars = synthetic_bars()
    signal = bars["session_date"].iloc[-1]
    path = charts.chart_path(tmp_path, "ep_day", "BRK.B")
    assert path.name == "ep_day_BRK-B.png"
    out = charts.before_shot(
        bars, path, title="t", signal_session=signal, sessions=120, pivot=25.0, order_stop=23.0
    )
    assert out == path and path.stat().st_size > 5_000
    mtime = path.stat().st_mtime_ns
    charts.before_shot(bars, path, title="t", signal_session=signal, sessions=120)
    assert path.stat().st_mtime_ns == mtime  # never redrawn


def test_chart_stops_at_the_signal_session(tmp_path):
    bars = synthetic_bars()
    path = tmp_path / "c.png"
    # A signal before any bar: nothing to draw.
    assert (
        charts.before_shot(
            bars, path, title="t", signal_session=DAY0 - dt.timedelta(days=1), sessions=60
        )
        is None
    )
    assert not path.exists()


def test_draw_for_run_skips_tickers_without_bars(tmp_path):
    bars = synthetic_bars()
    signal = bars["session_date"].iloc[-1]
    selected = {"ep_day": pd.DataFrame({"ticker": ["AAA", "ZZZ"], "rank": [1, 2]})}
    drawn = charts.draw_for_run(tmp_path, signal, "eod", selected, bars, 120)
    assert list(drawn) == [("ep_day", "AAA")]
