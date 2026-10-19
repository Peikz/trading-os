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
    context,
    enrich,
    epstudy,
    history,
    industries,
    metrics,
    notify,
    outcomes,
    report,
    sizing,
    stats,
    store,
    tv,
    universe,
    watchlists,
)
from trading_os.config import INTRADAY_SLOTS, load_config
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
        df = metrics.prefer_history(df)
        exact = int((df["rvol_basis"] == "history_50d_excl_today").sum())
        status(f"History: {covered} of {LOOKBACK_SESSIONS} sessions; exact RVOL on {exact} rows")
    previous = clock.previous_session(cfg.schedule, session)
    df["earnings_flag"] = metrics.earnings_flag(df["earnings_date_last"], session, previous)
    uni = universe.build_universe(df, cfg.universe, slot)
    status(f"Universe: {len(uni)} logged tier, {(uni['tier'] == 'alert').sum()} alert tier")
    uni, ranked_industries = _with_market_facts(uni, cfg, session)

    state = watchlists.current(watchlists.load_events(args.data_dir))
    for name in watchlists.LISTS:
        uni[f"on_{name}"] = uni["ticker"].isin(watchlists.active(state, name))
    if slot in INTRADAY_SLOTS and cfg.scans["pivot_watch"].enabled:
        uni = _with_breakout_levels(uni, args.data_dir, cfg, state, session)
    results = run_scans(uni, cfg, slot)
    if slot == "weekly":
        results = _with_cats(results, args.data_dir, cfg, session)
    extras, header = _breadth_and_light(args.data_dir, cfg, session, slot, uni)
    if slot in ("eod", "weekly") and not ranked_industries.empty:
        extras["industries"] = ranked_industries
    if slot == "weekly":
        header = [*header, *industries.lines(ranked_industries, cfg.context["industry_top_n"])]
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
    results = _with_sizing(results, args.data_dir, cfg)
    selected = notify.select_for_push(results, cfg)
    if slot == "mid":
        selected = _not_pushed_earlier(selected, args.data_dir, session, "am")
    results, selected = _with_context(results, selected, cfg, session)
    pushed: dict[str, set[str]] = {}
    push_error: requests.RequestException | None = None
    if args.no_push:
        status("Push: skipped (--no-push)")
    else:
        report_path = store.run_outputs(args.data_dir, ctx)["report"]
        link = notify.report_url(cfg, report_path.relative_to(args.data_dir).as_posix())
        message = notify.build_message(ctx, results, selected, cfg, header, click=link)
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
    snapshot = None if slot in INTRADAY_SLOTS else uni
    store.write_run(args.data_dir, ctx, snapshot, candidates, extras)
    for name, hits in results.items():
        alert = int((hits["tier"] == "alert").sum()) if len(hits) else 0
        status(f"{notify.SCAN_LABELS.get(name, name)}: {len(hits)} hits ({alert} alert), saved")
    outputs = store.run_outputs(args.data_dir, ctx)
    drawn = {}
    if slot in ("eod", "pm", *INTRADAY_SLOTS) and any(len(h) for h in selected.values()):
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


