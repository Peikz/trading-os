"""Market regime filters (Emil, 20 Oct 2026): would skipping trades in a bad market have fixed
the weak years (2018, 2021, 2022)? Facts, not advice.

A daily regime table for 2016-2026 from Alpaca's daily bars with the live rules (SPEC §6.5):
the QQQ trend, the Stockbee breadth state, the scan count (the Sunday screen: price > $5,
30-day average volume > 500K, up >= 50 % in a quarter, above the 20-day MA; taken from the
week's last close; the country filter has no history and is left out), and the Market Light
from those three; plus SPY and QQQ against their 50- and 200-day MAs.

Each trade gets the regime of the session BEFORE its entry day: what was known when the order
went in (for an entry at a signal's close, the regime of that close). Then every filter keeps
or skips it, and the trades kept are scored: count, win rate and mean R per exit (capped at 20
per trade, like the other studies), overall and per year.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import breadth, ep_history, long_history
from trading_os import history_metrics as hm

FILTERS: Mapping[str, Callable[[pd.DataFrame], pd.Series]] = {
    "all": lambda r: pd.Series(True, index=r.index),
    "light_green": lambda r: r["light"] == "GREEN",
    "light_not_red": lambda r: r["light"].isin(["GREEN", "YELLOW"]),
    "qqq_up": lambda r: r["qqq_trend"] == "up",
    "qqq_not_down": lambda r: r["qqq_trend"].isin(["up", "sideways"]),
    "breadth_not_weak": lambda r: r["breadth_state"].isin(["strong", "neutral"]),
    "spy_above_ma200": lambda r: r["spy_close"] > r["spy_sma200"],
    "qqq_above_ma50": lambda r: r["qqq_close"] > r["qqq_sma50"],
}
CAP = 20
FUND_TYPES = {"ETF", "ETN", "ETS", "ETV", "FUND", "INDEX", "SP"}
STOCK_TYPES = {"CS", "ADRC", "ADRP", "ADRS", "OS", "GDR", "NYRS"}
INDEXES = {"SPY", "QQQ"}


def non_stocks(data_dir: Path) -> set[str]:
    """Tickers Massive lists as an ETF, ETN, fund or index (delisted ones included) and never
    as a stock: kept out of breadth, the scan count and the scored trades, like the live
    screens, which only see stocks and ADRs."""
    path = Path(data_dir) / "data" / "ep_enrich" / "tickers.parquet"
    if not path.exists():
        return set()
    listed = pd.read_parquet(path, columns=["ticker", "type"])
    funds = set(listed.loc[listed["type"].isin(FUND_TYPES), "ticker"])
    stocks = set(listed.loc[listed["type"].isin(STOCK_TYPES), "ticker"])
    return funds - stocks


def scan_counts(g: Mapping[str, np.ndarray], sc: Mapping) -> np.ndarray:
    """The Sunday screen's count for every session (from the bars)."""
    c, v = g["close"], g["volume"]
    with np.errstate(divide="ignore", invalid="ignore"):
        hit = (
            (c > sc["price_gt"])
            & (hm.rolling_mean(v, 30) > sc["avg_volume_gt"])
            & ((c / hm.shift(c, 63) - 1) * 100 >= sc["perf_3m_min_pct"])
            & (c > hm.rolling_mean(c, sc["above_sma"]))
        )
    return hit.sum(axis=1)


def _index_line(c: np.ndarray, tickers: pd.Index, symbol: str, prefix: str) -> dict:
    if symbol not in tickers:
        return {}
    close = c[:, tickers.get_loc(symbol)]
    out = {f"{prefix}_close": close}
    for w in (50, 200):
        out[f"{prefix}_sma{w}"] = hm.rolling_mean(close[:, None], w)[:, 0]
    return out


