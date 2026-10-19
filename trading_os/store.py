"""Append-only Parquet storage in the private data repo (SPEC §7).

Historical files are never rewritten: writing to an existing path raises. Scheduled runs write
to the canonical partitions; forced runs (manual tests) write under data/manual/ so the
canonical history holds real session runs only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SPEC_CANDIDATE_COLUMNS = [
    "signal_id",
    "run_ts",
    "session_date",
    "slot",
    "run_kind",
    "scan",
    "ticker",
    "rank",
    "tier",
    "pushed",
    "pivot",
    "order_stop",
    "risk_adr",
    "base_len",
    "contraction_depths",
    "b1",
    "b2",
    "b3",
    "b4",
    "b5",
    "notes",
]
# Values behind each hit, kept for audit (CLAUDE.md: store what a human might want to check).
AUDIT_COLUMNS = [
    "gap_pct",
    "chg_pct",
    "rvol50",
    "rvol_basis",
    "rvol10_tv",
    "volume",
    "dollar_volume",
    "close",
    "market_cap",
    "avg_volume_20d",
    "prev_volume",
    "close_loc",
    "ah_change_pct",
    "ah_volume",
    "above_ma10",
    "above_ma20",
    "above_ma50",
    "above_ma200",
    "earnings_flag",
]
_PHASE2_FLOAT = ["pivot", "order_stop", "risk_adr", "base_len"]
_PHASE2_BOOL = ["b1", "b2", "b3", "b4", "b5"]


class AlreadyWritten(FileExistsError):
    """Refusing to overwrite a historical file."""


@dataclass(frozen=True)
class RunContext:
    session: dt.date
    slot: str
    run_ts: dt.datetime  # UTC
    run_kind: str  # scheduled | manual
    forced: bool = False


def signal_id(session: dt.date, slot: str, scan: str, ticker: str) -> str:
    """Stable hash of (date, slot, scan, ticker)."""
    key = f"{session.isoformat()}|{slot}|{scan}|{ticker}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def run_paths(data_dir: Path, ctx: RunContext) -> dict[str, Path]:
    root = Path(data_dir) / "data"
    stem = f"{ctx.session.isoformat()}_{ctx.slot}"
    if ctx.forced:
        base = root / "manual" / f"{stem}_{ctx.run_ts:%H%M%S}"
        return {
            "universe": base / "universe.parquet",
            "candidates": base / "candidates.parquet",
            "export": base / "export.xlsx",
        }
    year = str(ctx.session.year)
    return {
        "universe": root / "universe" / year / f"{stem}.parquet",
        "candidates": root / "candidates" / year / f"{stem}.parquet",
        "export": root / "exports" / f"{stem}.xlsx",
    }


def already_done(data_dir: Path, session: dt.date, slot: str) -> bool:
    ctx = RunContext(session=session, slot=slot, run_ts=dt.datetime.now(dt.UTC), run_kind="")
    return any(path.exists() for path in run_paths(data_dir, ctx).values())


def stamp(df: pd.DataFrame, ctx: RunContext) -> pd.DataFrame:
    """Prefix run metadata columns (point-in-time: as known at run time)."""
    out = df.copy()
    meta = {
        "run_ts": pd.Timestamp(ctx.run_ts),
        "session_date": pd.Timestamp(ctx.session),
        "slot": ctx.slot,
        "run_kind": ctx.run_kind,
        "data_source": "tradingview",
    }
    for position, (name, value) in enumerate(meta.items()):
        out.insert(position, name, value)
    return out


def build_candidates(
    results: dict[str, pd.DataFrame],
    ctx: RunContext,
    pushed: dict[str, set[str]],
) -> pd.DataFrame:
    """One row per scan hit, in the SPEC §7 candidates layout plus audit columns."""
    frames = []
    for scan, hits in results.items():
        if hits.empty:
            continue
        sent = pushed.get(scan, set())
        rows = pd.DataFrame(
            {
                "signal_id": [signal_id(ctx.session, ctx.slot, scan, t) for t in hits["ticker"]],
                "scan": scan,
                "ticker": hits["ticker"].to_numpy(),
                "rank": hits["rank"].to_numpy(),
                "tier": hits["tier"].to_numpy(),
                "pushed": hits["ticker"].isin(sent).to_numpy(),
            }
        )
        for column in AUDIT_COLUMNS:
            rows[column] = hits[column].to_numpy() if column in hits else pd.NA
        frames.append(rows)
    if frames:
        out = pd.concat(frames, ignore_index=True)
    else:
        out = pd.DataFrame(
            columns=["signal_id", "scan", "ticker", "rank", "tier", "pushed", *AUDIT_COLUMNS]
        )
    # Breakout fields (Phase 2) stay empty for EP scans, so the schema is stable from day one.
    for column in _PHASE2_FLOAT:
        out[column] = pd.Series(pd.NA, index=out.index, dtype="Float64")
    for column in _PHASE2_BOOL:
        out[column] = pd.Series(pd.NA, index=out.index, dtype="boolean")
    for column in ("contraction_depths", "notes"):
        out[column] = pd.Series(pd.NA, index=out.index, dtype="string")
    out = stamp(out, ctx)
    ordered = [c for c in SPEC_CANDIDATE_COLUMNS if c in out.columns]
    return out[ordered + [c for c in out.columns if c not in ordered]]


def write_run(
    data_dir: Path, ctx: RunContext, universe: pd.DataFrame, candidates: pd.DataFrame
) -> dict[str, Path]:
    """Write universe, candidates and the xlsx export; never overwrite.

    Files are staged next to their targets and renamed at the end, candidates last, so a
    crash never leaves a half-written run that looks complete.
    """
    paths = run_paths(data_dir, ctx)
    for path in paths.values():
        if path.exists():
            raise AlreadyWritten(path.name)
    staged: list[tuple[Path, Path]] = []
    for key, writer in (
        ("universe", lambda p: stamp(universe, ctx).to_parquet(p, index=False)),
        ("export", lambda p: _write_export(candidates, p)),
        ("candidates", lambda p: candidates.to_parquet(p, index=False)),
    ):
        target = paths[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        writer(tmp)
        staged.append((tmp, target))
    for tmp, target in staged:
        tmp.rename(target)
    return paths


def _write_export(candidates: pd.DataFrame, path: Path) -> None:
    sheet = candidates.copy()
    for column in sheet.columns:
        if isinstance(sheet[column].dtype, pd.DatetimeTZDtype):
            sheet[column] = sheet[column].dt.tz_convert("UTC").dt.tz_localize(None)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="candidates", index=False)
