"""Scan registry. Every scan is a pure function (universe frame, scan config) -> hits frame."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from trading_os.config import Config, ScanConfig
from trading_os.scans.ep import ep_day

ScanFn = Callable[[pd.DataFrame, ScanConfig], pd.DataFrame]

REGISTRY: dict[str, ScanFn] = {
    "ep_day": ep_day,
}


def run_scans(universe: pd.DataFrame, cfg: Config, slot: str) -> dict[str, pd.DataFrame]:
    """Run every built and enabled scan for the slot, in config order."""
    return {
        name: REGISTRY[name](universe, scan)
        for name, scan in cfg.scans.items()
        if scan.slot == slot and scan.enabled and name in REGISTRY
    }
