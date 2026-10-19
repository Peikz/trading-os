"""TradingView screener client (`tradingview-screener`, no login, 15-min delayed data).

One request per run fetches the whole universe; every scan then works on that DataFrame.
Field names, types and units were verified against live data; see docs/fields.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd
from tradingview_screener import Query, col

# Technical guard, not a trading threshold: the US universe after floors is ~5-6k rows.
MAX_ROWS = 10_000

# Canonical column -> TradingView field. Columns ending in _tv are TradingView's own
# calculations, kept for audit next to the SPEC §5 definitions.
FIELDS: dict[str, str] = {
    "symbol": "name",
    "exchange": "exchange",
    "type": "type",
    "typespecs": "typespecs",
    "is_primary": "is_primary",
    "sector": "sector",
    "industry": "industry",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "prev_close": "close[1]",
    "prev_volume": "volume[1]",
    "chg_pct": "change",
    "chg_abs": "change_abs",
    "gap_pct": "gap",
    "market_cap": "market_cap_basic",
    "float_shares": "float_shares_outstanding",
    "rvol10_tv": "relative_volume_10d_calc",
    "avg_volume_10d_tv": "average_volume_10d_calc",
    "avg_volume_30d_tv": "average_volume_30d_calc",
    "avg_volume_60d_tv": "average_volume_60d_calc",
    "avg_volume_90d_tv": "average_volume_90d_calc",
    "avg_dollar_volume_30d_tv": "AvgValue.Traded_30d",
    "ma10": "SMA10",
    "ma20": "SMA20",
    "ma50": "SMA50",
    "ma200": "SMA200",
    "high_52w": "price_52_week_high",
    "perf_1m_tv": "Perf.1M",
    "perf_3m_tv": "Perf.3M",
    "perf_6m_tv": "Perf.6M",
    "adr14_usd_tv": "ADR",
    "earnings_date_last": "earnings_release_date",
    "earnings_date_next": "earnings_release_next_date",
    "rev_growth_q": "total_revenue_yoy_growth_fq",
    "eps_growth_q": "earnings_per_share_diluted_yoy_growth_fq",
    "pm_change_pct": "premarket_change",
    "pm_gap_pct": "premarket_gap",
    "pm_volume": "premarket_volume",
    "ah_change_pct": "postmarket_change",
    "ah_volume": "postmarket_volume",
}
_CANONICAL = {tv: canon for canon, tv in FIELDS.items()}
_EPOCH_FIELDS = ("earnings_date_last", "earnings_date_next")


class TruncatedResult(RuntimeError):
    """TradingView returned fewer rows than it matched."""


def canonical(tv_field: str) -> str:
    """Canonical column name for a TradingView field (used to resolve config proxies)."""
    return _CANONICAL[tv_field]


def build_universe_query(universe: Mapping[str, Any], fields: list[str] | None = None) -> Query:
    """Server-side floors and exclusions for the logged tier (SPEC §4)."""
    logged = universe["logged"]
    query = (
        Query(universe["market"])
        .select(*(fields or FIELDS.values()))
        .where(
            col("close") >= logged["price_min"],
            col("market_cap_basic") >= logged["market_cap_min"],
            col("exchange").not_in(list(universe["exclude_exchanges"])),
            col("type").isin(list(universe["include_types"])),
            col("typespecs").has_none_of(list(universe["exclude_typespecs"])),
        )
        .order_by("market_cap_basic", ascending=False)
        .limit(MAX_ROWS)
    )
    # The package's default filter keeps primary listings only, which drops second share
    # classes, interlisted Canadian stocks and most ADRs. Our filters above are explicit.
    query.query.pop("filter2", None)
    return query


def fetch_universe(universe: Mapping[str, Any]) -> pd.DataFrame:
    total, raw = build_universe_query(universe).get_scanner_data(timeout=30)
    if len(raw) != total:
        raise TruncatedResult(f"TradingView matched {total} rows but returned {len(raw)}")
    return normalize(raw)


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename TradingView fields to canonical columns and fix types."""
    df = raw.rename(columns=_CANONICAL).rename(columns={"ticker": "tv_ticker"})
    df.insert(0, "ticker", df.pop("symbol"))
    df["typespecs"] = df["typespecs"].map(_join_list)
    for column in _EPOCH_FIELDS:
        df[column] = pd.to_datetime(df[column], unit="s", utc=True)
    return df


def _join_list(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ",".join(sorted(str(v) for v in value))
    return "" if value is None or value != value else str(value)
