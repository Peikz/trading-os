"""High tight flag and pocket pivot for the history studies (Emil, 20 Oct 2026). Study only,
not live scans; a live scan needs Emil's OK on the rules and a SPEC entry first.

High tight flag (`htf`, config `htf:`): William O'Neil's high, tight flag (How to Make Money
in Stocks) and Mark Minervini's power play (Trade Like a Stock Market Wizard, 2013), the same
pattern. A pole of about +100 % within 8 weeks, then a flag of 3-6 weeks that corrects at
most 20-25 % (O'Neil: 10-25 %; Minervini: 20 %, 25 % for low-priced stocks) on drying volume.
- pole: the highest high of the last `flag_max_days` + 1 sessions (the pivot) is at least
  `pole_min_pct` above the lowest low of the `pole_max_days` sessions before it, and no high
  of those sessions is above it (a new high, not a rebound);
- flag: `flag_min_days` to `flag_max_days` sessions after that high, never above it, its
  lowest low at most `flag_depth_max_pct` under it, its average volume at most
  `flag_volume_ratio_max` x the pole's;
- trigger for the next session(s): the pivot (the flag's high). Order stop: the low of the
  last `right_side_days` sessions, at most `stop_max_pct` under the pivot (Minervini's 7-8 %).
Minervini also allows flags of only 10-12 sessions and drops the volatility contraction when
the flag is 10 % deep or less; `flag_days` and `flag_depth_pct` are stored for those splits.

Pocket pivot (`pocket_pivot`, config `pocket_pivot:`): Gil Morales and Chris Kacher (Trade
Like an O'Neil Disciple, 2010). An up day whose volume beats every down day's volume of the
prior `down_volume_days` sessions, in a stock pivoting off its 10-day line (a continuation
pivot) or its 50-day line (a base pivot), not extended, and not under a declining 50-day:
- the day's low within `touch_adr` ADR of yesterday's MA, the close above it and at most
  `close_ext_adr_max` ADR above it (the authors give no number for "extended": proposed);
- close above yesterday's 50-day MA, which is not lower than `ma50_slope_days` sessions
  before.
Entry at the pivot day's close (they buy it during the day); `pivot` (the day's high) is the
next session's trigger for a confirmed entry. Stop: the day's low (their sell guides are a
close under the 10-day or 50-day line). Levels (MAs, ADR) are yesterday's, known before the
session.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from trading_os import history_metrics as hm

STRATEGIES = ("htf", "pocket_pivot")
AVG_VOLUME_DAYS = 50
DRYUP_DAYS = 5  # recent volume for the stored dry-up ratio


def last_extreme(
    a: np.ndarray, window: int, how: str, latest: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """(value, sessions since) of the max or min of the last `window` rows; on ties the
    earliest row (a base starts at the first touch of its high), or the latest with `latest`
    (a move starts from the last touch of its low). NaN unless all `window` values exist."""
    n = len(a)
    value = np.full(a.shape, np.nan)
    since = np.full(a.shape, np.nan)
    if n < window:
        return value, since
    fill = -np.inf if how == "max" else np.inf
    view = sliding_window_view(np.where(np.isnan(a), fill, a), window, axis=0)
    if latest:
        view = view[..., ::-1]
    pick = view.argmax(axis=-1) if how == "max" else view.argmin(axis=-1)
    if latest:
        pick = window - 1 - pick
    rows = np.arange(window - 1, n)[:, None]
    found = pick + np.arange(n - window + 1)[:, None]  # absolute row of the extreme
    cols = np.arange(a.shape[1])[None, :]
    full = ~np.isnan(hm.rolling_extreme(a, window, how))[window - 1 :]
    value[window - 1 :] = np.where(full, a[found, cols], np.nan)
    since[window - 1 :] = np.where(full, rows - found, np.nan)
    return value, since


def at_offset(a: np.ndarray, back: np.ndarray) -> np.ndarray:
    """a[t - back, j] for every cell (t, j): NaN where `back` is NaN or reaches before row 0."""
    rows = np.arange(len(a))[:, None] - np.nan_to_num(back, nan=-1).astype(int)
    ok = ~np.isnan(back) & (rows >= 0) & (rows < len(a))
    picked = a[np.where(ok, rows, 0), np.arange(a.shape[1])[None, :]]
    return np.where(ok, picked, np.nan)


def min_since(a: np.ndarray, start: np.ndarray, end: np.ndarray, longest: int) -> np.ndarray:
    """Min of a[t - start .. t - end] for every cell (offsets back from row t, start >= end);
    NaN if the offsets are NaN or a value in the window is missing. `longest` bounds start."""
    out = np.full(a.shape, np.inf)
    known = ~np.isnan(start) & ~np.isnan(end)
    for k in range(longest + 1):
        inside = known & (k >= end) & (k <= start)
        out = np.where(inside, np.minimum(out, hm.shift(a, k) if k else a), out)
    return np.where(known & (start >= end) & ~np.isinf(out), out, np.nan)


def mean_between(a: np.ndarray, first: np.ndarray, last: np.ndarray) -> np.ndarray:
    """Mean of rows first..last (absolute row numbers per cell, first <= last); NaN where a
    row number is NaN or out of range. Missing values count as 0 (volume)."""
    zero = np.zeros((1, a.shape[1]))
    cs = np.vstack([zero, np.cumsum(np.nan_to_num(a), axis=0)])
    n, cols = len(a), np.arange(a.shape[1])[None, :]
    ok = ~np.isnan(first) & ~np.isnan(last) & (first >= 0) & (last < n) & (last >= first)
    lo = np.where(ok, first, 0).astype(int)
    hi = np.where(ok, last, 0).astype(int)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(ok, (cs[hi + 1, cols] - cs[lo, cols]) / (hi - lo + 1), np.nan)


def _base(g: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    with np.errstate(divide="ignore", invalid="ignore"):
        adr_pct = hm.rolling_mean((high / low - 1) * 100, hm.ADR_DAYS)
    return {
        "adr_pct": adr_pct,
        "adr_usd": adr_pct * close / 100,
        "avg_volume": hm.rolling_mean(volume, AVG_VOLUME_DAYS),
        "ma50": hm.rolling_mean(close, 50),
    }


def htf_rules(g: Mapping[str, np.ndarray], conf: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Every value and rule of the high tight flag for every (session, ticker); the flag ends
    at the session (its close is known)."""
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    base = _base(g)
    longest = conf["flag_max_days"]
    pivot, flag_days = last_extreme(high, longest + 1, "max")
    pole_window = conf["pole_max_days"] + 1
    pole_low, pole_low_since = last_extreme(low, pole_window, "min", latest=True)
    pole_low = at_offset(pole_low, flag_days)
    pole_days = at_offset(pole_low_since, flag_days)
    before = at_offset(hm.rolling_extreme(high, pole_window, "max"), flag_days)
    rows = np.arange(len(high))[:, None].astype(float)
    peak = rows - flag_days  # absolute row of the pole's high
    flag_low = min_since(low, flag_days - 1, np.zeros_like(flag_days), longest)
    flag_high = -min_since(-high, flag_days - 1, np.zeros_like(flag_days), longest)
    pole_volume = mean_between(volume, peak - pole_days + 1, peak)
    flag_volume = mean_between(volume, peak + 1, rows)
    rs = conf["right_side_days"]
    right_low = hm.rolling_extreme(low, rs, "min")
    with np.errstate(divide="ignore", invalid="ignore"):
        pole_pct = (pivot / pole_low - 1) * 100
        depth = (pivot - flag_low) / pivot * 100
        flag_volume_ratio = flag_volume / pole_volume
        order_stop = np.fmax(right_low, pivot * (1 - conf["stop_max_pct"] / 100))
        values = {
            "pivot": pivot,
            "flag_days": flag_days,
            "pole_low": pole_low,
            "pole_days": pole_days,
            "pole_pct": pole_pct,
            "flag_low": flag_low,
            "flag_high": flag_high,  # the flag's own high (under the pivot)
            "flag_depth_pct": depth,
            "pivot_dist_pct": (pivot - close) / pivot * 100,
            "flag_volume_ratio": flag_volume_ratio,
            "pole_volume_ratio": pole_volume / at_offset(base["avg_volume"], flag_days + pole_days),
            "dryup_ratio": hm.rolling_mean(volume, DRYUP_DAYS) / base["avg_volume"],
            "right_low": right_low,
            "order_stop": order_stop,
            "risk_pct": (pivot - order_stop) / pivot * 100,
            "above_ma50": close > base["ma50"],
            "adr_pct": base["adr_pct"],
        }
        rules = {
            "pole": pole_pct >= conf["pole_min_pct"],
            "pole_top": pivot >= before,  # the pole's high tops the pole_max_days before it
            "flag_length": (flag_days >= conf["flag_min_days"])
            & (flag_days <= conf["flag_max_days"]),
            "flag_depth": depth <= conf["flag_depth_max_pct"],
            "flag_volume": flag_volume_ratio <= conf["flag_volume_ratio_max"],
        }
    return values | {"rules": rules}


