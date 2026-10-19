"""New York time guard and NYSE calendar (SPEC §3).

Jobs are scheduled with two UTC crons (one per DST state). The guard decides whether this run is
inside the slot's New York window on a trading day, so EU/US DST mismatches and holidays never
produce a run.
"""

from __future__ import annotations

import datetime as dt
from functools import cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from trading_os.config import Schedule

_LOOKAROUND = dt.timedelta(days=14)


@cache
def _calendar(name: str) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(name)


def ny_time(schedule: Schedule, now: dt.datetime) -> dt.datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(schedule.timezone))


def is_session(schedule: Schedule, day: dt.date) -> bool:
    return bool(_calendar(schedule.calendar).is_session(pd.Timestamp(day)))


def previous_session(schedule: Schedule, session: dt.date) -> dt.date:
    return _calendar(schedule.calendar).previous_session(pd.Timestamp(session)).date()


def in_window(schedule: Schedule, slot: str, now: dt.datetime) -> bool:
    """True when `now` is inside the slot's New York window on a trading day.

    The weekly slot has no time window: it runs on its weekday (New York date).
    """
    local = ny_time(schedule, now)
    if slot == "weekly":
        return local.weekday() == schedule.weekly_weekday
    start, end = schedule.windows_et[slot]
    return is_session(schedule, local.date()) and start <= local.time() <= end


def session_date(schedule: Schedule, slot: str, now: dt.datetime) -> dt.date:
    """The trading session a run at `now` belongs to.

    eod, weekly: the latest session whose close is at or before `now` (Sunday reports Friday).
    pm: the next session whose open is after `now` (a pre-market run reports today's session).
    """
    cal = _calendar(schedule.calendar)
    now_utc = pd.Timestamp(now).tz_convert("UTC")
    day = ny_time(schedule, now).date()
    if slot in ("eod", "weekly"):
        sessions = cal.sessions_in_range(day - _LOOKAROUND, day)
        for session in reversed(sessions):
            if cal.session_close(session) <= now_utc:
                return session.date()
    elif slot == "pm":
        sessions = cal.sessions_in_range(day, day + _LOOKAROUND)
        for session in sessions:
            if cal.session_open(session) > now_utc:
                return session.date()
    else:
        raise ValueError(f"no session rule for slot {slot!r}")
    raise LookupError(f"no {slot} session near {day}")
