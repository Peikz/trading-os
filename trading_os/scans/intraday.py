"""Scans that run during the session (SPEC §6.1b)."""

from __future__ import annotations

import pandas as pd

from trading_os.config import ScanConfig
from trading_os.scans.ep import ranked


def pivot_watch(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """BO-Watch names at or near their pivot during the session (Emil, 19 Oct 2026).

    Pivot and order stop come from the latest EOD run where the name passed B1-B4 (the job
    merges them in). A hit is a price at most `near_pivot_pct` % below the pivot, or above it;
    `pivot_crossed` says which and `pivot_dist_pct` how far. Ranked by relative volume at this
    time of day, strongest first: breakouts need volume, and the grade stays the human's.
    """
    if "pivot" not in df:
        return df.iloc[0:0].assign(rank=pd.Series(dtype="int64"))
    on_list = df.get("on_bo_watch", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    out = df.assign(
        pivot_dist_pct=(df["close"] / df["pivot"] - 1) * 100,
        pivot_crossed=df["close"] >= df["pivot"],
    )
    hit = on_list & df["pivot"].notna() & (out["pivot_dist_pct"] >= -scan["near_pivot_pct"])
    return ranked(out, hit, "rvol_at_time_tv")
