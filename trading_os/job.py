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
    heat,
    history,
    ibd,
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


def run_kind() -> str:
    """scheduled: started by GitHub's cron or by the cron-job.org timer (the workflow's
    `timer` input sets RUN_TRIGGER); manual: started by hand."""
    timed = os.environ.get("RUN_TRIGGER") == "timer"
    return "scheduled" if timed or os.environ.get("GITHUB_EVENT_NAME") == "schedule" else "manual"


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
        run_kind=run_kind(),
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
    if slot == "ah":  # after hours: a release today, the evening the move happens
        df["earnings_flag"] = metrics.earnings_today(
            df["earnings_date_last"], df["earnings_date_next"], session
        )
    uni = universe.build_universe(df, cfg.universe, slot)
    status(f"Universe: {len(uni)} logged tier, {(uni['tier'] == 'alert').sum()} alert tier")
    uni, ranked_industries = _with_market_facts(uni, cfg, session)
    if slot == "eod" and (cfg.scans["luk_flush"].enabled or cfg.scans["luk_pullback"].enabled):
        uni = _with_luk(uni, args.data_dir, cfg, session)
    if slot == "eod" and (cfg.scans["vcp"].enabled or cfg.scans["minervini_tt"].enabled):
        uni = _with_minervini(uni, args.data_dir, cfg, session)
    if slot == "eod" and cfg.scans["ma_surf"].enabled:
        uni = _with_surf(uni, args.data_dir, cfg, session)

    state = watchlists.current(watchlists.load_events(args.data_dir))
    for name in watchlists.LISTS:
        uni[f"on_{name}"] = uni["ticker"].isin(watchlists.active(state, name))
    if slot in INTRADAY_SLOTS and cfg.scans["pivot_watch"].enabled:
        uni = _with_breakout_levels(uni, args.data_dir, cfg, state, session)
    results = run_scans(uni, cfg, slot)
    if slot == "weekly":
        results = _with_cats(results, args.data_dir, cfg, session)
    extras, header, push_head = _breadth_and_light(args.data_dir, cfg, session, slot, uni)
    if slot in ("eod", "weekly") and not ranked_industries.empty:
        extras["industries"] = ranked_industries
    if slot == "eod":
        sector_table = _sectors()
        if not sector_table.empty:
            extras["sectors"] = sector_table
    if slot == "weekly":
        header = [*header, *industries.lines(ranked_industries, cfg.context["industry_top_n"])]
    if slot in ("pm", "eod"):
        header = [*header, *_position_lines(args.data_dir, cfg, session, slot, uni)]
    if slot == "eod":
        health_line = _job_health(cfg)
        header = [*header, *health_line]
        # the push names a job problem only (Emil, 23 Oct 2026: market head, then the stocks)
        push_head = [*push_head, *(x for x in health_line if not x.startswith("🩺 All"))]
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
    results = _with_grades(results, args.data_dir, cfg, session, slot, extras, df)
    results = _with_short_interest(results, args.data_dir, cfg, session)
    results = _with_heat_tags(results, args.data_dir, session)
    ibd_info = _ibd_state(args.data_dir, session, slot, extras)
    results = _with_ibd(results, ibd_info)
    if slot in ("pm", "eod"):  # the report only: the push stays market head + stocks
        header = [*header, *ibd.line(ibd_info)]
    if slot == "am":
        results = _flagged_last_evening(results, args.data_dir, cfg, session)
    selected = notify.select_for_push(results, cfg, slot)
    carried = _from_last_close(args.data_dir, cfg, session, uni) if slot == "pm" else {}
    if carried:
        selected.update(notify.select_for_push(carried, cfg, slot))
    if slot == "mid":
        selected = _not_pushed_earlier(selected, args.data_dir, session, "am")
    # Last close's hits go into the message and report only; this run saves its own.
    shown, selected = _with_context({**results, **carried}, selected, cfg, session)
    results = {name: shown[name] for name in results}
    pushed: dict[str, set[str]] = {}
    push_error: requests.RequestException | None = None
    if args.no_push:
        status("Push: skipped (--no-push)")
    else:
        report_path = store.run_outputs(args.data_dir, ctx)["report"]
        link = notify.report_url(cfg, report_path.relative_to(args.data_dir).as_posix())
        message = notify.build_message(ctx, shown, selected, cfg, push_head, click=link)
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
    _report(ctx, cfg, shown, selected, header, drawn, outputs["report"])
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


def _with_luk(uni: pd.DataFrame, data_dir: Path, cfg, session) -> pd.DataFrame:
    """Martin Luk's AVWAP flush flags (EOD). A problem leaves the scan empty, never fails."""
    from trading_os import luk_live

    try:
        out = luk_live.attach(uni, data_dir, cfg, session)
        status(f"Luk flush: {int(out['luk_flush'].sum())} flagged")
        return out
    except Exception as exc:  # noqa: BLE001 - one scan's inputs; the run goes on
        status(f"Luk flush: FAILED ({type(exc).__name__}), scan empty")
        return uni


