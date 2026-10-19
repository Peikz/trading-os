"""Join full-history metrics (history_metrics) onto a job's universe as `hist_*` columns.

Phase 1 scans keep using the TradingView fields (SPEC §11.6); scans that need real history
(Parabolic, tight bases) read the `hist_*` columns, which stay NaN until enough sessions
of bars exist (Massive, or our own EOD snapshots).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from trading_os import clock, history
from trading_os import history_metrics as hm
from trading_os.config import Config

HIST_COLUMNS = [
    "adr20_pct",
    "adr20_usd",
    "rvol50",
    "ret_22",
    "ret_63",
    "ret_126",
    "ma10_rising",
    "ma20_rising",
    "ma50_rising",
    "ma200_rising",
    "dist_ma10_adr",
    "consec_up",
    "consec_down",
    "gain_max_pct",
    "drop_max_pct",
    "range_nd",
    "avg_volume_short",
    "avg_volume_long",
]


def scan_windows(cfg: Config) -> hm.ScanWindows:
    scans = cfg.scans
    return hm.ScanWindows(
        gain_days=scans["parabolic_short"]["lookback_days_max"],
        drop_days=scans["parabolic_long"]["lookback_days_max"],
        range_days=scans["tight_bases"]["range_days"],
        volume_short_days=scans["tight_bases"]["volume_short_days"],
        volume_long_days=scans["tight_bases"]["volume_long_days"],
    )


def todays_bars(df: pd.DataFrame, session: dt.date) -> pd.DataFrame:
    """The current run's daily values in the bars shape."""
    return pd.DataFrame(
        {
            "session_date": session,
            "ticker": df["ticker"].astype("string"),
            "open": df["open"],
            "high": df["high"],
            "low": df["low"],
            "close": df["close"],
            "volume": df["volume"].astype("float64"),
            "source": "tradingview",
        }
    )


def attach_history(
    df: pd.DataFrame, data_dir: Path, cfg: Config, session: dt.date
) -> tuple[pd.DataFrame, int]:
    """`df` plus `hist_*` columns, and how many sessions of history were available."""
    sessions = clock.sessions_back(cfg.schedule, session, hm.LOOKBACK_SESSIONS)
    past = history.load_bars(data_dir, sessions[:-1])
    covered = int(past["session_date"].nunique()) + 1
    bars = pd.concat([past, todays_bars(df, session)], ignore_index=True)
    metrics = hm.compute(bars, sessions, keep=[session], windows=scan_windows(cfg))
    joined = metrics[["ticker", *HIST_COLUMNS]].rename(
        columns={c: f"hist_{c}" for c in HIST_COLUMNS}
    )
    joined["ticker"] = joined["ticker"].astype(df["ticker"].dtype)
    return df.merge(joined, on="ticker", how="left"), covered
