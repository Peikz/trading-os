"""Indexes, sectors and themes: where the market is and where money is moving (Emil, 22 Oct
2026). The EOD job fetches these ETFs in one TradingView request and saves the row per ETF
(`data/sectors/`); the dashboard's Market page shows the table and a rotation chart.

Rotation, like a relative-rotation graph: each ETF's 1-month return against SPY's (where it
stands) and its 1-week return against SPY's (where it is heading). Leading: ahead on both;
weakening: ahead over the month, behind this week; lagging: behind on both; improving: behind
over the month, ahead this week. Facts, not advice.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

# (TradingView symbol, name, group). ETFs, so outside the stock universe.
ETFS = [
    ("AMEX:SPY", "S&P 500", "Index"),
    ("NASDAQ:QQQ", "Nasdaq 100", "Index"),
    ("AMEX:IWM", "Russell 2000 (small caps)", "Index"),
    ("AMEX:MDY", "S&P 400 (mid caps)", "Index"),
    ("AMEX:DIA", "Dow Jones", "Index"),
    ("AMEX:RSP", "S&P 500 equal weight", "Index"),
    ("CBOE:ARKK", "ARK Innovation (speculative growth)", "Index"),
    ("AMEX:XLK", "Technology", "Sector"),
    ("AMEX:XLC", "Communication", "Sector"),
    ("AMEX:XLY", "Consumer discretionary", "Sector"),
    ("AMEX:XLF", "Financials", "Sector"),
    ("AMEX:XLI", "Industrials", "Sector"),
    ("AMEX:XLV", "Health care", "Sector"),
    ("AMEX:XLE", "Energy", "Sector"),
    ("AMEX:XLB", "Materials", "Sector"),
    ("AMEX:XLP", "Consumer staples", "Sector"),
    ("AMEX:XLU", "Utilities", "Sector"),
    ("AMEX:XLRE", "Real estate", "Sector"),
    ("NASDAQ:SMH", "Semiconductors", "Theme"),
    ("CBOE:IGV", "Software", "Theme"),
    ("AMEX:XBI", "Biotech", "Theme"),
    ("AMEX:KRE", "Regional banks", "Theme"),
    ("CBOE:ITB", "Homebuilders", "Theme"),
    ("AMEX:XRT", "Retail", "Theme"),
    ("AMEX:XOP", "Oil and gas producers", "Theme"),
    ("AMEX:GDX", "Gold miners", "Theme"),
    ("AMEX:URA", "Uranium", "Theme"),
    ("AMEX:TAN", "Solar", "Theme"),
    ("AMEX:JETS", "Airlines", "Theme"),
    ("NASDAQ:IBIT", "Bitcoin", "Theme"),
]
FIELDS = {
    "close": "close",
    "change": "chg_pct",
    "Perf.W": "ret_1w",
    "Perf.1M": "ret_1m",
    "Perf.3M": "ret_3m",
    "Perf.6M": "ret_6m",
    "Perf.YTD": "ret_ytd",
    "SMA20": "sma20",
    "SMA50": "sma50",
    "SMA200": "sma200",
    "relative_volume_10d_calc": "rvol",
}
COLUMNS = ["symbol", "ticker", "name", "group", *FIELDS.values()]
QUADRANTS = ("Leading", "Weakening", "Lagging", "Improving")


def fetch(details: Callable[[list[str], list[str]], pd.DataFrame]) -> pd.DataFrame:
    """One row per ETF from one request (`details`: tv.fetch_details)."""
    raw = details([s for s, _, _ in ETFS], list(FIELDS))
    rows = []
    for symbol, name, group in ETFS:
        if symbol not in raw.index:
            continue
        rec = raw.loc[symbol]
        row = {"symbol": symbol, "ticker": symbol.split(":")[1], "name": name, "group": group}
        for field, column in FIELDS.items():
            value = rec.get(field)
            row[column] = float(value) if value is not None and value == value else np.nan
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)


def rotation(table: pd.DataFrame) -> pd.DataFrame:
    """`table` plus each ETF's 1-week and 1-month return minus SPY's, its trend (over the 50-
    and 200-day), and its rotation quadrant."""
    if table.empty:
        return table.assign(vs_spy_1w=[], vs_spy_1m=[], quadrant=[], trend=[])
    spy = table[table["ticker"] == "SPY"]
    base_w = float(spy["ret_1w"].iloc[0]) if len(spy) else 0.0
    base_m = float(spy["ret_1m"].iloc[0]) if len(spy) else 0.0
    out = table.copy()
    out["vs_spy_1w"] = out["ret_1w"] - base_w
    out["vs_spy_1m"] = out["ret_1m"] - base_m
    ahead_m, ahead_w = out["vs_spy_1m"] >= 0, out["vs_spy_1w"] >= 0
    out["quadrant"] = np.select(
        [ahead_m & ahead_w, ahead_m & ~ahead_w, ~ahead_m & ~ahead_w],
        ["Leading", "Weakening", "Lagging"],
        "Improving",
    )
    above50, above200 = out["close"] > out["sma50"], out["close"] > out["sma200"]
    out["trend"] = np.select(
        [above50 & above200, ~above50 & above200, above50 & ~above200],
        ["over 50d and 200d", "under 50d, over 200d", "over 50d, under 200d"],
        "under 50d and 200d",
    )
    return out


def industry_moves(latest: pd.DataFrame, earlier: pd.DataFrame) -> pd.DataFrame:
    """Each industry's rank now and how many places it moved since `earlier` (positive: up)."""
    if latest.empty:
        return latest
    before = earlier.set_index("industry")["industry_rank"] if len(earlier) else pd.Series()
    out = latest[["industry", "sector", "industry_rank", "members", "med_ret_22", "med_ret_63"]]
    out = out.copy()
    out["moved"] = out["industry"].map(before) - out["industry_rank"]
    return out.sort_values("industry_rank").reset_index(drop=True)
