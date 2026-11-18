"""The Chart page's stock lists: the source lists to step through (today's hits, each of your
watchlists, open positions, the Screener's last result) with a last close, the day's change
and, for scan hits, the setup and grade. Display only: nothing here writes data."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pandas as pd

from trading_os import dashboard, my_watchlists, notify

HITS = "Today's hits"
POSITIONS = "Open positions"
SCREENER = "Last screener result"
GRADE_ORDER = ["A+++", "A++", "A+", "A", "B", "C"]  # then ungraded
COLUMNS = ["ticker", "close", "chg_pct", "setup", "grade"]


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS)


def hit_rows(runs, frames: Callable[[str], pd.DataFrame] = pd.read_parquet) -> pd.DataFrame:
    """Every alert-tier hit of the newest session's runs, one row per ticker (its best grade, then
    pushed first): ticker, setup label and grade."""
    if not runs:
        return _frame([])
    today = [r for r in runs if r.session == runs[0].session]
    parts = [frames(str(r.candidates)) for r in today]
    hits = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if hits.empty:
        return _frame([])
    if "tier" in hits:
        hits = hits[hits["tier"] == "alert"]
    pushed = hits["pushed"] if "pushed" in hits else pd.Series(False, index=hits.index)
    hits = hits.assign(_pushed=pushed.fillna(False).astype(bool))
    grade = hits["grade"] if "grade" in hits else pd.Series(None, index=hits.index, dtype=object)
    rank = grade.map({g: i for i, g in enumerate(GRADE_ORDER)}).fillna(len(GRADE_ORDER))
    hits = hits.assign(_rank=rank).sort_values(
        ["_rank", "_pushed"], ascending=[True, False], kind="stable"
    )
    rows: dict[str, dict] = {}
    for row in hits.to_dict("records"):
        grade = row.get("grade")
        rows.setdefault(
            row["ticker"],
            {
                "ticker": row["ticker"],
                "setup": notify.SCAN_LABELS.get(row["scan"], row["scan"]),
                "grade": grade if isinstance(grade, str) else "",
            },
        )
    return _frame(list(rows.values()))


def with_prices(rows: pd.DataFrame, snapshot: pd.DataFrame | None) -> pd.DataFrame:
    """Rows with close and chg_pct from the universe snapshot (blank where it lacks the stock)."""
    rows = rows.drop(columns=["close", "chg_pct"], errors="ignore")
    have = [c for c in ("close", "chg_pct") if snapshot is not None and c in snapshot]
    if snapshot is not None and have and "ticker" in snapshot:
        rows = rows.merge(snapshot[["ticker", *have]].drop_duplicates("ticker"), how="left")
    for c in ("close", "chg_pct"):
        if c not in rows:
            rows[c] = float("nan")
    for c in ("setup", "grade"):
        if c not in rows:
            rows[c] = ""
    return rows[COLUMNS].reset_index(drop=True)


def build(
    data_dir: Path,
    runs,
    frames: Callable[[str], pd.DataFrame] = pd.read_parquet,
    screener: Sequence[str] = (),
    snapshot: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """List name -> its rows (`COLUMNS`). Empty lists are left out. `snapshot` is the newest
    universe (ticker, close, chg_pct) for the price columns."""
    out: dict[str, pd.DataFrame] = {HITS: hit_rows(runs, frames)}
    events = my_watchlists.load(data_dir)
    members = my_watchlists.current(events)
    for name in my_watchlists.lists(events):
        tickers = list(members.loc[members["list"] == name, "ticker"])
        out[name] = _frame([{"ticker": t} for t in tickers])
    positions = dashboard.latest_positions(data_dir)
    out[POSITIONS] = _frame([{"ticker": t} for t in positions.get("ticker", [])])
    out[SCREENER] = _frame([{"ticker": t} for t in screener])
    return {name: with_prices(rows, snapshot) for name, rows in out.items() if len(rows)}


def where_is(
    lists: Mapping[str, pd.DataFrame], ticker: str, prefer: str | None = None
) -> str | None:
    """The list to show for a ticker: `prefer` if it has it, else the first list that does."""
    if prefer in lists and ticker in set(lists[prefer]["ticker"]):
        return prefer
    return next((n for n, rows in lists.items() if ticker in set(rows["ticker"])), None)


def neighbour(tickers: Sequence[str], current: str, by: int) -> str | None:
    """The ticker `by` steps from `current` in the list (wrapping); the first (or, going back,
    the last) when the current one is not in it."""
    tickers = list(tickers)
    if not tickers:
        return None
    if current not in tickers:
        return tickers[0] if by > 0 else tickers[-1]
    return tickers[(tickers.index(current) + by) % len(tickers)]


def row_label(row: Mapping, chips: bool = False) -> str:
    """One row as a button label: ticker, close, change (green/red) and, for hits, setup and
    grade. `chips`: just ticker and change, for the phone's one-line strip."""
    chg = row.get("chg_pct")
    change = ""
    if chg is not None and pd.notna(chg):
        change = f":{'green' if chg >= 0 else 'red'}[{chg:+.1f}%]"
    close = row.get("close")
    price = f"{close:,.2f}" if close is not None and pd.notna(close) else ""
    if chips:
        return " ".join(x for x in (f"**{row['ticker']}**", change) if x)
    head = " ".join(x for x in (f"**{row['ticker']}**", price, change) if x)
    tag = " ".join(x for x in (row.get("setup") or "", row.get("grade") or "") if x)
    return f"{head}  \n{tag}" if tag else head
