"""Daily notes with stock tags (synthetic data only)."""

import datetime as dt

from trading_os import daily_notes

A, B = "".join(["S", "R", "F"]), "".join(["K", "L", "M"])


def test_tags_come_from_the_field_and_cashtags():
    assert daily_notes.tags_from(f"Watching ${B.lower()} and ${A} today", f"{A}, nasdaq:{B}") == [
        A,
        B,
    ]
    assert daily_notes.tags_from("no tags here, $5 move") == []


def test_notes_by_day_and_by_tag_with_edits_kept(tmp_path):
    first = daily_notes.add(tmp_path, f"Gap held on ${A}", dt.date(2026, 10, 21))
    daily_notes.add(tmp_path, "Market weak, sat out", dt.date(2026, 10, 22))
    daily_notes.add(tmp_path, "Both set up", dt.date(2026, 10, 22), f"{A} {B}")
    assert len(daily_notes.current(tmp_path)) == 3
    on_a = daily_notes.current(tmp_path, A.lower())
    assert on_a["text"].tolist() == ["Both set up", f"Gap held on ${A}"]  # newest day first
    assert daily_notes.all_tags(tmp_path) == sorted([A, B])

    daily_notes.edit(tmp_path, first, "Gap held, sold half", dt.date(2026, 10, 21), B)
    assert daily_notes.current(tmp_path, A)["text"].tolist() == ["Both set up"]  # retagged
    daily_notes.remove(tmp_path, first)
    assert len(daily_notes.current(tmp_path)) == 2
    texts = daily_notes.events(tmp_path)["text"].dropna().tolist()
    assert f"Gap held on ${A}" in texts and "Gap held, sold half" in texts  # the log keeps both
