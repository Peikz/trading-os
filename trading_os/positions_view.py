"""The Positions page and the Journal's open positions, without any UI (React dashboard, Nov
2026): moved from `app/streamlit_app.py` and `app/board.py` so the Streamlit and the React
dashboards show the same numbers.

Prices are the newest daily close in the data repo; live Alpaca prices only when its keys are
in the environment. Exits are the plan's facts (`manage.review`), not advice. Read-only.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import board_data, clock, manage, review

CLOSE_SOURCE = "the newest daily close in the data repo (not live)"
LIVE_SOURCE = "live (Alpaca IEX, last trade) where it has one, else the last close"
PLAN_CAPTION = (
    "Exits are the plan's facts, not advice: hold = sell at the close after N sessions; "
    "trail = out on a close under the 20-day MA. Fills and stops come from the Journal."
)


def recent_bars(data_dir: Path, tickers: tuple[str, ...], sessions: int = 10) -> pd.DataFrame:
    """The newest daily bars of a few tickers, from the compact bars-2y file."""
    import pyarrow.dataset as ds

    paths = {board_data.bars_file(Path(data_dir), t) for t in tickers} - {None}
    if not paths:
        return pd.DataFrame(columns=["ticker", "session_date", "close"])
    flt = ds.field("ticker").isin(list(tickers))
    bars = ds.dataset(sorted(paths), format="parquet").to_table(filter=flt).to_pandas()
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    newest = sorted(set(bars["session_date"]))[-sessions:]
    return bars[bars["session_date"].isin(newest)]


def plan_check(
    positions: pd.DataFrame, runs, cfg, read: Callable[[str], pd.DataFrame] = pd.read_parquet
) -> tuple[pd.DataFrame, dt.date | None]:
    """What each position's plan says at the newest EOD close (`manage.review`), and that
    session. Empty without an EOD snapshot."""
    eod_runs = [r for r in runs if r.slot == "eod" and r.universe.exists()]
    if positions.empty or not eod_runs:
        return pd.DataFrame(), None
    snap = read(str(eod_runs[0].universe))
    day = eod_runs[0].session
    around = [
        *clock.sessions_back(cfg.schedule, day, 400),
        *clock.sessions_after(cfg.schedule, day, 10, day + dt.timedelta(days=30)),
    ]
    return manage.review(positions, snap, day, around, cfg.grading, "eod"), day


def live_prices(tickers, env: Mapping[str, str] | None = None) -> tuple[dict, str]:
    """Live last trades from Alpaca when its keys are set, else {} (then the last close)."""
    env = os.environ if env is None else env
    key, secret = env.get("ALPACA_API_KEY_ID"), env.get("ALPACA_API_SECRET_KEY")
    if not (key and secret):
        return {}, CLOSE_SOURCE
    try:
        from trading_os.alpaca import AlpacaClient

        prices = AlpacaClient(key, secret, per_minute=60).latest_prices(list(tickers))
        return prices, LIVE_SOURCE
    except Exception:  # noqa: BLE001 - falls back to the close
        return {}, CLOSE_SOURCE


def _num(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v


def open_view(data_dir: Path, positions: pd.DataFrame, account_usd: float | None) -> pd.DataFrame:
    """Open positions at the newest close: open P&L and R, at risk to the stops
    (`review.open_risk`)."""
    if positions.empty:
        return positions
    last = recent_bars(Path(data_dir), tuple(sorted(positions["ticker"])))
    return review.open_risk(positions, last, account_usd)


def totals(view: pd.DataFrame) -> dict[str, float]:
    """The three numbers over the cards: positions, open P&L, at risk to the stops."""
    if view.empty:
        return {"positions": 0, "open_pnl": 0.0, "at_risk_usd": 0.0, "at_risk_pct": None}
    pct = view["at_risk_pct"].sum() if "at_risk_pct" in view else None
    return {
        "positions": int(len(view)),
        "open_pnl": float(view["open_pnl"].sum()),
        "at_risk_usd": float(view["at_risk_usd"].sum()),
        "at_risk_pct": float(pct) if pct is not None else None,
    }


def plan_facts(info: Mapping[str, Any]) -> list[str]:
    """What the plan says today, the action (if any) and earnings within two sessions."""
    facts: list[str] = []
    if not len(info):
        return facts
    rule, held, hold = info.get("rule"), info.get("held"), info.get("hold")
    if rule == "hold" and hold == hold and hold:
        facts.append(
            f"Plan: sell at the close after {int(hold)} sessions · day {int(held)} of {int(hold)}"
        )
    elif rule == "trail_ma20":
        facts.append("Plan: trail the 20-day MA, out on a close under it")
    elif rule == "cover_ma20":
        facts.append("Plan: cover on a close over the 20-day MA")
    action = info.get("action")
    if isinstance(action, str) and action:
        facts.append(f"⚠️ {action}")
    earn = info.get("earnings")
    if earn is not None and not pd.isna(earn):
        facts.append(f"📅 Earnings {earn}")
    return facts


def card(p: Mapping[str, Any], info: Mapping[str, Any], price: float | None) -> dict[str, Any]:
    """One position card's numbers: price (and % from the entry), open R and P&L, the distance
    to the stop, and the plan's facts. `price`: live, else the last close."""
    price = _num(p.get("last_close") if price is None else price)
    sign = 1 if p.get("direction") == "long" else -1
    entry, stop = _num(p.get("entry_avg")), _num(p.get("order_stop"))
    qty = abs(_num(p.get("open_quantity")) or 0)
    qty = 0.0 if qty != qty else qty
    risk = (entry - stop) * sign if stop == stop else math.nan
    r_now = (price - entry) * sign / risk if risk == risk and risk > 0 else math.nan
    to_stop = (price - stop) * sign / price * 100 if risk == risk and price else math.nan
    return {
        "ticker": p["ticker"],
        "setup": p.get("setup") or "",
        "direction": p.get("direction"),
        "shares": qty,
        "entry_date": p.get("entry_date"),
        "entry": entry,
        "price": price,
        "move_pct": (price / entry - 1) * 100 * sign if entry else math.nan,
        "open_r": r_now,
        "pnl": (price - entry) * sign * qty,
        "to_stop_pct": to_stop,
        "stop": stop,
        "facts": plan_facts(info),
    }


def cards(view: pd.DataFrame, check: pd.DataFrame, prices: Mapping[str, float]) -> list[dict]:
    """One card per open position (see `card`)."""
    plan = check.set_index("ticker") if len(check) else pd.DataFrame()
    out = []
    for p in view.to_dict("records"):
        t = p["ticker"]
        info = plan.loc[t].to_dict() if t in plan.index else {}
        out.append(card(p, info, prices.get(t)))
    return out
