"""Scan registry. Every scan is a pure function (universe frame, scan config) -> hits frame."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from trading_os.config import Config, ScanConfig
from trading_os.scans.ep import (
    ep9m,
    ep9m_early,
    ep9m_pace,
    ep_ah,
    ep_am,
    ep_day,
    ep_pm,
    watchlist_gappers,
)
from trading_os.scans.history_scans import (
    breakout_trigger,
    breakout_watch,
    luk_flush,
    parabolic_long,
    parabolic_short,
    tight_bases,
)
from trading_os.scans.intraday import pivot_watch
from trading_os.scans.momentum import mb_down, mb_up
from trading_os.scans.weekly import growth_bucket_1, growth_bucket_2, qm_gainers

ScanFn = Callable[[pd.DataFrame, ScanConfig], pd.DataFrame]

REGISTRY: dict[str, ScanFn] = {
    "ep_pm": ep_pm,
    "ep9m_early": ep9m_early,
    "watchlist_gappers": watchlist_gappers,
    "ep_day": ep_day,
    "ep_close": ep_day,  # the EP-Day rule on the live data 15 minutes before the close
    "ep_ah": ep_ah,
    "ep_am": ep_am,
    "ep9m": ep9m,
    "ep9m_pace": ep9m_pace,
    "pivot_watch": pivot_watch,
    "mb_up": mb_up,
    "mb_down": mb_down,
    "parabolic_short": parabolic_short,
    "parabolic_long": parabolic_long,
    "breakout_watch": breakout_watch,
    "breakout_trigger": breakout_trigger,
    "qm_gainers": qm_gainers,
    "growth_bucket_1": growth_bucket_1,
    "growth_bucket_2": growth_bucket_2,
    "tight_bases": tight_bases,
    "luk_flush": luk_flush,
}


def run_scans(universe: pd.DataFrame, cfg: Config, slot: str) -> dict[str, pd.DataFrame]:
    """Run every built and enabled scan for the slot, in config order."""
    return {
        name: REGISTRY[name](universe, scan)
        for name, scan in cfg.scans.items()
        if scan.runs_in(slot) and scan.enabled and name in REGISTRY
    }
