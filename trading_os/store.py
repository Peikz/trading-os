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
    "rvol_at_time_tv",
    "rvol_base_volume",
    "proj_volume",
    "volume",
    "dollar_volume",
    "close",
    "market_cap",
    "avg_volume_20d",
    "prev_volume",
    "close_loc",
    "pm_change_pct",
    "pm_gap_pct",
    "pm_gap_used",
    "pm_volume",
    "pm_price",
    "pm_dollar_volume",
    "ah_change_pct",
    "ah_volume",
    "above_ma10",
    "above_ma20",
    "above_ma50",
    "above_ma200",
    "earnings_flag",
    "dist_ma10_adr",
    "adr20_pct",
    "avg_dollar_volume_20d",
    "ret_22",
    "ret_63",
    "ret_126",
    "qm_lists",
    "rev_growth_q",
    "rev_growth_q_prev",
    "eps_growth_q",
    "eps_growth_q_prev",
    "revenue_ttm",
    "growth_quarters_checked",
    "pct_from_52w_high",
    "hist_gain_max_pct",
    "hist_drop_max_pct",
    "hist_consec_up",
    "hist_consec_down",
    "hist_dist_ma10_adr",
    "hist_adr20_pct",
    "hist_adr20_usd",
    "hist_range_nd",
    "hist_avg_volume_short",
    "hist_avg_volume_long",
    "tightness_adr",
    "cats",
    "cats_growth",
    "cats_recent",
    "cats_volume",
    "cats_extension",
    "plan_entry",
    "plan_stop",
    "plan_stop_basis",
    "plan_shares",
    "plan_position_usd",
    "plan_risk_usd",
    "plan_capped",
    "plan_fx_rate",
    "ctx_done",
    "ctx_eps_surprise_pct",
    "ctx_rev_surprise_pct",
    "ctx_earnings_time",
    "ctx_perf_1y",
    "ctx_eps_growth_q",
    "ctx_eps_growth_q_prev",
    "ctx_rev_growth_q",
    "ctx_rev_growth_q_prev",
    "ctx_prior_6m_pct",
    "ctx_float_turnover",
    "ctx_news_title",
    "ctx_news_publisher",
    "ctx_news_time",
    "ctx_news_url",
]
_PHASE2_FLOAT = ["pivot", "order_stop", "risk_adr", "base_len"]
_PHASE2_BOOL = ["b1", "b2", "b3", "b4", "b5"]


# zstd keeps the data repo ~15 % smaller than the default snappy; readers need no change.
PARQUET_OPTIONS = {"index": False, "compression": "zstd", "compression_level": 9}


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


def run_paths(data_dir: Path, ctx: RunContext, extras: tuple[str, ...] = ()) -> dict[str, Path]:
    root = Path(data_dir) / "data"
    stem = f"{ctx.session.isoformat()}_{ctx.slot}"
    if ctx.forced:
        base = root / "manual" / f"{stem}_{ctx.run_ts:%H%M%S}"
        return {
            "universe": base / "universe.parquet",
            "candidates": base / "candidates.parquet",
            "export": base / "export.xlsx",
            **{name: base / f"{name}.parquet" for name in extras},
        }
    year = str(ctx.session.year)
    return {
        "universe": root / "universe" / year / f"{stem}.parquet",
        "candidates": root / "candidates" / year / f"{stem}.parquet",
        "export": root / "exports" / f"{stem}.xlsx",
        # Per-run tables (breadth, scan count, watchlist events): data/<name>/YYYY/<stem>.parquet
        **{name: root / name / year / f"{stem}.parquet" for name in extras},
    }


def run_outputs(data_dir: Path, ctx: RunContext) -> dict[str, Path]:
    """Chart folder and Markdown report for a run. Forced runs keep both in their manual
    folder, so tests never touch the session history."""
    stem = f"{ctx.session.isoformat()}_{ctx.slot}"
    if ctx.forced:
        base = Path(data_dir) / "data" / "manual" / f"{stem}_{ctx.run_ts:%H%M%S}"
        return {
            "charts": base / "charts",
            "report": base / "report.md",
            "stats": base / "stats.md",
        }
    year = str(ctx.session.year)
    return {
        "charts": Path(data_dir) / "data" / "charts" / year / stem,
        "report": Path(data_dir) / "reports" / year / f"{stem}.md",
        "stats": Path(data_dir) / "reports" / "stats" / year / f"{ctx.session.isoformat()}.md",
    }