def _sectors() -> pd.DataFrame:
    """Indexes, sectors and themes (`sectors.py`) in one TradingView request, for the
    dashboard's Market page. Auxiliary: never fails the run."""
    from trading_os import sectors

    try:
        table = once_more(
            lambda: sectors.fetch(tv.fetch_details), label="TradingView", wait_s=TV_RETRY_WAIT_S
        )
        status(f"Sectors: {len(table)} of {len(sectors.ETFS)} saved")
        return table
    except Exception as exc:  # noqa: BLE001 - the Market page shows the last saved day
        status(f"Sectors: FAILED ({type(exc).__name__}), left out")
        return pd.DataFrame()


def _job_health(cfg) -> list[str]:
    """One line on the timed jobs since yesterday (on time, late, missed, failed), from GitHub's
    run list (needs GH_TOKEN in Actions). Auxiliary: never fails the run."""
    from trading_os import health, timer

    try:
        runs = health.run_list(100)
        if runs.empty:
            return []
        line = timer.health_line(runs, cfg.schedule.windows_et, dt.datetime.now(dt.UTC))
        status("Job check: " + ("all on time" if line.startswith("🩺 All") else "issues found"))
        return [line]
    except Exception as exc:  # noqa: BLE001 - the push goes out without the line
        status(f"Job check: FAILED ({type(exc).__name__}), left out")
        return []


def _position_lines(data_dir: Path, cfg, session, slot: str, uni: pd.DataFrame) -> list[str]:
    """The position manager's block (`manage.py`): each open position's plan, day k of N, the
    day's exits, 20-day MA closes, earnings, R and risk. Auxiliary: never fails the run."""
    from trading_os import dashboard, manage, saxo

    try:
        positions = dashboard.latest_positions(data_dir)
        if positions.empty:
            return []
        # Your working stop orders at Saxo win over the logged stop (scripts/saxo_sync.py).
        positions = saxo.with_broker_stops(positions, saxo.latest_stops(data_dir))
        if slot == "eod":
            market = uni
        else:
            last = clock.previous_session(cfg.schedule, session)
            path = history.universe_snapshot_path(data_dir, last)
            market = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["ticker"])
        today = dt.date.today() + dt.timedelta(days=30)
        sessions = [
            *clock.sessions_back(cfg.schedule, session, 400),
            *clock.sessions_after(cfg.schedule, session, 10, today),
        ]
        table = manage.review(positions, market, session, sessions, cfg.grading, slot)
        status(f"Positions: {len(table)} open, {int(table['action'].ne('').sum())} with an action")
        return manage.push_lines(table)
    except Exception as exc:  # noqa: BLE001 - the push goes out without the block
        status(f"Positions: FAILED ({type(exc).__name__}), left out")
        return []


def _from_last_close(data_dir: Path, cfg, session, uni: pd.DataFrame) -> dict:
    """Pre-market: the last session's hits of the scans that push now (`push_slot: pm`:
    BO-Watch, MA-surf, the parabolics, Luk flush from the EOD run; EP-AH from the after-hours
    check, Emil 23 Oct 2026), with today's pre-market price and move, so they arrive before the
    open. `carried_from` is the run they came from. Auxiliary: a problem leaves them out, never
    fails the run."""
    names = [
        name
        for name, scan in cfg.scans.items()
        if scan.enabled
        and scan.action == "push"
        and isinstance(scan.slot, str)
        and scan.slot != "pm"
        and "pm" in notify.push_slots(scan)
    ]
    if not names:
        return {}
    try:
        last = clock.previous_session(cfg.schedule, session)
        folder = Path(data_dir) / "data" / "candidates" / str(last.year)
        fields = [c for c in ("pm_price", "pm_change_pct", "pm_volume") if c in uni]
        pm = uni.drop_duplicates("ticker").set_index("ticker")[fields]
        runs, out = {}, {}
        for name in names:
            slot = cfg.scans[name].slot
            if slot not in runs:
                path = folder / f"{last}_{slot}.parquet"
                runs[slot] = pd.read_parquet(path) if path.exists() else None
            if runs[slot] is None:
                continue
            rows = runs[slot][runs[slot]["scan"] == name]
            rows = rows.drop(columns=fields, errors="ignore").join(pm, on="ticker")
            out[name] = rows.assign(carried_from=slot).reset_index(drop=True)
        if not out:
            status("Last close's watch: no run to carry over")
            return {}
        status("Last close's watch: " + ", ".join(f"{n} {len(h)}" for n, h in out.items()))
        return out
    except Exception as exc:  # noqa: BLE001 - extra lines in the push; the run goes on
        status(f"Last close's watch: FAILED ({type(exc).__name__}), left out")
        return {}


