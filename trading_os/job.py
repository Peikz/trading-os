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

import pandas as pd
import requests

from trading_os import (
    breadth,
    cats,
    charts,
    clock,
    enrich,
    epstudy,
    history,
    metrics,
    notify,
    outcomes,
    report,
    stats,
    store,
    tv,
    universe,
    watchlists,
)
from trading_os.config import load_config
from trading_os.history_metrics import LOOKBACK_SESSIONS
from trading_os.logsafe import run_guarded, status
from trading_os.retry import once_more
from trading_os.scans import run_scans

TV_RETRY_WAIT_S = 30
NTFY_RETRY_WAIT_S = 10


class PushFailed(RuntimeError):
    """ntfy could not be reached; the run's data was still saved."""


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

    raw = once_more(
        lambda: tv.fetch_universe(cfg.universe, with_history=slot == "weekly"),
        label="TradingView",
        wait_s=TV_RETRY_WAIT_S,
    )
    status(f"TradingView: {len(raw)} rows")
    df = metrics.add_phase1_metrics(raw, cfg.proxies)
    if slot == "weekly":
        df = metrics.add_growth_metrics(df)
    if slot in ("eod", "weekly"):
        df, covered = enrich.attach_history(df, args.data_dir, cfg, session)
        status(f"History: {covered} of {LOOKBACK_SESSIONS} sessions available")
    previous = clock.previous_session(cfg.schedule, session)
    df["earnings_flag"] = metrics.earnings_flag(df["earnings_date_last"], session, previous)
    uni = universe.build_universe(df, cfg.universe, slot)
    status(f"Universe: {len(uni)} logged tier, {(uni['tier'] == 'alert').sum()} alert tier")

    state = watchlists.current(watchlists.load_events(args.data_dir))
    for name in watchlists.LISTS:
        uni[f"on_{name}"] = uni["ticker"].isin(watchlists.active(state, name))
    results = run_scans(uni, cfg, slot)
    if slot == "weekly":
        results = _with_cats(results, args.data_dir, cfg, session)
    extras, header = _breadth_and_light(args.data_dir, cfg, session, slot, uni)
    if slot in ("pm", "eod"):
        events = watchlists.update(
            state,
            results,
            session,
            slot,
            lambda day: len(clock.sessions_after(cfg.schedule, day, 10_000, session)),
            cfg.watchlists,
        )
        if not events.empty:
            extras["watchlists"] = events
        status(f"Watchlists: {len(events)} events")
    selected = notify.select_for_push(results, cfg)
    pushed: dict[str, set[str]] = {}
    push_error: requests.RequestException | None = None
    if args.no_push:
        status("Push: skipped (--no-push)")
    else:
        message = notify.build_message(ctx, results, selected, cfg, header)
        try:
            once_more(
                lambda: notify.send(cfg.notify["server"], topic, message),
                label="ntfy",
                wait_s=NTFY_RETRY_WAIT_S,
            )
            pushed = {name: set(hits["ticker"]) for name, hits in selected.items()}
            status("Push: sent")
        except requests.RequestException as exc:
            push_error = exc
            status(f"Push: FAILED ({type(exc).__name__}), saving data anyway")

    candidates = store.build_candidates(results, ctx, pushed)
    store.write_run(args.data_dir, ctx, uni, candidates, extras)
    for name, hits in results.items():
        alert = int((hits["tier"] == "alert").sum()) if len(hits) else 0
        status(f"{notify.SCAN_LABELS.get(name, name)}: {len(hits)} hits ({alert} alert), saved")
    outputs = store.run_outputs(args.data_dir, ctx)
    drawn = {}
    if slot in ("eod", "pm") and any(len(h) for h in selected.values()):
        drawn = _charts(outputs["charts"], args.data_dir, cfg, session, slot, selected, df)
    _report(ctx, cfg, results, selected, header, drawn, outputs["report"])
    if slot == "weekly":
        _stats(args.data_dir, cfg, session, outputs["stats"])
    if slot == "eod" and not ctx.forced:
        _epstudy(cfg, candidates)
    if push_error is not None:
        raise PushFailed("ntfy unreachable after one retry; data saved") from push_error
    status(f"{label}: done")
    return 0


def _with_cats(results: dict, data_dir: Path, cfg, session) -> dict:
    """Add the CATS ranking column (SPEC §6.3) to the configured weekly lists."""
    rules = cfg.cats
    growth = set()
    for name in ("growth_bucket_1", "growth_bucket_2"):
        if name in results:
            growth |= set(results[name]["ticker"])
    window = clock.sessions_back(cfg.schedule, session, rules["recent_signal_sessions"])
    recent = cats.recent_signal_tickers(
        outcomes.load_candidates(data_dir), list(rules["recent_signal_scans"]), window
    )
    out = dict(results)
    for name in rules["apply_to"]:
        if name in out:
            out[name] = cats.add_cats(out[name], growth, recent, rules)
    return out


