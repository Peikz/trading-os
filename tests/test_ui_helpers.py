"""The dashboard's shared UI helpers (app/ui.py), on synthetic data."""

import sys

import pandas as pd
import pytest

pytest.importorskip("streamlit")
sys.path.insert(0, "app")
import ui  # noqa: E402


def test_utc_timestamps_read_in_new_york_and_copenhagen():
    text = ui.fmt_ts("2020-01-15T15:02:42.595549+00:00")
    assert text == "01-15 10:02 NY · 16:02 CPH"  # an old date shows the day too
    assert ui.fmt_ts(None) == "" and ui.fmt_ts(float("nan")) == ""


def test_raw_timestamp_columns_are_made_readable_but_dates_are_left():
    df = pd.DataFrame(
        {
            "fired_ts": ["2020-01-15T15:02:42+00:00"],
            "added_date": ["2020-01-15"],
            "n": [1],
        }
    )
    out = ui.readable_times(df)
    assert out["fired_ts"][0].endswith("CPH")
    assert out["added_date"][0] == "2020-01-15" and out["n"][0] == 1


def test_snake_case_names_become_words():
    assert ui.words("gap_min_pct") == "Gap min %"
    assert ui.words("net_r") == "Net R"
    assert ui.words("push_tier") == "Push tier"


def test_phone_column_order_puts_long_text_last():
    df = pd.DataFrame(
        {
            "setup": ["a", "b"],
            "plan": ["a long sentence about the plan here", "another long sentence about it"],
            "r": [0.1, 0.2],
        }
    )
    assert list(ui._text_last(df).columns) == ["setup", "r", "plan"]


def test_not_a_phone_without_a_request():
    assert ui.is_phone() is False


def test_close_level_labels_go_to_opposite_sides_and_stack_when_crowded():
    from trading_os import interactive_chart as ichart

    bars = pd.DataFrame(
        {
            "session_date": pd.date_range("2026-01-01", periods=30, freq="B"),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 1e6,
        }
    )
    fig = ichart.daily_figure(
        bars, title="t", levels={"pivot": 11.04, "order stop": 10.39, "entry": 10.40}
    )
    sides = {a.text.rsplit(" ", 1)[0]: a.xanchor for a in fig.layout.annotations if a.text}
    assert sides["order stop"] != sides["entry"]  # two close levels: opposite sides


def test_phone_figure_has_few_horizontal_month_ticks_and_no_mode_bar():
    from trading_os import interactive_chart as ichart

    bars = pd.DataFrame(
        {
            "session_date": pd.date_range("2025-06-01", periods=200, freq="B"),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 1e6,
        }
    )
    fig = ichart.for_phone(ichart.daily_figure(bars, title="t"))
    assert len(fig.layout.xaxis.tickvals) <= 5 and fig.layout.xaxis.tickangle == 0
    assert fig.layout.legend.orientation == "h"
    assert ichart.phone_config({"scrollZoom": True})["modeBarButtons"] == [
        ["drawline", "eraseshape", "resetScale2d"]
    ]
    assert not fig.layout.title.text
