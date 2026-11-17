"""How sure Emil was about a trade (21 Nov 2026): 1 = small, 2 = normal, 3 = high conviction.

Optional everywhere it is asked (a plan, a hand-logged fill, a trade or signal note); a trade
without one is simply left out of the by-conviction table. The stats are pure functions over
the closed-trades table, so the question "do my 3s beat my 1s?" is a table, not a feeling.
Facts about past trades, not advice.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

LEVELS = (1, 2, 3)
LABELS = {1: "1 · small", 2: "2 · normal", 3: "3 · high"}
STATS_COLUMNS = ["conviction", "trades", "win_pct", "mean_r", "total_r"]


def normalize(value: Any) -> int | None:
    """None, "", NaN and "none" mean no conviction; 1, 2 or 3 (also "2", 2.0) are kept;
    anything else raises ValueError."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if value is pd.NA:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "none", "nan", "<na>", "-", "—"):
            return None
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"conviction must be one of {LEVELS} or empty, not {value!r}") from None
    if number not in LEVELS:
        raise ValueError(f"conviction must be one of {LEVELS} or empty, not {value!r}")
    return int(number)


def label(value: Any) -> str:
    level = normalize(value)
    return LABELS[level] if level else "none"


def by_conviction(trades: pd.DataFrame) -> pd.DataFrame:
    """Closed trades per conviction level: count, win % (P&L above 0), mean R and total R
    (trades with an R). Levels without trades are left out; trades without a conviction too."""
    if trades.empty or "conviction" not in trades:
        return pd.DataFrame(columns=STATS_COLUMNS)
    level = pd.to_numeric(trades["conviction"], errors="coerce")
    frame = trades.assign(conviction=level).dropna(subset=["conviction"])
    rows = []
    for value, group in frame.groupby("conviction"):
        r = (
            pd.to_numeric(group["r_multiple"], errors="coerce").dropna()
            if ("r_multiple" in group)
            else pd.Series(dtype=float)
        )
        rows.append(
            {
                "conviction": int(value),
                "trades": int(len(group)),
                "win_pct": float((group["pnl"] > 0).mean() * 100),
                "mean_r": float(r.mean()) if len(r) else None,
                "total_r": float(r.sum()) if len(r) else None,
            }
        )
    return pd.DataFrame(rows, columns=STATS_COLUMNS)
