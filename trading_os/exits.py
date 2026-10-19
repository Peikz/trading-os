"""Managed exits for the history studies (Emil, 19 Oct 2026): how the trades are really run.

The fixed horizons (hold N days) measure the setup; these measure the setup plus the way
Qullamaggie and Stockbee manage it. Rules come from config `exits:` (proposed):

- partial + trail (Qullamaggie): sell `partial_fraction` at the close of day P (3 or 5),
  move the stop to break-even, trail the rest to the first close through the 10- or 20-day
  MA (from day P+1). Before day P the original stop applies to the whole position.
- time exit (Stockbee): the whole position at the close of day N (3 or 5), stop before.
- target (Stockbee): sell everything at `target_pct` if it comes within `target_days`
  (the stop wins a day that touches both), else at the close of that last day.

Long (side 1) or short (side -1). R is per unit of the original risk; a stop or break-even
hit fills at the level, or at the open when the day gapped through it. A missing bar leaves
the result unknown.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


def _fill(o: np.ndarray, d: int, level: float, side: int) -> float:
    if np.isnan(o[d]):
        return level
    return min(o[d], level) if side > 0 else max(o[d], level)


def _hit(h: np.ndarray, lo: np.ndarray, d: int, level: float, side: int) -> bool:
    return lo[d] <= level if side > 0 else h[d] >= level


def partial_trail(
    o,
    h,
    lo,
    c,
    ma: np.ndarray,
    t: int,
    entry: float,
    stop: float,
    side: int,
    partial_day: int,
    fraction: float,
    max_days: int,
) -> tuple[float, float]:
    """(R, sessions held) for: stop until day `partial_day`, sell `fraction` there, then a
    break-even stop and an MA trail for the rest."""
    risk = (entry - stop) * side
    n = len(c)
    if not risk > 0 or t + partial_day >= n:
        return np.nan, np.nan
    for d in range(t + 1, t + partial_day + 1):
        if np.isnan(lo[d]):
            return np.nan, np.nan
        if _hit(h, lo, d, stop, side):
            return (_fill(o, d, stop, side) - entry) * side / risk, float(d - t)
    first = (c[t + partial_day] - entry) * side / risk
    last = min(n - 1, t + max_days)
    for d in range(t + partial_day + 1, last + 1):
        if np.isnan(lo[d]):
            return np.nan, np.nan
        if _hit(h, lo, d, entry, side):  # break-even
            rest = (_fill(o, d, entry, side) - entry) * side / risk
            return fraction * first + (1 - fraction) * rest, float(d - t)
        through = c[d] < ma[d] if side > 0 else c[d] > ma[d]
        if not np.isnan(ma[d]) and through:
            rest = (c[d] - entry) * side / risk
            return fraction * first + (1 - fraction) * rest, float(d - t)
    rest = (c[last] - entry) * side / risk
    return fraction * first + (1 - fraction) * rest, float(last - t)


def time_exit(o, h, lo, c, t, entry, stop, side, days: int) -> float:
    risk = (entry - stop) * side
    if not risk > 0 or t + days >= len(c):
        return np.nan
    for d in range(t + 1, t + days + 1):
        if np.isnan(lo[d]):
            return np.nan
        if _hit(h, lo, d, stop, side):
            return (_fill(o, d, stop, side) - entry) * side / risk
    return (c[t + days] - entry) * side / risk


def target_exit(o, h, lo, c, t, entry, stop, side, target_pct: float, days: int) -> float:
    risk = (entry - stop) * side
    if not risk > 0 or t + days >= len(c):
        return np.nan
    target = entry * (1 + side * target_pct / 100)
    for d in range(t + 1, t + days + 1):
        if np.isnan(lo[d]):
            return np.nan
        if _hit(h, lo, d, stop, side):
            return (_fill(o, d, stop, side) - entry) * side / risk
        reached = h[d] >= target if side > 0 else lo[d] <= target
        if reached:
            gap = o[d] if not np.isnan(o[d]) else target
            price = max(gap, target) if side > 0 else min(gap, target)
            return (price - entry) * side / risk
    return (c[t + days] - entry) * side / risk


def managed(
    o,
    h,
    lo,
    c,
    mas: Mapping[int, np.ndarray],
    t: int,
    entry: float,
    stop: float | None,
    side: int,
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    """Every configured exit for one trade (NaN without a stop)."""
    row: dict[str, Any] = {}
    usable = stop is not None and not np.isnan(stop)
    for p in rules["partial_days"]:
        for w in rules["trail_mas"]:
            r, days = (
                partial_trail(
                    o,
                    h,
                    lo,
                    c,
                    mas[w],
                    t,
                    entry,
                    stop,
                    side,
                    p,
                    rules["partial_fraction"],
                    rules["max_days"],
                )
                if usable
                else (np.nan, np.nan)
            )
            row[f"r_q{p}_ma{w}"], row[f"days_q{p}_ma{w}"] = r, days
    for n in rules["time_days"]:
        row[f"r_time{n}d"] = time_exit(o, h, lo, c, t, entry, stop, side, n) if usable else np.nan
    target, days = rules["target_pct"], rules["target_days"]
    row[f"r_target{target:g}_{days}d"] = (
        target_exit(o, h, lo, c, t, entry, stop, side, target, days) if usable else np.nan
    )
    return row


def columns(rules: Mapping[str, Any]) -> list[str]:
    out = [f"r_q{p}_ma{w}" for p in rules["partial_days"] for w in rules["trail_mas"]]
    out += [f"r_time{n}d" for n in rules["time_days"]]
    out.append(f"r_target{rules['target_pct']:g}_{rules['target_days']}d")
    return out


def compare(df, rules: Mapping[str, Any], by: list[str] | None = None):
    """Per group and exit: trades, win rate (R > 0), mean R (capped at 20) and median R,
    next to holding 5 and 21 sessions with the stop."""
    import pandas as pd

    names = [*columns(rules), "r_5d", "r_21d"]
    groups = df.groupby(by, dropna=False, observed=True) if by else [("all", df)]
    rows = []
    for key, part in groups:
        for name in names:
            if name not in part:
                continue
            r = part[name].dropna()
            rows.append(
                {
                    "group": key,
                    "exit": name,
                    "trades": len(r),
                    "win%": (r > 0).mean() * 100 if len(r) else np.nan,
                    "mean_R": r.clip(upper=20).mean() if len(r) else np.nan,
                    "median_R": r.median() if len(r) else np.nan,
                }
            )
    return pd.DataFrame(rows)
