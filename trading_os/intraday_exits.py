"""Exits for the minute-bar study, many trades at once (Emil, 19 Oct 2026). Facts, not advice.

The entry day runs bar by bar in `intraday_entries.entry_day_exit`. From the next session on,
every trade runs on daily bars here, as matrices (trades x the `K` sessions after the entry
day), so a month of trades takes a few array passes rather than a Python loop per trade.

Exits (a short runs the same code on mirrored prices):

- `hold_{n}d`: hold n sessions (1, 5, 21) with the stop;
- `trail_{line}`: the first close through the 10-/20-day MA or EMA 9/21 (Luk), stop before;
- `q{p}_ma{w}`: config `exits:`, a third at the close of day p, then a break-even stop and
  the rest on the w-day MA (Qullamaggie);
- `time{n}d`: out at the close of day n, stop before (Stockbee);
- `target{x}_{n}d`: out at +x % within n days, stop first on a day that touches both;
- grading study only (`extra`): `mrev_ma{w}`, out at yesterday's w-day MA (a bounce's or a
  short's target), and `tgt{x}R_{n}d`, out at +x R within n days.

Every exit also reports the sessions it held (`days_*`). A stop day fills at the stop, or at
the open when it gapped through. A trade stopped on the entry day has that result in every
exit. After a delisting (bars stop) the last close counts;
a trade whose window runs past the newest data is unknown (NaN) for that exit, except the
trails, which close at the newest close like the other history studies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

K = 63  # sessions after the entry day (a quarter); the trails close here at the latest
HORIZONS = (1, 5, 21)


def windows(arr: np.ndarray, t: np.ndarray, j: np.ndarray, k: int = K) -> np.ndarray:
    """Rows t+1 .. t+k of column j for every trade: (trades, k), NaN past the last row."""
    rows = t[:, None] + 1 + np.arange(k)[None, :]
    inside = rows < arr.shape[0]
    return np.where(inside, arr[np.minimum(rows, arr.shape[0] - 1), j[:, None]], np.nan)


def _first(mask: np.ndarray) -> np.ndarray:
    """Index of the first True per row, or the row length when there is none."""
    return np.where(mask.any(axis=1), mask.argmax(axis=1), mask.shape[1])


def _ffill(a: np.ndarray, first: np.ndarray) -> np.ndarray:
    """Forward-fill NaN along each row, starting from `first` (the entry day's close)."""
    full = np.concatenate([first[:, None], a], axis=1)
    idx = np.where(~np.isnan(full), np.arange(full.shape[1])[None, :], 0)
    np.maximum.accumulate(idx, axis=1, out=idx)
    return np.take_along_axis(full, idx, axis=1)[:, 1:]


def _pick(a: np.ndarray, k: np.ndarray) -> np.ndarray:
    k = np.minimum(k, a.shape[1] - 1)
    return np.take_along_axis(a, k[:, None], axis=1)[:, 0]


def run(
    daily: Mapping[str, np.ndarray],
    lines: Mapping[str, np.ndarray],
    t: np.ndarray,
    j: np.ndarray,
    entry: np.ndarray,
    stop: np.ndarray,
    side: np.ndarray,
    day0: tuple[np.ndarray, np.ndarray],
    rules: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
    k: int = K,
) -> dict[str, np.ndarray]:
    """R (per unit of the starting risk) for every exit and trade, plus the % move held to
    1, 5 and 21 sessions and the sessions each exit held (`days_*`, 0 = out on the entry
    day). `daily`: session x ticker open/high/low/close; `lines`: the trail lines on the same
    grid (ma10, ma20, ema9, ema21); `day0`: (stopped on the entry day, exit price that day).

    The partial exits also keep their two legs (`r_part{p}`: the part sold at day p's close;
    `r_rest{p}_ma{w}`: the rest), so any partial fraction can be priced later. `extra`
    (config `intraday_study:`) adds the grading study's exits: `mrev_ma{w}`, out when the
    price reaches yesterday's w-day MA (a bounce or a short's cover; a limit order at the
    MA, filled at the open when it gaps through), and `tgt{x}R_{n}d`, out at +x R within n
    sessions. `k`: sessions the window reaches (the trails close there at the latest)."""
    n_rows = daily["close"].shape[0]
    sign = side[:, None].astype(float)
    o, h, lo, c = (windows(daily[f], t, j, k) for f in ("open", "high", "low", "close"))
    if (side < 0).any():  # a short is a long on mirrored prices
        o, c = o * sign, c * sign
        h, lo = np.where(sign > 0, h, -lo), np.where(sign > 0, lo, -h)
    e, s = entry * side, stop * side
    risk = e - s
    stopped0, exit0 = day0
    x0 = exit0 * side
    r0 = (x0 - e) / risk
    c_fill = _ffill(c, x0)
    left = n_rows - 1 - t  # sessions of data after the entry day
    stop_k = _first(lo <= s[:, None])
    stop_px = np.minimum(np.where(np.isnan(_pick(o, stop_k)), s, _pick(o, stop_k)), s)

    def r(price):
        return np.where(stopped0, r0, (price - e) / risk)

    def held(days, known):
        return np.where(known, np.where(stopped0, 0, days), np.nan)

    out: dict[str, np.ndarray] = {"r_0d": r0, "stopped_0d": stopped0}
    for n in HORIZONS:
        price = np.where(stop_k < n, stop_px, c_fill[:, n - 1])
        known = stopped0 | (left >= n)
        out[f"r_hold_{n}d"] = np.where(known, r(price), np.nan)
        pnl = (np.where(stopped0, x0, price) / e - 1) * 100 * side
        out[f"pnl_hold_{n}d"] = np.where(known, pnl, np.nan)
        out[f"stopped_{n}d"] = np.where(known, stopped0 | (stop_k < n), np.nan)
        out[f"days_hold_{n}d"] = held(np.where(stop_k < n, stop_k + 1, n), known)
    last = np.clip(left, 1, k) - 1  # the newest session inside the window
    for name, line in lines.items():
        m = windows(line, t, j, k) * sign
        through = c < m  # NaN compares False
        hit = _first(through)
        stop_first = (stop_k < k) & (stop_k <= hit)
        price = np.where(
            stop_first, stop_px, np.where(hit < k, _pick(c_fill, hit), _pick(c_fill, last))
        )
        days = np.where(stop_first, stop_k, np.where(hit < k, hit, last)) + 1
        known = stopped0 | (left >= 1)
        out[f"r_trail_{name}"] = np.where(known, r(price), np.nan)
        out[f"days_trail_{name}"] = held(days, known)
    frac = rules["partial_fraction"]
    for p in rules["partial_days"]:
        first_part = c_fill[:, p - 1]
        known = stopped0 | (left >= p)
        stopped_before = stop_k < p
        stop_r = (stop_px - e) / risk
        out[f"r_part{p}"] = np.where(
            known, r(np.where(stopped_before, stop_px, first_part)), np.nan
        )
        for w in rules["trail_mas"]:
            m = windows(lines[f"ma{w}"], t, j, k) * sign
            be = lo <= e[:, None]
            through = c < m
            after = np.arange(k)[None, :] >= p
            hit = _first((be | through) & after)
            be_first = _pick(be, hit) & (hit < k)
            rest = np.where(
                be_first,
                np.minimum(np.where(np.isnan(_pick(o, hit)), e, _pick(o, hit)), e),
                np.where(hit < k, _pick(c_fill, hit), _pick(c_fill, last)),
            )
            value = frac * (first_part - e) / risk + (1 - frac) * (rest - e) / risk
            value = np.where(stopped_before, stop_r, value)
            out[f"r_q{p}_ma{w}"] = np.where(known, np.where(stopped0, r0, value), np.nan)
            rest_r = np.where(stopped_before, stop_r, (rest - e) / risk)
            out[f"r_rest{p}_ma{w}"] = np.where(known, np.where(stopped0, r0, rest_r), np.nan)
            days = np.where(stopped_before, stop_k + 1, np.where(hit < k, hit + 1, last + 1))
            out[f"days_q{p}_ma{w}"] = held(days, known)
    for n in rules["time_days"]:
        price = np.where(stop_k < n, stop_px, c_fill[:, n - 1])
        known = stopped0 | (left >= n)
        out[f"r_time{n}d"] = np.where(known, r(price), np.nan)
        out[f"days_time{n}d"] = held(np.where(stop_k < n, stop_k + 1, n), known)
    pct, days_max = rules["target_pct"], rules["target_days"]
    target = np.where(side > 0, entry * (1 + pct / 100), -entry * (1 - pct / 100))
    name = f"target{pct:g}_{days_max}d"
    price, days = _target(o, h, c_fill, stop_k, stop_px, target, days_max)
    known = stopped0 | (left >= days_max)
    out[f"r_{name}"] = np.where(known, r(price), np.nan)
    out[f"days_{name}"] = held(days, known)
    if extra:
        for w in extra.get("mrev_mas", ()):
            m = windows(lines[f"ma{w}"], t - 1, j, k) * sign  # yesterday's MA, every day
            hit = _first(h >= m)
            level = _pick(m, hit)
            fill = np.where(np.isnan(_pick(o, hit)), level, np.maximum(_pick(o, hit), level))
            stop_first = (stop_k < k) & (stop_k <= hit)
            price = np.where(stop_first, stop_px, np.where(hit < k, fill, _pick(c_fill, last)))
            days = np.where(stop_first, stop_k, np.where(hit < k, hit, last)) + 1
            known = stopped0 | (left >= 1)
            out[f"r_mrev_ma{w}"] = np.where(known, r(price), np.nan)
            out[f"days_mrev_ma{w}"] = held(days, known)
        n = extra.get("r_target_days", 10)
        for x in extra.get("r_targets", ()):
            price, days = _target(o, h, c_fill, stop_k, stop_px, e + x * risk, n)
            known = stopped0 | (left >= n)
            out[f"r_tgt{x:g}R_{n}d"] = np.where(known, r(price), np.nan)
            out[f"days_tgt{x:g}R_{n}d"] = held(days, known)
    return out


def _target(o, h, c_fill, stop_k, stop_px, target, n):
    """(exit price, sessions held) for a limit order at `target` (mirrored prices) good for
    n sessions: filled at the target, or at the open when the day gaps through it; the stop
    wins on a day that touches both; not filled = out at day n's close."""
    hit = _first(h[:, :n] >= target[:, None])
    gap = _pick(o, hit)
    fill = np.maximum(np.where(np.isnan(gap), target, gap), target)
    stop_first = (stop_k < n) & (stop_k <= hit)
    price = np.where(stop_first, stop_px, np.where(hit < n, fill, c_fill[:, n - 1]))
    days = np.where(stop_first, stop_k + 1, np.where(hit < n, hit + 1, n))
    return price, days
