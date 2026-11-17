"""Saved chart marks: trend lines and AVWAP anchors per ticker (synthetic data only)."""

import datetime as dt

from trading_os import chart_marks

A = "".join(["C", "H", "Q"])


def test_saved_marks_follow_add_and_remove(tmp_path):
    line = chart_marks.add_line(tmp_path, A, dt.date(2026, 1, 5), 10, dt.date(2026, 1, 9), 11)
    chart_marks.add_anchor(tmp_path, A, dt.date(2026, 1, 6), "gap")
    marks = chart_marks.current(tmp_path, A)
    assert sorted(marks["kind"]) == ["anchor", "line"]
    chart_marks.remove(tmp_path, line)
    assert chart_marks.current(tmp_path, A)["kind"].tolist() == ["anchor"]
    assert chart_marks.current(tmp_path, "OTHER").empty


def pts(x0, y0, x1, y1, mark_id=None, past_end=False):
    return {"id": mark_id, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "past_end": past_end}


def test_drawn_changes_find_new_moved_and_erased_lines():
    rendered = {
        "keep": pts("2026-01-05", 10, "2026-01-09", 11),
        "move": pts("2026-01-05", 12, "2026-01-09", 13),
        "gone": pts("2026-01-06", 9, "2026-01-08", 9.5),
    }
    shapes = [
        pts("2026-01-05", 10.00001, "2026-01-09", 11, "keep"),  # float noise: not a move
        pts("2026-01-06", 12, "2026-01-09", 13, "move"),
        pts("2026-01-05", 8, "2026-01-07", 8.5),  # new
        pts("2026-01-07", 8, "2026-01-07", 9),  # both ends on one day: no slope, ignored
    ]
    new, erased, moved = chart_marks.drawn_changes(rendered, shapes)
    assert [s["x1"] for s in new] == ["2026-01-07"]
    assert erased == ["gone"] and list(moved) == ["move"]


def test_apply_drawn_saves_once_per_change_and_keeps_name_and_extension(tmp_path):
    kept = chart_marks.add_line(tmp_path, A, "2026-01-05", 10, "2026-01-09", 11, "base", True)
    gone = chart_marks.add_line(tmp_path, A, "2026-01-06", 9, "2026-01-08", 9.5)
    saved = chart_marks.current(tmp_path, A)
    report = {
        "ticker": A.lower(),
        "rendered": {
            kept: pts("2026-01-05", 10, "2026-01-12", 12.75),  # drawn extended to today
            gone: pts("2026-01-06", 9, "2026-01-08", 9.5),
        },
        "shapes": [
            pts("2026-01-05", 10.5, "2026-01-12", 13, kept),  # moved
            pts("2026-01-06", 8, "2026-01-12", 9, past_end=True),  # drawn into the future
        ],
    }
    other = dict(report, ticker="OTHER")
    assert chart_marks.apply_drawn(tmp_path, A, other, saved) == {
        "added": 0,
        "removed": 0,
        "moved": 0,
    }
    done = chart_marks.apply_drawn(tmp_path, A, report, saved)
    assert done == {"added": 1, "removed": 1, "moved": 1}
    now = chart_marks.current(tmp_path, A).sort_values("y0")
    assert len(now) == 2 and kept not in set(now["mark_id"]) and gone not in set(now["mark_id"])
    drawn, moved = now.iloc[0], now.iloc[1]
    assert bool(drawn["extend"]) and drawn["label"] == ""
    assert moved["label"] == "base" and bool(moved["extend"]) and moved["y0"] == 10.5


def test_a_level_is_a_flat_line_that_persists_and_draws(tmp_path):
    import pandas as pd
    import pytest

    from trading_os import interactive_chart as ichart

    days = [d.date() for d in pd.bdate_range("2026-01-05", periods=30)]
    chart_marks.add_level(tmp_path, A, 12.5, days[5], days[20])
    chart_marks.add_line(tmp_path, A, days[5], 10, days[20], 11)
    marks = chart_marks.current(tmp_path, A)
    flat = [chart_marks.is_level(m) for m in marks.to_dict("records")]
    assert sorted(flat) == [False, True]
    level = marks[[chart_marks.is_level(m) for m in marks.to_dict("records")]].iloc[0]
    assert chart_marks.describe(level) == "Level 12.50"
    assert level["extend"]  # extended to the last bar
    labels = [d.isoformat() for d in days]
    shapes = ichart.line_shapes(days, labels, [level.to_dict()])
    assert len(shapes) == 1 and shapes[0]["y0"] == shapes[0]["y1"] == 12.5
    assert shapes[0]["x1"] == labels[-1]  # reaches the newest bar
    chart_marks.remove(tmp_path, level["mark_id"])  # and goes away like any line
    assert len(chart_marks.current(tmp_path, A)) == 1
    with pytest.raises(ValueError):
        chart_marks.add_level(tmp_path, A, 0, days[0], days[1])
    with pytest.raises(ValueError):
        chart_marks.add_level(tmp_path, A, 5, days[0], days[0])
