"""The scan runs of one day (UX round 3, 18 Nov 2026): the board used to show the newest run of
each slot; this reads every run of the day from the same run files and lets the dashboard show
one run, or all of them together ("All today": de-duplicated, best grade first, every stock
tagged with the runs it came from). Nothing here changes what a scan writes or how it grades.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from typing import Any

import pandas as pd

from trading_os import board_data, clock, dashboard

# The slots the board reads (`board_data.collect`), in the order they run during the day
SLOTS = ("pm", "am", "mid", "eod", "ah")
NAMES = {
    "pm": "Pre-market",
    "am": "10:15",
    "mid": "12:00",
    "eod": "End of day",
    "ah": "After hours",
}
ALL = "all"


def run_key(run: dashboard.Run) -> str:
    """`2026-10-21_eod`: the same id `/api/runs` gives a scheduled run."""
    return f"{run.session.isoformat()}_{run.slot}"


def todays_runs(runs: Iterable[dashboard.Run]) -> list[dashboard.Run]:
    """The scheduled runs of the newest session the data repo has, in the order they ran."""
    found = [r for r in runs if r.kind == "scheduled" and r.slot in SLOTS and r.candidates.exists()]
    if not found:
        return []
    session = max(r.session for r in found)
    return sorted((r for r in found if r.session == session), key=lambda r: SLOTS.index(r.slot))


def times(run: dashboard.Run) -> dict[str, str | None]:
    """The run's scheduled start in New York and Copenhagen (`07:17`), or None when unknown."""
    start = dashboard.slot_start(run.slot, run.session)
    if start is None:
        return {"ny": None, "cph": None}
    return {
        "ny": f"{start:%H:%M}",
        "cph": f"{start.astimezone(clock.COPENHAGEN):%H:%M}",
    }


def collect_run(
    run: dashboard.Run,
    lookup: list[dashboard.Run],
    cfg: Any,
    scan_frames: Callable[[str], dict],
    exchanges: Callable[[str], dict] | None,
    everything: bool = False,
) -> pd.DataFrame:
    """One run's pushed alert-tier hits as the board reads them (`board_data.collect`), with the
    sector and exchange taken from the newest snapshot among `lookup`."""
    return board_data.collect(
        [run], cfg, scan_frames, exchanges, everything=everything, lookup=lookup
    )


def union(
    frames: list[tuple[dashboard.Run, pd.DataFrame]], everything: bool = False
) -> pd.DataFrame:
    """Every run's hits in one frame: one row per stock and scan (per stock with `everything`),
    the best grade first as on the board; `runs` lists the run slots each stock appeared in."""
    parts = [f.assign(runs=run.slot) for run, f in frames if not f.empty]
    if not parts:
        return pd.DataFrame()
    both = pd.concat(parts, ignore_index=True)
    key = ["ticker"] if everything else ["ticker", "scan"]
    seen = both.groupby(key, sort=False)["runs"].agg(lambda s: list(dict.fromkeys(s)))
    both = both.sort_values(["_g", "_s"], ascending=[True, False], kind="stable")
    both = both.drop_duplicates(key, keep="first").copy()
    index = pd.MultiIndex.from_frame(both[key]) if len(key) > 1 else both["ticker"]
    both["runs"] = [seen.loc[k] for k in index]
    return both.reset_index(drop=True)


def hits(
    run_id: str | None,
    found: list[dashboard.Run],
    cfg: Any,
    scan_frames: Callable[[str], dict],
    exchanges: Callable[[str], dict] | None,
    everything: bool = False,
) -> pd.DataFrame | None:
    """The hits of one run of today (`run_id`) or of all of them (`ALL`). None: no such run."""
    today = todays_runs(found)
    if run_id == ALL:
        picked = today
    else:
        picked = [r for r in today if run_key(r) == run_id]
        if not picked:
            return None
    frames = [(r, collect_run(r, found, cfg, scan_frames, exchanges, everything)) for r in picked]
    out = union(frames, everything)
    if out.empty and not frames:
        return pd.DataFrame()
    return out


def summary(
    found: list[dashboard.Run],
    cfg: Any,
    scan_frames: Callable[[str], dict],
    exchanges: Callable[[str], dict] | None,
    graded: tuple[str, ...],
) -> dict[str, Any]:
    """The run picker's chips: the day, each run (time in New York and Copenhagen, hit count:
    the stocks to act on) and the day as a whole."""
    today = todays_runs(found)
    frames = [(r, collect_run(r, found, cfg, scan_frames, exchanges)) for r in today]

    def count(frame: pd.DataFrame) -> int:
        if frame.empty or "grade" not in frame:
            return 0
        return int(frame[frame["grade"].isin(graded)]["ticker"].nunique())

    every = union(frames)
    session: dt.date | None = today[0].session if today else None
    return {
        "session": session.isoformat() if session else None,
        "all": {"id": ALL, "label": "All today", "count": count(every)},
        "runs": [
            {
                "id": run_key(r),
                "slot": r.slot,
                "name": NAMES.get(r.slot, r.slot),
                **times(r),
                "count": count(f),
            }
            for r, f in frames
        ],
    }