def pushed_in(data_dir: Path, session: dt.date, slot: str) -> dict[str, set[str]]:
    """Tickers pushed per scan by the scheduled run of (session, slot); empty if none."""
    ctx = RunContext(session=session, slot=slot, run_ts=dt.datetime.now(dt.UTC), run_kind="")
    path = run_paths(data_dir, ctx)["candidates"]
    if not path.exists():
        return {}
    cands = pd.read_parquet(path, columns=["scan", "ticker", "pushed"])
    sent = cands[cands["pushed"].fillna(False).astype(bool)]
    return {scan: set(group["ticker"]) for scan, group in sent.groupby("scan")}


def already_done(data_dir: Path, session: dt.date, slot: str) -> bool:
    ctx = RunContext(session=session, slot=slot, run_ts=dt.datetime.now(dt.UTC), run_kind="")
    return any(path.exists() for path in run_paths(data_dir, ctx).values())


def stamp(df: pd.DataFrame, ctx: RunContext) -> pd.DataFrame:
    """Prefix run metadata columns (point-in-time: as known at run time)."""
    meta_columns = ("run_ts", "session_date", "slot", "run_kind", "data_source")
    out = df.drop(columns=[c for c in meta_columns if c in df.columns])
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
        for column in [*_PHASE2_FLOAT, *_PHASE2_BOOL, "contraction_depths"]:
            if column in hits:
                rows[column] = hits[column].to_numpy()
        for column in AUDIT_COLUMNS:
            rows[column] = hits[column].to_numpy() if column in hits else pd.NA
        frames.append(rows)
    if frames:
        out = pd.concat(frames, ignore_index=True)
    else:
        out = pd.DataFrame(
            columns=["signal_id", "scan", "ticker", "rank", "tier", "pushed", *AUDIT_COLUMNS]
        )
    for column in ("rank", "growth_quarters_checked"):
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")
    # Breakout fields (Phase 2) stay empty for EP scans, so the schema is stable from day one.
    for column, dtype in [
        *[(c, "Float64") for c in _PHASE2_FLOAT],
        *[(c, "boolean") for c in _PHASE2_BOOL],
        ("contraction_depths", "string"),
        ("notes", "string"),
    ]:
        values = out[column] if column in out else pd.Series(pd.NA, index=out.index)
        out[column] = values.astype("object").where(values.notna(), pd.NA).astype(dtype)
    out = stamp(out, ctx)
    ordered = [c for c in SPEC_CANDIDATE_COLUMNS if c in out.columns]
    return out[ordered + [c for c in out.columns if c not in ordered]]


def write_run(
    data_dir: Path,
    ctx: RunContext,
    universe: pd.DataFrame | None,
    candidates: pd.DataFrame,
    extras: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Path]:
    """Write universe, candidates and the xlsx export; never overwrite. Intraday runs pass
    no universe: two more full snapshots a day would double the data repo's growth.

    Files are staged next to their targets and renamed at the end, candidates last, so a
    crash never leaves a half-written run that looks complete.
    """
    extras = extras or {}
    paths = run_paths(data_dir, ctx, tuple(extras))
    if universe is None:
        paths.pop("universe")
    for path in paths.values():
        if path.exists():
            raise AlreadyWritten(path.name)
    staged: list[tuple[Path, Path]] = []
    writers = [] if universe is None else [("universe", _parquet_writer(stamp(universe, ctx)))]
    for key, writer in (
        *writers,
        ("export", lambda p: _write_export(candidates, p)),
        *[(name, _parquet_writer(stamp(frame, ctx))) for name, frame in extras.items()],
        ("candidates", lambda p: candidates.to_parquet(p, **PARQUET_OPTIONS)),
    ):
        target = paths[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        writer(tmp)
        staged.append((tmp, target))
    for tmp, target in staged:
        tmp.rename(target)
    return paths


def _parquet_writer(frame: pd.DataFrame):
    return lambda path: frame.to_parquet(path, **PARQUET_OPTIONS)


def _write_export(candidates: pd.DataFrame, path: Path) -> None:
    sheet = candidates.copy()
    for column in sheet.columns:
        if isinstance(sheet[column].dtype, pd.DatetimeTZDtype):
            sheet[column] = sheet[column].dt.tz_convert("UTC").dt.tz_localize(None)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="candidates", index=False)
