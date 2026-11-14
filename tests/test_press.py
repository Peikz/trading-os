"""Pressing: the last 20 closed A+/A by exit order, on only above +1R, x2 on A+/A hits only."""

import datetime as dt

import pandas as pd

from trading_os import press
from trading_os.config import load_config

CONF = {**load_config().grading["press"], "enabled": True}  # the rule itself; live it is off
DAYS = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(200)]


def results(rs: list[float], grade: str = "A+", status: str = "closed") -> pd.DataFrame:
    """One closed trade a day, held 2 sessions, bought at the signal's own session."""
    return pd.DataFrame({
        "session_date": DAYS[: len(rs)], "grade": grade, "status": status,
        "entry_rule": "t_1015", "sessions": 2, "r_net": rs,
    })  # fmt: skip


def test_on_only_with_a_full_window_above_the_threshold():
    asof = DAYS[-1]
    assert not press.state(results([3.0] * 19), DAYS, CONF, asof)["active"]  # 19 closed
    on = press.state(results([3.0] * 19 + [-1.0]), DAYS, CONF, asof)
    assert on["active"] and on["mult"] == 2.0 and on["mean_r"] == round((57 - 1) / 20, 3)
    off = press.state(results([1.0] * 20), DAYS, CONF, asof)  # exactly +1R: not above
    assert not off["active"] and off["mult"] == 1.0


def test_only_the_last_20_closed_count_and_open_or_b_trades_dont():
    rs = [-1.0] * 10 + [2.0] * 20  # the 10 old losers fall out of the window
    assert press.state(results(rs), DAYS, CONF, DAYS[-1])["active"]
    mixed = pd.concat([results([2.0] * 20), results([-1.0] * 30, grade="B"),
                       results([-1.0] * 30, status="open")])  # fmt: skip
    st = press.state(mixed, DAYS, CONF, DAYS[-1])
    assert st["active"] and st["closed"] == 20


def test_apply_doubles_a_plus_and_a_only():
    hits = pd.DataFrame({"grade": ["A+", "A", "B", "C"], "grade_risk_mult": [2.0, 1.5, 1.0, 0.0]})
    on = {"active": True, "mult": 2.0}
    out = press.apply(hits, on, CONF)
    assert out["grade_risk_mult"].tolist() == [4.0, 3.0, 1.0, 0.0]
    assert out["press_mult"].tolist() == [2.0, 2.0, 1.0, 1.0]
    same = press.apply(hits, {"active": False, "mult": 1.0}, CONF)
    assert same["grade_risk_mult"].tolist() == [2.0, 1.5, 1.0, 0.0]
    assert press.apply(hits, None, CONF)["grade_risk_mult"].tolist() == [2.0, 1.5, 1.0, 0.0]
    off = press.apply(
        hits, on, {**CONF, "enabled": False}
    )  # switched off: a saved state is ignored
    assert off["grade_risk_mult"].tolist() == [2.0, 1.5, 1.0, 0.0]


def test_a_saved_state_is_used_only_for_later_sessions(tmp_path):
    st = press.state(results([3.0] * 20), DAYS, CONF, dt.date(2026, 11, 5))
    press.save(tmp_path, st)
    assert press.load(tmp_path, dt.date(2026, 11, 6))["active"]
    assert press.load(tmp_path, dt.date(2026, 11, 5))["active"]  # the same close: after hours
    assert press.load(tmp_path, dt.date(2026, 11, 4)) is None
    assert press.line(st)[0].startswith("🔥 Pressing")
    assert press.line({"active": False}) == []
