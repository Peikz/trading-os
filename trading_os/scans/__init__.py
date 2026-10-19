"""Scan registry. Every scan is a pure function (universe frame, scan config) -> hits frame."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from trading_os.config import Config, ScanConfig
from trading_os.scans.ep import ep9m, ep_ah, ep_day, ep_pm
from trading_os.scans.momentum import mb_down, mb_up
from trading_os.scans.weekly import growth_bucket_1, growth_bucket_2, qm_gainers

ScanFn = Callable[[pd.DataFrame, ScanConfig], pd.DataFrame]

REGISTRY: dict[str, ScanFn] = {
    "ep_pm": ep_pm,
    "ep_day": ep_day,
    "ep_ah": ep_ah,
    "ep9m": ep9m,
    "mb_up": mb_up,
    "mb_down": mb_down,
    "qm_gainers": qm_gainers,
    "growth_bucket_1": growth_bucket_1,
    "growth_bucket_2": growth_bucket_2,
}


def run_scans(universe: pd.DataFrame, cfg: Config, slot: str) -> dict[str, pd.DataFrame]:
    """Run every built and enabled scan for the slot, in config order."""
    return {
        name: REGISTRY[name](universe, scan)
        for name, scan in cfg.scans.items()
        if scan.slot == slot and scan.enabled and name in REGISTRY
    }
