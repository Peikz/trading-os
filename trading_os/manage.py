"""Position manager (Emil, 22 Oct 2026): what each open position's plan says to do, in the push.
Facts from the plans the studies measured; nothing places an order.

For every open position in the journal (`positions_*.parquet`, from your fills):
- the plan by its setup: hold N sessions and sell at that close (EP, EP9M, Luk flush, parabolic
  long; N from the grading config, 21), trail the 20-day MA (MA-surf, breakouts: out on a close
  under it), or cover on a close over the 20-day MA (parabolic short);
- day k of N; "sell at today's close" on the day (pre-market push) and "tomorrow" the evening
  before (EOD push); a close through the 20-day MA (EOD push);
- earnings within two sessions;
- R so far at the last close, and the open risk to the stop.
Prices are the last EOD universe snapshot (the close, the 20-day MA, the next earnings date).
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

HOLD, TRAIL, COVER = "hold", "trail_ma20", "cover_ma20"
DEFAULT_HOLD = 21
EARNINGS_WARN_SESSIONS = 2
TRAIL_SETUPS = ("ma_surf", "breakout_watch", "breakout_trigger", "pivot_watch", "qm_surf")
COVER_SETUPS = ("parabolic_short",)
HOLD_SETUPS = (
    "ep_am", "ep_ah", "ep_close", "ep_day", "ep9m", "ep9m_pace", "luk_flush",
    "luk_avwap_flush", "parabolic_long",
)  # fmt: skip
COLUMNS = [
    "ticker", "setup", "direction", "rule", "hold", "held", "close", "entry", "stop", "r_now",
    "risk_to_stop", "earnings", "action",
]  # fmt: skip


def hold_sessions(setup: str, grading: Mapping[str, Any]) -> int:
    """The plan's holding period for a setup: the grading rule's `hold_sessions`, else 21."""
    for rule in (grading.get("quality") or {}).values():
        if setup in rule.get("live_scans", ()):
            return int(rule.get("hold_sessions", DEFAULT_HOLD))
    return DEFAULT_HOLD


def plan(setup: Any, grading: Mapping[str, Any]) -> tuple[str | None, int | None]:
    setup = str(setup or "")
    if setup in TRAIL_SETUPS:
        return TRAIL, None
    if setup in COVER_SETUPS:
        return COVER, None
    if setup in HOLD_SETUPS:
        return HOLD, hold_sessions(setup, grading)
    return None, None


def _num(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v


def review(
    positions: pd.DataFrame,
    market: pd.DataFrame,
    session: dt.date,
    sessions: list[dt.date],
    grading: Mapping[str, Any],
    slot: str,
) -> pd.DataFrame:
    """One row per open position: its plan, day k of N, R now, risk to the stop and the action
    for the push of `slot` (pm: the day's exits; eod: tomorrow's exits and 20-day MA closes).
    `market`: ticker, close, ma20, earnings_date_next (the last EOD snapshot). `sessions`:
    trading days, oldest first, covering the entries and a few days past `session`."""
    if positions is None or positions.empty:
        return pd.DataFrame(columns=COLUMNS)
    last = market.drop_duplicates("ticker").set_index("ticker") if len(market) else pd.DataFrame()
    days = sorted(sessions)
    rows = []
    for p in positions.to_dict("records"):
        ticker = p["ticker"]
        setup = p.get("setup") or p.get("signal_scan")
        rule, hold = plan(setup, grading)
        short = str(p.get("direction", "long")).lower() == "short"
        sign = -1 if short else 1
        entry, stop = _num(p.get("entry_avg")), _num(p.get("order_stop"))
        qty = _num(p.get("open_quantity", p.get("quantity")))
        info = last.loc[ticker] if ticker in last.index else {}
        close = _num(info.get("close")) if len(info) else math.nan
        ma20 = _num(info.get("ma20")) if len(info) else math.nan
        entered = pd.Timestamp(p["entry_date"]).date()
        held = sum(1 for d in days if entered < d <= session)
        risk = (entry - stop) * sign
        r_now = (close - entry) * sign / risk if risk > 0 and close == close else math.nan
        to_stop = (close - stop) * sign * qty if stop == stop and close == close else math.nan
        earnings = None
        nxt = info.get("earnings_date_next") if len(info) else None
        if nxt is not None and not pd.isna(nxt):
            day = pd.Timestamp(nxt).date()
            ahead = sum(1 for d in days if session < d <= day) if day > session else 0
            if session <= day and ahead <= EARNINGS_WARN_SESSIONS:
                earnings = day
        action = ""
        if rule == HOLD and hold:
            if slot == "pm" and held == hold:
                action = f"day {held}/{hold}: the plan sells at today's close"
            elif slot == "eod" and held == hold - 1:
                action = f"day {held}/{hold}: the plan sells at tomorrow's close"
            elif held >= hold and slot == "eod" or held > hold:
                action = f"day {held}/{hold}: past the plan's exit day"
        elif slot == "eod" and close == close and ma20 == ma20:
            if rule == TRAIL and close < ma20:
                action = "closed under the 20-day MA: the plan's exit"
            elif rule == COVER and close > ma20:
                action = "closed over the 20-day MA: the plan covers"
        rows.append(
            {
                "ticker": ticker,
                "setup": setup,
                "direction": "short" if short else "long",
                "rule": rule,
                "hold": hold,
                "held": held,
                "close": close,
                "entry": entry,
                "stop": stop,
                "r_now": r_now,
                "risk_to_stop": to_stop,
                "earnings": earnings,
                "action": action,
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def _money(x: float) -> str:
    return f"${x / 1000:.1f}k" if abs(x) >= 1000 else f"${x:.0f}"


def push_lines(table: pd.DataFrame) -> list[str]:
    """`💼 3 open · $1.2k at risk to stops · avg +0.8R`, then one line per position, the ones
    with an action first."""
    if table.empty:
        return []
    risk = table["risk_to_stop"].dropna()
    r = table["r_now"].dropna()
    head = f"💼 {len(table)} open"
    if len(risk):
        head += f" · {_money(risk.clip(lower=0).sum())} at risk to stops"
    if len(r):
        head += f" · avg {r.mean():+.1f}R"
    lines = [head]
    order = table.assign(_a=table["action"].eq("")).sort_values(["_a", "ticker"])
    for row in order.to_dict("records"):
        parts = [f"▸ {row['ticker']}"]
        if row["r_now"] == row["r_now"]:
            parts.append(f"{row['r_now']:+.1f}R")
        if row["rule"] == HOLD and row["hold"] and not row["action"]:
            parts.append(f"day {row['held']}/{row['hold']}")
        if row["rule"] in (TRAIL, COVER) and not row["action"]:
            parts.append("trail MA20" if row["rule"] == TRAIL else "cover over MA20")
        if row["action"]:
            parts.append(f"🔔 {row['action']}")
        if row["earnings"] is not None:
            parts.append(f"📢 earnings {row['earnings']:%a %d %b}")
        lines.append(" · ".join([" ".join(parts[:2]), *parts[2:]]) if len(parts) > 1 else parts[0])
    return lines
