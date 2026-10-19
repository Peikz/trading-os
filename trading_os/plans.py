"""Trade plans (Emil, 20 Oct 2026): entry, stop and size decided before the trade, then matched
to the fill (plan vs actual). LOCAL USE ONLY: plans live in the private data repo
(data/journal/plans/), never in this public repo or its Actions logs.

A plan is an append-only event, `create` or `cancel`. Its status comes from the fills:
`filled` once an entry fill (a buy for a long, a sell for a short) of the same ticker arrives
on the plan's session or within `plan_valid_sessions` sessions after it, `expired` after
that, `cancelled`, else `open`. Slippage is the fill against the planned entry, in % and in R
(per unit of the planned risk); positive = worse than planned.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import clock
from trading_os.journal import normalize_ticker
from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = [
    "plan_id",
    "action",
    "saved_ts",
    "session_date",
    "ticker",
    "direction",
    "setup",
    "entry",
    "stop",
    "shares",
    "risk_usd",
    "position_usd",
    "note",
]


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "journal" / "plans"


def shares_for(
    entry: float, stop: float, risk_usd: float, account_usd: float, max_position_pct: float
) -> dict[str, Any] | None:
    """Shares so that the stop loses `risk_usd`, capped at `max_position_pct` of the account.
    Long (stop under entry) or short (stop over entry)."""
    per_share = abs(entry - stop)
    if not entry > 0 or not stop > 0 or not per_share > 0 or not risk_usd > 0:
        return None
    shares = math.floor(risk_usd / per_share)
    cap = math.floor(account_usd * max_position_pct / 100 / entry)
    capped = shares > cap
    shares = min(shares, cap)
    if shares <= 0:
        return None
    return {
        "shares": int(shares),
        "position_usd": float(shares * entry),
        "risk_usd": float(shares * per_share),
        "capped": bool(capped),
    }


def _write(data_dir: Path, row: dict[str, Any]) -> Path:
    out = folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{row['saved_ts']:%Y%m%dT%H%M%S%f}_{row['action']}.parquet"
    pd.DataFrame([row], columns=COLUMNS).to_parquet(path, **PARQUET_OPTIONS)
    return path


def create(
    data_dir: Path,
    session_date: dt.date,
    ticker: str,
    direction: str,
    entry: float,
    stop: float,
    shares: int,
    setup: str | None = None,
    note: str = "",
) -> str:
    """Save a plan; returns its id."""
    if direction not in ("long", "short"):
        raise ValueError("direction is long or short")
    if (entry - stop) * (1 if direction == "long" else -1) <= 0:
        raise ValueError("the stop must be on the losing side of the entry")
    stamp = unique_stamp()
    ticker = normalize_ticker(ticker)
    key = f"{session_date}|{ticker}|{direction}|{entry:g}|{stop:g}|{stamp.isoformat()}"
    plan_id = hashlib.sha1(key.encode()).hexdigest()[:12]
    _write(
        data_dir,
        {
            "plan_id": plan_id,
            "action": "create",
            "saved_ts": stamp,
            "session_date": session_date,
            "ticker": ticker,
            "direction": direction,
            "setup": setup or None,
            "entry": float(entry),
            "stop": float(stop),
            "shares": int(shares),
            "risk_usd": abs(entry - stop) * shares,
            "position_usd": entry * shares,
            "note": note,
        },
    )
    return plan_id


def cancel(data_dir: Path, plan_id: str) -> None:
    _write(data_dir, {"plan_id": plan_id, "action": "cancel", "saved_ts": unique_stamp()})


def load(data_dir: Path) -> pd.DataFrame:
    files = sorted(folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    events = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    events["session_date"] = pd.to_datetime(events["session_date"]).dt.date
    return events


def status(
    events: pd.DataFrame, fills: pd.DataFrame, schedule, valid_sessions: int, today: dt.date
) -> pd.DataFrame:
    """One row per plan with its status, and the fill and slippage when it was filled."""
    if events.empty:
        return pd.DataFrame(columns=[*COLUMNS, "status"])
    created = events[events["action"] == "create"].copy()
    cancelled = set(events.loc[events["action"] == "cancel", "plan_id"])
    rows = []
    for plan in created.to_dict("records"):
        later = clock.sessions_after(
            schedule, plan["session_date"], valid_sessions, today + dt.timedelta(days=40)
        )
        window = [plan["session_date"], *later]
        last_valid = window[-1]
        side = "buy" if plan["direction"] == "long" else "sell"
        match = fills[
            (fills["ticker"] == plan["ticker"])
            & (fills["side"] == side)
            & fills["trade_date"].isin(window)
        ].sort_values("trade_date")
        row = dict(plan)
        if len(match):
            first_day = match["trade_date"].iloc[0]
            day = match[match["trade_date"] == first_day]
            qty = day["quantity"].sum()
            price = (day["quantity"] * day["price"]).sum() / qty
            sign = 1 if plan["direction"] == "long" else -1
            risk = abs(plan["entry"] - plan["stop"])
            row |= {
                "status": "filled",
                "fill_date": first_day,
                "fill_price": price,
                "fill_shares": qty,
                "slippage_pct": (price / plan["entry"] - 1) * 100 * sign,
                "slippage_r": (price - plan["entry"]) * sign / risk if risk else None,
            }
        elif plan["plan_id"] in cancelled:
            row["status"] = "cancelled"
        elif today > last_valid:
            row["status"] = "expired"
        else:
            row["status"] = "open"
        rows.append(row)
    out = pd.DataFrame(rows)
    return out.sort_values("saved_ts", ascending=False).reset_index(drop=True)
