"""Broker fills from an uploaded file (.csv or .xlsx): read it, say what is in it, import it.

The Journal page's upload box (21 Nov 2026). The columns are mapped with the same config as
the command line (`journal.csv_columns`), so there is no broker-specific code here: the reader
is generic and tolerant (headers in any case, stray spaces, a title above the header row,
Excel sheets, `;` or tab separators, decimal commas). `preview` changes nothing; `run_import`
is the same append-only import and rebuild as `python -m trading_os.journal --csv`, so
importing a file twice adds nothing. Private data: nothing is logged, only counts are shown.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import journal

EXTENSIONS = ("csv", "xlsx")
HEADER_SEARCH_ROWS = 30  # a title or a few blank rows may sit above the header row


@dataclass
class Preview:
    """What an upload holds, before anything is written."""

    rows: int = 0
    found: dict[str, str] = field(default_factory=dict)  # standard name -> header in the file
    missing: list[str] = field(default_factory=list)  # configured headers the file lacks
    new: int = 0
    existing: int = 0
    first_date: Any = None
    last_date: Any = None
    sheet: str | None = None
    error: str | None = None
    fills: pd.DataFrame | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.fills is not None


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return content.decode(encoding)
        except (UnicodeError, ValueError):
            continue
    return content.decode("latin-1")


def _csv_grid(content: bytes) -> list[list[Any]]:
    text = _decode(content)
    head = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t|", key=head.count) if head else ","
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _xlsx_grids(content: bytes) -> dict[str, list[list[Any]]]:
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - zip/xml errors of any kind
        raise ValueError(f"the Excel file can't be opened ({type(exc).__name__})") from None
    try:
        return {sheet.title: [list(row) for row in sheet.iter_rows(values_only=True)]
                for sheet in book.worksheets}  # fmt: skip
    finally:
        book.close()


def _blank(value: Any) -> bool:
    return (
        value is None
        or (isinstance(value, float) and value != value)
        or (isinstance(value, str) and not value.strip())
    )


def _frame(grid: list[list[Any]], rules) -> tuple[pd.DataFrame, int]:
    """The table under the header row that matches most of the mapped headers (a title or
    blank rows above it are skipped), and how many of those headers it matched."""
    wanted = {journal.squash_header(h) for h in rules["csv_columns"].values()}
    best, best_hits = 0, -1
    for i, row in enumerate(grid[:HEADER_SEARCH_ROWS]):
        hits = len({journal.squash_header(c) for c in row if not _blank(c)} & wanted)
        if hits > best_hits:
            best, best_hits = i, hits
    if not grid:
        return pd.DataFrame(), 0
    names = [
        str(c).strip() if not _blank(c) else f"column{n + 1}" for n, c in enumerate(grid[best])
    ]
    width = len(names)
    body = [(row + [None] * width)[:width] for row in grid[best + 1 :]]
    frame = pd.DataFrame(body, columns=names)
    frame = frame[~frame.map(_blank).all(axis=1)].reset_index(drop=True)
    return frame, max(best_hits, 0)


def read_table(name: str, content: bytes, rules) -> tuple[pd.DataFrame, str | None]:
    """The export as a table, and the Excel sheet it came from (None for a CSV). Raises
    ValueError for a file that is neither .csv nor .xlsx or can't be read."""
    ext = Path(name).suffix.lower().lstrip(".")
    if ext == "csv":
        return _frame(_csv_grid(content), rules)[0], None
    if ext == "xlsx":
        grids = _xlsx_grids(content)
        scored = {title: _frame(grid, rules) for title, grid in grids.items() if grid}
        if not scored:
            raise ValueError("the Excel file has no rows")
        title = max(scored, key=lambda t: (scored[t][1], len(scored[t][0])))
        return scored[title][0], title
    raise ValueError(f"unsupported file type '.{ext}': upload a .csv or .xlsx export")


def preview(data_dir: Path, rules, name: str, content: bytes) -> Preview:
    """Read an upload and report rows, columns found/missing, new vs already imported fills and
    the date range. Never writes; a problem lands in `error` (a readable message)."""
    out = Preview()
    try:
        raw, out.sheet = read_table(name, content, rules)
        out.rows = len(raw)
        out.found, out.missing = journal.find_columns(raw, rules)
        if out.missing:
            raise ValueError(
                f"the file is missing columns {out.missing}; it has {list(raw.columns)}. "
                "Adjust journal.csv_columns in config/scans.yaml to its headers."
            )
        out.fills = journal.fills_from_frame(raw, rules)
    except ValueError as exc:
        out.error = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001 - a malformed file must not take the page down
        out.error = f"the file can't be read ({type(exc).__name__}); is it a fills export?"
        return out
    if out.fills.empty:
        out.error = "the file has a header but no fills under it"
        out.fills = None
        return out
    known = journal.load_fills(data_dir)
    out.new = len(journal.new_fills(known, out.fills))
    out.existing = len(out.fills) - out.new
    out.first_date, out.last_date = out.fills["trade_date"].min(), out.fills["trade_date"].max()
    return out


def run_import(data_dir: Path, cfg, name: str, content: bytes) -> str:
    """Import an upload (append-only; fills already imported are skipped) and rebuild the
    journal. Returns the same one-line summary as the command line. Raises ValueError with the
    reason when the file can't be imported."""
    seen = preview(data_dir, cfg.journal, name, content)
    if not seen.ok:
        raise ValueError(seen.error)
    return journal.import_fills(data_dir, cfg, seen.fills)


def summary_lines(seen: Preview) -> list[str]:
    """The preview as short lines for the page (no tickers: counts, columns and dates)."""
    if seen.error:
        return [seen.error]
    lines = [f"{seen.rows} rows read" + (f" from sheet '{seen.sheet}'" if seen.sheet else "")]
    lines.append(
        "columns found: "
        + ", ".join(f"{t} ← {h}" for t, h in seen.found.items())
        + (" · fees: none in the file, 0 used" if "fees" not in seen.found else "")
    )
    lines.append(f"{seen.new} new fills, {seen.existing} already imported")
    lines.append(f"dates {seen.first_date} to {seen.last_date}")
    return lines