def _with_short_interest(results: dict, data_dir: Path, cfg, session) -> dict:
    """Days to cover on every hit; A+/A heavily shorted become C (`short_interest`).
    Auxiliary: hits go out as they were on a problem."""
    from trading_os import short_interest

    dtc_max = cfg.grading.get("heavily_shorted_dtc")
    if not cfg.grading["enabled"] or not dtc_max or not any(len(h) for h in results.values()):
        return results
    try:
        table = short_interest.latest(data_dir, session)
        out = short_interest.attach(results, table, float(dtc_max))
        n = sum(int(h["si_tag"].notna().sum()) for h in out.values() if "si_tag" in h)
        status(f"Short interest: {n} hits heavily shorted")
        return out
    except Exception as exc:  # noqa: BLE001
        status(f"Short interest: FAILED ({type(exc).__name__}), left out")
        return results


def _ibd_state(data_dir: Path, session, slot: str, extras: dict) -> dict | None:
    """The IBD market state (`ibd`) at the last SPY close: today's at EOD (its breadth row is
    in `extras`, not written yet), else the last stored one before `session`. Tracked, not a
    rule. Auxiliary: None on a problem."""
    try:
        if slot == "eod" and "breadth" in extras and len(extras["breadth"]):
            return ibd.state_at(data_dir, session, extras["breadth"].iloc[0].to_dict())
        return ibd.state_at(data_dir, session - dt.timedelta(days=1))
    except Exception as exc:  # noqa: BLE001
        status(f"IBD state: FAILED ({type(exc).__name__}), left out")
        return None


def _with_ibd(results: dict, info: dict | None) -> dict:
    """`ibd_state`, `ibd_dist` and `ibd_tag` on every hit, for the live check's split."""
    if not info:
        return results
    text = ibd.tag(info)
    return {
        name: hits.assign(ibd_state=info["state"], ibd_dist=info["dist_count"], ibd_tag=text)
        if len(hits)
        else hits
        for name, hits in results.items()
    }


def _with_heat_tags(results: dict, data_dir: Path, session) -> dict:
    """Each hit's heat tag (`heat.tag`): how its setup did at the latest Sunday scan count's
    heat. Auxiliary: hits go out without it on a problem."""
    try:
        stats = heat.load(data_dir)
        count, _ = breadth.latest_scan_count(data_dir, session)
        if not stats or count is None:
            return results
        out = dict(results)
        for name, hits in results.items():
            text = heat.tag(stats, count, name)
            if text and len(hits):
                out[name] = hits.assign(heat_tag=text)
        return out
    except Exception as exc:  # noqa: BLE001
        status(f"Heat tags: FAILED ({type(exc).__name__}), left out")
        return results


def _with_minervini(uni: pd.DataFrame, data_dir: Path, cfg, session) -> pd.DataFrame:
    """Minervini's Trend Template and VCP flags (EOD). A problem leaves them empty."""
    from trading_os import minervini_live

    try:
        out = minervini_live.attach(uni, data_dir, cfg, session)
        status(
            f"Minervini: {int(out['minervini_tt'].sum())} Trend Template, "
            f"{int(out['vcp_watch'].sum())} VCP"
        )
        return out
    except Exception as exc:  # noqa: BLE001 - one scan's inputs; the run goes on
        status(f"Minervini: FAILED ({type(exc).__name__}), scans empty")
        return uni


def _with_surf(uni: pd.DataFrame, data_dir: Path, cfg, session) -> pd.DataFrame:
    """Qullamaggie's MA-surf flags (EOD). A problem leaves the scan empty, never fails."""
    from trading_os import surf_live

    try:
        out = surf_live.attach(uni, data_dir, cfg, session)
        status(f"MA-surf: {int(out['ma_surf'].sum())} flagged")
        return out
    except Exception as exc:  # noqa: BLE001 - one scan's inputs; the run goes on
        status(f"MA-surf: FAILED ({type(exc).__name__}), scan empty")
        return uni


def _with_grades(results: dict, data_dir: Path, cfg, session, slot: str, extras, df) -> dict:
    """Study grades and the graded plans (SPEC §11.17). Auxiliary: a failure leaves the hits
    ungraded and the push as before."""
    from trading_os import grade_live

    if not cfg.grading["enabled"]:
        return results
    try:
        market = None
        if "breadth" in extras and len(extras["breadth"]):
            market = extras["breadth"].iloc[0].to_dict()
        account, rate = _account_and_rate(data_dir, cfg)
        today = enrich.todays_bars(df, session) if slot in ("eod", "ah") else None
        out = grade_live.add_grades(
            results,
            data_dir,
            cfg,
            session,
            slot,
            market,
            account,
            rate,
            fetch_details=tv.fetch_details,
            today=today,
        )
        counts: dict[str, int] = {}
        for hits in out.values():
            if "grade" in hits:
                for g, n in hits["grade"].value_counts().items():
                    counts[g] = counts.get(g, 0) + int(n)
        status(f"Grades: {dict(sorted(counts.items()))}")
        return out
    except Exception as exc:  # noqa: BLE001 - grades are extra; alerts still go out
        status(f"Grades: FAILED ({type(exc).__name__}), hits sent ungraded")
        return results


