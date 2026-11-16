"""The practice range: picking, appending answers, the numbers, the hidden entry bar.
Synthetic data only."""

import random

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
        ("b2", "exam", -1.0),
    ]
    return pd.DataFrame(rows, columns=["signal_id", "pool", "net_r"])


def answer(data_dir, signals, sid, pool, choice):
    practice.save_answer(data_dir, signals, sid, pool, choice)


def test_no_repeats_within_a_pool_and_pool_runs_out(tmp_path):
    signals, rng, seen = make_signals(), random.Random(1), []
    while sid := practice.next_signal(signals, practice.load_answers(tmp_path), "practice", rng):
        seen.append(sid)
        answer(tmp_path, signals, sid, "practice", "2")
    assert sorted(seen) == ["a1", "a2", "a3", "a4"]
    assert practice.next_signal(signals, practice.load_answers(tmp_path), "practice", rng) is None
    # the exam is untouched by practice answers
    assert practice.next_signal(signals, practice.load_answers(tmp_path), "exam", rng) in {
        "b1",
        "b2",
    }


def test_answers_are_appended_not_overwritten(tmp_path):
    signals = make_signals()
    answer(tmp_path, signals, "a1", "practice", "1")
    first = sorted(practice.answers_folder(tmp_path).glob("*.parquet"))
    before = first[0].read_bytes()
    answer(tmp_path, signals, "a2", "practice", "skip")
    files = sorted(practice.answers_folder(tmp_path).glob("*.parquet"))
    assert len(files) == 2
    assert files[0].read_bytes() == before
    got = practice.load_answers(tmp_path)
    assert got["signal_id"].tolist() == ["a1", "a2"]
    assert got["choice"].tolist() == ["1", "skip"]
    assert str(got["answered_at"].dt.tz) == "UTC"


def test_answer_guards(tmp_path):
    signals = make_signals()
    answer(tmp_path, signals, "a1", "practice", "3")
    with pytest.raises(practice.AlreadyAnswered):
        answer(tmp_path, signals, "a1", "practice", "1")
    with pytest.raises(ValueError):
        answer(tmp_path, signals, "a2", "practice", "4")
    with pytest.raises(ValueError):
        answer(tmp_path, signals, "b1", "practice", "1")  # an exam signal in the practice pool
    with pytest.raises(ValueError):
        answer(tmp_path, signals, "zz", "practice", "1")
    assert len(practice.load_answers(tmp_path)) == 1


def test_stats_math(tmp_path):
    signals = make_signals()
    for sid, choice in [("a1", "3"), ("a2", "skip"), ("a3", "1"), ("a4", "3")]:
        answer(tmp_path, signals, sid, "practice", choice)
    s = practice.stats(signals, practice.load_answers(tmp_path), "practice")
    assert s["answered"] == 4 and s["remaining"] == 0 and s["pool_size"] == 4
    assert s["by_choice"]["3"] == {"count": 2, "mean_r": 2.0}  # (6 - 2) / 2
    assert s["by_choice"]["skip"] == {"count": 1, "mean_r": -1.0}
    assert s["by_choice"]["1"] == {"count": 1, "mean_r": 2.0}
    assert s["by_choice"]["2"] == {"count": 0, "mean_r": None}
    # picks: 1.5 * 6 + 0 * -1 + 0.5 * 2 + 1.5 * -2 = 7; every signal: 6 - 1 + 2 - 2 = 5
    assert s["picks_r"] == pytest.approx(7.0)
    assert s["equal_r"] == pytest.approx(5.0)
    assert s["picks_r_per_signal"] == pytest.approx(1.75)
    assert s["equal_r_per_signal"] == pytest.approx(1.25)
    assert s["big"] == {"total": 1, "taken": 1, "skipped": 0}
    assert s["losers"] == {"total": 2, "taken": 1, "skipped": 1}


def test_big_winner_skipped_is_counted(tmp_path):
    signals = make_signals()
    answer(tmp_path, signals, "a1", "practice", "skip")
    s = practice.stats(signals, practice.load_answers(tmp_path), "practice")
    assert s["big"] == {"total": 1, "taken": 0, "skipped": 1}
    assert s["picks_r"] == 0.0 and s["equal_r"] == 6.0


def test_empty_stats(tmp_path):
    s = practice.stats(make_signals(), practice.load_answers(tmp_path), "exam")
    assert s["answered"] == 0 and s["picks_r_per_signal"] is None
    assert s["remaining"] == 2


def test_exam_and_practice_are_separate(tmp_path):
    signals = make_signals()
    answer(tmp_path, signals, "a1", "practice", "2")
    answer(tmp_path, signals, "b1", "exam", "3")
    answer(tmp_path, signals, "b2", "exam", "skip")
    ex = practice.stats(signals, practice.load_answers(tmp_path), "exam")
    pr = practice.stats(signals, practice.load_answers(tmp_path), "practice")
    assert ex["answered"] == 2 and pr["answered"] == 1
    assert ex["picks_r"] == pytest.approx(15.0) and ex["equal_r"] == pytest.approx(9.0)
    assert pr["picks_r"] == pytest.approx(6.0)
    assert ex["by_choice"]["2"]["count"] == 0  # the practice answer is not in the exam


def test_hidden_bars_are_filtered_until_the_answer():
    bars = pd.DataFrame({"rel_day": [3, -2, 0, -1, 1], "close": [1.0, 2, 3, 4, 5]})
    before = practice.visible_bars(bars, answered=False)
    assert before["rel_day"].tolist() == [-2, -1]
    after = practice.visible_bars(bars, answered=True)
    assert after["rel_day"].tolist() == [-2, -1, 0, 1, 3]


def test_load_bars_reads_one_signal(tmp_path):
    folder = practice.folder(tmp_path)
    folder.mkdir(parents=True)
    pd.DataFrame(
        {"signal_id": ["x", "x", "y"], "rel_day": [0, -1, -1], "close": [1.0, 2.0, 3.0]}
    ).to_parquet(folder / "bars.parquet")
    got = practice.load_bars(tmp_path, "x")
    assert got["rel_day"].tolist() == [-1, 0] and got["close"].tolist() == [2.0, 1.0]
    assert not practice.available(tmp_path)  # signals.parquet is missing


def test_card_facts_handle_missing_numbers():
    row = pd.Series(
        {
            "setup_name": "EP",
            "grade": "A+",
            "gap_pct": float("nan"),
            "rvol_prev_day": 2.5,
            "dollar_vol_20d": 12_500_000.0,
            "price_band": "20-50",
            "adr_pct": 4.0,
            "dist_52w_high_pct": -10.0,
            "stop_pct": 5.0,
            "grade_rule": "a_b & c",
        }
    )
    facts = dict(practice.card_facts(row))
    assert facts["Gap at entry"] == "n/a" and facts["Volume, day before / 50-day avg"] == "2.5x"
    assert facts["Dollar volume, 20-day avg"] == "12.5 M$" and facts["Grade rule"] == "a b & c"
