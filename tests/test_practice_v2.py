"""Practice v2: notes, the shown flag, real dates and prices, the blind-vs-shown split.
Synthetic data only."""

import pandas as pd
import pytest

from trading_os import practice


def make_signals() -> pd.DataFrame:
    rows = [
        ("a1", "practice", 6.0),
        ("a2", "practice", -1.0),
        ("a3", "practice", 2.0),
        ("a4", "practice", -2.0),
        ("b1", "exam", 10.0),
    ]
    return pd.DataFrame(rows, columns=["signal_id", "pool", "net_r"])


def dates(entry, rels):
    return [d.strftime("%Y-%m-%d") for d in practice.session_dates(entry, rels)]


def test_session_dates_skip_weekends_and_holidays():
    # Fri 24 May 2024; Mon 27 May is Memorial Day, so +1 is Tue 28 May
    assert dates("2024-05-24", [0, 1, 2]) == ["2024-05-24", "2024-05-28", "2024-05-29"]
    assert dates("2024-05-24", [-1, -2]) == ["2024-05-23", "2024-05-22"]
    # backwards over the weekend and the holiday
    assert dates("2024-05-28", [-1, 0]) == ["2024-05-24", "2024-05-28"]
    # five sessions after Fri 24 May
    assert dates("2024-05-24", [5]) == ["2024-06-03"]
    # a long window both ways stays strictly increasing, one session per step
    window = practice.session_dates("2024-05-24", range(-130, 64))
    assert len(window) == 194 and window[130] == pd.Timestamp("2024-05-24")
    assert all(a < b for a, b in zip(window, window[1:], strict=False))
    assert all(d.weekday() < 5 for d in window)


def test_session_dates_refuse_a_non_session():
    with pytest.raises(ValueError):
        practice.session_dates("2024-05-25", [0])  # a Saturday
    with pytest.raises(ValueError):
        practice.session_dates("2024-05-27", [0])  # a holiday


def test_prices_are_denormalised_and_round_trip():
    # the entry level of 100 is the entry price; a 7 % stop sits 7 % below it
    assert practice.real_price(100.0, 42.5) == pytest.approx(42.5)
    assert practice.real_price(93.0, 42.5) == pytest.approx(42.5 * 0.93)
    close = pd.Series([95.0, 100.0, 120.0])
    assert practice.real_price(close, 8.0).tolist() == pytest.approx([7.6, 8.0, 9.6])
    assert practice.normalised_price(practice.real_price(97.3, 12.34), 12.34) == pytest.approx(97.3)


def test_answer_saves_note_and_shown(tmp_path):
    signals = make_signals()
    practice.save_answer(tmp_path, signals, "a1", "practice", "2", note="clean base", shown=True)
    practice.save_answer(tmp_path, signals, "a2", "practice", "skip")
    got = practice.load_answers(tmp_path)
    assert got["note"].tolist() == ["clean base", ""]
    assert got["shown"].tolist() == [True, False]
    assert practice.current_notes(tmp_path) == {"a1": "clean base", "a2": ""}


def test_note_edit_after_the_answer_is_append_only(tmp_path):
    signals = make_signals()
    practice.save_answer(tmp_path, signals, "a1", "practice", "2", note="first")
    practice.save_note(tmp_path, "a1", "second")
    first = sorted(practice.notes_folder(tmp_path).glob("*.parquet"))
    before = first[0].read_bytes()
    practice.save_note(tmp_path, "a1", "third")
    files = sorted(practice.notes_folder(tmp_path).glob("*.parquet"))
    assert len(files) == 2 and files[0].read_bytes() == before
    assert practice.current_notes(tmp_path)["a1"] == "third"
    assert len(practice.load_answers(tmp_path)) == 1  # the answer itself is untouched
    with pytest.raises(ValueError):
        practice.save_note(tmp_path, "a2", "not answered yet")


def test_old_answer_files_load_with_empty_note_and_not_shown(tmp_path):
    out = practice.answers_folder(tmp_path)
    out.mkdir(parents=True)
    old = {"signal_id": "a1", "pool": "practice", "choice": "2"}
    old["answered_at"] = pd.Timestamp("2026-01-01", tz="UTC")
    pd.DataFrame([old]).to_parquet(out / "20260101T000000000000.parquet")
    signals = make_signals()
    practice.save_answer(tmp_path, signals, "a2", "practice", "1", note="n", shown=True)
    got = practice.load_answers(tmp_path)
    assert got["note"].tolist() == ["", "n"] and got["shown"].tolist() == [False, True]
    assert got["shown"].dtype == bool
    assert practice.stats(signals, got, "practice")["answered"] == 2
    assert practice.current_notes(tmp_path) == {"a1": "", "a2": "n"}


def test_stats_split_by_shown(tmp_path):
    signals = make_signals()
    answers = [("a1", "3", False), ("a2", "skip", False), ("a3", "1", True), ("a4", "3", True)]
    for sid, choice, shown in answers:
        practice.save_answer(tmp_path, signals, sid, "practice", choice, shown=shown)
    s = practice.stats(signals, practice.load_answers(tmp_path), "practice")
    blind, shown = s["by_shown"]["blind"], s["by_shown"]["shown"]
    assert blind["answered"] == 2 and shown["answered"] == 2
    assert blind["picks_r"] == pytest.approx(9.0)  # 1.5 * 6 + 0
    assert blind["equal_r"] == pytest.approx(5.0)  # 6 - 1
    assert shown["picks_r"] == pytest.approx(-2.0)  # 0.5 * 2 + 1.5 * -2
    assert shown["equal_r"] == pytest.approx(0.0)  # 2 - 2
    assert shown["picks_r_per_signal"] == pytest.approx(-1.0)
    assert s["picks_r"] == pytest.approx(7.0)  # the totals still cover both
    empty = practice.stats(signals, practice.load_answers(tmp_path), "exam")
    assert empty["by_shown"]["blind"]["picks_r_per_signal"] is None
