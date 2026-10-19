"""EP-Watch and BO-Watch (SPEC §7, Phase 2).

Stored as an append-only event log, one file per run (data/watchlists/YYYY/<date>.parquet):
every add, refresh, move, trigger and expiry is a new row, so past state is never rewritten.
The current list is the latest event per (ticker, list).

Rules (config `watchlists:`, parts marked proposed):
- EP-Watch: alert-tier hits of the configured EP scans enter it; an entry expires after
  `ep_watch_max_sessions`, or moves on when the name qualifies for BO-Watch.
- BO-Watch: names passing B1-B4 (the breakout_watch scan); each qualifying day refreshes the
  entry, which expires after `bo_watch_stale_sessions` without qualifying. A B5 trigger on an
  active BO-Watch name marks it triggered.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os.store import signal_id

EVENT_COLUMNS = [
    "ticker",
    "list",
    "status",
    "status_date",
    "added_date",
    "source_signal_id",
    "reason",
]
LISTS = ("ep_watch", "bo_watch")


def load_events(data_dir: Path) -> pd.DataFrame:
    files = sorted((Path(data_dir) / "data" / "watchlists").glob("*/*.parquet"))
    if not files:
        return pd.DataFrame(columns=[*EVENT_COLUMNS, "run_ts"])
    events = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    for column in ("status_date", "added_date"):
        events[column] = pd.to_datetime(events[column]).dt.date
    return events


def current(events: pd.DataFrame) -> pd.DataFrame:
    """Latest event per (ticker, list)."""
    if events.empty:
        return events
    ordered = events.sort_values(["status_date", "run_ts"], kind="stable")
    return ordered.groupby(["ticker", "list"], as_index=False).tail(1).reset_index(drop=True)


def active(state: pd.DataFrame, list_name: str) -> set[str]:
    if state.empty:
        return set()
    rows = state[(state["list"] == list_name) & (state["status"] == "active")]
    return set(rows["ticker"])


def update(
    state: pd.DataFrame,
    results: Mapping[str, pd.DataFrame],
    session: dt.date,
    slot: str,
    sessions_since: Callable[[dt.date], int],
    rules: Mapping[str, Any],
) -> pd.DataFrame:
    """The day's new events, given yesterday's state and today's scan hits."""
    events: list[dict[str, Any]] = []
    latest = {(r["ticker"], r["list"]): r for r in state.to_dict("records")} if len(state) else {}

    def emit(ticker, list_name, status, reason, source=None, added=None):
        events.append(
            {
                "ticker": ticker,
                "list": list_name,
                "status": status,
                "status_date": session,
                "added_date": added or session,
                "source_signal_id": source,
                "reason": reason,
            }
        )

    def alert_hits(scan: str) -> pd.DataFrame:
        hits = results.get(scan)
        if hits is None or hits.empty:
            return pd.DataFrame(columns=["ticker"])
        return hits[hits["tier"] == "alert"] if "tier" in hits else hits

    bo_now = set(alert_hits("breakout_watch")["ticker"])
    triggered = set(alert_hits("breakout_trigger")["ticker"])

    # BO-Watch: add or refresh every qualifying name.
    for ticker in sorted(bo_now):
        prev = latest.get((ticker, "bo_watch"))
        is_active = prev is not None and prev["status"] == "active"
        added = prev["added_date"] if is_active else session
        source = signal_id(session, slot, "breakout_watch", ticker)
        emit(ticker, "bo_watch", "active", "refresh" if is_active else "B1-B4 pass", source, added)
        ep = latest.get((ticker, "ep_watch"))
        if ep is not None and ep["status"] == "active":
            emit(
                ticker,
                "ep_watch",
                "expired",
                "moved to bo_watch",
                ep["source_signal_id"],
                ep["added_date"],
            )

    # EP-Watch: alert-tier hits of the configured EP scans.
    for scan in rules["ep_watch_sources"]:
        for ticker in sorted(set(alert_hits(scan)["ticker"]) - bo_now):
            prev = latest.get((ticker, "ep_watch"))
            if prev is None or prev["status"] != "active":
                emit(
                    ticker,
                    "ep_watch",
                    "active",
                    f"{scan} alert",
                    signal_id(session, slot, scan, ticker),
                )

    # Triggers and expiry for names that were active before today.
    for (ticker, list_name), prev in latest.items():
        if prev["status"] != "active":
            continue
        if list_name == "bo_watch" and ticker in triggered:
            source = signal_id(session, slot, "breakout_trigger", ticker)
            emit(ticker, "bo_watch", "triggered", "B5 trigger", source, prev["added_date"])
        elif list_name == "bo_watch" and ticker not in bo_now:
            if sessions_since(prev["status_date"]) > rules["bo_watch_stale_sessions"]:
                emit(
                    ticker,
                    "bo_watch",
                    "expired",
                    "stale",
                    prev["source_signal_id"],
                    prev["added_date"],
                )
        elif list_name == "ep_watch" and ticker not in bo_now:
            if sessions_since(prev["added_date"]) > rules["ep_watch_max_sessions"]:
                emit(
                    ticker,
                    "ep_watch",
                    "expired",
                    "max age",
                    prev["source_signal_id"],
                    prev["added_date"],
                )
    return pd.DataFrame(events, columns=EVENT_COLUMNS)
