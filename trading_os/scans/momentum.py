"""Stockbee Momentum Burst scans (SPEC §6.2). Logged only, never pushed."""

from __future__ import annotations

import pandas as pd

from trading_os.config import ScanConfig
from trading_os.scans.ep import ranked


def _volume_rule(df: pd.DataFrame, scan: ScanConfig) -> pd.Series:
    ok = df["volume"] >= scan["volume_min"]
    if scan["volume_gt_prior"]:
        ok &= df["volume"] > df["prev_volume"]
    return ok


def mb_up(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Up 4 %+, volume above the prior day, closing near the high. Ranked by change."""
    hit = (
        (df["chg_pct"] >= scan["chg_min_pct"])
        & _volume_rule(df, scan)
        & (df["close_loc"] >= scan["close_loc_min"])
    )
    return ranked(df, hit, "chg_pct")


def mb_down(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Down 4 %+ on volume above the prior day. Ranked by change, biggest drop first."""
    hit = (df["chg_pct"] <= scan["chg_max_pct"]) & _volume_rule(df, scan)
    return ranked(df, hit, "chg_pct", ascending=True)