def regime_year(
    bars: pd.DataFrame, sessions: list, cfg, year: int, funds: set[str] = frozenset()
) -> pd.DataFrame:
    """The regime of every session in `year` (bars must reach 300 sessions back). `funds`
    are left out of the counts; SPY and QQQ stay for their own lines."""
    keep = bars["ticker"].map(lambda t: str(t).replace(".", "").isalpha())
    keep &= ~bars["ticker"].isin(set(funds) - INDEXES)
    stocks = bars[keep]
    g, tickers = hm.grids(stocks, sessions)
    out = ep_history.market_context(g, tickers, cfg)
    out.insert(0, "session_date", sessions)
    counts = pd.Series(scan_counts(g, cfg.market_light["scan_count"]), index=out.index)
    week = pd.Series([s.isocalendar()[:2] for s in sessions], index=out.index)
    last_of_week = ~week.duplicated(keep="last")
    out["scan_count"] = counts.where(last_of_week).ffill().shift(1)  # last week's count
    lines = {
        **_index_line(g["close"], tickers, "SPY", "spy"),
        **_index_line(g["close"], tickers, cfg.market_light["qqq"]["symbol"].split(":")[-1], "qqq"),
    }
    for name, values in lines.items():
        out[name] = values
    out = out.rename(columns={"mkt_qqq_trend": "qqq_trend", "mkt_breadth_state": "breadth_state"})
    out["light"] = [
        breadth.light(t, s, None if np.isnan(n) else int(n), cfg.market_light["thresholds"])[0]
        for t, s, n in zip(out["qqq_trend"], out["breadth_state"], out["scan_count"], strict=True)
    ]
    keep = [
        "session_date",
        "qqq_trend",
        "breadth_state",
        "scan_count",
        "light",
        "mkt_ratio_10d",
        *lines,
    ]
    out = out[[c for c in keep if c in out]]
    return out[pd.to_datetime(out["session_date"]).dt.year == year].reset_index(drop=True)


def regime_table(
    bars_dir: Path, cfg, first: int, last: int, funds: set[str] = frozenset()
) -> pd.DataFrame:
    """The regime of every session first..last, one year at a time (memory)."""
    frames = []
    for year in range(first, last + 1):
        bars = long_history.load_years(bars_dir, year - 2, year)
        if bars.empty:
            continue
        sessions, inside = long_history.window(cfg.schedule, year, bars["session_date"].max())
        sessions = [s for s in sessions if s <= inside[-1] and s in set(bars["session_date"])]
        part = bars[bars["session_date"].isin(set(sessions))]
        frames.append(regime_year(part, sessions, cfg, year, funds))
    return pd.concat(frames, ignore_index=True)


def known_before(trades: pd.DataFrame, regime: pd.DataFrame, same_day: bool) -> pd.DataFrame:
    """Each trade with the regime known when it was entered: the session before its entry
    day, or (`same_day`, entries at a signal's close) that day's close."""
    table = regime.sort_values("session_date").reset_index(drop=True)
    if not same_day:
        shifted = table.drop(columns="session_date").shift(1)
        table = pd.concat([table[["session_date"]], shifted], axis=1)
    return trades.merge(table, on="session_date", how="left")


def score(trades: pd.DataFrame, keys: list[str], exits: list[str]) -> pd.DataFrame:
    """Per filter and group: trades kept and, per exit, wins and the capped R sum (so years
    can be pooled exactly)."""
    rows = []
    for name, rule in FILTERS.items():
        kept = trades[rule(trades).fillna(False).to_numpy(dtype=bool)]
        if kept.empty:
            continue
        grouped = kept.groupby(keys, observed=True)
        part = grouped.size().rename("trades").to_frame()
        for exit_name in exits:
            r = kept[exit_name]
            part[f"wins_{exit_name}"] = (r > 0).groupby([kept[k] for k in keys]).sum()
            part[f"n_{exit_name}"] = r.notna().groupby([kept[k] for k in keys]).sum()
            part[f"sum_{exit_name}"] = r.clip(upper=CAP).groupby([kept[k] for k in keys]).sum()
        rows.append(part.reset_index().assign(filter=name))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def finish(sums: pd.DataFrame, keys: list[str], exits: list[str]) -> pd.DataFrame:
    """Pool the sums over years: mean R and win % per exit."""
    pooled = sums.groupby([*keys, "filter"], observed=True).sum(numeric_only=True).reset_index()
    for exit_name in exits:
        n = pooled[f"n_{exit_name}"].where(pooled[f"n_{exit_name}"] > 0)
        name = exit_name.removeprefix("r_")  # R_hold_5d, like the other studies
        pooled[f"R_{name}"] = pooled[f"sum_{exit_name}"] / n
        pooled[f"win_{name}%"] = pooled[f"wins_{exit_name}"] / n * 100
    drop = [c for c in pooled.columns if c.startswith(("wins_", "sum_", "n_"))]
    return pooled.drop(columns=drop)


