"""The React dashboard's redesign (Nov 2026): the plan card's decision line, the "Why" card,
the market's one word, the status dot and the order on one line. Synthetic rows only."""

import datetime as dt

import pandas as pd

from trading_os import board_data, health, ticket
from trading_os.config import load_config

CFG = load_config()
T = "".join(["W", "Z", "Q", "W"])  # synthetic


def row(**extra):
    return {"ticker": T, "scan": "ep_am", "grade": "A+", "grade_entry_rule": "t_1030",
            "run_session": dt.date(2026, 11, 3), "run_slot": "am", **extra}  # fmt: skip


def test_decision_reads_the_buy_time_in_new_york_and_copenhagen():
    d = board_data.decision(row(), CFG)
    assert d["text"] == "Buy at 10:30 New York"
    assert d["local"] == "16:30 in Copenhagen"
    assert d["session"] == "2026-11-03" and d["day"] == "Tue 03 Nov"


def test_decision_uses_the_real_offset_when_only_europe_has_moved_its_clocks():
    # 27 Oct 2026: Copenhagen on winter time (25 Oct), New York still on summer time (1 Nov)
    d = board_data.decision(row(run_session=dt.date(2026, 10, 27)), CFG)
    assert d["local"] == "15:30 in Copenhagen"


def test_decision_for_an_eod_find_is_the_next_session():
    d = board_data.decision(
        row(run_slot="eod", run_session=dt.date(2026, 11, 6), grade_entry_rule="next_open"), CFG
    )
    assert d["text"] == "Buy at the open, 09:30 New York" and d["session"] == "2026-11-09"


def test_decision_without_a_grade_or_for_a_pivot_setup():
    assert board_data.decision(row(grade="C"), CFG) is None
    d = board_data.decision(row(scan="breakout_watch", grade_entry_rule=None, pivot=12.5), CFG)
    assert d["text"] == "Buy-stop at the pivot 12.50" and d["local"] is None
    surf = board_data.decision(row(scan="ma_surf", grade_entry_rule=None), CFG)
    assert surf["text"] == "Buy-stop at the pivot from 10:00 New York"
    carried = board_data.decision(row(carried_from="ah"), CFG)
    assert carried["text"] == "Found after hours last night"


def test_why_turns_the_grade_into_plain_sentences():
    w = board_data.why(
        row(
            grade_why="4 quality points",
            grade_points="✅ earnings · ✅ EPS up y/y · ❌ market not hot",
            grade_hold_sessions=21.0,
            grade_stat_days_median=12.0,
            grade_stat_trades=812.0,
            grade_stat_mean_r=0.41,
            grade_stat_win_pct=52.0,
            heat_tag="🌡 warm: held",
        )
    )
    assert w["summary"] == "4 quality points"
    assert w["points"] == [
        {"ok": True, "text": "Earnings"},
        {"ok": True, "text": "EPS up y/y"},
        {"ok": False, "text": "Market not hot"},
    ]
    assert w["lines"] == [
        "Out at the close after 21 sessions (median 12).",
        "812 past trades in 2016-26: 52% won, average +0.41R.",
        "Warm: held",
    ]
    assert board_data.why({"ticker": T}) == {"summary": None, "points": [], "lines": []}


HEAT = {"bands": [[20, "cold"], [45, "cool"], [80, "warm"], [None, "hot"]],
        "band_labels": {"warm": "45-80"}}  # fmt: skip


def test_market_mood_is_one_word_with_its_three_reasons():
    calm = {"qqq_light": "GREEN", "scan_count": 90.0, "spy_close": 500.0, "spy_chg_pct": 0.5}
    up = {"state": "uptrend", "dist_count": 1}
    mood = board_data.market_mood(calm, up, HEAT)
    assert mood["level"] == "green" and mood["word"] == "Healthy market"
    assert [r["level"] for r in mood["reasons"]] == ["green", "green", "green"]
    assert mood["quotes"] == [{"label": "SPY", "value": "500.00", "delta": "+0.5%"}]

    mixed = board_data.market_mood({**calm, "qqq_light": "YELLOW", "scan_count": 70}, up, HEAT)
    assert mixed["level"] == "amber" and mixed["word"] == "Cautious market"
    assert mixed["reasons"][1]["text"].startswith("Heat is warm: 70 stocks")
    assert mixed["reasons"][1]["text"].endswith("(this band: 45-80).")

    down = {"state": "correction", "dist_count": 7}
    weak = board_data.market_mood({**calm, "qqq_light": "RED"}, down, HEAT)
    assert weak["level"] == "red" and weak["reasons"][2]["text"] == "IBD: correction (7 sell days)."
    assert board_data.market_mood(None, None, None)["level"] is None


def test_next_scan_names_the_slot_in_both_clocks():
    now = dt.datetime(2026, 11, 3, 13, 0, tzinfo=dt.UTC)  # 08:00 New York
    n = board_data.next_scan(CFG, now)
    assert n["name"] == "10:15 check"
    assert n["when"] == "Tue 03 Nov, 10:10 New York (16:10 in Copenhagen)"


def test_status_dot(tmp_path):
    now = dt.datetime(2026, 11, 3, 23, 0, tzinfo=dt.UTC)  # Tue 18:00 New York
    assert health.status(tmp_path, CFG.schedule, now)["level"] == "warn"  # no runs at all
    year = tmp_path / "data" / "candidates" / "2026"
    year.mkdir(parents=True)
    for day in ("2026-11-02", "2026-11-03"):
        for slot in ("pm", "am", "mid", "eod", "ah"):
            pd.DataFrame({"ticker": [T]}).to_parquet(year / f"{day}_{slot}.parquet")
    assert health.status(tmp_path, CFG.schedule, now) == {
        "level": "ok", "text": "Every scheduled run saved", "details": []
    }  # fmt: skip
    (year / "2026-11-03_mid.parquet").unlink()
    gap = health.status(tmp_path, CFG.schedule, now)
    assert gap["level"] == "warn" and gap["text"] == "1 run missing"
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-11-03T101500Z_eod.log").write_text("Traceback\nValueError: x\n")
    bad = health.status(tmp_path, CFG.schedule, now)
    assert bad["level"] == "error" and bad["text"] == "1 job failed"


def test_ticket_summary_is_the_order_on_one_line():
    r = {"ticker": T, "plan_entry": 20.0, "plan_stop": 18.0, "pivot": 21.0}
    market = ticket.build(r, "market", 500, 100_000, 25)
    assert market.summary() == "Buy 250 · Market · Day · stop loss 18.00 GTC"
    stop = ticket.build(r, "stop_limit", 500, 100_000, 25)
    assert stop.summary() == "Buy 161 · Stop limit 21.00, limit 21.10 · Day · stop loss 18.00 GTC"
