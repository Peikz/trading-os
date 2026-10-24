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

from trading_os.config import INTRADAY_SLOTS, Schedule

_LOOKAROUND = dt.timedelta(days=14)


@cache
def _calendar(name: str) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(name)


NEW_YORK = ZoneInfo("America/New_York")
COPENHAGEN = ZoneInfo("Europe/Copenhagen")  # Emil's own clock (Emil, 21 Oct 2026)


def both_times(when: dt.datetime) -> str:
    """`07:17 NY · 13:17 CPH`: a moment in New York and Copenhagen time (naive = UTC)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return f"{when.astimezone(NEW_YORK):%H:%M} NY · {when.astimezone(COPENHAGEN):%H:%M} CPH"


def ny_time(schedule: Schedule, now: dt.datetime) -> dt.datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(schedule.timezone))


def is_session(schedule: Schedule, day: dt.date) -> bool:
    return bool(_calendar(schedule.calendar).is_session(pd.Timestamp(day)))


def previous_session(schedule: Schedule, session: dt.date) -> dt.date:
    """The last session before `session`, which need not be a session itself: a Saturday or a
    holiday gives the session before it (the dashboard and the alert watcher ask on weekends)."""
    cal = _calendar(schedule.calendar)
    day = pd.Timestamp(session)
    if cal.is_session(day):
        return cal.previous_session(day).date()
    return cal.date_to_session(day, direction="previous").date()


def sessions_back(schedule: Schedule, until: dt.date, count: int) -> list[dt.date]:
    """The `count` sessions ending at `until` (inclusive when it is a session), oldest first."""
    cal = _calendar(schedule.calendar)
    end = pd.Timestamp(until)
    if not cal.is_session(end):
        end = cal.date_to_session(end, direction="previous")
    first = max(cal.first_session, cal.session_offset(end, -(count - 1)))
    return [s.date() for s in cal.sessions_in_range(first, end)]


def sessions_after(
    schedule: Schedule, session: dt.date, count: int, until: dt.date
) -> list[dt.date]:
    """Up to `count` sessions strictly after `session`, not later than `until`."""
    cal = _calendar(schedule.calendar)
    start = cal.next_session(pd.Timestamp(session))
    if start > pd.Timestamp(until):
        return []
    return [s.date() for s in cal.sessions_in_range(start, pd.Timestamp(until))][:count]


def sessions_until(schedule: Schedule, session: dt.date, days: pd.Series) -> pd.Series:
    """Trading sessions from `session` to each date: 0 on the session itself, NaN for a date
    already past or unknown. Used for "earnings in N days"."""
    cal = _calendar(schedule.calendar)
    start = pd.Timestamp(session)
    lookup = {}
    for day in days.dropna().unique():
        end = pd.Timestamp(day)
        lookup[day] = (
            float("nan") if end < start else float(len(cal.sessions_in_range(start, end)) - 1)
        )
    return days.map(lookup).astype("float64")


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
    am, mid: the latest session whose open is at or before `now` (today, during the session).
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
    elif slot in INTRADAY_SLOTS:
        sessions = cal.sessions_in_range(day - _LOOKAROUND, day)
        for session in reversed(sessions):
            if cal.session_open(session) <= now_utc:
                return session.date()
    else:
        raise ValueError(f"no session rule for slot {slot!r}")
    raise LookupError(f"no {slot} session near {day}")
