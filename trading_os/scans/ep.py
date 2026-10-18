"""Episodic pivot scans (SPEC §6.1, §6.2)."""

from __future__ import annotations

import pandas as pd

from trading_os.config import ScanConfig


def ep_day(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """EP-Day: gap, RVOL, volume, price and market-cap floors. Ranked by gap, largest first."""
    hit = (
        (df["gap_pct"] >= scan["gap_min_pct"])
        & (df["rvol50"] >= scan["rvol_min"])
        & (df["volume"] >= scan["volume_min"])
        & (df["close"] >= scan["price_min"])
        & (df["market_cap"] >= scan["market_cap_min"])
    )
    hits = df.loc[hit].sort_values(["gap_pct", "ticker"], ascending=[False, True])
    return hits.assign(rank=range(1, len(hits) + 1)).reset_index(drop=True)
