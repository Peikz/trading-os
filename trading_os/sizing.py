"""Position size for each pushed alert: entry, stop, shares, position and risk in USD.

The account (currency, size, risk per trade) is private: it lives in the data repo at
settings/account.yaml, never in this public repo, and is never printed to logs. Risk per
trade is converted to USD at the live rate from TradingView.

Entry and stop per scan (config `sizing:`):
- EP-Day, EP9M, EP9M pace: entry at the close (intraday: the last price), stop at the day's
  low but no more than `ep_stop_max_adr` × ADR $ and no less than `min_stop_adr` × ADR $
  below entry (proposed).
- EP-PM, EP9M early warning, watchlist gappers: entry at the pre-market price, stop
  `pm_stop_adr` × ADR $ below until the open sets a day low (proposed).
- EP after hours: entry at the post-market price, stop `pm_stop_adr` × ADR $ below.
- EP 10:30 (ep_am): as EP-Day, at the last price.
- Breakout trigger: entry at the close (B5 is checked at the close), stop = order stop (§6.4).
- BO-Watch: buy-stop at the pivot, stop = order stop (§6.4).
- BO pivot (intraday): over the pivot, entry at the last price; below it, buy-stop at the
  pivot. Stop = order stop.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PLAN_COLUMNS = [
    "plan_entry",
    "plan_stop",
    "plan_stop_basis",
    "plan_shares",
    "plan_position_usd",
    "plan_risk_usd",
    "plan_capped",
]
EP_CLOSE = ("ep_day", "ep_close", "ep_am", "ep9m", "ep9m_pace")  # intraday: the last price
EP_PREMARKET = ("ep_pm", "ep9m_early", "watchlist_gappers")
EP_AFTERHOURS = ("ep_ah",)
BREAKOUT_RULES = ("breakout_trigger", "breakout_watch", "pivot_watch")


@dataclass(frozen=True)
class Account:
    currency: str
    size: float
    risk_pct: float
    max_position_pct: float

    def risk_usd(self, usd_rate: float) -> float:
        """Risk per trade in USD; `usd_rate` = units of the account currency per 1 USD."""
        return self.size * self.risk_pct / 100 / usd_rate

    def size_usd(self, usd_rate: float) -> float:
        return self.size / usd_rate


def account_path(data_dir: Path) -> Path:
    return Path(data_dir) / "settings" / "account.yaml"


def load_account(data_dir: Path) -> Account | None:
    """The private account settings, or None when the file isn't there."""
    path = account_path(data_dir)
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Account(
        currency=str(raw.get("currency", "USD")).upper(),
        size=float(raw["size"]),
        risk_pct=float(raw["risk_pct"]),
        max_position_pct=float(raw.get("max_position_pct", 100)),
    )


def plan(row: Mapping[str, Any], scan: str, rules: Mapping[str, Any]) -> tuple[float, float, str]:
    """(entry, stop, stop basis) for a hit, or NaNs when the scan has no rule."""
    nan = float("nan")
    adr = row.get("adr20_usd", nan)
    if scan in EP_CLOSE:
        entry, low = row.get("close", nan), row.get("low", nan)
        floor = entry - rules["ep_stop_max_adr"] * adr
        ceiling = entry - rules["min_stop_adr"] * adr
        if pd.isna(low) or (not pd.isna(floor) and low < floor):
            return entry, floor, f"{rules['ep_stop_max_adr']:g} ADR"
        if not pd.isna(ceiling) and low > ceiling:  # closed near the low: keep a minimum distance
            return entry, ceiling, f"{rules['min_stop_adr']:g} ADR min"
        return entry, low, "day low"
    if scan in EP_AFTERHOURS:
        entry = row.get("ah_price", nan)
        if pd.isna(entry):
            entry = row.get("close", nan) * (1 + row.get("ah_change_pct", nan) / 100)
        return entry, entry - rules["pm_stop_adr"] * adr, f"{rules['pm_stop_adr']:g} ADR"
    if scan in EP_PREMARKET:
        entry = row.get("pm_price", nan)
        return (
            entry,
            entry - rules["pm_stop_adr"] * adr,
            f"{rules['pm_stop_adr']:g} ADR, move to day low",
        )
    if scan == "breakout_trigger":
        return row.get("close", nan), row.get("order_stop", nan), "order stop"
    if scan == "breakout_watch":
        return row.get("pivot", nan), row.get("order_stop", nan), "order stop, buy-stop at pivot"
    if scan == "pivot_watch":  # intraday: over the pivot buys now, below it waits at the pivot
        pivot, price = row.get("pivot", nan), row.get("close", nan)
        if not pd.isna(price) and not pd.isna(pivot) and price >= pivot:
            return price, row.get("order_stop", nan), "order stop"
        return pivot, row.get("order_stop", nan), "order stop, buy-stop at pivot"
    return nan, nan, ""


def size(
    entry: float, stop: float, risk_usd: float, account_usd: float, max_position_pct: float
) -> dict[str, Any] | None:
    """Shares so that a stop-out loses `risk_usd`, capped at `max_position_pct` of the account."""
    if any(pd.isna(x) for x in (entry, stop)) or not entry > stop > 0:
        return None
    risk_per_share = entry - stop
    shares = math.floor(risk_usd / risk_per_share)
    cap = math.floor(account_usd * max_position_pct / 100 / entry)
    capped = shares > cap
    shares = min(shares, cap)
    if shares <= 0:
        return None
    return {
        "plan_entry": float(entry),
        "plan_stop": float(stop),
        "plan_shares": int(shares),
        "plan_position_usd": float(shares * entry),
        "plan_risk_usd": float(shares * risk_per_share),
        "plan_capped": bool(capped),
    }


def add_plans(
    results: Mapping[str, pd.DataFrame],
    rules: Mapping[str, Any],
    account: Account,
    usd_rate: float,
) -> dict[str, pd.DataFrame]:
    """Plan columns on every hit of the scans that have an entry/stop rule."""
    risk_usd, account_usd = account.risk_usd(usd_rate), account.size_usd(usd_rate)
    out = {}
    for scan, hits in results.items():
        if scan not in (*EP_CLOSE, *EP_PREMARKET, *EP_AFTERHOURS, *BREAKOUT_RULES):
            out[scan] = hits
            continue
        rows = []
        for record in hits.to_dict("records"):
            entry, stop, basis = plan(record, scan, rules)
            sized = size(entry, stop, risk_usd, account_usd, account.max_position_pct)
            rows.append(
                {
                    **dict.fromkeys(PLAN_COLUMNS),
                    **(sized or {}),
                    "plan_stop_basis": basis if sized else None,
                }
            )
        out[scan] = hits.assign(**pd.DataFrame(rows, index=hits.index, columns=PLAN_COLUMNS))
    return out


def plan_line(row: Mapping[str, Any]) -> str | None:
    """`   buy 2.35 · stop 2.21 (day low) · 2,612 sh · $6.1k · risk $366`"""
    if row.get("plan_shares") is None or pd.isna(row.get("plan_shares")):
        return None
    position = row["plan_position_usd"]
    money = f"${position / 1000:.1f}k" if position >= 1000 else f"${position:.0f}"
    capped = " (capped)" if bool(row.get("plan_capped")) else ""
    stop = f"stop {row['plan_stop']:.2f} ({row['plan_stop_basis']})"
    return (
        f"   buy {row['plan_entry']:.2f} · {stop} · {int(row['plan_shares']):,} sh · "
        f"{money}{capped} · risk ${row['plan_risk_usd']:.0f}"
    )
