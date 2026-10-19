"""Outcomes of past signals (SPEC §7, Phase 3). Never edits candidates.

For every (signal, horizon) that has matured, written exactly once:
- entry: the signal session's close for EOD and weekly signals, its open for pre-market ones
  (a pre-market alert can be acted on at the open).
- window: the `horizon` sessions after the signal session (pre-market: starting with it).
- max_gain_pct / max_drawdown_pct: highest high / lowest low in the window vs entry.
- close_ret_pct: the window's last close vs entry.
- hit_order_stop, r_hypothetical: only when the candidate has an order stop (breakouts).

A window with a missing bar is not written yet; it may complete once Massive history covers it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import clock, history
from trading_os.config import INTRADAY_SLOTS, load_config
from trading_os.logsafe import run_guarded, status
from trading_os.store import PARQUET_OPTIONS, AlreadyWritten

OUTCOME_COLUMNS = [
    "signal_id",
    "horizon",
    "scan",
    "ticker",
    "session_date",
    "slot",
    "entry_price",
    "entry_basis",
    "max_gain_pct",
    "max_drawdown_pct",
    "close_ret_pct",
    "hit_order_stop",
    "r_hypothetical",
    "bars_source",
    "computed_ts",
]


def outcomes_path(data_dir: Path, run_session: dt.date) -> Path:
    return (
        Path(data_dir)
        / "data"
        / "outcomes"
        / str(run_session.year)
        / f"{run_session.isoformat()}.parquet"
    )


def load_candidates(data_dir: Path) -> pd.DataFrame:
    """Canonical (session-history) candidates; manual test runs are not signals."""
    files = sorted((Path(data_dir) / "data" / "candidates").glob("*/*.parquet"))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_parquet(f) for f in files]
    out = pd.concat(frames, ignore_index=True)
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out


def done_pairs(data_dir: Path) -> set[tuple[str, int]]:
    files = (Path(data_dir) / "data" / "outcomes").glob("*/*.parquet")
    pairs: set[tuple[str, int]] = set()
    for f in files:
        done = pd.read_parquet(f, columns=["signal_id", "horizon"])
        pairs.update(zip(done["signal_id"], done["horizon"].astype(int), strict=True))
    return pairs


def compute_outcomes(
    candidates: pd.DataFrame,
    bars: pd.DataFrame,
    horizons: Iterable[int],
    window_sessions: Callable[[dt.date, str, int], list[dt.date]],
    done: set[tuple[str, int]],
    computed_ts: pd.Timestamp,
) -> pd.DataFrame:
    """Matured, not-yet-written outcomes. `window_sessions(signal_session, slot, n)` returns
    the window's sessions that have closed so far (fewer than n means not matured)."""
    by_key = bars.set_index(["ticker", "session_date"]).sort_index()
    rows = []
    for cand in candidates.drop_duplicates("signal_id").to_dict("records"):
        for horizon in horizons:
            if (cand["signal_id"], horizon) in done:
                continue
            row = _one(cand, horizon, by_key, window_sessions, computed_ts)
            if row is not None:
                rows.append(row)
    if not rows:
        return pd.DataFrame(columns=OUTCOME_COLUMNS)
    out = pd.DataFrame(rows, columns=OUTCOME_COLUMNS)
    out["horizon"] = out["horizon"].astype(int)
    out["hit_order_stop"] = out["hit_order_stop"].astype("boolean")
    return out


def _one(cand, horizon, by_key, window_sessions, computed_ts):
    ticker, signal_day, slot = cand["ticker"], cand["session_date"], cand["slot"]
    window = window_sessions(signal_day, slot, horizon)
    if len(window) < horizon:
        return None  # not matured
    try:
        entry_bar = by_key.loc[(ticker, signal_day)]
        span = by_key.loc[[(ticker, s) for s in window]]
    except KeyError:
        return None  # a bar is missing; maybe later
    if slot in INTRADAY_SLOTS:  # bought during the session: entry at the price the run saw
        entry_basis, entry = "signal", float(cand.get("close", np.nan))
    else:
        entry_basis = "open" if slot == "pm" else "close"
        entry = float(entry_bar[entry_basis])
    if not entry > 0 or span[["high", "low", "close"]].isna().any().any():
        return None
    stop = cand.get("order_stop")
    stop = float(stop) if stop is not None and not pd.isna(stop) else np.nan
    last_close = float(span["close"].iloc[-1])
    has_stop = not np.isnan(stop) and stop < entry
    return {
        "signal_id": cand["signal_id"],
        "horizon": horizon,
        "scan": cand["scan"],
        "ticker": ticker,
        "session_date": signal_day,
        "slot": slot,
        "entry_price": entry,
        "entry_basis": entry_basis,
        "max_gain_pct": (float(span["high"].max()) / entry - 1) * 100,
        "max_drawdown_pct": (float(span["low"].min()) / entry - 1) * 100,
        "close_ret_pct": (last_close / entry - 1) * 100,
        "hit_order_stop": bool((span["low"] <= stop).any()) if has_stop else pd.NA,
        "r_hypothetical": (last_close - entry) / (entry - stop) if has_stop else np.nan,
        "bars_source": ",".join(sorted(set(span["source"]) | {entry_bar["source"]})),
        "computed_ts": computed_ts,
    }


def write_outcomes(data_dir: Path, run_session: dt.date, outcomes: pd.DataFrame) -> Path:
    path = outcomes_path(data_dir, run_session)
    if path.exists():
        raise AlreadyWritten(path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    outcomes.to_parquet(tmp, **PARQUET_OPTIONS)
    tmp.rename(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outcomes of past signals (Phase 3)")
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    parser.add_argument("--force", action="store_true", help="skip the trading-day guard")
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")

    return run_guarded(lambda: _run(args), Path(args.data_dir) / "logs", "Outcomes")


def _run(args: argparse.Namespace) -> int:
    cfg = load_config()
    now = dt.datetime.now(dt.UTC)
    run_session = clock.session_date(cfg.schedule, "eod", now)
    if not args.force and run_session != clock.ny_time(cfg.schedule, now).date():
        status("Outcomes: today's session hasn't closed or isn't a trading day, nothing to do")
        return 0
    if outcomes_path(args.data_dir, run_session).exists():
        status(f"Outcomes: {run_session} already done, nothing to do")
        return 0
    candidates = load_candidates(args.data_dir)
    if candidates.empty:
        status("Outcomes: no signals yet")
        return 0

    horizons = list(cfg.outcomes["horizons"])
    # Enough sessions to cover the longest window plus slack for late-arriving bars.
    sessions = clock.sessions_back(cfg.schedule, run_session, max(horizons) + 70)
    bars = history.load_bars(args.data_dir, sessions)

    def window(signal: dt.date, slot: str, n: int) -> list[dt.date]:
        if slot == "pm":
            return [signal, *clock.sessions_after(cfg.schedule, signal, n - 1, run_session)]
        return clock.sessions_after(cfg.schedule, signal, n, run_session)

    out = compute_outcomes(
        candidates, bars, horizons, window, done_pairs(args.data_dir), pd.Timestamp(now)
    )
    if out.empty:
        status(f"Outcomes: nothing matured ({candidates['signal_id'].nunique()} signals tracked)")
        return 0
    write_outcomes(args.data_dir, run_session, out)
    per_horizon = ", ".join(
        f"{h}d: {n}" for h, n in out["horizon"].value_counts().sort_index().items()
    )
    status(f"Outcomes: {len(out)} written ({per_horizon})")
    return 0
