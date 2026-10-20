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
