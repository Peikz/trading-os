"""Daily notes with stock tags (Emil, 22 Oct 2026): a note about a day in the Journal, tagged
with the stocks it is about. A tagged note also shows on each tagged stock's Chart page, under
its notes. Kept in the private data repo (data/journal/daily_notes/<year>/) as an append-only
event log like the stock notes: every save, edit and delete is a new row, and a note shows its
latest text while its latest event is not a delete.

Tags come from the tag field and from `$TICKER` written in the text.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path

import pandas as pd

from trading_os.journal import normalize_ticker
from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = ["note_id", "action", "note_date", "text", "tags", "saved_ts"]
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9.\-]{0,9})\b")


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "journal" / "daily_notes"


def tags_from(text: str, typed: str = "") -> list[str]:
    """Tickers from the tag field (comma or space separated) and `$TICKER` in the text, in
    order, without duplicates."""
    out: list[str] = []
    for raw in [*re.split(r"[\s,;]+", typed or ""), *CASHTAG.findall(text or "")]:
        ticker = normalize_ticker(raw.lstrip("$")) if raw else ""
        if TICKER.match(ticker) and ticker not in out:
            out.append(ticker)
    return out


def _write(data_dir: Path, row: dict) -> None:
    out = folder(data_dir) / str(row["saved_ts"].year)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=COLUMNS)
    frame.to_parquet(out / f"{row['saved_ts']:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def add(data_dir, text: str, note_date: dt.date | None = None, typed_tags: str = "") -> str:
    """Save a daily note (default: today); returns its id."""
    stamp = unique_stamp()
    note_id = hashlib.sha1(f"day|{stamp.isoformat()}".encode()).hexdigest()[:10]
    _write(
        data_dir,
        {
            "note_id": note_id,
            "action": "add",
            "note_date": pd.Timestamp(note_date or stamp).date(),
            "text": text.strip(),
            "tags": ",".join(tags_from(text, typed_tags)),
            "saved_ts": stamp,
        },
    )
    return note_id


def edit(data_dir, note_id: str, text: str, note_date: dt.date, typed_tags: str = "") -> None:
    """New text, day or tags for a note; the earlier version stays in the log."""
    _write(
        data_dir,
        {
            "note_id": note_id,
            "action": "edit",
            "note_date": pd.Timestamp(note_date).date(),
            "text": text.strip(),
            "tags": ",".join(tags_from(text, typed_tags)),
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
    """Live daily notes (latest version each), newest day first; with `ticker`, only the notes
    tagged with it. `tag_list` holds the tags as a list."""
    log = events(data_dir)
    if not len(log):
        return pd.DataFrame(columns=[*COLUMNS, "created_ts", "tag_list"])
    log = log.sort_values("saved_ts", kind="stable")
    created = log[log["action"] == "add"].groupby("note_id")["saved_ts"].min()
    latest = log.drop_duplicates("note_id", keep="last")
    out = latest[latest["action"] != "remove"].copy()
    out["created_ts"] = out["note_id"].map(created)
    out["tag_list"] = [[t for t in str(v or "").split(",") if t] for v in out["tags"]]
    if ticker is not None:
        wanted = normalize_ticker(ticker)
        out = out[[wanted in tags for tags in out["tag_list"]]]
    out = out.sort_values(["note_date", "created_ts"], ascending=False)
    return out.reset_index(drop=True)


def all_tags(data_dir) -> list[str]:
    """Every stock tagged in a live note, A to Z."""
    notes = current(data_dir)
    return sorted({t for tags in notes["tag_list"] for t in tags}) if len(notes) else []
