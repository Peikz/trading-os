"""The dashboard's search box (Emil, 22 Oct 2026: "a search box so I can search on things").

A ticker finds the stock everywhere: recent scan hits (with grade and points), the
watchlists, an open position, price alerts, stock notes and tagged daily notes. Words find
your notes, daily notes, journal notes and the guide's lines.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

import pandas as pd

TICKER = re.compile(r"^\$?[A-Za-z][A-Za-z0-9.\-]{0,5}$")


def looks_like_ticker(query: str) -> bool:
    return bool(TICKER.match(query.strip()))


def scan_hits(
    runs: Iterable[tuple[str, Mapping[str, pd.DataFrame]]], ticker: str, labels: Mapping
) -> pd.DataFrame:
    """Every run (label, its hits per scan) where `ticker` was a hit, newest run first."""
    cols = ["run", "scan", "tier", "grade", "why", "points"]
    rows = []
    for label, frames in runs:
        for scan, hits in frames.items():
            mine = hits[hits["ticker"] == ticker] if "ticker" in hits else hits.iloc[0:0]
            for r in mine.to_dict("records"):
                rows.append(
                    {
                        "run": label,
                        "scan": labels.get(scan, scan),
                        "tier": r.get("tier"),
                        "grade": r.get("grade"),
                        "why": r.get("grade_why"),
                        "points": r.get("grade_points"),
                    }
                )
    return pd.DataFrame(rows, columns=cols)


def text_hits(frame: pd.DataFrame, columns: Iterable[str], query: str) -> pd.DataFrame:
    """The rows where any of `columns` contains `query` (any case)."""
    present = [c for c in columns if c in frame]
    if frame.empty or not present or not query.strip():
        return frame.iloc[0:0]
    needle = query.strip().lower()
    mask = pd.Series(False, index=frame.index)
    for c in present:
        mask |= frame[c].astype(str).str.lower().str.contains(needle, regex=False, na=False)
    return frame[mask]


def guide_hits(text: str, query: str, limit: int = 10) -> list[tuple[str, str]]:
    """(section, line) of the guide's lines containing `query`, the section being the
    nearest heading above."""
    needle = query.strip().lower()
    if not needle:
        return []
    out, section = [], ""
    for line in text.splitlines():
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        if needle in line.lower() and line.strip():
            out.append((section, line.strip()))
            if len(out) >= limit:
                break
    return out
