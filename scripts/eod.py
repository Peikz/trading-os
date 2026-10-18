"""End-of-day job (SPEC §3: 16:20 New York, 22:20 Copenhagen).

Fetches the universe once, runs every built EOD scan, writes Parquet + xlsx to the private
data repo and sends one ntfy message. Prints counts and status only: this repo's Actions logs
are public.

    uv run python scripts/eod.py --data-dir ../trading-os-data             # scheduled behaviour
    uv run python scripts/eod.py --data-dir ../trading-os-data --force --no-push   # manual test
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

SLOT = "eod"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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


def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    now = dt.datetime.now(dt.UTC)

    if not args.force and not clock.in_window(cfg.schedule, SLOT, now):
        status("EOD: outside the New York window or not a trading day, nothing to do")
        return 0
    session = clock.session_date(cfg.schedule, SLOT, now)
    if not args.force and store.already_done(args.data_dir, session, SLOT):
        status(f"EOD: {session} already done, nothing to do")
        return 0

    topic = os.environ.get("NTFY_TOPIC", "")
    if not args.no_push and not topic:
        raise RuntimeError("NTFY_TOPIC is not set (use --no-push for local runs)")

    ctx = store.RunContext(
        session=session,
        slot=SLOT,
        run_ts=now,
        run_kind="scheduled" if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else "manual",
        forced=args.force,
    )
    status(f"EOD: session {session}, run_kind {ctx.run_kind}, forced {ctx.forced}")

    raw = tv.fetch_universe(cfg.universe)
    status(f"TradingView: {len(raw)} rows")
    df = metrics.add_phase1_metrics(raw, cfg.proxies)
    previous = clock.previous_session(cfg.schedule, session)
    df["earnings_flag"] = metrics.earnings_flag(df["earnings_date_last"], session, previous)
    uni = universe.build_universe(df, cfg.universe, SLOT)
    status(f"Universe: {len(uni)} logged tier, {(uni['tier'] == 'alert').sum()} alert tier")

    results = run_scans(uni, cfg, SLOT)
    selected = notify.select_for_push(results, cfg)
    pushed: dict[str, set[str]] = {}
    if args.no_push:
        status("Push: skipped (--no-push)")
    else:
        notify.send(cfg.notify["server"], topic, notify.build_message(ctx, results, selected))
        pushed = {name: set(hits["ticker"]) for name, hits in selected.items()}
        status("Push: sent")

    candidates = store.build_candidates(results, ctx, pushed)
    store.write_run(args.data_dir, ctx, uni, candidates)
    for name, hits in results.items():
        alert = int((hits["tier"] == "alert").sum()) if len(hits) else 0
        status(f"{notify.SCAN_LABELS.get(name, name)}: {len(hits)} hits ({alert} alert), saved")
    status("EOD: done")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_guarded(lambda: run(args), Path(args.data_dir) / "logs", "EOD")


if __name__ == "__main__":
    raise SystemExit(main())
