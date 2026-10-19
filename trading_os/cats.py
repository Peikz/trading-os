"""CATS score (SPEC §6.3): a ranking column, never a filter.

growth-bucket hit + recent MB/EP + volume trend − extension penalty. SPEC names the parts
but not the weights, so every number is in config `cats:` (proposed). Each component is
stored next to the score so the ranking can be audited.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os.tv import canonical


def recent_signal_tickers(
    candidates: pd.DataFrame, scans: list[str], sessions: list[dt.date]
) -> set[str]:
    """Tickers with a hit of one of `scans` in `sessions` (canonical runs only)."""
    if candidates.empty:
        return set()
    recent = candidates[candidates["scan"].isin(scans) & candidates["session_date"].isin(sessions)]
    return set(recent["ticker"])


def add_cats(
    hits: pd.DataFrame,
    growth_tickers: set[str],
    recent_tickers: set[str],
    rules: Mapping[str, Any],
) -> pd.DataFrame:
    """`hits` plus cats and its components."""
    out = hits.copy()
    if out.empty:
        for column in ("cats", "cats_growth", "cats_recent", "cats_volume", "cats_extension"):
            out[column] = pd.Series(dtype="float64")
        return out
    short, long = (canonical(f) for f in rules["volume_trend_fields"])
    with np.errstate(divide="ignore", invalid="ignore"):
        volume_rising = (out[short] / out[long]) > 1
    extension = (out["dist_ma10_adr"] - rules["extension_free_adr"]).clip(lower=0).fillna(0)
    out["cats_growth"] = out["ticker"].isin(growth_tickers) * rules["growth_bucket_points"]
    out["cats_recent"] = out["ticker"].isin(recent_tickers) * rules["recent_signal_points"]
    out["cats_volume"] = volume_rising.fillna(False) * rules["volume_trend_points"]
    out["cats_extension"] = -extension * rules["extension_penalty_per_adr"]
    out["cats"] = out[["cats_growth", "cats_recent", "cats_volume", "cats_extension"]].sum(axis=1)
    return out