def pocket_pivot_rules(g: Mapping[str, np.ndarray], conf: Mapping[str, Any]) -> dict[str, Any]:
    """Every value and rule of the pocket pivot for every (session, ticker)."""
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    base = _base(g)
    days = conf["down_volume_days"]
    prev_close = hm.shift(close, 1)
    known = ~np.isnan(close) & ~np.isnan(prev_close)
    with np.errstate(divide="ignore", invalid="ignore"):
        down = known & (close < prev_close)
        down_volume = np.where(known, np.where(down, volume, 0.0), np.nan)
        prior_max = hm.shift(hm.rolling_extreme(down_volume, days, "max"), 1)
        prior_down = hm.shift(hm.rolling_mean(np.where(known, down, np.nan), days), 1) * days
        adr = hm.shift(base["adr_usd"], 1)
        ma50 = hm.shift(base["ma50"], 1)
        level = np.full(close.shape, np.nan)
        ma_used = np.full(close.shape, np.nan)
        for w in conf["mas"]:  # the first MA it pivots off wins (10 before 50)
            ma = hm.shift(hm.rolling_mean(close, w), 1)
            pivots = (
                (low <= ma + conf["touch_adr"] * adr)
                & (close > ma)
                & (close <= ma + conf["close_ext_adr_max"] * adr)
            )
            take = pivots & np.isnan(level)
            level = np.where(take, ma, level)
            ma_used = np.where(take, w, ma_used)
        ma50_rising = ma50 >= hm.shift(ma50, conf["ma50_slope_days"])
        values = {
            "pivot": high,  # next session's confirmation trigger
            "entry_close": close,
            "order_stop": low,
            "risk_adr": (close - low) / adr,
            "pivot_ma": ma_used,
            "ma_level": level,
            "low_vs_ma_adr": (low - level) / adr,
            "close_vs_ma_adr": (close - level) / adr,
            "down_volume_max": prior_max,
            "down_days": prior_down,
            "volume_vs_down": volume / prior_max,
            "volume_vs_avg": volume / hm.shift(base["avg_volume"], 1),
            "chg_pct": (close / prev_close - 1) * 100,
            "close_loc": np.where(high > low, (close - low) / (high - low), np.nan),
            "ma50_rising": ma50_rising,
            "adr_pct": hm.shift(base["adr_pct"], 1),
        }
        rules = {
            "up_day": known & (close > prev_close),
            "volume": (prior_down >= 1) & (volume > prior_max),
            "near_ma": ~np.isnan(level),
            "above_rising_ma50": (close > ma50) & ma50_rising,
        }
    return values | {"rules": rules}


