"""System health (Emil, 20 Oct 2026): did every scheduled job leave its output, how fresh is
each dataset, what failed, and how late GitHub started the scheduled runs. Reads the local
data repo (pull first to see the latest); the run list needs the `gh` CLI signed in on this
PC and is optional.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

import pandas as pd

from trading_os import clock, dashboard
from trading_os.metrics import NEW_YORK

SLOTS = ("pm", "am", "mid", "close", "eod")
NEWER_SLOTS = {"close"}  # added 20 Oct 2026: sessions before its first run show "—"
MARKS = {"scheduled": "✅", "manual": "🟡 manual", "missing": "❌", "pending": "⏳", "none": "—"}
REPO_ROOT = Path(__file__).resolve().parents[1]


def run_grid(data_dir: Path, schedule, now: dt.datetime, sessions: int = 10) -> pd.DataFrame:
    """Sessions (newest first, from the first run on) x slots: ✅ the scheduled run saved its
    output, 🟡 only a manual run, ❌ nothing, ⏳ not due yet (today, before the window closes)."""
    found: dict[tuple, str] = {}
    runs = dashboard.list_runs(data_dir)
    for run in runs:
        key = (run.session, run.slot)
        if found.get(key) != "scheduled":
            found[key] = run.kind
    ny = clock.ny_time(schedule, now)
    first = min((r.session for r in runs), default=ny.date())
    started = {
        slot: min((r.session for r in runs if r.slot == slot), default=None) for slot in NEWER_SLOTS
    }
    rows = []
    days = [d for d in clock.sessions_back(schedule, ny.date(), sessions) if d >= first]
    for day in reversed(days):
        row = {"session": day}
        for slot in SLOTS:
            state = found.get((day, slot))
            if (
                state is None
                and slot in NEWER_SLOTS
                and (started[slot] is None or day < started[slot])
            ):
                state = "none"
            if state is None:
                end = schedule.windows_et[slot][1]
                due = day < ny.date() or (day == ny.date() and ny.time() > end)
                state = "missing" if due else "pending"
            row[slot] = MARKS[state]
        rows.append(row)
    return pd.DataFrame(rows)


def _newest(paths, parse) -> dt.date | None:
    dates = [d for d in (parse(p) for p in paths) if d is not None]
    return max(dates) if dates else None


def _date_in(name: str) -> dt.date | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return dt.date.fromisoformat(m[1])
    m = re.search(r"(\d{8})T", name)
    return dt.datetime.strptime(m[1], "%Y%m%d").date() if m else None


def freshness(data_dir: Path, schedule, now: dt.datetime, extra=None) -> pd.DataFrame:
    """Newest date of each dataset and how many sessions behind the last closed one it is.
    `extra`: dataset -> newest date for data that isn't in the local clone (it wins)."""
    root = Path(data_dir) / "data"
    ny = clock.ny_time(schedule, now)
    last_closed = clock.previous_session(schedule, ny.date())
    if clock.is_session(schedule, ny.date()) and ny.time() > schedule.windows_et["eod"][0]:
        last_closed = ny.date()
    items = {
        "Daily bars (Massive)": root.glob("bars/massive/*/*.parquet"),
        "EOD run": root.glob("candidates/*/*_eod.parquet"),
        "Pre-market run": root.glob("candidates/*/*_pm.parquet"),
        "Outcomes": root.glob("outcomes/**/*.parquet"),
        "EP history build": root.glob("ep_history/*.parquet"),
        "Strategy history build": (p for p in root.glob("strategy_history/*") if p.is_dir()),
        "Minute study build": (p for p in root.glob("intraday_study/*") if p.is_dir()),
        "Journal": root.glob("journal/journal_*.parquet"),
    }
    rows = []
    for name, paths in items.items():
        newest = (extra or {}).get(name) or _newest(paths, lambda p: _date_in(p.name))
        behind = None
        if newest is not None and newest <= last_closed:
            behind = len(clock.sessions_after(schedule, newest, 1000, last_closed))
        rows.append({"dataset": name, "newest": newest, "sessions_behind": behind})
    return pd.DataFrame(rows)


def errors(data_dir: Path, limit: int = 20) -> pd.DataFrame:
    """The newest failure logs (`logs/<stamp>_<job>.log`, written by `run_guarded`): when, which
    job, and the exception line. Local only; the public Actions logs never carry it."""
    files = sorted((Path(data_dir) / "logs").glob("*.log"), reverse=True)[:limit]
    rows = []
    for f in files:
        lines = [x for x in f.read_text(encoding="utf-8", errors="replace").splitlines() if x]
        stamp, _, job = f.stem.partition("_")
        rows.append({"when": stamp, "job": job, "error": lines[-1] if lines else ""})
    return pd.DataFrame(rows, columns=["when", "job", "error"])


def _crons() -> dict[str, list[tuple[int, int]]]:
    """Workflow name -> its (hour, minute) UTC cron times, read from .github/workflows."""
    out: dict[str, list[tuple[int, int]]] = {}
    for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        name = re.search(r"^name:\s*(.+)$", text, re.M)
        times = re.findall(r'cron:\s*"(\d+) (\d+) ', text)
        if name and times:
            out[name[1].strip()] = [(int(h), int(m)) for m, h in times]
    return out


def minutes_late(created: dt.datetime, crons: list[tuple[int, int]]) -> float | None:
    """Minutes between the latest cron time at or before `created` (UTC) and `created`."""
    best = None
    for day_offset in (0, 1):
        day = created.date() - dt.timedelta(days=day_offset)
        for h, m in crons:
            planned = dt.datetime.combine(day, dt.time(h, m), tzinfo=dt.UTC)
            if planned <= created and (best is None or planned > best):
                best = planned
    return None if best is None else (created - best).total_seconds() / 60


def run_list(limit: int = 100) -> pd.DataFrame:
    """Recent workflow runs via `gh` (one API call): workflowName, event, status, conclusion,
    createdAt (UTC). Empty without the gh CLI or a connection."""
    try:
        raw = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "-L",
                str(limit),
                "--json",
                "workflowName,event,status,conclusion,createdAt,updatedAt",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return pd.DataFrame()
    return pd.DataFrame(json.loads(raw or "[]"))


def github_runs(runs: pd.DataFrame, limit: int = 40) -> pd.DataFrame:
    """The newest `limit` of `run_list`, with how late GitHub started the scheduled ones."""
    if runs.empty:
        return runs
    runs = runs.head(limit).copy()
    crons = _crons()
    created = pd.to_datetime(runs["createdAt"], utc=True)
    runs["started"] = created.dt.tz_convert(NEW_YORK).dt.strftime("%a %d %b %H:%M ET")
    runs["minutes_late"] = [
        round(minutes_late(c.to_pydatetime(), crons.get(w, [])) or 0)
        if e == "schedule" and crons.get(w)
        else None
        for c, w, e in zip(created, runs["workflowName"], runs["event"], strict=True)
    ]
    keep = ["workflowName", "event", "started", "minutes_late", "status", "conclusion"]
    return runs[keep].rename(columns={"workflowName": "workflow"})
