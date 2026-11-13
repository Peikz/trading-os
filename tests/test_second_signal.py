"""Second signal: a hit on a stock whose first plan is still open gets a tag and half the risk."""

import datetime as dt

import pandas as pd

from trading_os import board_data, clock, notify, second_signal, store
from trading_os.config import load_config

CFG = load_config()
CONF = CFG.grading["second_signal"]
DAY = dt.date(2026, 11, 12)  # a Thursday
LABELS = {"ep_ah": "EP-AH", "ep9m": "EP9M"}


def hits(tickers, grades) -> pd.DataFrame:
    return pd.DataFrame({"ticker": tickers, "grade": grades, "grade_risk_mult": 1.0})


def test_open_plans_keep_the_newest_open_a_grade_plan_per_stock():
    res = pd.DataFrame({
        "ticker": ["AAA", "AAA", "BBB", "CCC", "DDD"],
        "session_date": [dt.date(2026, 11, 3), dt.date(2026, 11, 10), DAY, DAY, DAY],
        "scan": ["ep9m", "ma_surf", "ep_am", "ep_am", "luk_flush"],
        "grade": ["A+", "A", "A+", "B", "A"],
        "status": ["open", "open", "closed", "open", "waiting"],
    })  # fmt: skip
    plans = second_signal.open_plans(res, set(CONF["grades"]))
    assert plans == {"AAA": {"since": "2026-11-10", "scan": "ma_surf"}}  # B, closed, waiting: no
    assert second_signal.open_plans(pd.DataFrame(columns=["status", "grade"]), {"A"}) == {}


def test_apply_tags_and_halves_only_graded_hits_with_an_open_first_plan():
    firsts = {"AAA": [{"since": "2026-11-10", "scan": "ep9m"}],
              "CCC": [{"since": "2026-11-10", "scan": "ep9m"}]}  # fmt: skip
    out = second_signal.apply(
        hits(["AAA", "BBB", "CCC"], ["A+", "A+", "C"]), "ep_am", firsts, CONF, DAY, LABELS
    )
    assert out["grade_risk_mult"].tolist() == [0.5, 1.0, 1.0]
    assert out["second_mult"].tolist() == [0.5, 1.0, 1.0]
    assert out["second_tag"].iloc[0] == "➕ Second signal: EP9M from 10 Nov still open · half size"
    assert out["second_tag"].iloc[1:].isna().all()  # no first plan; a C is not bought at all


def test_the_same_scan_earlier_the_same_session_is_a_repeat_not_a_second_signal():
    plain = hits(["AAA"], ["A+"])
    again = {"AAA": [{"since": DAY.isoformat(), "scan": "ep9m"}]}
    assert "second_tag" not in second_signal.apply(plain, "ep9m", again, CONF, DAY)
    other_scan = second_signal.apply(plain, "ep_am", again, CONF, DAY, LABELS)
    assert other_scan["second_tag"].iloc[0].startswith("➕ Second signal: EP9M from 12 Nov")
    days_later = {"AAA": [{"since": "2026-11-05", "scan": "ep9m"}]}
    assert "second_tag" in second_signal.apply(plain, "ep9m", days_later, CONF, DAY)
    assert second_signal.apply(plain, "ep9m", {}, CONF, DAY) is plain


def _save_run(tmp_path, session, slot, rows):
    ctx = store.RunContext(
        session=session, slot=slot, run_ts=dt.datetime.now(dt.UTC), run_kind="scheduled"
    )
    path = store.run_paths(tmp_path, ctx)["candidates"]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path)


def test_held_reads_the_saved_plans_and_the_runs_after_that_close(tmp_path):
    evening = clock.previous_session(CFG.schedule, DAY)
    second_signal.save(tmp_path, evening, {"AAA": {"since": "2026-11-05", "scan": "ep9m"}})
    _save_run(tmp_path, evening, "ah", {
        "ticker": ["BBB", "CCC"], "scan": ["ep_ah", "ep_ah"], "grade": ["A+", "C"],
        "grade_entry_rule": ["ah_1645", "ah_1645"],
    })  # fmt: skip
    _save_run(tmp_path, DAY, "am", {
        "ticker": ["DDD"], "scan": ["ep9m"], "grade": ["A+"], "grade_entry_rule": ["t_1015"],
    })  # fmt: skip
    morning = second_signal.held(tmp_path, CFG, DAY, "am")
    assert set(morning) == {"AAA", "BBB"}  # the 10:15 run does not see itself; a C is no plan
    midday = second_signal.held(tmp_path, CFG, DAY, "mid")
    assert set(midday) == {"AAA", "BBB", "DDD"}
    assert midday["BBB"] == [{"since": evening.isoformat(), "scan": "ep_ah"}]
    # a state from a later close is not used; with none, the runs after the close still count
    second_signal.save(tmp_path, DAY + dt.timedelta(days=1), {"ZZZ": {"since": "x", "scan": "y"}})
    assert set(second_signal.held(tmp_path, CFG, DAY, "mid")) == {"BBB", "DDD"}


def test_update_saves_the_open_plans_for_the_next_runs(tmp_path):
    res = pd.DataFrame({
        "ticker": ["AAA"], "session_date": [DAY], "scan": ["ep9m"], "grade": ["A+"],
        "status": ["open"],
    })  # fmt: skip
    assert second_signal.update(tmp_path, DAY, res, set(CONF["grades"])) == 1
    saved = second_signal.load(tmp_path, DAY)["plans"]
    assert saved == {"AAA": {"since": str(DAY), "scan": "ep9m"}}
    assert second_signal.load(tmp_path, DAY - dt.timedelta(days=1)) is None


def test_the_tag_shows_in_the_push_block_and_on_the_card():
    text = second_signal.tag({"since": "2026-11-11", "scan": "ep_ah"}, 0.5, LABELS)
    row = {"ticker": "AAA", "close": 10.0, "gap_pct": 12.0, "rvol50": 4.0,
           "dollar_volume": 5e7, "second_tag": text}  # fmt: skip
    lines = [line.text for line in notify._block(row, "ep_am", "am")]
    assert any(text in line for line in lines)
    assert board_data.tags(row)[0] == text
    assert second_signal.tag({"since": "2026-11-11", "scan": "x"}, 0.75, {}).endswith("x0.75 size")