def run(
    regime: pd.DataFrame,
    trade_files: list[Path],
    same_day: bool,
    keys: list[str],
    funds: set[str] = frozenset(),
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """(pooled over all years, per year, fund trades dropped) for every filter, file by file
    (memory)."""
    overall, by_year, exits, dropped = [], [], None, 0
    for path in trade_files:
        trades = pd.read_parquet(path)
        if trades.empty:
            continue
        fund = trades["ticker"].isin(funds)
        dropped += int(fund.sum())
        trades = trades[~fund]
        trades["session_date"] = pd.to_datetime(trades["session_date"]).dt.date
        exits = exits or [c for c in trades.columns if c.startswith("r_")]
        trades = known_before(trades, regime, same_day)
        trades["year"] = pd.to_datetime(trades["session_date"]).dt.year
        overall.append(score(trades, keys, exits))
        by_year.append(score(trades, [*keys, "year"], exits))
    sums, yearly = pd.concat(overall), pd.concat(by_year)
    return finish(sums, keys, exits), finish(yearly, [*keys, "year"], exits), dropped


def compare(table: pd.DataFrame, keys: list[str], exit_name: str, min_trades: int = 200):
    """One row per group: mean R with no filter, the best filter, and the trades it keeps."""
    col = f"R_{exit_name}"
    base = table[table["filter"] == "all"].set_index(keys)[[col, "trades"]]
    rows = []
    for key, part in table[table["trades"] >= min_trades].groupby(keys, observed=True):
        key = key if isinstance(key, tuple) else (key,)
        lookup = key if len(keys) > 1 else key[0]  # a one-key index holds plain values
        if lookup not in base.index:
            continue
        best = part.sort_values(col, ascending=False).iloc[0]
        all_r, all_n = base.loc[lookup, col], base.loc[lookup, "trades"]
        rows.append(
            dict(zip(keys, key, strict=True))
            | {
                "R_all": all_r,
                "trades_all": int(all_n),
                "best_filter": best["filter"],
                "R_filtered": best[col],
                "kept_%": best["trades"] / all_n * 100,
            }
        )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    from trading_os.logsafe import run_guarded

    return run_guarded(lambda: _main(argv), None, "Regime study")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    from trading_os.config import load_config
    from trading_os.logsafe import status

    parser = argparse.ArgumentParser(description="Market regime filters over 10 years")
    parser.add_argument("--bars", type=Path, required=True, help="Alpaca YYYY.parquet files")
    parser.add_argument("--data-dir", type=Path, required=True, help="for Massive's ticker types")
    parser.add_argument("--history", type=Path, help="history-10y files")
    parser.add_argument("--minute", type=Path, help="intraday-10y files")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--years", default="2016-2026")
    args = parser.parse_args(argv)
    cfg = load_config()
    first, last = (int(y) for y in args.years.split("-"))
    funds = non_stocks(args.data_dir)
    regime = regime_table(args.bars, cfg, first, last, funds)
    args.out.mkdir(parents=True, exist_ok=True)
    regime.to_parquet(args.out / "regime_daily.parquet", index=False)
    lights = regime["light"].value_counts().to_dict()
    status(f"Regime: {len(regime)} sessions, lights {lights}, {len(funds)} funds left out")
    if args.minute:
        files = sorted(args.minute.glob("intraday_[0-9][0-9][0-9][0-9].parquet"))
        keys = ["strategy", "entry", "stop_rule"]
        overall, yearly, dropped = run(regime, files, False, keys, funds)
        overall.to_parquet(args.out / "regime_minute.parquet", index=False)
        yearly.to_parquet(args.out / "regime_minute_by_year.parquet", index=False)
        status(f"Regime: minute study scored, {dropped} fund trades left out")
    if args.history:
        files = sorted(args.history.glob("strategy_*.parquet"))
        overall, yearly, dropped = run(regime, files, True, ["strategy"], funds)
        eps = []
        for f in sorted(args.history.glob("ep_*.parquet")):
            ep = pd.read_parquet(f)
            eps.append(ep[ep["is_ep_day"] & (ep["tier"] == "alert")].assign(strategy="ep_day"))
        if eps:
            tmp = args.out / "_ep_days.parquet"
            pd.concat(eps, ignore_index=True).to_parquet(tmp, index=False)
            ep_all, ep_years, _ = run(regime, [tmp], True, ["strategy"], funds)
            overall = pd.concat([overall, ep_all], ignore_index=True)
            yearly = pd.concat([yearly, ep_years], ignore_index=True)
            tmp.unlink()
        overall.to_parquet(args.out / "regime_daily_study.parquet", index=False)
        yearly.to_parquet(args.out / "regime_daily_study_by_year.parquet", index=False)
        status(f"Regime: daily histories scored, {dropped} fund hits left out")
    return 0
