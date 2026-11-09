"""Step 1 of the backtest module (docs/backlog/backtest.md §2, §10.1): daily bars, the
point-in-time universe filter and QQQ.

The bars are the data repo's `bars-alpaca` release: Alpaca daily bars, split- and
dividend-adjusted, one file per year, delisted stocks included. Every universe value on day t
uses only rows up to and including t. Logs carry counts only (this repo's Actions logs are
public).
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from trading_os.audit import ordinary_ticker
from trading_os.backtest.config import (  # noqa: F401 (re-exported)
    DEFAULT_PATH,
    BacktestConfig,
    UniverseConfig,
    load_config,
    parse_config,
)
from trading_os.logsafe import status

BAR_COLUMNS = ["session_date", "ticker", "open", "high", "low", "close", "volume"]
SURVIVORSHIP_LINE = (
    "Survivorship: delisted tickers are included (Alpaca bars, bars-alpaca release)."
)


def excluded_tickers(listed: pd.DataFrame, cfg: UniverseConfig) -> set[str]:
    """Tickers the reference table lists only under excluded types (ETFs, ADRs, warrants, ...),
    plus SPACs found by name. A ticker also listed as a common stock stays in."""
    kinds = listed["type"].fillna("")
    bad = set(listed.loc[kinds.isin(cfg.exclude_types), "ticker"])
    good = set(listed.loc[~kinds.isin(cfg.exclude_types) & (kinds != ""), "ticker"])
    out = bad - good
    if cfg.spac_name_patterns:
        pattern = "|".join(re.escape(p) for p in cfg.spac_name_patterns)
        names = listed["name"].fillna("").str.lower()
        out |= set(listed.loc[names.str.contains(pattern, regex=True), "ticker"])
    return out


def load_bars(files: Iterable[Path]) -> pd.DataFrame:
    """The year files as one long frame, one row per (session, ticker), sorted."""
    parts = [pd.read_parquet(f, columns=BAR_COLUMNS) for f in files]
    if not parts:
        return pd.DataFrame(columns=BAR_COLUMNS)
    bars = pd.concat(parts, ignore_index=True)
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    bars = bars.drop_duplicates(["ticker", "session_date"], keep="last")
    return bars.sort_values(["ticker", "session_date"]).reset_index(drop=True)


def with_universe(bars: pd.DataFrame, cfg: BacktestConfig, excluded: set[str]) -> pd.DataFrame:
    """Add `avg_volume` (the ticker's last `avg_volume_days` sessions up to and including t)
    and `in_universe` (ordinary stock, not excluded, not an index ticker, price and volume
    floors on day t). Index tickers keep their rows with `in_universe` False."""
    u = cfg.universe
    out = bars.sort_values(["ticker", "session_date"]).reset_index(drop=True)
    out["avg_volume"] = out.groupby("ticker", sort=False)["volume"].transform(
        lambda v: v.rolling(u.avg_volume_days, min_periods=u.avg_volume_days).mean()
    )
    names = pd.Series(out["ticker"].unique())
    stock = set(
        names[
            names.map(ordinary_ticker) & ~names.isin(excluded) & ~names.isin(cfg.data.index_tickers)
        ]
    )
    out["in_universe"] = (
        out["ticker"].isin(stock)
        & (out["close"] >= u.price_min)
        & (out["avg_volume"] >= u.avg_volume_min)
    )
    return out


def index_bars(bars: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """One index ticker's bars by session (QQQ for the regime tag)."""
    rows = bars[bars["ticker"] == ticker]
    return rows.set_index("session_date")[["open", "high", "low", "close", "volume"]].sort_index()


def row_counts(bars: pd.DataFrame) -> pd.DataFrame:
    """Per year: bar rows, tickers, universe rows, and the average universe size per session."""
    year = pd.Series([d.year for d in bars["session_date"]], index=bars.index)
    g = bars.groupby(year)
    uni = bars[bars["in_universe"]]
    ug = uni.groupby(year[uni.index])
    out = (
        pd.DataFrame(
            {
                "sessions": g["session_date"].nunique(),
                "rows": g.size(),
                "tickers": g["ticker"].nunique(),
                "universe_rows": ug.size(),
                "universe_tickers": ug["ticker"].nunique(),
            }
        )
        .fillna(0)
        .astype(int)
    )
    out["universe_per_session"] = (out["universe_rows"] / out["sessions"].clip(lower=1)).round(0)
    out.index.name = "year"
    return out


def bar_files(cfg: BacktestConfig, bars_dir: Path | None, data_dir: Path | None) -> list[Path]:
    """The configured year files: from a local folder, else downloaded from the data repo's
    release into the cache (needs `gh` signed in and `--data-dir`)."""
    names = [f"{y}.parquet" for y in cfg.data.years]
    if bars_dir is not None:
        return [Path(bars_dir) / n for n in names if (Path(bars_dir) / n).exists()]
    if data_dir is None:
        return []
    from trading_os import remote_data

    files = remote_data.fetch(remote_data.repo_of(data_dir), cfg.data.source, "20*.parquet")
    return sorted(f for f in files if f.name in names)


def prepare(cfg: BacktestConfig, files: list[Path], listed: pd.DataFrame | None) -> pd.DataFrame:
    excluded = excluded_tickers(listed, cfg.universe) if listed is not None else set()
    return with_universe(load_bars(files), cfg, excluded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest step 1: bars, universe, QQQ")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--bars-dir", type=Path, help="local year files (default: the release)")
    parser.add_argument("--data-dir", type=Path, help="data repo, for the ticker type table")
    parser.add_argument("--out", type=Path, help="write the prepared bars here, one file a year")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    files = bar_files(cfg, args.bars_dir, args.data_dir)
    if not files:
        status("Backtest data: no bar files")
        return 1
    listed = None
    table = args.data_dir / "data" / "ep_enrich" / "tickers.parquet" if args.data_dir else None
    if table is not None and table.exists():
        listed = pd.read_parquet(table, columns=["ticker", "name", "type"])
    else:
        status("Backtest data: no ticker type table, only symbol shapes filter the universe")
    bars = prepare(cfg, files, listed)
    status(SURVIVORSHIP_LINE)
    if cfg.universe.market_cap_min is not None:
        status("Backtest data: market cap filter skipped (no point-in-time market cap)")
    for t in cfg.data.index_tickers:
        status(f"Backtest data: index {len(index_bars(bars, t))} sessions")
    counts = row_counts(bars)
    for year, r in counts.iterrows():
        status(
            f"Backtest data {year}: {r.sessions:.0f} sessions, {r.rows:.0f} rows, "
            f"{r.tickers:.0f} tickers, "
            f"universe {r.universe_tickers:.0f} tickers, {r.universe_per_session:.0f} a session"
        )
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        year = pd.Series([d.year for d in bars["session_date"]], index=bars.index)
        for y, part in bars.groupby(year):
            part.to_parquet(args.out / f"universe_{y}.parquet", index=False)
        status(f"Backtest data: {len(counts)} year files written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
