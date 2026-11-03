"""When the server's price-alert service watches (deploy/, Hetzner prep, Nov 2026).

The GitHub job is started twice a session by the cron-job.org timer (a job may run 6 hours at
most). On the server one long-running process watches every regular NYSE session from 09:25
New York (a few minutes to build the watch list before the 09:30 open) to the close, which is
16:00 or 13:00 on an early close, and sleeps otherwise: weekends, XNYS holidays, nights. All
times come from the exchange calendar (`trading_os.clock`), so summer and winter time and the
calendar's own holidays and early closes need no table here.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from trading_os import clock
from trading_os.config import Schedule

START = dt.time(9, 25)  # New York; the watcher itself checks prices from 09:30
LOOKAHEAD_DAYS = 15  # longer than any run of days without a session


def window(schedule: Schedule, day: dt.date) -> tuple[dt.datetime, dt.datetime] | None:
    """(start, end) of the watch on `day` in New York time, or None when it is no session."""
    if not clock.is_session(schedule, day):
        return None
    start = dt.datetime.combine(day, START, tzinfo=ZoneInfo(schedule.timezone))
    return start, clock.session_close(schedule, day)


def next_window(schedule: Schedule, now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """The watch going on at `now` (aware), or else the next one."""
    today = clock.ny_time(schedule, now).date()
    for offset in range(LOOKAHEAD_DAYS):
        found = window(schedule, today + dt.timedelta(days=offset))
        if found is not None and found[1] > now:
            return found
    raise LookupError(f"no session within {LOOKAHEAD_DAYS} days of {today}")


def watching(schedule: Schedule, now: dt.datetime) -> bool:
    start, end = next_window(schedule, now)
    return start <= now < end
