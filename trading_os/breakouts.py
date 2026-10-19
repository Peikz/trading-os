"""Breakout criteria B1-B5 (SPEC §6.4, Phase 2).

Code computes each criterion as a boolean and stores every intermediate value (pivot, base
length, contraction depths, right-side range, ...) so a human can audit it. Code never
assigns the A/B/C grade.

The base is measured back from its highest high: the pivot is the highest high of the last
`base_max_days` sessions, and the base runs from that session to the evaluation session.
Contractions come from a zigzag inside the base: a pullback counts once price has come back
up by at least `swing_adr_mult` × ADR $ from its low.

Two evaluations per ticker and session T:
- watch: the base ends at T; B1-B4.
- trigger: the base ends at T-1 and T's bar is checked against it for B5.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from trading_os.history_metrics import rolling_mean, shift

ADR_DAYS = 20
AVG_VOLUME_DAYS = 50
RVOL_DAYS = 50
MA_SLOPE_LOOKBACK = 5


@dataclass
class Base:
    pivot: float
    base_len: int
    prior_move_pct: float
    prior_move_days: int
    contraction_depths: list[float]
    contraction_lows: list[float]
    last_contraction_low: float
    base_volume_ratio: float
    right_side_range_adr: float
    right_side_volume_ratio: float
    adr_usd: float
    ma_stacked: bool
    order_stop: float
    risk_adr: float
    b1: bool
    b2: bool
    b3: bool
    b4: bool


def zigzag_pullbacks(
    high: np.ndarray, low: np.ndarray, threshold: float
) -> tuple[list[float], list[float]]:
    """Pullbacks inside a base that starts at its highest high (index 0).

    Returns (depths in %, swing lows). A pullback is confirmed when price rises at least
    `threshold` above its low; the last, unconfirmed pullback counts too if it is at least
    `threshold` deep, so a base still forming its right side is measured.
    """
    depths: list[float] = []
    lows: list[float] = []
    swing_high = high[0]
    swing_low = np.inf
    falling = True
    for h, lo in zip(high[1:], low[1:], strict=True):
        if falling:
            swing_low = min(swing_low, lo)
            if h - swing_low >= threshold:  # turned up: pullback confirmed
                depths.append((swing_high - swing_low) / swing_high * 100)
                lows.append(swing_low)
                falling, swing_high = False, h
        else:
            swing_high = max(swing_high, h)
            if swing_high - lo >= threshold:  # turned down: a new pullback starts
                falling, swing_low = True, lo
    if falling and np.isfinite(swing_low) and swing_high - swing_low >= threshold:
        depths.append((swing_high - swing_low) / swing_high * 100)
        lows.append(swing_low)
    return depths, lows


def analyze_base(
    end: int,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    ind: Mapping[str, np.ndarray],
    p: Mapping[str, Any],
) -> Base | None:
    """B1-B4 for a base ending at index `end` of one ticker's arrays (oldest first)."""
    base_max, base_min = p["base_max_days"], p["base_min_days"]
    start = end - base_max + 1
    if start < 0:
        return None
    window_high = high[start : end + 1]
    adr_usd = ind["adr_usd"][end]
    if np.isnan(window_high).any() or not adr_usd > 0:
        return None

    peak = start + int(np.argmax(window_high))
    prior_start = peak - p["prior_move_max_days"]
    if prior_start < 0 or np.isnan(low[prior_start : end + 1]).any():
        return None
    pivot = float(high[peak])
    base_len = end - peak + 1
    trough = prior_start + int(np.argmin(low[prior_start : peak + 1]))
    prior_move_pct = (pivot / low[trough] - 1) * 100

    depths, lows = zigzag_pullbacks(
        high[peak : end + 1], low[peak : end + 1], p["swing_adr_mult"] * adr_usd
    )
    last_low = lows[-1] if lows else float(np.min(low[peak : end + 1]))
    contracting = all(
        b <= p["contraction_ratio_max"] * a for a, b in zip(depths, depths[1:], strict=False)
    )
    higher_lows = all(b > a for a, b in zip(lows, lows[1:], strict=False))
    base_volume_ratio = float(np.mean(volume[peak : end + 1]) / ind["avg_volume"][peak])

    rs = p["right_side_days"]
    rs_range = float(np.max(high[end - rs + 1 : end + 1]) - np.min(low[end - rs + 1 : end + 1]))
    rs_volume_ratio = float(np.mean(volume[end - rs + 1 : end + 1]) / ind["avg_volume"][end])

    order_stop = max(last_low, pivot - p["stop_adr_mult"] * adr_usd)
    ma10, ma20, ma50 = ind["ma10"][end], ind["ma20"][end], ind["ma50"][end]
    return Base(
        pivot=pivot,
        base_len=base_len,
        prior_move_pct=float(prior_move_pct),
        prior_move_days=int(peak - trough),
        contraction_depths=[round(float(d), 2) for d in depths],
        contraction_lows=[float(x) for x in lows],
        last_contraction_low=float(last_low),
        base_volume_ratio=base_volume_ratio,
        right_side_range_adr=rs_range / adr_usd,
        right_side_volume_ratio=rs_volume_ratio,
        adr_usd=float(adr_usd),
        ma_stacked=bool(ma10 > ma20 > ma50),
        order_stop=float(order_stop),
        risk_adr=float((pivot - order_stop) / adr_usd),
        b1=bool(prior_move_pct >= p["prior_move_min_pct"]),
        b2=bool(
            base_min <= base_len <= base_max
            and len(depths) >= p["min_contractions"]
            and contracting
            and higher_lows
            and base_volume_ratio < p["base_volume_ratio_max"]
        ),
        b3=bool(
            close[end] > ma10
            and close[end] > ma20
            and ind["ma10_rising"][end]
            and ind["ma20_rising"][end]
        ),
        b4=bool(
            base_len >= rs
            and rs_range < p["right_side_range_adr_max"] * adr_usd
            and rs_volume_ratio < 1.0
        ),
    )


