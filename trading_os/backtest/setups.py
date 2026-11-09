"""Step 3 of the backtest module (docs/backlog/backtest.md §5): the six setups on daily bars.

Each setup is a pure function `(w, ind, params) -> rows` over the wide frames from
`indicators.wide` and the indicator dict from `indicators.compute`. One row per signal:
`setup, session_date, ticker, side (+1 long, -1 short), entry, stop, adr_usd, stop_adr, skip`
plus audit columns (`pivot`, `base_len`, `trigger`, `close_ok`, `anchor_age`). `skip` marks a
stop wider than the setup's `stop_max_adr` (§4 skip rule); skipped rows are kept for audit.

Decisions use only bars up to the signal day. The close-fill setups (L1, L2, L3, S1, S2) enter at
the signal day's close. B0 is a buy stop: its base, pivot and filters come from the day before,
and the trigger day supplies the fill (max(open, trigger), none above the limit) and the close
check (`close_ok`), which the trade engine (step 4) turns into `fail_sold`.

Daily stand-ins for intraday entries (Martin Luk enters on 1-5 minute charts). Info-only
shorts (S1, S2) assume borrow is always available.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

ROW_COLUMNS = [
    "setup",
    "session_date",
    "ticker",
    "side",
    "entry",
    "stop",
    "adr_usd",
    "stop_adr",
    "skip",
    "close_ok",
    "pivot",
    "base_len",
    "trigger",
    "anchor_age",
]


def _a(frame: pd.DataFrame) -> np.ndarray:
    return frame.to_numpy(dtype="float64")


def _shift(a: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(a, np.nan, dtype="float64")
    if k < len(a):
        out[k:] = a[: len(a) - k]
    return out


def _roll(frame_or_arr, window: int, how: str) -> np.ndarray:
    df = pd.DataFrame(frame_or_arr)
    r = df.rolling(window, min_periods=window)
    return getattr(r, how)().to_numpy(dtype="float64")


def _rows(setup: str, w, mask: np.ndarray, side: int, entry, stop, adr, max_adr, **extra):
    t_idx, j_idx = np.nonzero(mask)
    if len(t_idx) == 0:
        return pd.DataFrame(columns=ROW_COLUMNS)
    pick = (t_idx, j_idx)
    e, s, d = entry[pick], stop[pick], adr[pick]
    dist = (e - s) * side / d
    out = pd.DataFrame(
        {
            "setup": setup,
            "session_date": w["close"].index[t_idx],
            "ticker": w["close"].columns[j_idx],
            "side": side,
            "entry": e,
            "stop": s,
            "adr_usd": d,
            "stop_adr": dist,
            "skip": ~(dist <= max_adr) | ~(dist > 0),
        }
    )
    for name in ROW_COLUMNS[9:]:
        v = extra.get(name)
        out[name] = (v[pick] if isinstance(v, np.ndarray) else v) if v is not None else np.nan
    if "close_ok" not in extra:
        out["close_ok"] = True
    return out[ROW_COLUMNS]


def _base(w, ind) -> dict[str, np.ndarray]:
    return {
        "o": _a(w["open"]),
        "h": _a(w["high"]),
        "l": _a(w["low"]),
        "c": _a(w["close"]),
        "v": _a(w["volume"]),
        "uni": w["in_universe"].to_numpy(dtype=bool),
        "adr": _a(ind["adr_usd"]),
    }


def _vol50(ind) -> np.ndarray:
    key = next(k for k in ind if k.startswith("vol"))
    return _a(ind[key])


def _runup(h: np.ndarray, low: np.ndarray, days: int) -> np.ndarray:
    """Largest low-to-later-high gain (percent) within the last `days` sessions, approximately:
    each day's high over the lowest low of the `days` sessions up to it, best of the window."""
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = h / _roll(low, days, "min")
    return (_roll(ratio, days, "max") - 1) * 100


