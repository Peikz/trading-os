"""Daily price history: append-only bars in the data repo, plus a loader (SPEC §7, Phase 2).

Two sources, one shape:
- `massive`: grouped daily bars (all US stocks, one file per session), from the backfill and
  the daily update. Preferred when present.
- `tradingview`: OHLCV taken from our own canonical EOD universe snapshots. Fills the gap
  until Massive history exists, and covers only the logged-tier universe.

Bars are stored as fetched. Massive's split adjustment is "as of fetch time", which the
`fetched_ts` and `adjusted` columns record.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from trading_os.store import AlreadyWritten

BAR_COLUMNS = [
    "session_date",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "trades",
    "source",
    "adjusted",
    "fetched_ts",
]
SOURCES = ("massive", "tradingview")
# The only snapshot columns history needs (a snapshot has ~100).
SNAPSHOT_COLUMNS = ["run_ts", "session_date", "ticker", "open", "high", "low", "close", "volume"]


def bars_path(data_dir: Path, source: str, session: dt.date) -> Path:
    return (
        Path(data_dir)
        / "data"
        / "bars"
        / source
        / str(session.year)
        / f"{session.isoformat()}.parquet"
    )


def universe_snapshot_path(data_dir: Path, session: dt.date) -> Path:
    return (
        Path(data_dir)
        / "data"
        / "universe"
        / str(session.year)
        / f"{session.isoformat()}_eod.parquet"
    )


def have_bars(data_dir: Path, source: str, session: dt.date) -> bool:
    return bars_path(data_dir, source, session).exists()


def write_bars(data_dir: Path, source: str, session: dt.date, bars: pd.DataFrame) -> Path:
    """Write one session's bars; never overwrite (point-in-time)."""
    path = bars_path(data_dir, source, session)
    if path.exists():
        raise AlreadyWritten(path.name)
    missing = set(BAR_COLUMNS) - set(bars.columns)
    if missing:
        raise ValueError(f"bars missing columns {sorted(missing)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    bars[BAR_COLUMNS].to_parquet(tmp, index=False)
    tmp.rename(path)
    return path


def bars_from_snapshot(snapshot: pd.DataFrame) -> pd.DataFrame:
    """OHLCV of an EOD universe snapshot in the bars shape (source `tradingview`)."""
    out = pd.DataFrame(
        {
            "session_date": pd.to_datetime(snapshot["session_date"]).dt.date,
            "ticker": snapshot["ticker"].astype("string"),
            "open": snapshot["open"],
            "high": snapshot["high"],
            "low": snapshot["low"],
            "close": snapshot["close"],
            "volume": snapshot["volume"].astype("float64"),
            "vwap": float("nan"),
            "trades": pd.array([pd.NA] * len(snapshot), dtype="Int64"),
            "source": "tradingview",
            "adjusted": False,
            "fetched_ts": pd.to_datetime(snapshot["run_ts"], utc=True),
        }
    )
    return out[BAR_COLUMNS]


def load_bars(data_dir: Path, sessions: Iterable[dt.date]) -> pd.DataFrame:
    """Bars for the given sessions, Massive where present, else our EOD snapshots.

    Returns one row per (ticker, session), sorted by ticker then session. Sessions with
    neither source are simply absent; callers see the gap as missing rows.
    """
    frames = []
    for session in sessions:
        massive = bars_path(data_dir, "massive", session)
        if massive.exists():
            frames.append(pd.read_parquet(massive))
            continue
        snapshot = universe_snapshot_path(data_dir, session)
        if snapshot.exists():
            frames.append(bars_from_snapshot(pd.read_parquet(snapshot, columns=SNAPSHOT_COLUMNS)))
    if not frames:
        return pd.DataFrame(columns=BAR_COLUMNS)
    bars = pd.concat(frames, ignore_index=True)
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    return bars.sort_values(["ticker", "session_date"]).reset_index(drop=True)
