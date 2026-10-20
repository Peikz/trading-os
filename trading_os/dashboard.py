"""Data layer for the private dashboard app (app/streamlit_app.py).

Reads the local clone of the private data repo, and writes the human inputs (grades, notes,
screenshots) back to it as append-only events. Nothing here runs in GitHub Actions.

Grades are the human's call (SPEC §6.4: A = all five criteria, B = four, C = three or fewer).
The app shows the criteria; it never picks the grade.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from trading_os import watchlists
from trading_os.store import PARQUET_OPTIONS

SLOT_ORDER = {"weekly": 0, "eod": 1, "mid": 2, "am": 3, "pm": 4}
GRADES = ("", "A", "B", "C")
NOTE_COLUMNS = ["kind", "ref_id", "grade", "notes", "tags", "attachments", "saved_ts"]
_CANONICAL = re.compile(r"^(\d{4}-\d{2}-\d{2})_(pm|am|mid|eod|weekly)$")
_MANUAL = re.compile(r"^(\d{4}-\d{2}-\d{2})_(pm|am|mid|eod|weekly)_(\d{6})$")


@dataclass(frozen=True)
class Run:
    session: dt.date
    slot: str
    kind: str  # scheduled | manual
    candidates: Path
    universe: Path
    breadth: Path | None
    report: Path | None
    charts: Path
    stamp: str = ""
    created: float = 0.0
    breadth_pm: Path | None = None  # file time, orders manual runs (their folder name has no date)

    @property
    def label(self) -> str:
        extra = f" (manual {self.stamp})" if self.kind == "manual" else ""
        return f"{self.session.isoformat()} · {self.slot}{extra}"


def list_runs(data_dir: Path, include_manual: bool = True) -> list[Run]:
    """Every run in the data repo, newest first."""
    root = Path(data_dir)
    runs = []
    for path in (root / "data" / "candidates").glob("*/*.parquet"):
        m = _CANONICAL.match(path.stem)
        if not m:
            continue
        day, slot = dt.date.fromisoformat(m[1]), m[2]
        year, stem = path.parent.name, path.stem
        breadth = root / "data" / "breadth" / year / f"{stem}.parquet"
        breadth_pm = root / "data" / "breadth_pm" / year / f"{stem}.parquet"
        report = root / "reports" / year / f"{stem}.md"
        runs.append(
            Run(
                session=day,
                slot=slot,
                kind="scheduled",
                candidates=path,
                universe=root / "data" / "universe" / year / f"{stem}.parquet",
                breadth=breadth if breadth.exists() else None,
                report=report if report.exists() else None,
                charts=root / "data" / "charts" / year / stem,
                breadth_pm=breadth_pm if breadth_pm.exists() else None,
            )
        )
    if include_manual:
        for folder in (root / "data" / "manual").glob("*"):
            m = _MANUAL.match(folder.name)
            if not m or not (folder / "candidates.parquet").exists():
                continue
            breadth, report = folder / "breadth.parquet", folder / "report.md"
            runs.append(
                Run(
                    session=dt.date.fromisoformat(m[1]),
                    slot=m[2],
                    kind="manual",
                    candidates=folder / "candidates.parquet",
                    universe=folder / "universe.parquet",
                    breadth=breadth if breadth.exists() else None,
                    report=report if report.exists() else None,
                    charts=folder / "charts",
                    stamp=m[3],
                    created=(folder / "candidates.parquet").stat().st_mtime,
                    breadth_pm=(folder / "breadth_pm.parquet")
                    if (folder / "breadth_pm.parquet").exists()
                    else None,
                )
            )
    return sorted(
        runs,
        key=lambda r: (r.session, -SLOT_ORDER[r.slot], r.kind == "scheduled", r.created),
        reverse=True,
    )


def chart_for(run: Run, scan: str, ticker: str) -> Path | None:
    safe = str(ticker).replace("/", "-").replace(".", "-")
    path = run.charts / f"{scan}_{safe}.png"
    return path if path.exists() else None


def breadth_history(data_dir: Path) -> pd.DataFrame:
    files = sorted((Path(data_dir) / "data" / "breadth").glob("*/*.parquet"))
    if not files:
        return pd.DataFrame()
    frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.date
    return frame.sort_values("session_date").reset_index(drop=True)


def watchlist_state(data_dir: Path) -> pd.DataFrame:
    return watchlists.current(watchlists.load_events(data_dir))


def latest_journal(data_dir: Path) -> pd.DataFrame:
    snapshots = sorted((Path(data_dir) / "data" / "journal").glob("journal_*.parquet"))
    return pd.read_parquet(snapshots[-1]) if snapshots else pd.DataFrame()


def latest_positions(data_dir: Path) -> pd.DataFrame:
    """Open positions from the newest journal rebuild."""
    snapshots = sorted((Path(data_dir) / "data" / "journal").glob("positions_*.parquet"))
    return pd.read_parquet(snapshots[-1]) if snapshots else pd.DataFrame()


# --- human inputs: grades, notes, screenshots (append-only events)


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:80]


def save_note(
    data_dir: Path,
    kind: str,
    ref_id: str,
    grade: str,
    notes: str,
    tags: str,
    attachments: list[str],
    now: dt.datetime | None = None,
) -> Path:
    """Record a grade/notes event for a trade or a signal. Earlier events are kept."""
    if kind not in ("trade", "signal"):
        raise ValueError("kind must be trade or signal")
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}")
    now = now or dt.datetime.now(dt.UTC)
    folder = Path(data_dir) / "data" / "journal" / "notes" / str(now.year)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now:%Y%m%dT%H%M%S%f}_{kind}_{_safe(ref_id)}.parquet"
    event = {
        "kind": kind,
        "ref_id": ref_id,
        "grade": grade,
        "notes": notes,
        "tags": tags,
        "attachments": ";".join(attachments),
        "saved_ts": pd.Timestamp(now),
    }
    pd.DataFrame([event], columns=NOTE_COLUMNS).to_parquet(path, **PARQUET_OPTIONS)
    return path


def notes_state(data_dir: Path) -> pd.DataFrame:
    """Latest note per (kind, ref_id)."""
    files = sorted((Path(data_dir) / "data" / "journal" / "notes").glob("*/*.parquet"))
    if not files:
        return pd.DataFrame(columns=NOTE_COLUMNS)
    events = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    events = events.sort_values("saved_ts", kind="stable")
    return events.groupby(["kind", "ref_id"], as_index=False).tail(1).reset_index(drop=True)


def save_attachment(
    data_dir: Path, ref_id: str, filename: str, content: bytes, now: dt.datetime | None = None
) -> str:
    """Store an uploaded screenshot; returns its path relative to the data repo."""
    now = now or dt.datetime.now(dt.UTC)
    folder = Path(data_dir) / "data" / "journal" / "attachments" / _safe(ref_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now:%Y%m%dT%H%M%S}_{_safe(filename)}"
    path.write_bytes(content)
    return path.relative_to(Path(data_dir)).as_posix()


# --- syncing the local clone with GitHub


def git(data_dir: Path, *args: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "-C", str(data_dir), *args], capture_output=True, text=True, check=False
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def download_release(
    data_dir: Path, tag: str, folder: Path, patterns: list[str] | None = None
) -> tuple[bool, str]:
    """Download a release of the data repo (gh CLI, signed in on this PC) into `folder`,
    all files or only those matching `patterns`."""
    folder.mkdir(parents=True, exist_ok=True)
    ok, remote = git(data_dir, "remote", "get-url", "origin")
    repo = remote.strip().removesuffix(".git").split("github.com/")[-1] if ok else ""
    try:
        done = subprocess.run(
            [
                "gh",
                "release",
                "download",
                tag,
                "-R",
                repo,
                "-D",
                str(folder),
                "--clobber",
                *[arg for p in patterns or [] for arg in ("-p", p)],
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def pull(data_dir: Path) -> tuple[bool, str]:
    return git(data_dir, "pull", "--rebase", "--autostash")


# What the dashboard writes for you: journal, plans, notes and grades, your watchlists, your
# chart lines and anchors, and docs. Save & push commits these folders and nothing else.
SAVED_BY_YOU = ("data/journal", "data/my_watchlists", "data/chart_marks", "docs")


def save_and_push(data_dir: Path, message: str = "journal: notes and grades") -> tuple[bool, str]:
    paths = [p for p in SAVED_BY_YOU if (Path(data_dir) / p).exists()]
    if paths:
        ok, out = git(data_dir, "add", "--", *paths)
        if not ok:
            return ok, out
    if git(data_dir, "diff", "--cached", "--quiet")[0]:
        return True, "nothing new to save"
    ok, out = git(data_dir, "commit", "-m", message)
    if not ok:
        return ok, out
    ok, out = pull(data_dir)
    if not ok:
        return ok, out
    return git(data_dir, "push")
