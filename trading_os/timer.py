"""The timer that starts the timed jobs on the minute (Emil, 20 Oct 2026). GitHub's own
scheduler started them 2½ to 6½ hours late on 19-20 Oct, so the pre-market and intraday
checks never ran inside their windows. A free cron-job.org account now calls GitHub's API to
start each workflow at its New York time (summer and winter time handled there); GitHub's
cron lines stay as a backup.

Extra starts are harmless: every job exits outside its New York window and skips a session it
already saved, and the data-repo jobs queue one behind the other. That is also why each
scan has a second start a little later, in case the first run failed.

The runs live in `config/runs.yaml` (Emil, 4 Nov 2026: edit them on Lab → Runs), one per line;
`load` reads and checks them. `scripts/timer_setup.py` creates these jobs at cron-job.org; the
System health page checks that GitHub started each one on time (`check`). A run that is off is
dropped at cron-job.org, and GitHub's backup cron exits at once (`switched_off`).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import yaml

REPO = "Peikz/trading-os"
TIMEZONE = "America/New_York"
PREFIX = "trading-os: "  # the titles of our jobs at cron-job.org
WEEKDAYS = (1, 2, 3, 4, 5)  # cron-job.org numbering: 0 = Sunday ... 6 = Saturday
TUE_SAT = (2, 3, 4, 5, 6)  # the mornings after a session
DAYS = {"weekdays": WEEKDAYS, "tue-sat": TUE_SAT, "sat": (6,)}
RUNS_PATH = Path(__file__).resolve().parent.parent / "config" / "runs.yaml"
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
    tz: str = TIMEZONE  # the clock `at` is on (the weekly run: Copenhagen)
    on: bool = True  # off: the timer drops it, GitHub's backup cron exits at once

    @property
    def title(self) -> str:
        zone = "ET" if self.tz == TIMEZONE else "CPH"
        return f"{PREFIX}{self.key}{' retry' if self.retry else ''} {self.at} {zone}"


class RunsError(ValueError):
    """config/runs.yaml is not what the timer can run."""


KEYS = {"key", "workflow", "name", "at", "days", "inputs", "retry", "tz", "enabled"}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse(text: str) -> tuple[TimerJob, ...]:
    """The runs in `text` (config/runs.yaml), checked: known keys, an HH:MM time, known days and
    clock, one title per run, and a run's lines on or off together. A scan's time inside its
    window is checked by `outside_windows`, which needs scans.yaml."""
    data = yaml.safe_load(text) or {}
    rows = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RunsError("runs.yaml: no `runs:` list")
    jobs = []
    for n, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise RunsError(f"run {n}: not a {{key: ..., at: ...}} line")
        unknown = set(row) - KEYS
        missing = {"key", "workflow", "name", "at", "days"} - set(row)
        if unknown or missing:
            raise RunsError(f"run {n}: unknown {sorted(unknown)}, missing {sorted(missing)}")
        at = str(row["at"])
        if not HHMM.match(at):
            raise RunsError(f"run {n} ({row['key']}): time {at!r} is not HH:MM")
        if row["days"] not in DAYS:
            raise RunsError(f"run {n} ({row['key']}): days must be one of {sorted(DAYS)}")
        tz = str(row.get("tz", TIMEZONE))
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as err:
            raise RunsError(f"run {n} ({row['key']}): unknown clock {tz!r}") from err
        for flag in ("retry", "enabled"):
            if not isinstance(row.get(flag, flag == "enabled"), bool):
                raise RunsError(f"run {n} ({row['key']}): {flag} must be true or false")
        inputs = row.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise RunsError(f"run {n} ({row['key']}): inputs must be {{name: value}}")
        jobs.append(
            TimerJob(
                str(row["key"]),
                str(row["workflow"]),
                str(row["name"]),
                at,
                DAYS[row["days"]],
                {k: str(v) for k, v in inputs.items()},
                bool(row.get("retry", False)),
                tz,
                bool(row.get("enabled", True)),
            )
        )
    titles = [j.title for j in jobs]
    if len(set(titles)) != len(titles):
        raise RunsError("two runs have the same key, time and clock")
    for key in {j.key for j in jobs}:
        if len({j.on for j in jobs if j.key == key}) > 1:
            raise RunsError(f"{key}: its lines must be on or off together")
    return tuple(jobs)


def load(path: Path = RUNS_PATH) -> tuple[TimerJob, ...]:
    return parse(Path(path).read_text(encoding="utf-8"))


def outside_windows(jobs, windows: dict) -> list[str]:
    """The scan runs whose New York time falls outside their slot's window (`windows`: slot ->
    (start, end) times, from scans.yaml); such a run would start and do nothing."""
    bad = []
    for job in jobs:
        if job.key in windows:
            start, end = windows[job.key]
            hour, minute = _hm(job.at)
            if job.tz != TIMEZONE or not start <= dt.time(hour, minute) <= end:
                bad.append(
                    f"{job.key} {job.at}: outside its window {start:%H:%M}-{end:%H:%M} New York"
                )
    return bad


JOBS = load()


def active(jobs=None) -> tuple[TimerJob, ...]:
    """The runs that are on."""
    return tuple(j for j in (JOBS if jobs is None else jobs) if j.on)


def skip(key: str, label: str) -> bool:
    """`switched_off`, said in the log: the job then exits with nothing to do."""
    if not switched_off(key):
        return False
    from trading_os.logsafe import status

    status(f"{label}: switched off on Lab → Runs, nothing to do")
    return True


def switched_off(key: str, jobs=None) -> bool:
    """True when the run `key` is off and this start came from a schedule (GitHub's cron or
    the timer), so the job should exit at once. Started by hand, it always runs."""
    lines = [j for j in (JOBS if jobs is None else jobs) if j.key == key]
    timed = (
        os.environ.get("GITHUB_EVENT_NAME") == "schedule"
        or os.environ.get("RUN_TRIGGER") == "timer"
    )
    return bool(lines) and not any(j.on for j in lines) and timed


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
            "timezone": job.tz,
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
    wanted = {job.title: job for job in active()}
    create = [job for title, job in wanted.items() if title not in ours]
    update = [(ours[title], job) for title, job in wanted.items() if title in ours]
    delete = [job_id for title, job_id in ours.items() if title not in wanted]
    return create, update, delete


def last_fire(job: TimerJob, now: dt.datetime) -> dt.datetime:
    """When the timer last started `job` at or before `now` (both UTC)."""
    ny = now.astimezone(ZoneInfo(job.tz))
    hour, minute = _hm(job.at)
    for back in range(8):
        day = ny.date() - dt.timedelta(days=back)
        fire = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ZoneInfo(job.tz))
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
    for job in (j for j in active() if not j.retry):
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
            if "conclusion" in runs:  # a run that started but failed counts as failed
                ended = runs.loc[mine.index, "conclusion"].fillna("")
                if len(ended) and (ended == "failure").all():
                    verdict = "❌ failed"
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


def health_line(runs: pd.DataFrame, windows: dict, now: dt.datetime, hours: float = 24) -> str:
    """`🩺 All 9 timed jobs since yesterday ran on time`, or the ones that didn't: one line for
    the EOD push (Emil, 22 Oct 2026), so a silent failure shows the same day."""
    table = check(runs, windows, now)
    jobs = [j for j in active() if not j.retry]  # the rows of `check`, in order
    since = now - dt.timedelta(hours=hours)
    keep = [
        i
        for i, job in enumerate(jobs)
        if last_fire(job, now) >= since and "due" not in table.iloc[i]["status"]
    ]
    if not keep:
        return "🩺 Job check: nothing was due"
    recent = table.iloc[keep]
    bad = recent[~recent["status"].str.startswith("✅")]
    if bad.empty:
        return f"🩺 All {len(recent)} timed jobs since yesterday ran on time"
    pairs = zip(bad["job"], bad["status"], strict=True)
    issues = [f"{job.split(' ')[0]} {state}" for job, state in pairs]
    return f"🩺 {len(recent) - len(bad)}/{len(recent)} jobs OK · " + " · ".join(issues)
