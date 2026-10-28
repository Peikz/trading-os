"""The Saxo order ticket for a graded signal (Emil, 26 Oct 2026: the dashboard as the only tool,
Saxo for execution). Nothing is sent anywhere: this works out what to type into Saxo.

The plan's order type is the default (the study's entry); Emil "sometimes" uses another, so
any of `ORDER_TYPES` can be picked and the ticket recomputes. Shares keep the grade's risk:
risk in USD / (worst expected fill - stop), capped at the account's max position. The stop
loss always goes in as its own GTC order.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from trading_os import plans

ORDER_TYPES = {
    "market": "Market",
    "limit": "Limit",
    "stop": "Stop (buy-stop)",
    "stop_limit": "Stop limit",
    "limit_ext": "Limit, extended hours",
    "moc": "Market on close",
}
MARKET_RULES = {"t_1030", "t_1015", "t_1200", "next_1030", "next_open"}
STOP_LIMIT_BUFFER_PCT = 0.5  # stop-limit: the limit this far over the trigger
WHEN = {
    "t_1030": "~10:30 New York (16:30 CPH)",
    "t_1015": "after 10:15 New York (16:15 CPH)",
    "t_1200": "after 12:00 New York (18:00 CPH)",
    "next_1030": "next session ~10:30 New York (16:30 CPH)",
    "next_open": "at the next open, 09:30 New York (15:30 CPH)",
    "pivot_1000": "from 10:00 New York (16:00 CPH)",
    "ah_1645": "now, before 17:00 New York (23:00 CPH, Saxo's cutoff)",
    "close": "15:45-15:58 New York (21:45 CPH)",
}


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def default_type(row: Mapping[str, Any]) -> str:
    """The order type the study's plan uses."""
    rule = str(row.get("grade_entry_rule") or "")
    if rule.startswith("ah_"):
        return "limit_ext"
    if rule == "pivot_1000" or row.get("scan") in ("ma_surf", "breakout_watch", "pivot_watch"):
        return "stop"
    if rule == "close":
        return "moc"
    return "market"


@dataclass(frozen=True)
class Ticket:
    order_type: str
    trigger: float | None  # buy-stop / stop-limit trigger
    limit: float | None  # limit price (limit, stop-limit, extended hours)
    est_entry: float  # the price the shares are sized on (the worst expected fill)
    stop: float
    shares: int
    risk_usd: float
    position_usd: float
    capped: bool
    when: str

    def lines(self) -> list[tuple[str, str]]:
        """(label, value to type) in Saxo's order: the entry order, then the stop loss."""
        out = [("Buy", f"{self.shares}"), ("Order type", ORDER_TYPES[self.order_type])]
        if self.trigger is not None:
            out.append(("Trigger (stop) price", f"{self.trigger:.2f}"))
        if self.limit is not None:
            out.append(("Limit price", f"{self.limit:.2f}"))
        out.append(("Duration", "Day"))
        out.append(("Stop loss (own order, GTC)", f"{self.stop:.2f}"))
        return out


def plan_price(row: Mapping[str, Any], order_type: str) -> float | None:
    """The plan's price for `order_type`: the pivot as a buy-stop's trigger when the hit has
    one, else the plan's entry (else the grade's, else the close)."""
    plan_entry = next(
        (v for k in ("plan_entry", "grade_entry", "close") if (v := _num(row.get(k))) is not None),
        None,
    )
    if plan_entry is None:  # no plan, no ticket
        return None
    pivot = _num(row.get("pivot"))
    return pivot if order_type in ("stop", "stop_limit") and pivot else plan_entry


def build(
    row: Mapping[str, Any],
    order_type: str,
    risk_usd: float,
    account_usd: float,
    max_position_pct: float,
    price: float | None = None,
) -> Ticket | None:
    """The ticket for `row` (a graded hit with its plan) as `order_type`. `price`: the user's own
    price for a limit / trigger (else the plan's). None without an entry and a stop."""
    stop = _num(row.get("plan_stop")) or _num(row.get("grade_stop"))
    plan = plan_price(row, order_type)
    if plan is None or stop is None:
        return None
    base = price or plan
    trigger = limit = None
    if order_type == "stop":
        trigger, est = base, base
    elif order_type == "stop_limit":
        trigger = base
        limit = round(base * (1 + STOP_LIMIT_BUFFER_PCT / 100), 2)
        est = limit
    elif order_type in ("limit", "limit_ext"):
        limit, est = base, base
    else:  # market, market on close
        est = base
    if not est > stop:
        return None
    size = plans.shares_for(est, stop, risk_usd, account_usd, max_position_pct)
    if size is None:
        return None
    rule = str(row.get("grade_entry_rule") or "")
    return Ticket(
        order_type=order_type,
        trigger=trigger,
        limit=limit,
        est_entry=float(est),
        stop=float(stop),
        shares=size["shares"],
        risk_usd=size["risk_usd"],
        position_usd=size["position_usd"],
        capped=size["capped"],
        when=WHEN.get(rule, ""),
    )