def _account_and_rate(data_dir: Path, cfg):
    """(account or None, units of the account currency per USD)."""
    account = sizing.load_account(data_dir)
    if account is None or account.currency == "USD":
        return account, 1.0
    symbol = cfg.sizing["fx_symbol"].format(currency=account.currency)
    rate = once_more(lambda: tv.fetch_fx(symbol), label="TradingView", wait_s=TV_RETRY_WAIT_S)
    return account, rate


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


EVENING_NOTE = "flagged last evening (16:50)"


def _flagged_last_evening(results: dict, data_dir: Path, cfg, session) -> dict:
    """EP 10:30 gaps the 16:50 after-hours check pushed the evening before get a note instead
    of a second buy (one position per stock, as in the study's portfolio runs)."""
    hits = results.get("ep_am")
    if hits is None or hits.empty:
        return results
    previous = clock.previous_session(cfg.schedule, session)
    evening = store.pushed_in(data_dir, previous, "ah").get("ep_ah", set())
    flagged = hits["ticker"].isin(evening)
    status(f"EP 10:30: {int(flagged.sum())} flagged last evening")
    if not flagged.any():
        return results
    note = pd.Series(None, index=hits.index, dtype=object).mask(flagged, EVENING_NOTE)
    return {**results, "ep_am": hits.assign(seen_earlier=note)}


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
    """(extras, the report's header, the push's head). EOD: today's breadth row and lines.
    Pre-market: the light for today, last close's breadth and the pre-market movers. Weekly:
    the Sunday scan count. The header ends with the market heat lines (`heat`); the push
    keeps only the Light, the heat and QQQ against its averages (Emil, 23 Oct 2026)."""
    stats = heat.load(data_dir)
    if slot == "weekly":
        count = breadth.scan_count(uni, cfg)
        field = cfg.market_light["scan_count"]["avg_volume_field"]
        status("Market Light scan count: saved")
        frame = pd.DataFrame([{"scan_count": count, "avg_volume_field": field}])
        return (
            {"market_light_count": frame},
            heat.push_lines(stats, count),
            heat.short_line(stats, count),
        )
    if slot not in ("eod", "pm") or not cfg.scans["breadth"].enabled:
        return {}, [], []
    qqq = once_more(
        lambda: tv.fetch_quote(cfg.market_light["qqq"]["symbol"]),
        label="TradingView",
        wait_s=TV_RETRY_WAIT_S,
    )
    indexes = breadth.index_fields(_index_quotes(cfg))
    if slot == "pm":
        last = breadth.latest_eod_row(data_dir, session)
        pm_row = {**breadth.premarket_row(uni, qqq, cfg, session, last), **indexes}
        if last and not pm_row.get("qqq_light"):  # an EOD row from before the QQQ light
            try:
                pm_row["qqq_light"] = breadth.qqq_light_from_bars(
                    data_dir,
                    cfg.schedule,
                    pm_row["last_eod_session"],
                    cfg.market_light["qqq"]["symbol"],
                    cfg.market_light["qqq"]["slope_lookback"],
                )
            except Exception:  # noqa: BLE001 - the light shows n/a
                pm_row["qqq_light"] = None
        status("Pre-market breadth: saved")
        lines = breadth.premarket_lines(pm_row, last)
        light, *qqq_ma = breadth.short_lines(pm_row, breadth.premarket_suffix(pm_row), last)
        head = [light, *heat.short_line(stats, pm_row.get("scan_count")), *qqq_ma]
        count = pm_row.get("scan_count")
        return {"breadth_pm": pd.DataFrame([pm_row])}, lines + heat.push_lines(stats, count), head
    row = {**breadth.breadth_row(uni, qqq, cfg, data_dir, session), **indexes}
    status(f"Breadth: saved ({row['ratio_days_available']} of 10 days for the ratios)")
    status("Market Light: " + ("computed" if row["light"] else "waiting for inputs"))
    lines = breadth.push_lines(row) + heat.push_lines(stats, row.get("scan_count"))
    light, *qqq_ma = breadth.short_lines(row)
    head = [light, *heat.short_line(stats, row.get("scan_count")), *qqq_ma]
    return {"breadth": pd.DataFrame([row])}, lines, head


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
