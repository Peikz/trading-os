"""Mark Minervini's Trend Template and VCP for the history studies (Emil, 19 Oct 2026).
Study only, not live scans. Rules from his books (Trade Like a Stock Market Wizard, 2013;
Think & Trade Like a Champion, 2017); the mechanical reading of them is (proposed) in config
`minervini:`.

Trend Template, all eight on the same day:
1. close above the 150- and 200-day MA; 2. 150-day above 200-day; 3. 200-day rising for at
least a month (`ma200_rising_days`); 4. 50-day above the 150- and 200-day; 5. close above the
50-day; 6. at least 30 % above the 52-week low; 7. within 25 % of the 52-week high;
8. RS >= 70 (our 1-99 RS on 1/3/6-month returns; IBD's own rating is not public).

VCP (volatility contraction pattern) on a Trend Template stock, base ending the day before:
- the base runs from its highest high within `base_max_days` and is >= `base_min_days` long;
- 2-6 contractions (from each swing high, one not exceeded within `swing_bars` sessions
  either side, to the next; at least `swing_adr_mult` ADR deep), each shallower than
  the one before, the first <= `first_contraction_max_pct` deep, the last <= `last_..._pct`;
- volume dries up: the last 10 sessions average <= `dryup_ratio_max` x the 50-day average;
- pivot = the high the last contraction started from.

`vcp_breakout`: the session trades through the pivot (a buy stop: filled at the pivot, or the
open if it gapped over). Stop: the last contraction's low, but at most `stop_max_pct` under
the entry (his "cut at 7-8 %"). Volume on the day (`vol_ratio`, vs the 50-day average) is
stored, not required: it is only known at the close ("40-50 % above average", he says).
`minervini_tt`: the Trend Template on Fridays, returns only (a watchlist, not a trade).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os import history_metrics as hm

STRATEGIES = ("minervini_tt", "vcp_breakout")
RS_WINDOWS = (21, 63, 126)


def rs_rating(close: np.ndarray, windows=RS_WINDOWS) -> np.ndarray:
    """1-99 per session across all stocks: the mean percentile rank of the returns (the live
    `metrics.rs_percentile`, on the grid). Needs the whole cross-section, not a chunk."""
    ranks = []
    with np.errstate(divide="ignore", invalid="ignore"):
        for w in windows:
            ret = close / hm.shift(close, w) - 1
            ranks.append(pd.DataFrame(ret).rank(axis=1, pct=True).to_numpy())
    return np.round(np.nanmean(np.stack(ranks), axis=0) * 98 + 1) if ranks else close


def trend_template(g: Mapping[str, np.ndarray], rs: np.ndarray, conf) -> np.ndarray:
    close, high, low = g["close"], g["high"], g["low"]
    ma50, ma150, ma200 = (hm.rolling_mean(close, w) for w in (50, 150, 200))
    low52 = hm.rolling_extreme(low, 252, "min")
    high52 = hm.rolling_extreme(high, 252, "max")
    with np.errstate(invalid="ignore"):
        return (
            (close > ma150)
            & (close > ma200)
            & (ma150 > ma200)
            & (ma200 > hm.shift(ma200, conf["ma200_rising_days"]))
            & (ma50 > ma150)
            & (ma50 > ma200)
            & (close > ma50)
            & (close >= low52 * (1 + conf["above_52w_low_pct"] / 100))
            & (close >= high52 * (1 - conf["within_52w_high_pct"] / 100))
            & (rs >= conf["rs_min"])
        )


def contractions(high: np.ndarray, low: np.ndarray, bars: int, min_depth_pct: float) -> list:
    """(swing high, lowest low after it, depth %) per pullback in a base that starts at its
    highest high (index 0). A swing high is above the `bars` sessions before it and not
    exceeded in the `bars` after it (so it needs `bars` sessions after it); each pullback runs
    to the next swing high, the last one to the end. Pullbacks under `min_depth_pct` are
    dropped (noise), except the last, which is the tightness being measured."""
    n = len(high)
    tops = (
        [0]
        + [
            i
            for i in range(1, n - bars)
            if high[i] > np.max(high[max(0, i - bars) : i])  # strictly: a flat top counts once
            and high[i] >= np.max(high[i + 1 : i + bars + 1])
        ]
    )
    out = []
    for top, nxt in zip(tops, [*tops[1:], n], strict=True):
        low_after = float(np.min(low[top:nxt]))
        depth = (high[top] - low_after) / high[top] * 100
        if depth >= min_depth_pct or nxt == n:
            out.append((float(high[top]), low_after, float(depth)))
    return out


def vcp(end: int, h, lo, v, avg50, adr_pct, conf) -> dict[str, Any] | None:
    """The VCP of one stock's base ending at index `end`, or None."""
    start = end - conf["base_max_days"] + 1
    if start < 0 or not adr_pct > 0 or np.isnan(h[start : end + 1]).any():
        return None
    peak = start + int(np.argmax(h[start : end + 1]))
    if end - peak + 1 < conf["base_min_days"]:
        return None
    found = contractions(
        h[peak : end + 1], lo[peak : end + 1], conf["swing_bars"], conf["swing_adr_mult"] * adr_pct
    )
    depths = [d for _, _, d in found]
    if not 2 <= len(found) <= 6:
        return None
    shrinking = all(b < a for a, b in zip(depths, depths[1:], strict=False))
    if not (
        shrinking
        and depths[0] <= conf["first_contraction_max_pct"]
        and depths[-1] <= conf["last_contraction_max_pct"]
    ):
        return None
    recent = np.nanmean(v[end - 9 : end + 1])
    dryup = recent / avg50[end] if avg50[end] > 0 else np.nan
    if not dryup <= conf["dryup_ratio_max"]:
        return None
    pivot = found[-1][0]  # the high the last contraction started from
    return {
        "pivot": pivot,
        "last_low": float(found[-1][1]),
        "contractions": len(found),
        "depths": ",".join(f"{d:.1f}" for d in depths),
        "last_depth_pct": depths[-1],
        "base_len": end - peak + 1,
        "dryup_ratio": float(dryup),
    }


