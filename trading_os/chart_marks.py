"""Your saved chart drawings (Emil, 20 Oct 2026): trend lines and anchored-VWAP anchors per
ticker, kept in the private data repo (data/chart_marks/) as an append-only event log: every
add and remove is a new row; a mark is current while its latest event is an add.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from trading_os.journal import normalize_ticker
from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = [
    "mark_id",
    "action",
    "kind",
    "ticker",
    "label",
    "x0",
    "y0",
    "x1",
    "y1",
    "extend",
    "anchor",
    "saved_ts",
]


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "chart_marks"


def _write(data_dir: Path, row: dict) -> None:
    out = folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=COLUMNS)
    frame.to_parquet(out / f"{row['saved_ts']:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def _new_id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def add_line(data_dir, ticker, x0, y0: float, x1, y1: float, label="", extend=True) -> str:
    """Save a trend line through two (date, price) points; returns its id."""
    stamp = unique_stamp()
    ticker = normalize_ticker(ticker)
    mark_id = _new_id("line", ticker, x0, y0, x1, y1, stamp.isoformat())
    _write(
        data_dir,
        {
            "mark_id": mark_id,
            "action": "add",
            "kind": "line",
            "ticker": ticker,
            "label": label,
            "x0": pd.Timestamp(x0).date(),
            "y0": float(y0),
            "x1": pd.Timestamp(x1).date(),
            "y1": float(y1),
            "extend": bool(extend),
            "saved_ts": stamp,
        },
    )
    return mark_id


def add_anchor(data_dir, ticker, anchor, label="") -> str:
    """Save an anchored-VWAP anchor date; returns its id."""
    stamp = unique_stamp()
    ticker = normalize_ticker(ticker)
    mark_id = _new_id("anchor", ticker, anchor, stamp.isoformat())
    _write(
        data_dir,
        {
            "mark_id": mark_id,
            "action": "add",
            "kind": "anchor",
            "ticker": ticker,
            "label": label,
            "anchor": pd.Timestamp(anchor).date(),
            "saved_ts": stamp,
        },
    )
    return mark_id


def remove(data_dir, mark_id: str) -> None:
    _write(data_dir, {"mark_id": mark_id, "action": "remove", "saved_ts": unique_stamp()})


def current(data_dir, ticker: str) -> pd.DataFrame:
    """The ticker's marks whose latest event is an add."""
    files = sorted(folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    events = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    latest = events.sort_values("saved_ts").drop_duplicates("mark_id", keep="last")
    adds = events[events["action"] == "add"].drop_duplicates("mark_id")
    alive = set(latest.loc[latest["action"] == "add", "mark_id"])
    out = adds[adds["mark_id"].isin(alive) & (adds["ticker"] == normalize_ticker(ticker))]
    return out.reset_index(drop=True)
