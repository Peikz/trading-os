"""The dashboard's 2-year daily bars as one compact file (Emil, 20 Oct 2026).

The per-session Massive files in the data repo stay as they are (append-only). This packs
the last `SESSIONS` of them into `bars_2y_<newest session>_<letter>.parquet`, one small file
per first letter of the ticker (a chart downloads only its letter): only the columns the
charts use, 32-bit numbers, ordinary tickers (ETFs like SPY and QQQ included), sorted by
ticker so one stock's rows sit together. The `bars-pack` workflow refreshes it daily in the
data repo's `bars-2y` release; the dashboard reads it from its cache instead of keeping 500
bar files on the PC.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

from trading_os import history
from trading_os.audit import ordinary_ticker
from trading_os.logsafe import status

SESSIONS = 520  # two years and a little (the 200-day MA needs a run-up)
COLUMNS = ["session_date", "ticker", "open", "high", "low", "close", "volume", "vwap"]
PREFIX = "bars_2y_"


def shard_of(ticker: str) -> str:
    """The file a ticker's bars are in: its first letter, `_` for anything else."""
    first = str(ticker)[:1].upper()
    return first if first.isalpha() else "_"


def pack(data_dir: Path, sessions: int = SESSIONS) -> pd.DataFrame:
    files = sorted((Path(data_dir) / "data" / "bars").rglob("*.parquet"))
    days = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})[-sessions:]
    bars = history.load_bars(Path(data_dir), days)
    bars = bars[bars["ticker"].map(ordinary_ticker)]
    out = bars[[c for c in COLUMNS if c in bars]].copy()
    for column in ("open", "high", "low", "close", "volume", "vwap"):
        if column in out:
            out[column] = out[column].astype("float32")
    return out.sort_values(["ticker", "session_date"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pack the dashboard's 2-year daily bars")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    bars = pack(args.data_dir)
    if bars.empty:
        status("Bars pack: no bars")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    newest = max(bars["session_date"])
    for shard, part in bars.groupby(bars["ticker"].map(shard_of)):
        path = args.out / f"{PREFIX}{newest}_{shard}.parquet"
        part.to_parquet(path, index=False, compression="zstd", row_group_size=100_000)
    sessions = bars["session_date"].nunique()
    files = len(list(args.out.glob(f"{PREFIX}{newest}_*.parquet")))
    status(f"Bars pack: {sessions} sessions, {bars['ticker'].nunique()} tickers, {files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
