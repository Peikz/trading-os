"""Ten-year histories (Emil, 20 Oct 2026): the strategy and EP studies over Alpaca's daily bars
since 2016, one calendar year per run, so GitHub runs the years as parallel jobs (a laptop
with 8 GB can't hold ten years of grids).

Each year runs on its own window of sessions: `LEAD` before it (the 52-week, 200-day and base
windows need them) and `TAIL` after it (outcomes reach 252 sessions out). Only the hits dated
in the year are kept, so the years join without overlap. The code is the same as the 2-year
studies; only the bars differ (Alpaca, split- and dividend-adjusted, delisted names included).
2016 starts thin: its first months have no full 52-week or 200-day window yet.

Output (one year): `strategy_<year>.parquet` and `ep_<year>.parquet` in `--out`, uploaded by
the workflow to the data repo's `history-10y` release. Logs print counts only.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from trading_os import clock, ep_history, strategy_history
from trading_os.logsafe import status
from trading_os.store import PARQUET_OPTIONS

LEAD, TAIL = 300, 260
BAR_COLUMNS = ["session_date", "ticker", "open", "high", "low", "close", "volume"]


def load_years(folder: Path, first: int, last: int) -> pd.DataFrame:
    """Alpaca's yearly daily-bar files (`YYYY.parquet`) for the years first..last."""
    frames = []
    for year in range(first, last + 1):
        path = Path(folder) / f"{year}.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path, columns=BAR_COLUMNS))
    if not frames:
        return pd.DataFrame(columns=BAR_COLUMNS)
    bars = pd.concat(frames, ignore_index=True)
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    for column in ("open", "high", "low", "close"):
        bars[column] = bars[column].astype("float64")
    bars["volume"] = bars["volume"].astype("float64")
    return bars.sort_values(["ticker", "session_date"]).reset_index(drop=True)


def window(schedule, year: int, newest: dt.date) -> tuple[list[dt.date], list[dt.date]]:
    """(all sessions of the run, the sessions inside `year`)."""
    first = dt.date(year, 1, 1)
    last = min(dt.date(year, 12, 31), newest)
    inside = [s for s in clock.sessions_back(schedule, last, 300) if s >= first]
    before = clock.sessions_back(schedule, first - dt.timedelta(days=1), LEAD)
    after = clock.sessions_after(schedule, inside[-1], TAIL, newest) if inside else []
    return [*before, *inside, *after], inside


def newest_universe(data_dir: Path) -> pd.DataFrame:
    """ticker, tv_ticker, market_cap from the newest universe snapshot, picked by the date in
    its name (file times are all the same in a fresh checkout)."""
    root = Path(data_dir) / "data"
    files = [*root.glob("universe/*/*.parquet"), *root.glob("manual/*/universe.parquet")]
    named = [(f.parent.name if f.name == "universe.parquet" else f.stem, f) for f in files]
    if not named:
        return pd.DataFrame(columns=["ticker", "tv_ticker", "market_cap"])
    _, newest = max(named)
    cols = ["ticker", "tv_ticker", "market_cap"]
    return pd.read_parquet(newest, columns=cols).drop_duplicates("ticker")


def run_year(year: int, bars_dir: Path, data_dir: Path, cfg, fundamentals: bool = True):
    """(strategy hits, EP hits) dated in `year`."""
    bars = load_years(bars_dir, year - 2, year + 2)
    if bars.empty:
        return pd.DataFrame(), pd.DataFrame()
    newest = bars["session_date"].max()
    sessions, inside = window(cfg.schedule, year, newest)
    have = set(bars["session_date"])
    sessions = [s for s in sessions if s in have]
    bars = bars[bars["session_date"].isin(set(sessions))]
    keep = set(inside)

    caps = {}
    snap = newest_universe(data_dir)
    if len(snap):
        caps = dict(zip(snap["ticker"], snap["market_cap"], strict=True))
    strategies = strategy_history.find(bars, sessions, cfg, caps)
    strategies = strategies[strategies["session_date"].isin(keep)].reset_index(drop=True)

    eps = ep_history.find(bars, sessions, cfg)
    eps = eps[eps["session_date"].isin(keep)].reset_index(drop=True)
    if fundamentals and len(eps):
        from trading_os import tv

        listed = snap[snap["ticker"].isin(set(eps["ticker"]))] if len(snap) else snap
        if len(listed):
            details = ep_history.fetch_details(listed["tv_ticker"].tolist(), tv.fetch_details)
            joined = details.join(listed.set_index("tv_ticker")["ticker"]).set_index("ticker")
            eps = ep_history.add_fundamentals(eps, joined, cfg)
    return strategies, eps


def _slim(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.select_dtypes("float64").columns:
        out[column] = out[column].astype("float32")
    return out


def load(folder: Path, kind: str, columns: list[str] | None = None) -> pd.DataFrame:
    """Every downloaded year of one kind (`strategy` or `ep`), optionally only `columns`."""
    files = sorted(Path(folder).glob(f"{kind}_*.parquet"))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        if columns:
            names = set(pq.read_schema(f).names)
            frames.append(pd.read_parquet(f, columns=[c for c in columns if c in names]))
        else:
            frames.append(pd.read_parquet(f))
    out = pd.concat(frames, ignore_index=True)
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out


def main(argv: list[str] | None = None) -> int:
    from trading_os.logsafe import run_guarded

    return run_guarded(lambda: _main(argv), None, "Long history")


def _main(argv: list[str] | None = None) -> int:
    from trading_os.config import load_config

    parser = argparse.ArgumentParser(description="One year of the 10-year history studies")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--bars", type=Path, required=True, help="folder of YYYY.parquet files")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-fundamentals", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config()
    strategies, eps = run_year(
        args.year, args.bars, args.data_dir, cfg, fundamentals=not args.no_fundamentals
    )
    args.out.mkdir(parents=True, exist_ok=True)
    _slim(strategies).to_parquet(args.out / f"strategy_{args.year}.parquet", **PARQUET_OPTIONS)
    _slim(eps).to_parquet(args.out / f"ep_{args.year}.parquet", **PARQUET_OPTIONS)
    counts = strategies.groupby("strategy").size().to_dict() if len(strategies) else {}
    ep_days = int(eps["is_ep_day"].sum()) if len(eps) else 0
    status(f"Long history {args.year}: {len(strategies)} strategy hits {counts}, {ep_days} EP-Days")
    return 0
