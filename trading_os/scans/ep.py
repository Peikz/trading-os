"""Episodic pivot scans (SPEC §6.1, §6.2)."""

from __future__ import annotations

import pandas as pd

from trading_os.config import PM_GAP_COLUMNS, ScanConfig


def ranked(df: pd.DataFrame, hit: pd.Series, by: str, ascending: bool = False) -> pd.DataFrame:
    """Hits sorted by `by` (ties broken by ticker) with a 1-based `rank` column."""
    hits = df.loc[hit].sort_values([by, "ticker"], ascending=[ascending, True])
    return hits.assign(rank=range(1, len(hits) + 1)).reset_index(drop=True)


def ep_pm(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """EP-PM: pre-market move, pre-market volume, price and market-cap floors.

    Price is the prior close (the alert tier's price). Ranked by pre-market change.
    """
    hit = (
        (df["pm_change_pct"] >= scan["pm_change_min_pct"])
        & (df["close"] >= scan["price_min"])
        & (df["pm_volume"] >= scan["pm_volume_min"])
        & (df["market_cap"] >= scan["market_cap_min"])
    )
    return ranked(df, hit, "pm_change_pct")


def ep9m_early(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """EP9M early warning: heavy pre-market volume and a pre-market gap.

    Which gap (current pre-market price, or the first pre-market print) is `pm_gap_basis`
    in config; the value used is stored as `pm_gap_used`. Ranked by pre-market volume.
    """
    out = df.assign(pm_gap_used=df[PM_GAP_COLUMNS[scan["pm_gap_basis"]]])
    hit = (out["pm_volume"] >= scan["pm_volume_min"]) & (
        out["pm_gap_used"] >= scan["pm_gap_min_pct"]
    )
    return ranked(out, hit, "pm_volume")


def watchlist_gappers(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Names on the configured watchlists gapping in pre-market. Ranked by the gap.

    Membership comes from the `on_<list>` columns the job adds from the watchlist state.
    """
    out = df.assign(pm_gap_used=df[PM_GAP_COLUMNS[scan["pm_gap_basis"]]])
    on_list = pd.Series(False, index=out.index)
    for name in scan["lists"]:
        on_list |= out.get(f"on_{name}", pd.Series(False, index=out.index)).fillna(False)
    hit = on_list & (out["pm_gap_used"] >= scan["pm_gap_min_pct"])
    return ranked(out, hit.astype(bool), "pm_gap_used")


def ep_day(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """EP-Day: gap, RVOL, volume, price and market-cap floors. Ranked by gap, largest first."""
    hit = (
        (df["gap_pct"] >= scan["gap_min_pct"])
        & (df["rvol50"] >= scan["rvol_min"])
        & (df["volume"] >= scan["volume_min"])
        & (df["close"] >= scan["price_min"])
        & (df["market_cap"] >= scan["market_cap_min"])
    )
    return ranked(df, hit, "gap_pct")


def ep9m(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Stockbee EP9M: 9M+ shares and up 4 %+. No MA filter; MA position is stored as columns.

    Ranked by volume, largest first.
    """
    hit = (df["volume"] >= scan["volume_min"]) & (df["chg_pct"] >= scan["chg_min_pct"])
    return ranked(df, hit, "volume")


def ep9m_pace(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """EP9M during the session: up 4 %+ and 9M+ shares traded or on pace (Emil, 19 Oct 2026).

    Pace = TradingView's relative volume at this time of day (5-minute bars) x the stock's
    normal daily volume (the RVOL base, today excluded), and never below what has already
    traded. Stored as `proj_volume`. Ranked by it, largest first.
    """
    pace = df["rvol_at_time_tv"] * df["rvol_base_volume"]
    out = df.assign(proj_volume=pace.where(pace > df["volume"], df["volume"]))
    hit = (out["proj_volume"] >= scan["volume_min"]) & (out["chg_pct"] >= scan["chg_min_pct"])
    return ranked(out, hit, "proj_volume")


def ep_ah(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """EP-AH: post-market move at the EOD run (toggle, default off).

    Ranked by post-market change.
    """
    hit = (
        (df["ah_change_pct"] >= scan["ah_change_min_pct"])
        & (df["close"] >= scan["price_min"])
        & (df["market_cap"] >= scan["market_cap_min"])
        & (df["ah_volume"] >= scan["ah_volume_min"])
    )
    return ranked(df, hit, "ah_change_pct")