def _hits(name: str, found: dict, tickers, sessions: list) -> pd.DataFrame:
    mask = np.logical_and.reduce(list(found["rules"].values()))
    t, j = np.nonzero(mask)
    return pd.DataFrame(
        {
            "strategy": name,
            "session_date": [sessions[i] for i in t],
            "ticker": np.asarray(tickers)[j],
            **{k: v[t, j] for k, v in found.items() if k != "rules"},
        }
    )


def find(g: Mapping[str, np.ndarray], tickers, sessions: list, cfg) -> pd.DataFrame:
    """High tight flags (setup at the session's close, trigger the next session) and pocket
    pivots (the session itself). No tier filter: the caller applies the alert tier like for
    every other strategy. `cfg` is the Config (its `htf` and `pocket_pivot` sections)."""
    htf = _hits("htf", htf_rules(g, cfg.htf), tickers, sessions)
    if len(htf):  # the same flag qualifies on consecutive sessions: pivot_date names it
        row = {s: i for i, s in enumerate(sessions)}
        htf["pivot_date"] = [
            sessions[row[s] - int(d)]
            for s, d in zip(htf["session_date"], htf["flag_days"], strict=True)
        ]
        htf["day_in_setup"] = htf.groupby(["ticker", "pivot_date"]).cumcount() + 1
    pp = _hits("pocket_pivot", pocket_pivot_rules(g, cfg.pocket_pivot), tickers, sessions)
    frames = [f for f in (htf, pp) if len(f)]
    if not frames:
        return pd.DataFrame(columns=["strategy", "session_date", "ticker"])
    return pd.concat(frames, ignore_index=True)