def _with_market_facts(uni: pd.DataFrame, cfg, session) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-stock facts for the alert lines: RS percentile, industry rank, sessions to the next
    earnings. Auxiliary: a problem here leaves them blank and never fails the run."""
    try:
        out = uni.copy()
        windows = [int(d) for d in cfg.proxies["returns"]]
        out["rs_pct"] = metrics.rs_percentile(out, windows)
        next_day = metrics.ny_dates(out["earnings_date_next"])
        out["earnings_in_sessions"] = clock.sessions_until(cfg.schedule, session, next_day)
        out["earnings_soon"] = out["earnings_in_sessions"] <= cfg.context["earnings_soon_sessions"]
        table = industries.rank(out, cfg)
        out = industries.add_rank(out, table)
        status(f"Industries: {len(table)} ranked")
        return out, table
    except Exception as exc:  # noqa: BLE001 - facts only; scans and alerts don't need them
        status(f"Industries: FAILED ({type(exc).__name__}), facts without ranks")
        return uni, pd.DataFrame(columns=industries.COLUMNS)


def _with_breakout_levels(uni: pd.DataFrame, data_dir: Path, cfg, state, session) -> pd.DataFrame:
    """Pivot and order stop of the active BO-Watch names, from their latest EOD row."""
    names = watchlists.active(state, "bo_watch")
    max_runs = cfg.watchlists["bo_watch_stale_sessions"] + 1
    levels = store.breakout_levels(data_dir, session, names, max_runs)
    status(f"BO levels: {len(levels)} of {len(names)} BO-Watch names have a pivot")
    out = uni.drop(columns=[c for c in levels.columns if c != "ticker" and c in uni])
    return out.merge(levels, on="ticker", how="left")


def _index_quotes(cfg) -> dict:
    """SPY, QQQ (Nasdaq 100) and VIX for the market header. Auxiliary: a missing quote just
    drops its part of the line."""
    symbols = {
        "spy": cfg.context["spy_symbol"],
        "qqq": cfg.market_light["qqq"]["symbol"],
        "vix": cfg.context["vix_symbol"],
    }
    quotes = {}
    for name, symbol in symbols.items():
        try:
            quotes[name] = once_more(
                lambda s=symbol: tv.fetch_index(s),
                label="TradingView",
                wait_s=TV_RETRY_WAIT_S,
            )
        except Exception as exc:  # noqa: BLE001 - header extra only
            status(f"{name.upper()} quote: FAILED ({type(exc).__name__})")
    return quotes


def _not_pushed_earlier(selected: dict, data_dir: Path, session, slot: str) -> dict:
    """A name goes out once per session: drop what the earlier intraday run already pushed."""
    earlier = store.pushed_in(data_dir, session, slot)
    out = {n: hits[~hits["ticker"].isin(earlier.get(n, set()))] for n, hits in selected.items()}
    repeats = sum(len(selected[n]) - len(out[n]) for n in selected)
    status(f"Push: {repeats} already sent at 10:15, skipped")
    return out


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


def _with_context(results: dict, selected: dict, cfg, session) -> tuple[dict, dict]:
    """Facts behind the top pushed EPs and breakouts. Auxiliary: never fails the run."""
    conf = cfg.context
    names = [
        n
        for n, hits in selected.items()
        if n in (*context.EP_SCANS, *context.BREAKOUT_SCANS) and len(hits)
    ]
    if not names:
        return results, selected
    try:
        tops = {
            n: selected[n][~notify.partial_rows(selected[n])].head(conf["max_per_scan"])
            for n in names
        }
        tops = {n: top for n, top in tops.items() if len(top)}
        symbols = sorted({t for top in tops.values() for t in top.get("tv_ticker", [])})
        details = once_more(
            lambda: tv.fetch_details(symbols, list(context.DETAIL_FIELDS)),
            label="TradingView",
            wait_s=TV_RETRY_WAIT_S,
        )
        details = context.growth_columns(details.rename(columns=context.DETAIL_FIELDS))
        news = _news_lookup(cfg, session)
        out_results, out_selected = dict(results), dict(selected)
        for name, top in tops.items():
            facts = context.add_context(
                top,
                details,
                news if name in context.EP_SCANS else None,
                premarket=name in context.PREMARKET_SCANS,
            )
            extra = [c for c in (*context.CONTEXT_COLUMNS, "ctx_done") if c in facts]
            by_ticker = facts.set_index("ticker")[extra]
            for frame_map in (out_results, out_selected):
                frame = frame_map[name]
                for column in extra:
                    frame = frame.assign(**{column: frame["ticker"].map(by_ticker[column])})
                frame_map[name] = frame
        status("Context: added")
        return out_results, out_selected
    except Exception as exc:  # noqa: BLE001 - alerts still go out, just without the facts
        status(f"Context: FAILED ({type(exc).__name__}), alerts sent without it")
        return results, selected


def _news_lookup(cfg, session):
    """Latest fresh headline per ticker from Massive, capped per run; None without a key."""
    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        return None
    from trading_os.massive import MassiveClient, RateLimiter

    client = MassiveClient(
        key, cfg.history["massive_base_url"], RateLimiter(cfg.history["calls_per_minute"])
    )
    conf, cache = cfg.context, {}
    # Back to the start of the previous session day (ET) at least, so a Monday run still
    # sees Friday's after-close news.
    previous = clock.previous_session(cfg.schedule, session)
    since_previous = pd.Timestamp(previous).tz_localize(cfg.schedule.timezone)
    recent = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=conf["news_max_age_hours"])
    cutoff = min(recent, since_previous)

    def lookup(ticker: str):
        if ticker in cache:
            return cache[ticker]
        if len(cache) >= conf["news_max_tickers"]:
            return None
        try:
            items = client.news(ticker, limit=3)
        except requests.RequestException:
            items = []
        fresh = [
            i
            for i in items
            if i.get("published_utc") and pd.Timestamp(i["published_utc"]) >= cutoff
        ]
        cache[ticker] = fresh[0] if fresh else None
        return cache[ticker]

    return lookup


def _with_sizing(results: dict, data_dir: Path, cfg) -> dict:
    """Entry / stop / shares for every hit of the scans with a rule. The account is private
    (data repo settings/account.yaml) and no amount is ever printed."""
    account = sizing.load_account(data_dir)
    if account is None:
        status("Sizing: no settings/account.yaml in the data repo, skipped")
        return results
    rate = 1.0
    if account.currency != "USD":
        symbol = cfg.sizing["fx_symbol"].format(currency=account.currency)
        try:
            rate = once_more(
                lambda: tv.fetch_fx(symbol), label="TradingView", wait_s=TV_RETRY_WAIT_S
            )
        except Exception as exc:  # noqa: BLE001 - alerts still go out, just without sizes
            status(f"Sizing: FAILED to get the exchange rate ({type(exc).__name__}), skipped")
            return results
    planned = sizing.add_plans(results, cfg.sizing, account, rate)
    for name, hits in planned.items():
        if "plan_shares" in hits:
            planned[name] = hits.assign(plan_fx_rate=rate)
    status("Sizing: added")
    return planned


def _breadth_and_light(data_dir: Path, cfg, session, slot: str, uni: pd.DataFrame):
    """EOD: today's breadth row and push lines. Pre-market: the light for today, last close's
    breadth and the pre-market movers. Weekly: the Sunday scan count."""
    if slot == "weekly":
        count = breadth.scan_count(uni, cfg)
        field = cfg.market_light["scan_count"]["avg_volume_field"]
        status("Market Light scan count: saved")
        frame = pd.DataFrame([{"scan_count": count, "avg_volume_field": field}])
        return {"market_light_count": frame}, []
    if slot not in ("eod", "pm") or not cfg.scans["breadth"].enabled:
        return {}, []
    qqq = once_more(
        lambda: tv.fetch_quote(cfg.market_light["qqq"]["symbol"]),
        label="TradingView",
        wait_s=TV_RETRY_WAIT_S,
    )
    indexes = breadth.index_fields(_index_quotes(cfg))
    if slot == "pm":
        last = breadth.latest_eod_row(data_dir, session)
        pm_row = {**breadth.premarket_row(uni, qqq, cfg, session, last), **indexes}
        status("Pre-market breadth: saved")
        return {"breadth_pm": pd.DataFrame([pm_row])}, breadth.premarket_lines(pm_row, last)
    row = {**breadth.breadth_row(uni, qqq, cfg, data_dir, session), **indexes}
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
        if slot in ("eod", *INTRADAY_SLOTS):  # today's bar comes from this run
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