def b0(w, ind, p: Mapping[str, float]) -> pd.DataFrame:
    """Breakout: prior move, a 10-40 session base with higher lows, trend, tight right side;
    buy stop over the base high. The longest valid base wins."""
    b = _base(w, ind)
    h, low, c, o, v = b["h"], b["l"], b["c"], b["o"], b["v"]
    vol50 = _vol50(ind)
    runup = _runup(h, low, int(p["prior_move_days"]))
    pivot = np.full_like(c, np.nan)
    base_len = np.full_like(c, np.nan)
    for n in range(int(p["base_min_days"]), int(p["base_max_days"]) + 1):
        hi = _shift(_roll(h, n, "max"), 1)
        lo = _shift(_roll(low, n, "min"), 1)
        second = n - n // 2
        lo2 = _shift(_roll(low, second, "min"), 1)
        lo1 = _shift(_roll(low, n // 2, "min"), 1 + second)
        prior = _shift(runup, n + 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            ok = (
                ((hi / lo - 1) * 100 <= p["base_depth_max_pct"])
                & (lo2 >= lo1)
                & (prior >= p["prior_move_min_pct"])
            )
        pivot = np.where(ok, hi, pivot)
        base_len = np.where(ok, n, base_len)
    s10, s20 = _a(ind["sma10"]), _a(ind["sma20"])
    trend = (c > s10) & (s10 > s20) & (s10 > _shift(s10, 5)) & (s20 > _shift(s20, 5))
    k = int(p["tight_days"])
    tight = (_roll(h, k, "max") - _roll(low, k, "min") <= p["tight_range_max_adr"] * b["adr"]) & (
        _roll(v, k, "mean") < vol50
    )
    setup_ok = _shift((trend & tight & b["uni"]).astype(float), 1) == 1
    adr = _shift(b["adr"], 1)
    trigger = pivot * p["trigger_above_pivot"]
    limit = trigger * p["limit_above_trigger"]
    with np.errstate(invalid="ignore"):
        mask = setup_ok & np.isfinite(pivot) & (h >= trigger) & (o <= limit)
        entry = np.maximum(o, trigger)
        stop = np.maximum(_shift(_roll(low, int(p["stop_low_days"]), "min"), 1), pivot - adr)
        close_ok = (c > pivot) & (c > (h + low) / 2) & (v > _shift(vol50, 1))
    return _rows(
        "B0",
        w,
        mask,
        1,
        entry,
        stop,
        adr,
        np.inf,  # the stop rule caps it at 1 ADR under the pivot; no skip (spec §5 B0)
        close_ok=close_ok,
        pivot=pivot,
        base_len=base_len,
        trigger=trigger,
    )


def l1(w, ind, p: Mapping[str, float]) -> pd.DataFrame:
    """Pullback to the rising 9/21 EMA or AVWAP: a leader whose 30 %+ high came 3-7 sessions
    ago dips to within 0.5 ADR$ of EMA9, EMA21 or AVWAP without closing under EMA50, then
    closes over EMA9 and the prior high. Stop: the pullback low."""
    b = _base(w, ind)
    h, low, c = b["h"], b["l"], b["c"]
    e9, e21, e50 = _a(ind["ema9"]), _a(ind["ema21"]), _a(ind["ema50"])
    av = _a(ind["avwap"])
    lead = ind["leader"].to_numpy(dtype=bool)
    with np.errstate(invalid="ignore"):
        cand = (
            lead & (e9 > e21) & (e21 > e50) & (e21 > _shift(e21, 5)) & (c > e9) & (c > _shift(h, 1))
        )
    days = int(p["prior_move_days"])
    a_min, a_max = int(p["high_age_min"]), int(p["high_age_max"])
    mask = np.zeros_like(cand)
    stop = np.full_like(c, np.nan)
    age = np.full_like(c, np.nan)
    for t, j in zip(*np.nonzero(cand), strict=True):
        if t < days - 1:
            continue
        hw = h[t - days + 1 : t + 1, j]
        if np.isnan(hw).any():
            continue
        k = len(hw) - 1 - int(np.argmax(hw[::-1]))  # latest highest high
        top = t - days + 1 + k
        if not a_min <= t - top <= a_max:
            continue
        if (hw[k] / np.min(low[t - days + 1 : top + 1, j]) - 1) * 100 < p["prior_move_min_pct"]:
            continue
        pb = slice(top + 1, t + 1)
        gaps = np.vstack([low[pb, j] - e9[pb, j], low[pb, j] - e21[pb, j], low[pb, j] - av[pb, j]])
        touch = np.nanmin(gaps, axis=0) <= p["touch_adr"] * b["adr"][pb, j]
        if not touch.any() or (c[pb, j] < e50[pb, j]).any():
            continue
        mask[t, j] = True
        stop[t, j] = np.min(low[pb, j])
        age[t, j] = t - top
    return _rows("L1", w, mask, 1, c, stop, b["adr"], p["stop_max_adr"], anchor_age=age)


def l2(w, ind, p: Mapping[str, float]) -> pd.DataFrame:
    """Undercut and reclaim: a leader over SMA50 trades under the lowest low of the prior 10
    sessions and closes back over it, in the upper half of the day and over the open."""
    b = _base(w, ind)
    h, low, c, o = b["h"], b["l"], b["c"], b["o"]
    level = _shift(_roll(low, int(p["undercut_days"]), "min"), 1)
    lead = ind["leader"].to_numpy(dtype=bool)
    with np.errstate(invalid="ignore"):
        mask = (
            lead
            & (c > _a(ind["sma50"]))
            & (low < level)
            & (c > level)
            & (c > (h + low) / 2)
            & (c > o)
        )
    return _rows("L2", w, mask, 1, c, low, b["adr"], p["stop_max_adr"], pivot=level)


def l3(w, ind, p: Mapping[str, float]) -> pd.DataFrame:
    """Catalyst gap-up (EP): open >= 10 % over the prior close on >= 3x vol50 and >= 300K shares,
    perf126 the day before under 30 % (neglect), closing green in the upper half. Max stop is
    1.5x the pre-gap ADR$."""
    b = _base(w, ind)
    h, low, c, o, v = b["h"], b["l"], b["c"], b["o"], b["v"]
    vol50 = _shift(_vol50(ind), 1)
    perf126 = _shift(_a(ind["perf126"]), 1)
    uni = _shift(b["uni"].astype(float), 1) == 1
    with np.errstate(invalid="ignore"):
        mask = (
            uni
            & (o >= _shift(c, 1) * (1 + p["gap_min_pct"] / 100))
            & (v >= p["volume_min_x"] * vol50)
            & (v >= p["volume_min"])
            & (perf126 < p["neglect_perf_max_pct"])
            & (c > o)
            & (c > (h + low) / 2)
        )
    return _rows("L3", w, mask, 1, c, low, _shift(b["adr"], 1), p["stop_max_adr"])


def s1(w, ind, p: Mapping[str, float]) -> pd.DataFrame:
    """Weak bounce short: a former leader broke under EMA21 on 1.5x vol50 within 10 sessions,
    bounced 2-4 sessions on light volume to within 0.5 ADR$ of the falling EMA9/EMA21, and now
    closes under the prior low. Stop: the bounce high."""
    b = _base(w, ind)
    h, low, c, v = b["h"], b["l"], b["c"], b["v"]
    e9, e21 = _a(ind["ema9"]), _a(ind["ema21"])
    vol50 = _vol50(ind)
    lead = ind["leader"].to_numpy(dtype=float)
    former = _roll(lead, int(p["former_leader_days"]), "max") == 1
    with np.errstate(invalid="ignore"):
        broke = (c < e21) & (v >= p["breakdown_volume_x"] * _shift(vol50, 1))
        cand = former & b["uni"] & (e21 < _shift(e21, 5)) & (c < _shift(low, 1))
    bd_days = int(p["breakdown_days"])
    k_min, k_max = int(p["bounce_min_days"]), int(p["bounce_max_days"])
    mask = np.zeros_like(cand)
    stop = np.full_like(c, np.nan)
    for t, j in zip(*np.nonzero(cand), strict=True):
        if t < bd_days:
            continue
        recent = np.nonzero(broke[t - bd_days : t, j])[0]
        if len(recent) == 0:
            continue
        bd = t - bd_days + int(recent[-1])
        seg = low[bd:t, j]
        if np.isnan(seg).any():
            continue
        pl = bd + int(np.argmin(seg))
        n = t - 1 - pl
        if not k_min <= n <= k_max:
            continue
        bounce = slice(pl + 1, t)
        if not np.mean(v[bounce, j]) < vol50[t - 1, j]:
            continue
        top = pl + 1 + int(np.argmax(h[bounce, j]))
        near = min(e9[top, j] - h[top, j], e21[top, j] - h[top, j])
        if not near <= p["touch_adr"] * b["adr"][top, j]:
            continue
        mask[t, j] = True
        stop[t, j] = np.max(h[pl + 1 : t + 1, j])
    return _rows("S1", w, mask, -1, c, stop, b["adr"], p["stop_max_adr"])


def s2(w, ind, p: Mapping[str, float]) -> pd.DataFrame:
    """Parabolic short: the day before closed up, >= 3 ADR$ over EMA9, with >= 5 up closes in 7
    sessions and perf21 >= 50 %; today is the first failure (red and under the prior close).
    Stop: today's high."""
    b = _base(w, ind)
    h, c, o = b["h"], b["c"], b["o"]
    e9 = _a(ind["ema9"])
    up = (c > _shift(c, 1)).astype(float)
    ups = _roll(up, int(p["up_closes_days"]), "sum")
    with np.errstate(invalid="ignore"):
        stretched = (
            b["uni"]
            & (c >= e9 + p["extension_adr"] * b["adr"])
            & (ups >= p["up_closes_min"])
            & (_a(ind["perf21"]) >= p["perf21_min_pct"])
            & (up == 1)
        )
        mask = (_shift(stretched.astype(float), 1) == 1) & (c < o) & (c < _shift(c, 1))
    return _rows("S2", w, mask, -1, c, h, b["adr"], p["stop_max_adr"])


SETUPS: dict[str, Callable] = {"B0": b0, "L1": l1, "L2": l2, "L3": l3, "S1": s1, "S2": s2}


def signals(w, ind, setups: Mapping[str, Mapping[str, float]], names=None) -> pd.DataFrame:
    """Every setup's rows, sorted by day, setup and ticker."""
    parts = [SETUPS[n](w, ind, setups[n.lower()]) for n in (names or SETUPS)]
    parts = [x for x in parts if len(x)]
    if not parts:
        return pd.DataFrame(columns=ROW_COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["session_date", "setup", "ticker"]).reset_index(drop=True)
