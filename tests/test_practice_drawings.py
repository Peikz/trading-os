"""Lines drawn on practice charts: saved per signal, append-only, kept apart from the real
stocks' chart marks. Synthetic data only."""

import pytest

from trading_os import chart_marks
from trading_os import practice_drawings as drawings


def labels(first=-5, last=3):
    return {r: f"day {r:+d}" for r in range(first, last + 1)}


def report(shapes, rendered=None, ticker="s1"):
    return {"seq": "1", "ticker": ticker, "rendered": rendered or {}, "shapes": shapes}


def test_a_line_is_saved_for_its_signal_only(tmp_path):
    mark = drawings.add_line(tmp_path, "s1", -20, 95.0, -3, 102.0)
    assert drawings.current(tmp_path, "s2").empty
    got = drawings.current(tmp_path, "s1")
    assert got["mark_id"].tolist() == [mark]
    assert got.iloc[0][["x0", "y0", "x1", "y1"]].tolist() == [-20, 95.0, -3, 102.0]
    # never mixed with the real stocks' marks
    assert chart_marks.current(tmp_path, "S1").empty
    assert not chart_marks.folder(tmp_path).exists()


def test_remove_is_a_new_row_and_the_line_stays_on_disk(tmp_path):
    keep = drawings.add_line(tmp_path, "s1", -20, 95.0, -3, 102.0)
    gone = drawings.add_level(tmp_path, "s1", 101.5, -30, -1)
    before = sorted(drawings.folder(tmp_path).glob("*.parquet"))
    drawings.remove(tmp_path, gone, "s1")
    after = sorted(drawings.folder(tmp_path).glob("*.parquet"))
    assert len(after) == len(before) + 1 and set(before) <= set(after)  # nothing rewritten
    assert drawings.current(tmp_path, "s1")["mark_id"].tolist() == [keep]
    assert drawings.is_level(drawings.current(tmp_path, "s1").iloc[0]) is False


def test_guards(tmp_path):
    with pytest.raises(ValueError):
        drawings.add_line(tmp_path, "s1", -5, 100.0, -5, 101.0)  # both ends on one day
    with pytest.raises(ValueError):
        drawings.add_level(tmp_path, "s1", 0.0, -5, -1)


def test_shapes_follow_the_bars_on_screen_and_the_price_scale(tmp_path):
    drawings.add_line(tmp_path, "s1", -4, 100.0, -2, 102.0)  # one point per day
    marks = drawings.current(tmp_path, "s1").to_dict("records")
    blind = drawings.shapes(marks, labels(-5, -1), lambda v: v, last_rel=-1)
    assert len(blind) == 1
    shape = blind[0]
    assert shape["name"] == f"mark:{marks[0]['mark_id']}"
    assert (shape["x0"], shape["y0"]) == ("day -4", 100.0)
    assert (shape["x1"], shape["y1"]) == ("day -2", 102.0)
    dollars = drawings.shapes(marks, labels(-5, -1), lambda v: v * 0.5, last_rel=-1)
    assert dollars[0]["y0"] == pytest.approx(50.0) and dollars[0]["y1"] == pytest.approx(51.0)
    # a line whose first day is not on screen is left out
    assert drawings.shapes(marks, labels(-3, -1), lambda v: v, last_rel=-1) == []


def test_extended_line_runs_on_when_more_bars_are_shown(tmp_path):
    drawings.add_line(tmp_path, "s1", -4, 100.0, -2, 102.0, extend=True)
    marks = drawings.current(tmp_path, "s1").to_dict("records")
    before = drawings.shapes(marks, labels(-5, -1), lambda v: v, last_rel=-1)[0]
    after = drawings.shapes(marks, labels(-5, 3), lambda v: v, last_rel=3)[0]
    assert before["x1"] == "day -1" and before["y1"] == pytest.approx(103.0)
    assert after["x1"] == "day +3" and after["y1"] == pytest.approx(107.0)


def test_chart_report_saves_new_moved_and_erased_lines(tmp_path):
    names = labels(-5, 3)

    def to_norm(v):
        return v * 2.0  # chart dollars -> normalised

    new = {"id": None, "x0": "day -4", "y0": 50.0, "x1": "day -1", "y1": 51.5, "past_end": False}
    counts = drawings.apply_drawn(tmp_path, "s1", report([new]), names, to_norm)
    assert counts == {"added": 1, "removed": 0, "moved": 0}
    saved = drawings.current(tmp_path, "s1").iloc[0]
    assert (saved["x0"], saved["y0"], saved["x1"], saved["y1"]) == (-4, 100.0, -1, 103.0)
    mid = saved["mark_id"]
    # moved: one end dragged up
    start = {"x0": "day -4", "y0": 50.0, "x1": "day -1", "y1": 51.5}
    moved = dict(start, id=mid, y1=52.0, past_end=False)
    counts = drawings.apply_drawn(
        tmp_path, "s1", report([moved], {mid: dict(start, past_end=False)}), names, to_norm
    )
    assert counts == {"added": 0, "removed": 0, "moved": 1}
    now = drawings.current(tmp_path, "s1")
    assert len(now) == 1 and now.iloc[0]["y1"] == pytest.approx(104.0)
    # erased: the chart no longer reports it
    rid = now.iloc[0]["mark_id"]
    gone = {"x0": "day -4", "y0": 50.0, "x1": "day -1", "y1": 52.0}
    counts = drawings.apply_drawn(tmp_path, "s1", report([], {rid: gone}), names, to_norm)
    assert counts["removed"] == 1 and drawings.current(tmp_path, "s1").empty


def test_a_report_for_another_signal_is_ignored(tmp_path):
    new = {"id": None, "x0": "day -4", "y0": 50.0, "x1": "day -1", "y1": 51.5, "past_end": False}
    counts = drawings.apply_drawn(tmp_path, "s2", report([new]), labels(), lambda v: v)
    assert counts == {"added": 0, "removed": 0, "moved": 0}
    assert drawings.current(tmp_path, "s2").empty


def test_line_drawn_past_the_last_bar_is_extended(tmp_path):
    new = {"id": None, "x0": "day -4", "y0": 100.0, "x1": "day -1", "y1": 103.0, "past_end": True}
    drawings.apply_drawn(tmp_path, "s1", report([new]), labels(-5, -1), lambda v: v)
    assert bool(drawings.current(tmp_path, "s1").iloc[0]["extend"]) is True