def _breadth_and_light(data_dir: Path, cfg, session, slot: str, uni: pd.DataFrame):
    """EOD: today's breadth row and the two push lines. Weekly: the Sunday scan count."""
    if slot == "weekly":
        count = breadth.scan_count(uni, cfg)
        field = cfg.market_light["scan_count"]["avg_volume_field"]
        status("Market Light scan count: saved")
        frame = pd.DataFrame([{"scan_count": count, "avg_volume_field": field}])
        return {"market_light_count": frame}, []
    if slot != "eod" or not cfg.scans["breadth"].enabled:
        return {}, []
    qqq = once_more(
        lambda: tv.fetch_quote(cfg.market_light["qqq"]["symbol"]),
        label="TradingView",
        wait_s=TV_RETRY_WAIT_S,
    )
    row = breadth.breadth_row(uni, qqq, cfg, data_dir, session)
    status(f"Breadth: saved ({row['ratio_days_available']} of 10 days for the ratios)")
    status("Market Light: " + ("computed" if row["light"] else "waiting for inputs"))
    return {"breadth": pd.DataFrame([row])}, breadth.push_lines(row)


def _epstudy(cfg, candidates: pd.DataFrame) -> None:
    """Phase 3 Breakout Log rows. Off unless configured; never fails the run."""
    conf = cfg.epstudy
    secret = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not conf["enabled"]:
        return
    if not conf["sheet_id"] or not secret:
        status("EPStudy: enabled but sheet_id or GOOGLE_SERVICE_ACCOUNT_JSON missing, skipped")
        return
    try:
        columns = list(conf["columns"])
        rows = epstudy.rows_for(candidates, conf["scans"], columns)
        http = epstudy.session_from_secret(secret)
        added = epstudy.append_new(http, conf["sheet_id"], conf["worksheet"], columns, rows)
        status(f"EPStudy: {added} rows appended")
    except Exception as exc:  # noqa: BLE001 - auxiliary; the data is already saved
        status(f"EPStudy: FAILED ({type(exc).__name__}), run data unaffected")


def _stats(data_dir: Path, cfg, session, path: Path) -> None:
    """Weekly outcome statistics. Auxiliary: a problem never fails the run."""
    try:
        found = stats.load_outcomes(data_dir)
        table = stats.summarize(outcomes.load_candidates(data_dir), found, cfg.stats["min_signals"])
        text = stats.to_markdown(table, session, len(found), cfg.stats["min_signals"])
        status("Stats: saved" if report.write(path, text) else "Stats: already exists")
    except Exception as exc:  # noqa: BLE001 - auxiliary; the data is already saved
        status(f"Stats: FAILED ({type(exc).__name__}), run data unaffected")


def _report(ctx, cfg, results, selected, header, drawn, path: Path) -> None:
    """The run's Markdown report. Like charts, a problem here never fails the run."""
    try:
        text = report.build(
            ctx, results, selected, header, drawn, path, cfg.report["max_rows_per_scan"]
        )
        status("Report: saved" if report.write(path, text) else "Report: already exists")
    except Exception as exc:  # noqa: BLE001 - auxiliary; the data is already saved
        status(f"Report: FAILED ({type(exc).__name__}), run data unaffected")


def _charts(charts_dir: Path, data_dir: Path, cfg, session, slot: str, selected, df) -> dict:
    """Before-shot PNGs for the pushed candidates. A chart problem never fails the run."""
    try:
        sessions = cfg.charts["sessions"] + max(charts.MA_COLORS)
        past = clock.sessions_back(cfg.schedule, session, sessions)
        bars = history.load_bars(data_dir, [s for s in past if s != session])
        if slot == "eod":  # today's bar is the run itself (not written to history yet)
            bars = pd.concat([bars, enrich.todays_bars(df, session)], ignore_index=True)
        drawn = charts.draw_for_run(
            charts_dir, session, slot, selected, bars, cfg.charts["sessions"]
        )
        status(f"Charts: {len(drawn)} saved")
        return drawn
    except Exception as exc:  # noqa: BLE001 - charts are auxiliary; the data is already saved
        status(f"Charts: FAILED ({type(exc).__name__}), run data unaffected")
        return {}


def main(slot: str, label: str, description: str, argv: list[str] | None = None) -> int:
    args = parse_args(description, argv)
    return run_guarded(lambda: run(slot, label, args), Path(args.data_dir) / "logs", label)
