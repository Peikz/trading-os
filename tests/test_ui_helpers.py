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
