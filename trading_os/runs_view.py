"""Lab → Runs, without any UI (Emil, 4 Nov 2026: "see all the push and scan runs and edit
them", "an overview of it"). Every timed run in start order: its New York and Copenhagen time,
its second start, its days, the scans it runs and the ones it pushes, on or off. And the edit of
a run's times and on/off in config/runs.yaml.

Like `scan_editor`, the file is never rewritten: only the value after `at:` or `enabled:` in the
run's own lines changes. The result must load (`timer.parse`) and every scan run must start
inside its New York window (`timer.outside_windows`) before anything is written. Committing and
pushing is a separate step; the Timer sync workflow then updates cron-job.org by itself.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from trading_os import clock, notify, timer
from trading_os.scan_editor import commit_and_push as _commit_and_push
from trading_os.scan_editor import diff

WHAT = {  # what each run does, in a few words
    "backfill": "Daily bars of the last sessions (Massive)",
    "bars-pack": "Packs two years of daily bars for the dashboard",
    "pm": "Pre-market scans and push",
    "am": "Morning scans and push",
    "mid": "Midday scans and push",
    "eod": "End-of-day scans and push, with the market lines",
    "ah": "After-hours scans and push",
    "outcomes": "How past signals went",
    "alerts": "Watches your price alerts through the session",
    "weekly": "Weekly lists and push",
}
DAYS_TEXT = {timer.WEEKDAYS: "Mon-Fri", timer.TUE_SAT: "Tue-Sat", (6,): "Sat"}
CAPTION = (
    "Every timed run in start order: when it starts (New York · Copenhagen), the scans it "
    "runs and the ones it pushes. Edit a run's times or turn it off below, or a scan's "
    "settings further down. Each change is checked like the jobs check it and saved on this "
    "PC; GitHub's jobs and the timer use it after Commit & push."
)


def _moment(job: timer.TimerJob, today: dt.date) -> dt.datetime:
    hour, minute = (int(x) for x in job.at.split(":"))
    return dt.datetime.combine(today, dt.time(hour, minute), tzinfo=ZoneInfo(job.tz))


def keys(jobs=None) -> list[str]:
    """The runs in start order (New York time of the first start); the Saturday run last."""
    jobs = timer.JOBS if jobs is None else jobs
    today = dt.date.today()
    first = {}
    for job in jobs:
        if not job.retry and job.key not in first:
            ny = _moment(job, today).astimezone(clock.NEW_YORK).time()
            first[job.key] = (job.days == (6,), ny)
    return sorted(first, key=first.get)


def _label(cfg, name: str) -> str:
    return "Market lines" if name == "breadth" else notify.scan_label(cfg, name)


def _lines(jobs, key: str) -> tuple[timer.TimerJob, list[timer.TimerJob]]:
    mine = [j for j in jobs if j.key == key]
    main = next(j for j in mine if not j.retry)
    return main, [j for j in mine if j.retry]


def overview(cfg, jobs=None, today: dt.date | None = None, started=None) -> list[dict[str, Any]]:
    """One row per run. `started`: `timer.check`'s table (job, status), to add how its last
    start went; None when GitHub's runs aren't loaded."""
    jobs = timer.JOBS if jobs is None else jobs
    today = today or dt.date.today()
    status = {}
    if started is not None and len(started):
        status = dict(zip(started["job"], started["status"], strict=False))
    rows = []
    for key in keys(jobs):
        main, retries = _lines(jobs, key)
        runs_here = [n for n, s in cfg.scans.items() if s.enabled and key in (s.slots or (s.slot,))]
        pushed = [
            n
            for n, s in cfg.scans.items()
            if s.enabled and s.action == "push" and key in notify.push_slots(s)
        ]
        row = {
            "run": f"{main.name} ({key})" if main.name.lower() != key else main.name,
            "on": main.on,
            "starts (NY · CPH)": clock.both_times(_moment(main, today)),
            "second start": " · ".join(clock.both_times(_moment(r, today)) for r in retries),
            "days": DAYS_TEXT.get(main.days, ", ".join(map(str, main.days))),
            "does": WHAT.get(key, ""),
            "scans": ", ".join(_label(cfg, n) for n in runs_here),
            "pushes": ", ".join(_label(cfg, n) for n in pushed),
            "key": key,
        }
        if status:
            row["last start"] = status.get(f"{key} ({main.name})", "")
        rows.append(row)
    return rows


def form(cfg, key: str, jobs=None) -> dict[str, Any]:
    """The edit form's fields for run `key`: on, the first and second start, its clock, and
    the New York window a scan run must start in (None for the other runs)."""
    jobs = timer.JOBS if jobs is None else jobs
    main, retries = _lines(jobs, key)
    window = cfg.schedule.windows_et.get(key)
    return {
        "enabled": main.on,
        "first": main.at,
        "second": retries[0].at if retries else None,
        "clock": "Copenhagen" if main.tz != timer.TIMEZONE else "New York",
        "window": (f"{window[0]:%H:%M}", f"{window[1]:%H:%M}") if window else None,
    }


RUN_LINE = re.compile(r"^\s*-\s*\{.*\}\s*$")


def apply(text: str, key: str, changes: dict[str, Any], windows: dict) -> str:
    """`text` (config/runs.yaml) with run `key` changed: `enabled` (both lines), `first` and
    `second` (the retry line's time). Raises `timer.RunsError` when the result doesn't load or
    a scan run would start outside its window."""
    out, seen = [], False
    for line in text.splitlines(keepends=True):
        body = line.split("#", 1)[0]
        if RUN_LINE.match(body.rstrip("\n")) and re.search(rf"\bkey:\s*{re.escape(key)}\s*,", body):
            seen = True
            retry = re.search(r"\bretry:\s*true\b", body) is not None
            at = changes.get("second" if retry else "first")
            if at:
                line, n = re.subn(r'\bat:\s*"[^"]*"', f'at: "{at}"', line, count=1)
                if n != 1:
                    raise timer.RunsError(f"{key}: no at: on its line")
            if "enabled" in changes:
                flag = "true" if changes["enabled"] else "false"
                line, n = re.subn(r"\benabled:\s*(true|false)\b", f"enabled: {flag}", line, count=1)
                if n != 1:
                    raise timer.RunsError(f"{key}: no enabled: on its line")
        out.append(line)
    if not seen:
        raise timer.RunsError(f"{key}: no such run in runs.yaml")
    new = "".join(out)
    jobs = timer.parse(new)
    bad = timer.outside_windows(jobs, windows)
    if bad:
        raise timer.RunsError("; ".join(bad))
    for job in jobs:  # the change must read back as asked
        if job.key == key:
            want = changes.get("second" if job.retry else "first")
            if (want and job.at != want) or job.on != changes.get("enabled", job.on):
                raise timer.RunsError(f"{key}: the change did not read back")
    return new


def save(key: str, changes: dict[str, Any], windows: dict, path: Path = timer.RUNS_PATH) -> str:
    """Write the checked change; returns the diff (empty: nothing changed)."""
    old = Path(path).read_text(encoding="utf-8")
    new = apply(old, key, changes, windows)
    if new != old:
        Path(path).write_text(new, encoding="utf-8", newline="\n")
    return diff(old, new)


def commit_and_push(key: str, path: Path = timer.RUNS_PATH) -> tuple[bool, str]:
    """Commit config/runs.yaml and push it: GitHub's jobs read it, and the Timer sync workflow
    updates cron-job.org."""
    return _commit_and_push(f"run {key}", path)
