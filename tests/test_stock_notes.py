"""Notes per stock on the Chart page (synthetic data only)."""

import datetime as dt

from trading_os import dashboard, stock_notes

A = "".join(["C", "H", "Q"])


def test_notes_are_kept_per_stock_newest_day_first(tmp_path):
    stock_notes.add(tmp_path, A, "first", dt.date(2025, 3, 4))
    stock_notes.add(tmp_path, A.lower(), " second ", dt.date(2026, 1, 2))
    stock_notes.add(tmp_path, "OTHER", "elsewhere", dt.date(2026, 1, 2))
    notes = stock_notes.current(tmp_path, A)
    assert notes["text"].tolist() == ["second", "first"]
    assert notes["note_date"].tolist() == [dt.date(2026, 1, 2), dt.date(2025, 3, 4)]
    assert len(stock_notes.current(tmp_path)) == 3


def test_edit_and_delete_keep_the_old_text_in_the_log(tmp_path):
    note = stock_notes.add(tmp_path, A, "draft", dt.date(2025, 3, 4))
    stock_notes.edit(tmp_path, note, A, "final", dt.date(2025, 3, 5))
    [row] = stock_notes.current(tmp_path, A).to_dict("records")
    assert (row["text"], row["note_date"]) == ("final", dt.date(2025, 3, 5))
    assert row["created_ts"] < row["saved_ts"]
    stock_notes.remove(tmp_path, note)
    assert stock_notes.current(tmp_path, A).empty
    assert stock_notes.events(tmp_path)["text"].dropna().tolist() == ["draft", "final"]


def test_notes_are_in_a_folder_save_and_push_commits():
    assert str(stock_notes.folder(".")).startswith(dashboard.SAVED_BY_YOU[0])
