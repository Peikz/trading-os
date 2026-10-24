import datetime as dt

import pytest

from trading_os.clock import (
    in_window,
    previous_session,
    session_date,
    sessions_after,
    sessions_back,
)
from trading_os.config import load_config

UTC = dt.UTC


@pytest.fixture(scope="module")
def schedule():
    return load_config().schedule


def utc(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


# The eod workflow fires at 20:17, 21:17 and 23:47 UTC. The window runs 16:15-23:59 ET, so a
# cron GitHub starts hours late still counts; later ones exit on "already done".
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 19, 20, 17), True),  # Mon, EDT: 16:17 ET
        (utc(2026, 10, 19, 21, 17), True),  # Mon, EDT: 17:17 ET
        (utc(2026, 10, 19, 20, 10), False),  # 16:10 ET, too early
        (utc(2026, 10, 20, 2, 30), True),  # Mon 22:30 EDT: hours late, still the session
        (utc(2026, 10, 20, 4, 30), False),  # Tue 00:30 EDT: past midnight, too late
        (utc(2026, 10, 26, 20, 17), True),  # after EU DST change (25 Oct), US still EDT
        (utc(2026, 11, 2, 20, 17), False),  # after US DST change (1 Nov): 15:17 EST
        (utc(2026, 11, 2, 21, 17), True),  # 16:17 EST
        (utc(2026, 11, 26, 21, 17), False),  # Thanksgiving
        (utc(2026, 11, 27, 21, 17), True),  # early close day: session still counts
        (utc(2026, 10, 18, 20, 17), False),  # Sunday
    ],
)
def test_eod_window(schedule, now, expected):
    assert in_window(schedule, "eod", now) is expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 19, 11, 30), True),  # 07:30 EDT
        (utc(2026, 11, 2, 11, 30), False),  # 06:30 EST
        (utc(2026, 11, 2, 12, 30), True),  # 07:30 EST
    ],
)
def test_pm_window(schedule, now, expected):
    assert in_window(schedule, "pm", now) is expected


def test_eod_session_on_trading_day(schedule):
    assert session_date(schedule, "eod", utc(2026, 10, 19, 20, 17)) == dt.date(2026, 10, 19)


def test_eod_session_on_sunday_is_friday(schedule):
    assert session_date(schedule, "eod", utc(2026, 10, 18, 20, 40)) == dt.date(2026, 10, 16)


def test_eod_session_before_close_is_previous_day(schedule):
    # 15:00 ET Monday: Monday has not closed yet.
    assert session_date(schedule, "eod", utc(2026, 10, 19, 19, 0)) == dt.date(2026, 10, 16)


def test_eod_session_after_thanksgiving(schedule):
    assert session_date(schedule, "eod", utc(2026, 11, 26, 21, 17)) == dt.date(2026, 11, 25)


def test_pm_session_is_today(schedule):
    assert session_date(schedule, "pm", utc(2026, 10, 19, 11, 30)) == dt.date(2026, 10, 19)


def test_naive_datetime_rejected(schedule):
    with pytest.raises(ValueError):
        in_window(schedule, "eod", dt.datetime(2026, 10, 19, 20, 17))


def test_weekly_runs_on_sunday_and_reports_friday(schedule):
    sunday_evening_cet = utc(2026, 10, 18, 16, 0)
    assert in_window(schedule, "weekly", sunday_evening_cet)
    assert not in_window(schedule, "weekly", utc(2026, 10, 19, 16, 0))  # Monday
    assert session_date(schedule, "weekly", sunday_evening_cet) == dt.date(2026, 10, 16)


def test_sessions_back_skips_holidays(schedule):
    # Five sessions ending the Friday after Thanksgiving (26 Nov is a holiday).
    assert sessions_back(schedule, dt.date(2026, 11, 27), 5) == [
        dt.date(2026, 11, 20),
        dt.date(2026, 11, 23),
        dt.date(2026, 11, 24),
        dt.date(2026, 11, 25),
        dt.date(2026, 11, 27),
    ]
    # A Sunday rolls back to Friday.
    assert sessions_back(schedule, dt.date(2026, 10, 18), 1) == [dt.date(2026, 10, 16)]


def test_sessions_after(schedule):
    after = sessions_after(schedule, dt.date(2026, 11, 24), 3, until=dt.date(2026, 12, 31))
    assert after == [dt.date(2026, 11, 25), dt.date(2026, 11, 27), dt.date(2026, 11, 30)]
    assert sessions_after(schedule, dt.date(2026, 11, 24), 3, until=dt.date(2026, 11, 25)) == [
        dt.date(2026, 11, 25)
    ]


# The intraday workflow fires at 14:17 / 15:17 UTC (10:15 check) and 16:03 / 17:03 UTC (12:00
# check). Each cron lands in at most one window; summer's second crons find the check done.
@pytest.mark.parametrize(
    ("now", "am", "mid"),
    [
        (utc(2026, 10, 19, 14, 17), True, False),  # Mon, EDT: 10:17 ET
        (utc(2026, 10, 19, 15, 17), True, False),  # 11:17 ET, retry of the 10:15 check
        (utc(2026, 10, 19, 16, 3), False, True),  # 12:03 ET
        (utc(2026, 10, 19, 17, 3), False, True),  # 13:03 ET, retry of the 12:00 check
        (utc(2026, 11, 2, 14, 17), False, False),  # after US DST change: 09:17 EST
        (utc(2026, 11, 2, 15, 17), True, False),  # 10:17 EST
        (utc(2026, 11, 2, 16, 3), True, False),  # 11:03 EST: the 10:15 check, done by then
        (utc(2026, 11, 2, 17, 3), False, True),  # 12:03 EST
        (utc(2026, 11, 26, 15, 17), False, False),  # Thanksgiving
        (utc(2026, 10, 18, 14, 17), False, False),  # Sunday
    ],
)
def test_intraday_windows(schedule, now, am, mid):
    assert in_window(schedule, "am", now) is am
    assert in_window(schedule, "mid", now) is mid


def test_intraday_session_is_today_once_open(schedule):
    assert session_date(schedule, "am", utc(2026, 10, 19, 14, 17)) == dt.date(2026, 10, 19)
    assert session_date(schedule, "mid", utc(2026, 10, 19, 16, 3)) == dt.date(2026, 10, 19)
    # Before the open (a forced run) it is the previous session.
    assert session_date(schedule, "am", utc(2026, 10, 19, 11, 0)) == dt.date(2026, 10, 16)


def test_previous_session_takes_any_day(schedule):
    """A Saturday (the dashboard on a weekend) gives Friday; a session gives the one before."""
    assert previous_session(schedule, dt.date(2026, 10, 24)) == dt.date(2026, 10, 23)
    assert previous_session(schedule, dt.date(2026, 10, 26)) == dt.date(2026, 10, 23)
    assert previous_session(schedule, dt.date(2026, 11, 26)) == dt.date(
        2026, 11, 25
    )  # Thanksgiving
