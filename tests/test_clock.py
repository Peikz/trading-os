import datetime as dt

import pytest

from trading_os.clock import in_window, session_date
from trading_os.config import load_config

UTC = dt.UTC


@pytest.fixture(scope="module")
def schedule():
    return load_config().schedule


def utc(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


# The eod workflow fires at 20:17 and 21:17 UTC. Exactly one of them lands in 16:15-17:30 ET
# in winter; in summer both do and the second one exits on "already done".
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 19, 20, 17), True),  # Mon, EDT: 16:17 ET
        (utc(2026, 10, 19, 21, 17), True),  # Mon, EDT: 17:17 ET
        (utc(2026, 10, 19, 20, 10), False),  # 16:10 ET, too early
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
