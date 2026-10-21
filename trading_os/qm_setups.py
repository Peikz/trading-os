"""Qullamaggie's breakout from a base that surfs the rising 10- or 20-day MA, for the history
studies (Emil, 20 Oct 2026), and since 21 Oct 2026 the live EOD scan `ma_surf` (Emil: "I will
use this strategy more"; `surf_live.py`, SPEC §6.2) with these rules unchanged.

From his streams (the qullamaggie MCP transcripts; video ids in brackets, the swing trading
school of July 2020 states the method in full [155-158]): a momentum stock with an ADR of
4-5 % or more [158] makes a big move up [12, 156]; it then pulls back or goes sideways for a
few days to a few weeks [129, 155, 157], surfing the rising 10-day MA (strongest names) or
20-day MA (slower names) [155, 156, 158], building higher lows, getting tight [155, 158] on
drying volume [114, 180]; the 10-day (preferably the 20-day too) catches up with the price,
so it is not extended [158]. He buys the opening range high the day the range breaks [156],
only while the stock is up less than its ADR on the day [156], stop at the day's low [157];
sells a third to a half after 3-5 days, stop to break-even, trails the rest to the first
close under the 10-day MA [155, 156, 158], the 20-day for slower stocks (ADR under ~5 %)
[168, 208].

The mechanical reading, every value in config `qm_surf:` (proposed), base ending at the
session (its close known), trigger for the next session(s):
- `adr`: ADR(20) >= `adr_min_pct`.
- `prior_move`: the pivot (the highest high of the last `base_max_days` sessions) is at least
  `prior_move_min_pct` above the lowest low of the `prior_move_max_days` sessions before it.
- `base`: `base_min_days` to `base_max_days` sessions from the pivot to the session.
- `surf`: the closes of the whole base, and of at least `surf_min_days` sessions, are on the
  10-day MA (or, failing that, the 20-day), at most `surf_tol_adr` ADR under it, and that MA
  is rising (above its value 5 sessions earlier, SPEC §5).
- `near_ma`: the close at most `near_ma_adr_max` ADR above that MA.
- `higher_low`: the low of the last `right_side_days` sessions is above the base's low.
- `tight` / `dry`: those sessions' range <= `right_range_adr_max` ADR, their average volume
  <= `right_volume_ratio_max` x the 50-day average.
- `reachable`: pivot <= close + `trigger_within_adr` ADR, so a fill at the pivot is not up
  more than his 1 ADR on the day (`max_entry` is that price).
Order stop: the right side's low, at most `stop_adr_max` ADR under the pivot (his own stop,
the breakout day's low, is only known on that day: the minute study's "low so far").
`trail_ma`: 10 at ADR >= `trail_fast_adr_min_pct`, else 20.

How it differs from the breakout B1-B5 (SPEC §6.4): B2 needs two or more pullbacks, each
<= 0.85 x the one before, in a 10-40 session base; B3 checks the MAs on the last day only; B5
triggers at the close on range and RVOL. Here the base may be a single pullback of 5+ days,
but every close in it rides the rising MA, the price has to be back near that MA, and the
trigger is a buy stop at the range high within 1 ADR of the prior close.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os import history_metrics as hm
from trading_os.patterns import at_offset, last_extreme, mean_between, min_since

STRATEGIES = ("qm_surf",)
AVG_VOLUME_DAYS = 50


def rules(g: Mapping[str, np.ndarray], conf: Mapping[str, Any]) -> dict[str, Any]:
    """Every value and rule for every (session, ticker)."""
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    longest = conf["base_max_days"]
    with np.errstate(divide="ignore", invalid="ignore"):
        adr_pct = hm.rolling_mean((high / low - 1) * 100, hm.ADR_DAYS)
        adr = adr_pct * close / 100
        avg_volume = hm.rolling_mean(volume, AVG_VOLUME_DAYS)
        mas = {w: hm.rolling_mean(close, w) for w in (10, 20, 50)}
        pivot, since = last_extreme(high, longest, "max")
        base_len = since + 1
        trough, trough_since = last_extreme(
            low, conf["prior_move_max_days"] + 1, "min", latest=True
        )
        prior_move = (pivot / at_offset(trough, since) - 1) * 100
        rows = np.arange(len(high))[:, None].astype(float)
        base_low = min_since(low, since, np.zeros_like(since), longest)
        rs = conf["right_side_days"]
        right_low = hm.rolling_extreme(low, rs, "min")
        right_range = (hm.rolling_extreme(high, rs, "max") - right_low) / adr
        right_volume = hm.rolling_mean(volume, rs) / avg_volume
        surf_ma = np.full(close.shape, np.nan)
        surf_days = np.full(close.shape, np.nan)
        for w in conf["surf_mas"]:  # the first MA it surfs wins (10 before 20)
            ma = mas[w]
            on = close >= ma - conf["surf_tol_adr"] * adr
            streak = hm.consecutive(on & ~np.isnan(ma))
            rising = ma > hm.shift(ma, hm.MA_SLOPE_LOOKBACK)
            surfs = (streak >= np.fmax(base_len, conf["surf_min_days"])) & rising
            take = surfs & np.isnan(surf_ma)
            surf_ma = np.where(take, w, surf_ma)
            surf_days = np.where(take, streak, surf_days)
        line = np.full(close.shape, np.nan)
        for w in conf["surf_mas"]:
            line = np.where(surf_ma == w, mas[w], line)
        dist = (close - line) / adr
        order_stop = np.fmax(right_low, pivot - conf["stop_adr_max"] * adr)
        values = {
            "pivot": pivot,
            "base_len": base_len,
            "order_stop": order_stop,
            "risk_adr": (pivot - order_stop) / adr,
            "max_entry": close + conf["trigger_within_adr"] * adr,
            "trail_ma": np.where(adr_pct >= conf["trail_fast_adr_min_pct"], 10, 20),
            "adr_pct": adr_pct,
            "adr_usd": adr,
            "prior_move_pct": prior_move,
            "prior_move_days": at_offset(trough_since, since),
            "base_low": base_low,
            "base_depth_pct": (pivot - base_low) / pivot * 100,
            "base_volume_ratio": mean_between(volume, rows - since, rows) / avg_volume,
            "right_low": right_low,
            "right_range_adr": right_range,
            "right_volume_ratio": right_volume,
            "last_range_adr": (high - low) / adr,
            "pivot_dist_adr": (pivot - close) / adr,
            "surf_ma": surf_ma,
            "surf_days": surf_days,
            "surf_ma_dist_adr": dist,
            "dist_ma10_adr": (close - mas[10]) / adr,
            "dist_ma20_adr": (close - mas[20]) / adr,
            "ma_stacked": (mas[10] > mas[20]) & (mas[20] > mas[50]),
            "above_ma50": close > mas[50],
        }
        checks = {
            "adr": adr_pct >= conf["adr_min_pct"],
            "prior_move": prior_move >= conf["prior_move_min_pct"],
            "base": (base_len >= conf["base_min_days"]) & (base_len <= longest),
            "surf": ~np.isnan(surf_ma),
            "near_ma": dist <= conf["near_ma_adr_max"],
            "higher_low": (base_len > rs) & (right_low > base_low),
            "tight": right_range <= conf["right_range_adr_max"],
            "dry": right_volume <= conf["right_volume_ratio_max"],
            "reachable": values["pivot_dist_adr"] <= conf["trigger_within_adr"],
        }
    return values | {"rules": checks}


def find(g: Mapping[str, np.ndarray], tickers, sessions: list, conf) -> pd.DataFrame:
    """Every session a base qualifies (trigger: the pivot, the next session). The same base
    qualifies on consecutive sessions: `pivot_date` names it, `day_in_setup` counts its days.
    No tier filter: the caller applies the alert tier like for every other strategy."""
    found = rules(g, conf)
    mask = np.logical_and.reduce(list(found["rules"].values()))
    t, j = np.nonzero(mask)
    if not len(t):
        return pd.DataFrame(columns=["strategy", "session_date", "ticker"])
    start = t - found["base_len"][t, j].astype(int) + 1  # the pivot's session
    out = pd.DataFrame(
        {
            "strategy": "qm_surf",
            "session_date": [sessions[i] for i in t],
            "ticker": np.asarray(tickers)[j],
            "pivot_date": [sessions[i] for i in start],
            **{k: v[t, j] for k, v in found.items() if k != "rules"},
        }
    )
    out["ma_low_adr"] = _lowest_vs_ma(g, found, t, j)
    out["day_in_setup"] = out.groupby(["ticker", "pivot_date"]).cumcount() + 1
    return out


def _lowest_vs_ma(g, found, t, j) -> np.ndarray:
    """Deepest low of the base against the surfed MA, in ADR (negative: an undercut)."""
    out = np.full(len(t), np.nan)
    close, low = g["close"], g["low"]
    for k, (i, c) in enumerate(zip(t, j, strict=True)):
        start = i - int(found["base_len"][i, c]) + 1
        w = int(found["surf_ma"][i, c])
        if start - w + 1 < 0:
            continue
        lows = low[start : i + 1, c]
        ma = np.array([np.mean(close[d - w + 1 : d + 1, c]) for d in range(start, i + 1)])
        out[k] = np.min(lows - ma) / found["adr_usd"][i, c]
    return out
