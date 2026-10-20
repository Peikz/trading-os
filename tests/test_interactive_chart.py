"""Interactive charts and saved chart marks (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("plotly")  # a dashboard dependency (the app group); CI runs without it
from trading_os import interactive_chart as ic  # noqa: E402

A = "".join(["C", "H", "Q"])


def bars(n=30, start=dt.date(2026, 1, 5)):
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    close = np.linspace(10, 13, n)
    return pd.DataFrame(
        {
            "session_date": days,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": np.full(n, 1000.0),
            "vwap": close,
        }
    )


def test_weekly_bars_take_the_week_open_high_low_close_and_volume():
    w = ic.weekly(bars(10))
    first = bars(10).iloc[:5]
    assert len(w) == 2 and w.iloc[0]["open"] == first["open"].iloc[0]
    assert w.iloc[0]["high"] == first["high"].max() and w.iloc[0]["volume"] == 5000
    assert w.iloc[0]["session_date"] == first["session_date"].iloc[-1]


def test_anchored_vwap_starts_at_the_anchor_and_weights_by_volume():
    b = bars(5)
    b.loc[3, "volume"] = 3000.0
    v = ic.anchored_vwap(b, b["session_date"].iloc[2])
    assert v.iloc[:2].isna().all() and v.iloc[2] == pytest.approx(b["close"].iloc[2])
    expected = (b["close"].iloc[2] * 1000 + b["close"].iloc[3] * 3000) / 4000
    assert v.iloc[3] == pytest.approx(expected)


def test_trend_lines_run_on_trading_days_and_extend_to_the_last():
    b = bars(10)
    labels = [d.isoformat() for d in b["session_date"]]
    xs, ys = ic.trend_line(labels, b["session_date"][1], 10.0, b["session_date"][3], 11.0)
    assert xs[0] == labels[1] and xs[-1] == labels[-1]  # extended
    assert ys[2] == pytest.approx(11.0) and ys[-1] == pytest.approx(10.0 + 0.5 * 8)
    short = ic.trend_line(labels, b["session_date"][3], 11.0, b["session_date"][1], 10.0, False)
    assert short[0][-1] == labels[3]  # points in either order, not extended
    assert ic.trend_line(labels, dt.date(2020, 1, 2), 1.0, b["session_date"][1], 2.0) is None


def test_quick_anchors_find_the_high_low_and_year_start():
    b = bars(30)
    anchors = ic.quick_anchors(b)
    assert anchors["highest high"] == b["session_date"].iloc[-1]
    assert anchors["lowest low"] == b["session_date"].iloc[0]
    assert anchors["year start"] == b["session_date"].iloc[0]


def test_daily_figure_draws_candles_lines_markers_fills_and_levels():
    b = bars(30)
    markers = pd.DataFrame(
        {"session_date": [b["session_date"][5]], "label_text": ["ep_day"], "side": ["long"]}
    )
    fills = pd.DataFrame(
        {"session_date": [b["session_date"][6]], "price": [11.0], "side": ["buy"], "quantity": [10]}
    )
    fig = ic.daily_figure(
        b,
        title=A,
        overlays=["MA10", "EMA9"],
        markers=markers,
        fills=fills,
        levels={"pivot": 12.0},
    )
    names = [t.name for t in fig.data]
    assert {"price", "MA10", "EMA9", "volume", "scan hits (long)", "my buys"} <= set(names)
    assert any("pivot" in str(a.text) for a in fig.layout.annotations)
    ic.add_avwaps(fig, b, {"low": b["session_date"][0]}, list(fig.data[0].x))
    assert "AVWAP low" in [t.name for t in fig.data]


def test_intraday_figure_draws_vwap_from_the_open():
    ts = pd.date_range("2026-03-02 09:00", periods=120, freq="1min", tz="America/New_York")
    m = pd.DataFrame(
        {
            "ts": ts,
            "minute": ts.hour * 60 + ts.minute,
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "volume": 100.0,
            "vwap": 10.0,
        }
    )
    vwap = ic.session_vwap(m)
    assert vwap[m["minute"] < 570].isna().all() and vwap.iloc[-1] == pytest.approx(10.0)
    fig = ic.intraday_figure(m, title=A, prev_close=9.5, every=5)
    assert "VWAP" in [t.name for t in fig.data]
