"""Universe exclusions and tiers (SPEC §4).

The logged tier is everything we store. The alert tier decides which hits may push.
Needs the metrics from metrics.add_phase1_metrics.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


def excluded(df: pd.DataFrame, universe: Mapping[str, Any]) -> pd.Series:
    """OTC, funds (ETFs/ETNs), warrants, rights, units and preferred shares."""
    banned_specs = set(universe["exclude_typespecs"])
    has_banned_spec = df["typespecs"].map(lambda specs: bool(set(specs.split(",")) & banned_specs))
    return (
        df["exchange"].isin(universe["exclude_exchanges"])
        | ~df["type"].isin(universe["include_types"])
        | has_banned_spec
    )


def logged_tier(df: pd.DataFrame, universe: Mapping[str, Any]) -> pd.Series:
    t = universe["logged"]
    return (
        (df["close"] >= t["price_min"])
        & (df["market_cap"] >= t["market_cap_min"])
        & (df["avg_dollar_volume_20d"] >= t["avg_dollar_volume_20d_min"])
    )


def alert_tier(df: pd.DataFrame, universe: Mapping[str, Any], slot: str) -> pd.Series:
    """Alert tier. EOD signals also need signal-day dollar volume (SWVL guard)."""
    t = universe["alert"]
    ok = (
        (df["close"] >= t["price_min"])
        & (df["market_cap"] >= t["market_cap_min"])
        & (df["avg_volume_20d"] >= t["avg_volume_20d_min"])
    )
    if slot == "eod":
        ok &= df["dollar_volume"] >= t["signal_dollar_volume_min"]
    return ok


def build_universe(df: pd.DataFrame, universe: Mapping[str, Any], slot: str) -> pd.DataFrame:
    """Logged-tier rows with a `tier` column (alert | log)."""
    keep = ~excluded(df, universe) & logged_tier(df, universe)
    out = df.loc[keep].copy()
    out["tier"] = alert_tier(out, universe, slot).map({True: "alert", False: "log"})
    return out.reset_index(drop=True)
