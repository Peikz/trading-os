"""Shared job runner for the scheduled slots (SPEC §3).

Fetches the universe once, runs every built scan for the slot, sends one ntfy message and
writes Parquet + xlsx to the private data repo. Prints counts and status only: the code
repo's Actions logs are public.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

from trading_os import clock, metrics, notify, store, tv, universe
from trading_os.config import load_config
from trading_os.logsafe import run_guarded, status
from trading_os.scans import run_scans


def parse_args(description: str, argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=os.environ.get("DATA_DIR"),
        help="checkout of trading-os-data (or env DATA_DIR)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="skip the time guard; output goes to data/manual/ and never counts as the session run",
    )
    parser.add_argument("--no-push", action="store_true", help="don't send the ntfy message")
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")
    return args


def run(slot: str, label: str, args: argparse.Namespace) -> int:
    cfg = load_config()
    now = dt.datetime.now(dt.UTC)

    if not args.force and not clock.in_window(cfg.schedule, slot, now):
        status(f"{label}: outside its New York window or day, nothing to do")
        return 0
    session = clock.session_date(cfg.schedule, slot, now)
    if not args.force and store.already_done(args.data_dir, session, slot):
        status(f"{label}: {session} already done, nothing to do")
        return 0

    topic = os.environ.get("NTFY_TOPIC", "")
    if not args.no_push and not topic:
        raise RuntimeError("NTFY_TOPIC is not set (use --no-push for local runs)")

    ctx = store.RunContext(
        session=session,
        slot=slot,
        run_ts=now,
        run_kind="scheduled" if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else "manual",
        forced=args.force,
    )
    status(f"{label}: session {session}, run_kind {ctx.run_kind}, forced {ctx.forced}")

    raw = tv.fetch_universe(cfg.universe, with_history=slot == "weekly")
    status(f"TradingView: {len(raw)} rows")
    df = metrics.add_phase1_metrics(raw, cfg.proxies)
    if slot == "weekly":
        df = metrics.add_growth_metrics(df)
    previous = clock.previous_session(cfg.schedule, session)
    df["earnings_flag"] = metrics.earnings_flag(df["earnings_date_last"], session, previous)
    uni = universe.build_universe(df, cfg.universe, slot)
    status(f"Universe: {len(uni)} logged tier, {(uni['tier'] == 'alert').sum()} alert tier")

    results = run_scans(uni, cfg, slot)
    selected = notify.select_for_push(results, cfg)
    pushed: dict[str, set[str]] = {}
    if args.no_push:
        status("Push: skipped (--no-push)")
    else:
        notify.send(cfg.notify["server"], topic, notify.build_message(ctx, results, selected, cfg))
        pushed = {name: set(hits["ticker"]) for name, hits in selected.items()}
        status("Push: sent")

    candidates = store.build_candidates(results, ctx, pushed)
    store.write_run(args.data_dir, ctx, uni, candidates)
    for name, hits in results.items():
        alert = int((hits["tier"] == "alert").sum()) if len(hits) else 0
        status(f"{notify.SCAN_LABELS.get(name, name)}: {len(hits)} hits ({alert} alert), saved")
    status(f"{label}: done")
    return 0


def main(slot: str, label: str, description: str, argv: list[str] | None = None) -> int:
    args = parse_args(description, argv)
    return run_guarded(lambda: run(slot, label, args), Path(args.data_dir) / "logs", label)