def indicators(high, low, close, volume) -> dict[str, np.ndarray]:
    """Per-session indicators on sessions × tickers arrays (all windows need full data)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        adr_pct = rolling_mean((high / low - 1) * 100, ADR_DAYS)
        ma10, ma20, ma50 = (rolling_mean(close, w) for w in (10, 20, 50))
        return {
            "adr_usd": adr_pct * close / 100,
            "avg_volume": rolling_mean(volume, AVG_VOLUME_DAYS),
            "rvol": volume / rolling_mean(shift(volume, 1), RVOL_DAYS),
            "ma10": ma10,
            "ma20": ma20,
            "ma50": ma50,
            "ma10_rising": ma10 > shift(ma10, MA_SLOPE_LOOKBACK),
            "ma20_rising": ma20 > shift(ma20, MA_SLOPE_LOOKBACK),
        }


def detect(
    grids: Mapping[str, np.ndarray],
    tickers: pd.Index,
    sessions: list[dt.date],
    params: Mapping[str, Any],
) -> pd.DataFrame:
    """Watch (B1-B4, base ending at the last session) and trigger (B5 against the base that
    ended the session before) for every ticker. One row per ticker that has a base."""
    high, low, close, volume = (grids[f] for f in ("high", "low", "close", "volume"))
    ind = indicators(high, low, close, volume)
    t = len(sessions) - 1
    rows = []
    for j, ticker in enumerate(tickers):
        col = {k: v[:, j] for k, v in ind.items()}
        args = (high[:, j], low[:, j], close[:, j], volume[:, j], col, params)
        watch = analyze_base(t, *args)
        before = analyze_base(t - 1, *args)
        if watch is None and before is None:
            continue
        row: dict[str, Any] = {"ticker": ticker, "session_date": sessions[t]}
        if watch is not None:
            row |= {f"bo_{k}": _flat(v) for k, v in asdict(watch).items()}
        if before is not None:
            day_range = high[t, j] - low[t, j]
            row |= {
                "trig_pivot": before.pivot,
                "trig_order_stop": before.order_stop,
                "trig_risk_adr": before.risk_adr,
                "trig_base_len": before.base_len,
                "trig_contraction_depths": _flat(before.contraction_depths),
                "trig_b1": before.b1,
                "trig_b2": before.b2,
                "trig_b3": before.b3,
                "trig_b4": before.b4,
                "trig_range_adr": float(day_range / before.adr_usd),
                "trig_rvol": float(col["rvol"][t]),
                "trig_b5": bool(
                    close[t, j] > before.pivot
                    and day_range > params["trigger_range_adr_min"] * before.adr_usd
                    and col["rvol"][t] >= params["trigger_rvol_min"]
                ),
            }
        rows.append(row)
    return pd.DataFrame(rows)


def _flat(value: Any) -> Any:
    if isinstance(value, list):
        return ",".join(f"{v:g}" for v in value)
    return value