def find(g: Mapping[str, np.ndarray], tickers, sessions: list, conf, rs: np.ndarray):
    """Trend Template Fridays and VCP breakouts (no tier filter; the caller applies it).
    `rs` is the RS rating for the same columns, computed on the full grid."""
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    tt = trend_template(g, rs, conf)
    with np.errstate(divide="ignore", invalid="ignore"):
        adr_pct = hm.rolling_mean((high / low - 1) * 100, hm.ADR_DAYS)
        avg50 = hm.rolling_mean(volume, 50)
        prior10 = hm.shift(hm.rolling_extreme(high, 10, "max"), 1)
        # A VCP pivot sits at or under the right side's high, so a VCP breakout day is at
        # least a new 10-day high: the cheap pre-filter before the base analysis.
        candidates = hm.shift(tt.astype(float), 1) == 1
        candidates &= high > prior10
    rows = []
    by_week: dict[tuple, int] = {}
    for i, s in enumerate(sessions):
        by_week[s.isocalendar()[:2]] = i
    fridays = np.zeros(len(sessions), dtype=bool)
    fridays[list(by_week.values())] = True
    t, j = np.nonzero(tt & fridays[:, None])
    rows.append(
        pd.DataFrame(
            {
                "strategy": "minervini_tt",
                "session_date": [sessions[i] for i in t],
                "ticker": np.asarray(tickers)[j],
                "rs_rating": rs[t, j],
            }
        )
    )
    found = []
    for j in np.unique(np.nonzero(candidates)[1]):
        hj, lj, vj, aj = high[:, j], low[:, j], volume[:, j], avg50[:, j]
        for t in np.nonzero(candidates[:, j])[0]:
            base = vcp(int(t) - 1, hj, lj, vj, aj, adr_pct[t - 1, j], conf)
            if base is None or not hj[t] >= base["pivot"]:
                continue
            found.append(
                {
                    "strategy": "vcp_breakout",
                    "session_date": sessions[t],
                    "ticker": tickers[j],
                    "rs_rating": rs[t - 1, j],
                    "vol_ratio": float(vj[t] / aj[t - 1]) if aj[t - 1] > 0 else np.nan,
                    **base,
                }
            )
    rows.append(pd.DataFrame(found))
    return (
        pd.concat([r for r in rows if len(r)], ignore_index=True)
        if any(map(len, rows))
        else (pd.DataFrame(columns=["strategy", "session_date", "ticker"]))
    )
