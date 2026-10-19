"""Massive grouped-daily backfill and daily catch-up (Phase 2). Resumable: sessions that
already have a bars file are skipped, newest missing sessions first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import requests

from trading_os import clock, history
from trading_os.config import Config, load_config
from trading_os.logsafe import run_guarded, status
from trading_os.massive import MassiveClient, RateLimiter


@dataclass(frozen=True)
class BackfillResult:
    fetched: int
    empty: int
    still_missing: int
    window: int


def missing_sessions(data_dir: Path, sessions: list[dt.date]) -> list[dt.date]:
    """Sessions without Massive bars, newest first."""
    return [s for s in reversed(sessions) if not history.have_bars(data_dir, "massive", s)]


def run_backfill(
    data_dir: Path, cfg: Config, client: MassiveClient, until: dt.date, max_calls: int
) -> BackfillResult:
    sessions = clock.sessions_back(cfg.schedule, until, cfg.history["backfill_sessions"])
    todo = missing_sessions(data_dir, sessions)
    fetched = empty = 0
    for session in todo[:max_calls]:
        bars = client.grouped_daily(session, adjusted=cfg.history["adjusted"])
        if bars.empty:  # not published yet: leave it for the next run
            empty += 1
            continue
        history.write_bars(data_dir, "massive", session, bars)
        fetched += 1
    return BackfillResult(fetched, empty, len(todo) - fetched, len(sessions))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Massive grouped-daily backfill")
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--max-calls", type=int, help="cap on API calls this run")
    group.add_argument(
        "--catchup", action="store_true", help="scheduled mode: config daily_catchup_calls"
    )
    group.add_argument(
        "--check", action="store_true", help="test the key on two sessions; writes nothing"
    )
    args = parser.parse_args(argv)
    if args.check:
        return run_guarded(_check, None, "Massive check")
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")
    return run_guarded(lambda: _run(args), Path(args.data_dir) / "logs", "Backfill")


def _check() -> int:
    """Fetch the latest session and the oldest in the backfill window; log counts only."""
    cfg = load_config()
    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        status("Massive check: MASSIVE_API_KEY not set")
        return 1
    client = MassiveClient(
        key, cfg.history["massive_base_url"], RateLimiter(cfg.history["calls_per_minute"])
    )
    latest = clock.session_date(cfg.schedule, "eod", dt.datetime.now(dt.UTC))
    oldest = clock.sessions_back(cfg.schedule, latest, cfg.history["backfill_sessions"])[0]
    failures = 0
    for label, session in (("latest session", latest), ("oldest backfill session", oldest)):
        try:
            bars = client.grouped_daily(session, adjusted=cfg.history["adjusted"])
            status(f"Massive check: {label} {session}: OK, {len(bars)} tickers")
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            status(f"Massive check: {label} {session}: HTTP {code}")
            failures += 1
    return 1 if failures else 0


def _run(args: argparse.Namespace) -> int:
    cfg = load_config()
    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        status("Backfill: MASSIVE_API_KEY not set, nothing to do")
        return 0
    if args.catchup:
        max_calls = cfg.history["daily_catchup_calls"]
    else:
        max_calls = args.max_calls or cfg.history["backfill_sessions"]
    until = clock.session_date(cfg.schedule, "eod", dt.datetime.now(dt.UTC))
    limiter = RateLimiter(cfg.history["calls_per_minute"])
    client = MassiveClient(key, cfg.history["massive_base_url"], limiter)
    result = run_backfill(args.data_dir, cfg, client, until, max_calls)
    status(
        f"Backfill: {result.fetched} sessions fetched, {result.empty} not published yet, "
        f"{result.still_missing} of {result.window} still missing"
    )
    return 0
