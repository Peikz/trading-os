"""The timer that starts the timed jobs on the minute (Emil, 20 Oct 2026). GitHub's own
scheduler started them 2½ to 6½ hours late on 19-20 Oct, so the pre-market and intraday
checks never ran inside their windows. A free cron-job.org account now calls GitHub's API to
start each workflow at its New York time (summer and winter time handled there); GitHub's
cron lines stay as a backup.

Extra starts are harmless: every job exits outside its New York window and skips a session it
already saved, and the data-repo jobs queue one behind the other. That is also why each
scan has a second start a little later, in case the first run failed.

`scripts/timer_setup.py` creates these jobs at cron-job.org; the System health page checks
that GitHub started each one on time (`check`).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd

REPO = "Peikz/trading-os"
TIMEZONE = "America/New_York"
PREFIX = "trading-os: "  # the titles of our jobs at cron-job.org
WEEKDAYS = (1, 2, 3, 4, 5)  # cron-job.org numbering: 0 = Sunday ... 6 = Saturday
TUE_SAT = (2, 3, 4, 5, 6)  # the mornings after a session
ON_TIME_MINUTES = 10
GRACE_MINUTES = 120  # jobs without a window: a start this late still counts


@dataclass(frozen=True)
class TimerJob:
    key: str  # the slot (pm, am, mid, eod) for the scans
    workflow: str  # file in .github/workflows
    name: str  # the workflow's name in GitHub's run list
    at: str  # "HH:MM", New York time
    days: tuple[int, ...]
    inputs: dict = field(default_factory=dict)
    retry: bool = False  # the second start, in case the first run failed

    @property
    def title(self) -> str:
        return f"{PREFIX}{self.key}{' retry' if self.retry else ''} {self.at} ET"


JOBS = (
    TimerJob("backfill", "backfill.yml", "Backfill", "05:30", TUE_SAT),
    TimerJob("bars-pack", "bars-pack.yml", "Bars pack", "06:15", TUE_SAT),
    TimerJob("pm", "premarket.yml", "Pre-market", "07:17", WEEKDAYS),
    TimerJob("pm", "premarket.yml", "Pre-market", "07:35", WEEKDAYS, retry=True),
    TimerJob("am", "intraday.yml", "Intraday", "10:17", WEEKDAYS, {"slot": "am"}),
    TimerJob("am", "intraday.yml", "Intraday", "10:40", WEEKDAYS, {"slot": "am"}, True),
    TimerJob("mid", "intraday.yml", "Intraday", "12:03", WEEKDAYS, {"slot": "mid"}),
    TimerJob("mid", "intraday.yml", "Intraday", "12:30", WEEKDAYS, {"slot": "mid"}, True),
    TimerJob("close", "intraday.yml", "Intraday", "15:43", WEEKDAYS, {"slot": "close"}),
    TimerJob("close", "intraday.yml", "Intraday", "15:50", WEEKDAYS, {"slot": "close"}, True),
    TimerJob("eod", "eod.yml", "EOD", "16:17", WEEKDAYS),
    TimerJob("eod", "eod.yml", "EOD", "17:00", WEEKDAYS, retry=True),
    TimerJob("outcomes", "outcomes.yml", "Outcomes", "18:00", WEEKDAYS),
    TimerJob("weekly", "weekly.yml", "Weekly", "12:00", (0,)),
)


def _hm(text: str) -> tuple[int, int]:
    hour, minute = text.split(":")
    return int(hour), int(minute)


def payload(job: TimerJob, token: str) -> dict:
    """The cron-job.org job (their REST API's DetailedJob) that starts `job` through GitHub's
    workflow_dispatch API with `token` (a fine-grained token: Actions read/write, this repo)."""
    hour, minute = _hm(job.at)
    return {
        "url": f"https://api.github.com/repos/{REPO}/actions/workflows/{job.workflow}/dispatches",
        "enabled": True,
        "title": job.title,
        "saveResponses": False,
        "requestMethod": 1,  # POST
        "schedule": {
            "timezone": TIMEZONE,
            "expiresAt": 0,
            "hours": [hour],
            "minutes": [minute],
            "mdays": [-1],
            "months": [-1],
            "wdays": list(job.days),
        },
        "extendedData": {
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"ref": "main", "inputs": {**job.inputs, "timer": "true"}}),
        },
        "notification": {"onFailure": True, "onFailureCount": 1, "onDisable": True},
    }


def plan(existing: list[dict]):
    """What to change at cron-job.org, given its job list (jobId, title): (jobs to create,
    (job id, job) pairs to update, job ids to delete). Ours are the titles starting with
    PREFIX; a job whose time changed is a new title, so the old one is deleted."""
    ours = {j["title"]: j["jobId"] for j in existing if str(j.get("title", "")).startswith(PREFIX)}
    wanted = {job.title: job for job in JOBS}
    create = [job for title, job in wanted.items() if title not in ours]
    update = [(ours[title], job) for title, job in wanted.items() if title in ours]
    delete = [job_id for title, job_id in ours.items() if title not in wanted]
    return create, update, delete


def last_fire(job: TimerJob, now: dt.datetime) -> dt.datetime:
    """When the timer last started `job` at or before `now` (both UTC)."""
    ny = now.astimezone(ZoneInfo(TIMEZONE))
    hour, minute = _hm(job.at)
    for back in range(8):
        day = ny.date() - dt.timedelta(days=back)
        fire = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ZoneInfo(TIMEZONE))
        if (day.weekday() + 1) % 7 in job.days and fire <= ny:
            return fire.astimezone(dt.UTC)
    raise ValueError(f"{job.title} has no day to run on")


def check(runs: pd.DataFrame, windows: dict, now: dt.datetime) -> pd.DataFrame:
    """Per timed job (not the second starts): when the timer last fired, when GitHub started a
    run of that workflow, and how that went: on time (within 10 minutes), late, missed (no
    run before the job's window closed, or within 2 hours for the jobs without one), or due.
    `runs`: workflowName and createdAt (UTC), any trigger. `windows`: slot -> (start, end)
    New York times, from config."""
    if runs.empty:
        runs = pd.DataFrame({"workflowName": pd.Series(dtype=str), "createdAt": []})
    created = pd.to_datetime(runs["createdAt"], utc=True)
    rows = []
    for job in (j for j in JOBS if not j.retry):
        fire = last_fire(job, now)
        if job.key in windows:
            end_ny = dt.datetime.combine(
                fire.astimezone(ZoneInfo(TIMEZONE)).date(),
                windows[job.key][1],
                tzinfo=ZoneInfo(TIMEZONE),
            )
            closes = end_ny.astimezone(dt.UTC)
        else:
            closes = fire + dt.timedelta(minutes=GRACE_MINUTES)
        mine = created[
            (runs["workflowName"] == job.name)
            & (created >= fire - dt.timedelta(minutes=2))
            & (created <= closes)
        ]
        if len(mine):
            start = mine.min().to_pydatetime()
            late = max(0, round((start - fire).total_seconds() / 60))
            verdict = "✅ on time" if late <= ON_TIME_MINUTES else f"🟡 {late} min late"
            started = start.astimezone(ZoneInfo(TIMEZONE)).strftime("%H:%M")
        else:
            verdict, started = ("⏳ due" if now <= closes else "❌ missed"), ""
        rows.append(
            {
                "job": f"{job.key} ({job.name})",
                "timer fired": fire.astimezone(ZoneInfo(TIMEZONE)).strftime("%a %d %b %H:%M"),
                "GitHub started": started,
                "status": verdict,
            }
        )
    return pd.DataFrame(rows)
