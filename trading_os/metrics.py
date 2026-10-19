"""Metric definitions (SPEC §5).

Phase 1 computes metrics from TradingView fields. Where TradingView's window differs from SPEC,
the proxy comes from config (SPEC §11.6) and the basis is stored on every row.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_os.tv import canonical

NEW_YORK = ZoneInfo("America/New_York")
MA_WINDOWS = (10, 20, 50, 200)  # SPEC §7 universe columns ma10..ma200


def dollar_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    """close × volume."""
    return close * volume


def close_location(close: pd.Series, high: pd.Series, low: pd.Series) -> pd.Series:
    """(close − low) / (high − low); NaN when the day has no range."""
    day_range = (high - low).where(high > low)
    return (close - low) / day_range


def average_excluding_today(avg_with_today: pd.Series, volume: pd.Series, days: int) -> pd.Series:
    """Mean of the previous `days − 1` sessions, from a `days`-session mean that includes today.

    TradingView's average_volume_Nd_calc includes today (docs/fields.md).
    """
    prior = (days * avg_with_today - volume) / (days - 1)
    return prior.where(prior > 0)


def relative_volume(volume: pd.Series, avg_excluding_today: pd.Series) -> pd.Series:
    """Today's volume / average volume excluding today."""
    return volume / avg_excluding_today


def above(close: pd.Series, average: pd.Series) -> pd.Series:
    """close > moving average; False when the average is missing."""
    return (close > average).fillna(False).astype(bool)


def adr_pct(adr_usd: pd.Series, close: pd.Series) -> pd.Series:
    """Average daily range as a percent of the close."""
    return adr_usd / close * 100


def distance_in_adr(close: pd.Series, average: pd.Series, adr_usd: pd.Series) -> pd.Series:
    """(close − MA) / ADR $: how many average daily ranges the close sits from the MA."""
    return (close - average) / adr_usd.where(adr_usd > 0)


def yoy_growth(history: object, quarter: int, *, abs_base: bool) -> float:
    """YoY growth in percent of quarter `quarter` (0 = latest) from a latest-first history.

    abs_base divides by |year-ago value| so a move from a loss to a profit reads as growth,
    matching TradingView's EPS growth (docs/fields.md).
    """
    if not isinstance(history, list | tuple) or len(history) <= quarter + 4:
        return np.nan
    current, base = history[quarter], history[quarter + 4]
    if current is None or base is None or base == 0:
        return np.nan
    return (current - base) / (abs(base) if abs_base else base) * 100


def add_growth_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Previous-quarter YoY growth from the history arrays, which are then dropped."""
    out = df.copy()
    out["rev_growth_q_prev"] = out["revenue_q_hist"].map(lambda h: yoy_growth(h, 1, abs_base=False))
    out["eps_growth_q_prev"] = out["eps_q_hist"].map(lambda h: yoy_growth(h, 1, abs_base=True))
    return out.drop(columns=["revenue_q_hist", "eps_q_hist"])


def add_phase1_metrics(df: pd.DataFrame, proxies: Mapping[str, object]) -> pd.DataFrame:
    """Add the metrics the Phase 1 EOD scans need. Returns a new frame."""
    out = df.copy()
    days = int(proxies["rvol_avg_days"])
    rvol_base = average_excluding_today(
        out[canonical(str(proxies["rvol_avg_volume"]))], out["volume"], days
    )
    out["dollar_volume"] = dollar_volume(out["close"], out["volume"])
    out["close_loc"] = close_location(out["close"], out["high"], out["low"])
    out["rvol50"] = relative_volume(out["volume"], rvol_base).replace([np.inf, -np.inf], np.nan)
    out["rvol_basis"] = f"tv_avg{days}d_excl_today"
    out["avg_volume_20d"] = out[canonical(str(proxies["avg_volume_20d"]))]
    out["avg_dollar_volume_20d"] = out[canonical(str(proxies["avg_dollar_volume_20d"]))]
    out["avg20_basis"] = f"tv:{proxies['avg_volume_20d']}"
    out["pm_dollar_volume"] = dollar_volume(out["pm_price"], out["pm_volume"])
    out["adr20_usd"] = out[canonical(str(proxies["adr"]))]
    out["adr20_pct"] = adr_pct(out["adr20_usd"], out["close"])
    out["adr_basis"] = f"tv:{proxies['adr']}/close"
    out["dist_ma10_adr"] = distance_in_adr(out["close"], out["ma10"], out["adr20_usd"])
    out["pct_from_52w_high"] = (out["close"] / out["high_52w"] - 1) * 100
    returns = proxies["returns"]
    for days, field in returns.items():  # type: ignore[union-attr]
        out[f"ret_{days}"] = out[canonical(str(field))]
    out["returns_basis"] = "tv:" + "/".join(str(f) for f in returns.values())  # type: ignore[union-attr]
    for window in MA_WINDOWS:
        out[f"above_ma{window}"] = above(out["close"], out[f"ma{window}"])
    return out


def earnings_flag(
    earnings_date_last: pd.Series, session: dt.date, previous_session: dt.date
) -> pd.Series:
    """True when the last earnings release fell on the signal session or the session before.

    Covers both before-open releases (signal day) and after-close releases (prior session).
    """
    release_day = earnings_date_last.dt.tz_convert(NEW_YORK).dt.date
    return release_day.isin([session, previous_session]).fillna(False).astype(bool)
