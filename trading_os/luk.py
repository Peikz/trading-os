"""Martin Luk's setups for the history studies (Emil, 19 Oct 2026). Study only, not live scans.

Luk (US Investing Championship winner 2024-2025) has published no rule sheet; these come
from public write-ups of his interviews, so every threshold is (proposed) in config `luk:`:

- Leader: up >= 30 % over 1, 3 or 6 months, ADR >= 5 % ("mainly", he says, not a hard rule).
- Strength: "lead" = EMA 9 > EMA 21 > EMA 50.
- luk_pullback: a lead stock (yesterday) whose low comes within `touch_adr` ADR of yesterday's
  EMA 9 or EMA 21 and closes back above that EMA.
- luk_avwap_flush: EMA 9 > EMA 21 with EMA 21 rising, yesterday's close above the VWAP
  anchored at the highest high of the last `avwap_lookback` sessions (a base of at least
  `base_min_days`); the day flushes `flush_adr` ADR under yesterday's close into that AVWAP
  and EMA 9 or 21, and closes back above both.
- luk_inside_day: an inside day (lower high, higher low) in a lead stock that closes above its
  EMA 21; entry the next session above the inside day's high, stop at its low.

Stops sit at the day's low (his: "below the low of the entry day"). His exit, a close under
EMA 9 (EMA 21 for more room), is measured for every strategy in `strategy_history`.
Levels (EMAs, AVWAP) are yesterday's, so they were known before the session.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os import history_metrics as hm

STRATEGIES = ("luk_pullback", "luk_avwap_flush", "luk_inside_day")


def avwap_from_high(g: Mapping[str, np.ndarray], lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """VWAP anchored at the highest high of the last `lookback` sessions, and the sessions
    since that high (both NaN until a full window exists)."""
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    n = len(high)
    out = np.full(high.shape, np.nan)
    since = np.full(high.shape, np.nan)
    if n < lookback:
        return out, since
    v = np.nan_to_num(volume)
    pv = np.nan_to_num((high + low + close) / 3) * v
    zero = np.zeros((1, high.shape[1]))
    cs_pv, cs_v = np.vstack([zero, np.cumsum(pv, axis=0)]), np.vstack([zero, np.cumsum(v, axis=0)])
    windows = np.lib.stride_tricks.sliding_window_view(
        np.where(np.isnan(high), -np.inf, high), lookback, axis=0
    )
    anchor = windows.argmax(axis=-1) + np.arange(n - lookback + 1)[:, None]  # absolute row
    full = ~np.isnan(hm.rolling_extreme(high, lookback, "max"))[lookback - 1 :]
    rows = np.arange(lookback - 1, n)[:, None]
    cols = np.arange(high.shape[1])[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        value = (cs_pv[rows + 1, cols] - cs_pv[anchor, cols]) / (
            cs_v[rows + 1, cols] - cs_v[anchor, cols]
        )
    out[lookback - 1 :] = np.where(full, value, np.nan)
    since[lookback - 1 :] = np.where(full, rows - anchor, np.nan)
    return out, since


def indicators(g: Mapping[str, np.ndarray], conf: Mapping[str, Any]) -> dict[str, np.ndarray]:
    high, low, close = g["high"], g["low"], g["close"]
    fast, mid, slow = conf["emas"]
    with np.errstate(divide="ignore", invalid="ignore"):
        adr_pct = hm.rolling_mean((high / low - 1) * 100, hm.ADR_DAYS)
        returns = [(close / hm.shift(close, w) - 1) * 100 for w in (21, 63, 126)]
    ema_fast, ema_mid, ema_slow = (hm.ema(close, s) for s in (fast, mid, slow))
    avwap, since = avwap_from_high(g, conf["avwap_lookback"])
    with np.errstate(invalid="ignore"):
        leader = np.zeros(close.shape, dtype=bool)
        for r in returns:
            leader |= r >= conf["leader_return_min_pct"]
        leader &= adr_pct >= conf["adr_min_pct"]
        lead = (ema_fast > ema_mid) & (ema_mid > ema_slow)
        mid_rising = ema_mid > hm.shift(ema_mid, 5)
    return {
        "adr_pct": adr_pct,
        "adr_usd": adr_pct * close / 100,
        "ema_fast": ema_fast,
        "ema_mid": ema_mid,
        "avwap": avwap,
        "base_days": since,
        "leader": leader,
        "lead": lead,
        "mid_rising": mid_rising,
    }


def _held(low, close, level, adr, touch):
    """The day's low came within `touch` ADR of `level` and the close is above it."""
    return (low <= level + touch * adr) & (close > level)


def find(g: Mapping[str, np.ndarray], tickers, sessions: list, conf) -> pd.DataFrame:
    """Every setup day (signal session t; levels from t-1). No tier filter: the caller
    applies the alert tier like for every other strategy."""
    ind = indicators(g, conf)
    y = {k: hm.shift(v.astype(float), 1) for k, v in ind.items()}  # as of yesterday
    high, low, close = g["high"], g["low"], g["close"]
    prev_close, prev_high, prev_low = (hm.shift(a, 1) for a in (close, high, low))
    adr, touch = y["adr_usd"], conf["touch_adr"]
    with np.errstate(invalid="ignore"):
        leader, lead = y["leader"] == 1, y["lead"] == 1
        fast = _held(low, close, y["ema_fast"], adr, touch)
        mid = _held(low, close, y["ema_mid"], adr, touch)
        pullback = leader & lead & (prev_close > y["ema_mid"]) & (fast | mid)
        flush = (
            leader
            & (y["ema_fast"] > y["ema_mid"])
            & (y["mid_rising"] == 1)
            & (prev_close > y["avwap"])
            & (y["base_days"] >= conf["base_min_days"])
            & (low <= prev_close - conf["flush_adr"] * adr)
            & _held(low, close, y["avwap"], adr, touch)
            & (fast | mid)
        )
        inside = (
            (ind["leader"])
            & (ind["lead"])
            & (high < prev_high)
            & (low > prev_low)
            & (close > ind["ema_mid"])
        )
    frames = []
    for name, mask, level in (
        ("luk_pullback", pullback, np.where(fast, y["ema_fast"], y["ema_mid"])),
        ("luk_avwap_flush", flush, y["avwap"]),
        ("luk_inside_day", inside, ind["ema_mid"]),
    ):
        t, j = np.nonzero(mask)
        frames.append(
            pd.DataFrame(
                {
                    "strategy": name,
                    "session_date": [sessions[i] for i in t],
                    "ticker": np.asarray(tickers)[j],
                    "level": level[t, j],
                    "ema_fast": (ind["ema_fast"] if name == "luk_inside_day" else y["ema_fast"])[
                        t, j
                    ],
                    "ema_mid": (ind["ema_mid"] if name == "luk_inside_day" else y["ema_mid"])[t, j],
                    "avwap": y["avwap"][t, j],
                    "base_days": y["base_days"][t, j],
                    "pivot": high[t, j] if name == "luk_inside_day" else np.nan,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)
