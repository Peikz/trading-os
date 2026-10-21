"""Your notes per stock (Emil, 21 Oct 2026): free text on the Chart page, kept in the private
data repo (data/journal/stock_notes/<year>/) as an append-only event log, so a note from years
back is still there. Every save, edit and delete is a new row; a note shows its latest text
while its latest event is not a delete.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pandas as pd

from trading_os.journal import normalize_ticker
from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = ["note_id", "action", "ticker", "note_date", "text", "saved_ts"]


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "journal" / "stock_notes"


def _write(data_dir: Path, row: dict) -> None:
    out = folder(data_dir) / str(row["saved_ts"].year)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=COLUMNS)
    frame.to_parquet(out / f"{row['saved_ts']:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def add(data_dir, ticker: str, text: str, note_date: dt.date | None = None) -> str:
    """Save a new note on `ticker` about `note_date` (default today); returns its id."""
    stamp = unique_stamp()
    ticker = normalize_ticker(ticker)
    note_date = pd.Timestamp(note_date or stamp).date()
    note_id = hashlib.sha1(f"{ticker}|{stamp.isoformat()}".encode()).hexdigest()[:10]
    _write(
        data_dir,
        {
            "note_id": note_id,
            "action": "add",
            "ticker": ticker,
            "note_date": note_date,
            "text": text.strip(),
            "saved_ts": stamp,
        },
    )
    return note_id


def edit(data_dir, note_id: str, ticker: str, text: str, note_date: dt.date) -> None:
    """New text for a note; the earlier text stays in the log."""
    _write(
        data_dir,
        {
            "note_id": note_id,
            "action": "edit",
            "ticker": normalize_ticker(ticker),
            "note_date": pd.Timestamp(note_date).date(),
            "text": text.strip(),
            "saved_ts": unique_stamp(),
        },
    )


def remove(data_dir, note_id: str) -> None:
    _write(data_dir, {"note_id": note_id, "action": "remove", "saved_ts": unique_stamp()})


def events(data_dir) -> pd.DataFrame:
    files = sorted(folder(data_dir).glob("*/*.parquet"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def current(data_dir, ticker: str | None = None) -> pd.DataFrame:
    """Live notes (latest text each), newest note day first; one ticker or all. `created_ts`
    is when the note was first written, `saved_ts` when it last changed."""
    log = events(data_dir)
    if not len(log):
        return pd.DataFrame(columns=[*COLUMNS, "created_ts"])
    log = log.sort_values("saved_ts", kind="stable")
    created = log[log["action"] == "add"].groupby("note_id")["saved_ts"].min()
    latest = log.drop_duplicates("note_id", keep="last")
    out = latest[latest["action"] != "remove"].copy()
    out["created_ts"] = out["note_id"].map(created)
    if ticker is not None:
        out = out[out["ticker"] == normalize_ticker(ticker)]
    out = out.sort_values(["note_date", "created_ts"], ascending=False)
    return out.reset_index(drop=True)
