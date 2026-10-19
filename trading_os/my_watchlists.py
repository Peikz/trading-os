"""Your own watchlists (Emil, 20 Oct 2026), next to the scans' EP-Watch and BO-Watch.

Kept as an append-only event log in the private data repo (data/my_watchlists/): every add
and remove is a new row, and a list's current members are the tickers whose latest event is
an add. A list exists while it has members. Separate from data/watchlists/, which the jobs
write. Tickers can be typed in or imported from a TradingView watchlist export (a .txt of
`EXCHANGE:TICKER` symbols separated by commas or new lines; `###SECTION` headers skipped).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from trading_os.journal import normalize_ticker
from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = ["list", "ticker", "action", "note", "saved_ts"]
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "my_watchlists"


def parse_tickers(text: str) -> list[str]:
    """Tickers from free text or a TradingView export, in order, without duplicates."""
    out = []
    for raw in re.split(r"[\s,;]+", text or ""):
        if not raw or raw.startswith("###"):
            continue
        ticker = normalize_ticker(raw)
        if TICKER.match(ticker) and ticker not in out:
            out.append(ticker)
    return out


def _write(data_dir: Path, rows: list[dict]) -> None:
    out = folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = rows[0]["saved_ts"]
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame.to_parquet(out / f"{stamp:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def add(data_dir: Path, list_name: str, tickers: list[str], note: str = "") -> int:
    """Add tickers to a list (created on first add); returns how many were given."""
    name = list_name.strip()
    if not name:
        raise ValueError("the list needs a name")
    if not tickers:
        return 0
    stamp = unique_stamp()
    _write(
        data_dir,
        [
            {"list": name, "ticker": t, "action": "add", "note": note, "saved_ts": stamp}
            for t in tickers
        ],
    )
    return len(tickers)


def remove(data_dir: Path, list_name: str, tickers: list[str]) -> None:
    if not tickers:
        return
    stamp = unique_stamp()
    rows = [
        {"list": list_name, "ticker": t, "action": "remove", "note": "", "saved_ts": stamp}
        for t in tickers
    ]
    _write(data_dir, rows)


def load(data_dir: Path) -> pd.DataFrame:
    files = sorted(folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def current(events: pd.DataFrame) -> pd.DataFrame:
    """Members now: list, ticker, the note and when it was added (latest add)."""
    if events.empty:
        return pd.DataFrame(columns=["list", "ticker", "note", "added"])
    latest = events.sort_values("saved_ts").drop_duplicates(["list", "ticker"], keep="last")
    members = latest[latest["action"] == "add"]
    out = members.rename(columns={"saved_ts": "added"})[["list", "ticker", "note", "added"]]
    return out.sort_values(["list", "ticker"]).reset_index(drop=True)


def lists(events: pd.DataFrame) -> list[str]:
    return sorted(current(events)["list"].unique())


MARKET_COLUMNS = [
    "close",
    "chg_pct",
    "rvol50",
    "adr20_pct",
    "rs_pct",
    "pct_from_52w_high",
    "ret_22",
    "ret_63",
    "above_ma50",
    "above_ma200",
    "earnings_in_sessions",
    "industry",
    "on_ep_watch",
    "on_bo_watch",
    "bo_pivot",
]


def with_market(members: pd.DataFrame, universe: pd.DataFrame, hits: pd.DataFrame) -> pd.DataFrame:
    """Members with the latest snapshot's facts and the scans they hit in that run."""
    out = members.copy()
    if not universe.empty:
        cols = ["ticker", *[c for c in MARKET_COLUMNS if c in universe]]
        out = out.merge(universe[cols], on="ticker", how="left")
        if "bo_pivot" in out and "close" in out:
            out["to_pivot_pct"] = (out["bo_pivot"] / out["close"] - 1) * 100
    if not hits.empty:
        scans = hits.groupby("ticker")["scan"].agg(lambda s: ", ".join(sorted(set(s))))
        out["in_scans"] = out["ticker"].map(scans).fillna("")
    return out
