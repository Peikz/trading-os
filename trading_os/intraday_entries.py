"""Entry rules for the minute-bar study (Emil, 19 Oct 2026). Facts, not advice.

Each strategy's rule is applied at the entry time with only the bars up to that moment, so no
entry is picked with facts from later in the day. One stock-day's bars come as arrays: `m` is
minutes after midnight New York on the entry day (the evening before is negative: 16:00 the
day before = -480), then open/high/low/close/volume/vwap. "At 10:30" is the close of the last
bar that started before 10:30.

| strategy              | entries                                    | rule at entry time      |
|-----------------------|--------------------------------------------|-------------------------|
| ep (gap stocks)       | 16:45/18:00 the evening before, 07:05,     | EP-AH / EP-PM move      |
|                       | 08:00, 09:15                               |                         |
|                       | the open, 5/15/30/60-min range high,       | opening gap >= 10 %     |
|                       | 10:30, 12:00, the close                    |                         |
| ep9m                  | 10:15, 12:00, the close                    | +4 %, on pace for 9M    |
| breakout              | buy-stop at the pivot; the same from       | the base of the day     |
|                       | 10:00; the close above the pivot           | before                  |
| luk_pullback / _flush | turn green after the touch; first 5-min    | Luk's levels (from      |
|                       | close back above the level; the close      | yesterday) touched      |
| next day (EOD hits)   | open, 5-min range high/low, prior          | the signal (prior       |
|                       | high/low break, 10:30                      | close)                  |

Stops for each entry, all at least `min_stop_adr` ADR and `min_stop_pct` % away: `lod` (the
low so far, or for a short the high so far), `adr` (`wide_stop_adr` ADR, the same for every
entry, so only the timing differs), plus the strategy's own: `order` (breakout order stop)
and `signal` (the signal day's low or high for next-day entries).

Fills: a market order at a bar's open can be stopped inside that bar; a price "at T" or a
stop order filled inside a bar starts the stop check at the next bar (`start`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

OPEN, CLOSE = 570, 960  # 09:30 and 16:00 New York
OPENING_RANGES = (5, 15, 30, 60)
SHORT = {"mb_down", "parabolic_short"}


@dataclass
class Bars:
    m: np.ndarray
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    v: np.ndarray
    vwap: np.ndarray

    def first(self, minute: int) -> int:
        """Index of the first bar starting at or after `minute`."""
        return int(np.searchsorted(self.m, minute, side="left"))

    def session(self) -> tuple[int, int]:
        return self.first(OPEN), self.first(CLOSE)

    def resample(self, size: int) -> Bars:
        """Bars of `size` minutes (09:30 starts a bar)."""
        key = (self.m - OPEN) // size
        edges = np.flatnonzero(np.diff(key)) + 1
        starts = np.concatenate([[0], edges])
        ends = np.concatenate([edges, [len(self.m)]])
        v = np.add.reduceat(self.v, starts) if len(self.m) else self.v
        pv = np.add.reduceat(self.vwap * self.v, starts) if len(self.m) else self.v
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap = np.where(v > 0, pv / v, self.c[ends - 1] if len(self.m) else self.c)
        return Bars(
            m=key[starts] * size + OPEN,
            o=self.o[starts],
            h=np.maximum.reduceat(self.h, starts) if len(self.m) else self.h,
            lo=np.minimum.reduceat(self.lo, starts) if len(self.m) else self.lo,
            c=self.c[ends - 1],
            v=v,
            vwap=vwap,
        )


def _at(b: Bars, minute: int, lo_index: int) -> int | None:
    """Index of the last bar (from `lo_index`) that started before `minute`."""
    i = b.first(minute) - 1
    return i if i >= lo_index else None


def _stop_order(b: Bars, level: float, i0: int, i1: int, side: int):
    """First bar in [i0, i1) that trades through `level` (a buy stop for side 1, a sell stop
    for -1): (index, fill, start). A bar that opens beyond the level fills at its open."""
    if i0 >= i1:
        return None
    hit = b.h[i0:i1] >= level if side > 0 else b.lo[i0:i1] <= level
    k = np.flatnonzero(hit)
    if not len(k):
        return None
    i = i0 + int(k[0])
    gapped = b.o[i] >= level if side > 0 else b.o[i] <= level
    fill = b.o[i] if gapped else level
    return i, float(fill), i if gapped else i + 1


class Book:
    """Collects entries for one stock-day, one row per stop rule, with the stop floor."""

    def __init__(self, adr: float, p: Mapping[str, Any]) -> None:
        self.adr, self.p, self.rows = adr, p, []

    def add(self, strategy, entry, side, start, price, stops: dict, **features) -> None:
        floor = max(self.p["min_stop_adr"] * self.adr, self.p["min_stop_pct"] / 100 * price)
        stops = dict(stops) | {"adr": price - side * self.p["wide_stop_adr"] * self.adr}
        for rule, level in stops.items():
            if level is None or not np.isfinite(level):
                continue
            # The floor holds for the 1-ADR stop too: on a quiet name (a T-bill fund, a
            # merger target) 1 ADR is a few cents, and R ran into the hundreds.
            level = min(level, price - floor) if side > 0 else max(level, price + floor)
            if (price - level) * side <= 0:
                continue
            self.rows.append(
                {
                    "strategy": strategy,
                    "entry": entry,
                    "side": side,
                    "start": int(start),
                    "price": float(price),
                    "stop_rule": rule,
                    "stop": float(level),
                }
                | features
            )


def _so_far(b: Bars, s0: int, i: int) -> dict[str, float]:
    """Session facts up to and including bar i: low, high, volume, VWAP."""
    sl = slice(s0, i + 1)
    v = b.v[sl].sum()
    vwap = (b.vwap[sl] * b.v[sl]).sum() / v if v > 0 else np.nan
    return {"low": float(b.lo[sl].min()), "high": float(b.h[sl].max()), "volume": v, "vwap": vwap}


def _features(b, s0, i, price, row) -> dict[str, Any]:
    f = _so_far(b, s0, i)
    avg = row.get("avg_volume_20d") or np.nan
    return {
        "above_vwap": bool(price > f["vwap"]) if f["vwap"] == f["vwap"] else None,
        "rvol_so_far": f["volume"] / avg if avg == avg and avg > 0 else np.nan,
    }


def gap(b: Bars, row: Mapping[str, Any], p: Mapping[str, Any]) -> list[dict]:
    """EP entries on a gap stock (strategy "ep")."""
    book, prev = Book(row["adr_usd"], p), row["prev_close"]
    s0, s1 = b.session()
    # After hours the evening before (EP-AH rule at 18:00; and at 16:45, inside Saxo's
    # extended hours, which end at 17:00 New York).
    a0 = b.first(-480)
    for name, minute in (("ah_1645", -435), ("ah_1800", -360)):
        i = _at(b, minute, a0)
        if i is None or not a0 < b.first(minute):
            continue
        price = float(b.c[i])
        ah_volume = b.v[a0 : i + 1].sum()
        change = (price / prev - 1) * 100
        if change >= p["ah_change_min_pct"] and ah_volume >= p["ah_volume_min"]:
            book.add("ep", name, 1, i + 1, price, {}, ah_change_pct=change)
    # Pre-market (EP-PM rule at 07:05, as Saxo's pre-market opens, 08:00 and 09:15).
    p0 = b.first(240)
    for name, minute in (("pm_0705", 425), ("pm_0800", 480), ("pm_0915", 555)):
        i = _at(b, minute, p0)
        if i is None:
            continue
        price = float(b.c[i])
        volume = b.v[p0 : i + 1].sum()
        change = (price / prev - 1) * 100
        if change >= p["pm_change_min_pct"] and volume >= p["pm_volume_min"] and price >= 1:
            low = float(b.lo[p0 : i + 1].min())
            book.add("ep", name, 1, i + 1, price, {"lod": low}, pm_change_pct=change)
    if s0 >= s1:
        return book.rows
    gap_pct = (b.o[s0] / prev - 1) * 100
    if gap_pct < p["gap_min_pct"]:
        return book.rows
    common = {"gap_pct": gap_pct}
    book.add("ep", "open", 1, s0, float(b.o[s0]), {}, **common)
    for n in OPENING_RANGES:
        r1 = b.first(OPEN + n)
        if r1 <= s0 or r1 >= s1:
            continue
        found = _stop_order(b, float(b.h[s0:r1].max()), r1, s1, 1)
        if found:
            i, fill, start = found
            low = float(b.lo[s0 : i + 1].min())
            book.add("ep", f"orh_{n}m", 1, start, fill, {"lod": low}, **common)
    for name, minute in (("t_1030", 630), ("t_1200", 720)):
        i = _at(b, minute, s0)
        if i is not None:
            price = float(b.c[i])
            f = _features(b, s0, i, price, row)
            book.add("ep", name, 1, i + 1, price, {"lod": _so_far(b, s0, i)["low"]}, **common, **f)
    price = float(b.c[s1 - 1])
    book.add("ep", "close", 1, s1, price, {"lod": float(b.lo[s0:s1].min())}, **common)
    return book.rows


def ep9m(b: Bars, row: Mapping[str, Any], p: Mapping[str, Any]) -> list[dict]:
    """EP9M at the intraday checks (up 4 %, on pace for 9M) and at the close."""
    book, prev = Book(row["adr_usd"], p), row["prev_close"]
    s0, s1 = b.session()
    if s0 >= s1:
        return book.rows
    for clock, fraction in p["pace_fraction"].items():
        hh, mm = (int(x) for x in clock.split(":"))
        i = _at(b, hh * 60 + mm, s0)
        if i is None:
            continue
        price = float(b.c[i])
        change = (price / prev - 1) * 100
        pace = b.v[s0 : i + 1].sum() / fraction
        if change >= p["ep9m_chg_min_pct"] and pace >= p["ep9m_volume_min"]:
            f = _features(b, s0, i, price, row)
            book.add(
                "ep9m",
                f"t_{hh:02d}{mm:02d}",
                1,
                i + 1,
                price,
                {"lod": _so_far(b, s0, i)["low"]},
                chg_pct=change,
                proj_volume=pace,
                **f,
            )
    price = float(b.c[s1 - 1])
    change = (price / prev - 1) * 100
    if change >= p["ep9m_chg_min_pct"] and b.v[s0:s1].sum() >= p["ep9m_volume_min"]:
        book.add("ep9m", "close", 1, s1, price, {"lod": float(b.lo[s0:s1].min())}, chg_pct=change)
    return book.rows


def pivot(b: Bars, row: Mapping[str, Any], p: Mapping[str, Any]) -> list[dict]:
    """Breakout entries at the pivot of the base that ended the session before."""
    book, level = Book(row["adr_usd"], p), float(row["pivot"])
    s0, s1 = b.session()
    if s0 >= s1:
        return book.rows
    setup = row.get("setup")
    name = setup if isinstance(setup, str) and setup else "breakout"  # NaN for non-VCP rows
    flags = {f"b{k}": bool(row.get(f"b{k}")) for k in range(1, 5)}
    common = flags | {
        "b_count": sum(flags.values()),
        "gap_pct": (b.o[s0] / row["prev_close"] - 1) * 100,
    }
    last_low = row.get("last_low")

    def order(price):  # VCP: the last contraction's low, at most stop_max_pct under the entry
        if last_low is None or last_low != last_low:
            return {"order": row.get("order_stop")}
        return {"order": max(last_low, price * (1 - p["vcp_stop_max_pct"] / 100))}

    found = _stop_order(b, level, s0, s1, 1)
    if found:
        i, fill, start = found
        stops = order(fill) | {"lod": float(b.lo[s0 : i + 1].min())}
        book.add(name, "pivot_cross", 1, start, fill, stops, cross_minute=int(b.m[i]), **common)
    ten = b.first(600)
    i = _at(b, 600, s0)
    if i is not None and ten < s1:
        if b.c[i] >= level:
            price, start, lod = float(b.c[i]), i + 1, float(b.lo[s0 : i + 1].min())
            book.add(name, "pivot_1000", 1, start, price, order(price) | {"lod": lod}, **common)
        else:
            later = _stop_order(b, level, ten, s1, 1)
            if later:
                j, fill, start = later
                lod = float(b.lo[s0 : j + 1].min())
                book.add(name, "pivot_1000", 1, start, fill, order(fill) | {"lod": lod}, **common)
    price = float(b.c[s1 - 1])
    if price > level:
        lod = float(b.lo[s0:s1].min())
        book.add(name, "pivot_close", 1, s1, price, order(price) | {"lod": lod}, **common)
    return book.rows


def luk(b: Bars, row: Mapping[str, Any], p: Mapping[str, Any]) -> list[dict]:
    """Martin Luk's pullback and AVWAP flush, bought during the session (levels from the day
    before; the touch must have happened before the entry)."""
    book, adr, prev = Book(row["adr_usd"], p), row["adr_usd"], row["prev_close"]
    s0, s1 = b.session()
    if s0 >= s1 or not adr > 0:
        return book.rows
    touch = p["touch_adr"] * adr
    lows = np.minimum.accumulate(b.lo[s0:s1])
    fast, mid, avwap = row["ema_fast"], row["ema_mid"], row["avwap"]
    setups = []
    if row.get("lead") and prev > mid:
        for name, level in (("ema9", fast), ("ema21", mid)):
            k = np.flatnonzero(lows <= level + touch)
            if len(k):
                setups.append(("luk_pullback", name, level, int(k[0])))
                break
    flush_ok = (
        fast > mid
        and row.get("mid_rising")
        and prev > avwap
        and (row.get("base_days") or 0) >= p["base_min_days"]
    )
    if flush_ok:
        ok = (
            (lows <= avwap + touch)  # touched the AVWAP ...
            & (lows <= max(fast, mid) + touch)  # ... and EMA 9 or EMA 21 ...
            & (lows <= prev - p["flush_adr"] * adr)  # ... in a flush under the prior close
        )
        k = np.flatnonzero(ok)
        if len(k):
            setups.append(("luk_avwap_flush", "avwap", avwap, int(k[0])))
    five = Bars(*(a[s0:s1] for a in (b.m, b.o, b.h, b.lo, b.c, b.v, b.vwap))).resample(5)
    for strategy, touched, level, k in setups:
        i_touch = s0 + k
        dip = (prev - lows[k]) / adr
        common = {"touched": touched, "dip_adr": dip}
        green = _stop_order(b, prev, i_touch + 1, s1, 1)
        if green:
            i, fill, start = green
            lod = float(b.lo[s0 : i + 1].min())
            book.add(strategy, "turn_green", 1, start, fill, {"lod": lod}, **common)
        closes_after = five.m + 5 > b.m[i_touch] + 1  # bars that close after the touch
        after = np.flatnonzero(closes_after & (five.c > level))
        if len(after):
            q = int(after[0])
            end = b.first(int(five.m[q]) + 5)  # first minute bar after that 5-minute bar
            lod = float(b.lo[s0:end].min())
            book.add(strategy, "reclaim_5m", 1, end, float(five.c[q]), {"lod": lod}, **common)
        price = float(b.c[s1 - 1])
        if price > level and (strategy != "luk_avwap_flush" or price > avwap):
            book.add(strategy, "close", 1, s1, price, {"lod": float(b.lo[s0:s1].min())}, **common)
    return book.rows


def next_day(b: Bars, row: Mapping[str, Any], p: Mapping[str, Any]) -> list[dict]:
    """The session after an end-of-day signal: long or short by strategy (on 5-minute bars,
    see `for_group`)."""
    strategy = row["strategy"]
    side = -1 if strategy in SHORT else 1
    book = Book(row["adr_usd"], p)
    s0, s1 = b.session()
    if s0 >= s1:
        return book.rows
    signal = {"signal": row["signal_low"] if side > 0 else row["signal_high"]}
    extreme = b.lo if side > 0 else b.h
    pick = np.min if side > 0 else np.max
    book.add(strategy, "next_open", side, s0, float(b.o[s0]), signal)
    if s0 + 1 < s1:
        level = float(b.h[s0] if side > 0 else b.lo[s0])
        found = _stop_order(b, level, s0 + 1, s1, side)
        if found:
            i, fill, start = found
            stops = signal | {"lod": float(extreme[s0])}
            book.add(strategy, "next_orb_5m", side, start, fill, stops)
    prior = row["signal_high"] if side > 0 else row["signal_low"]
    found = _stop_order(b, float(prior), s0, s1, side)
    if found:
        i, fill, start = found
        stops = signal | {"lod": float(pick(extreme[s0 : i + 1]))}
        book.add(strategy, "next_prior_break", side, start, fill, stops)
    i = _at(b, 630, s0)
    if i is not None:
        stops = signal | {"lod": float(pick(extreme[s0 : i + 1]))}
        book.add(strategy, "next_1030", side, i + 1, float(b.c[i]), stops)
    return book.rows


RULES = {
    "gap": gap,
    "ep9m": ep9m,
    "pivot": pivot,
    "vcp": pivot,
    "qm_surf": pivot,  # buy stop at the base high, the session after the setup
    "htf": pivot,
    "luk": luk,
    "next_day": next_day,
}


def for_group(b: Bars, group: str) -> Bars:
    """Next-day entries all run on 5-minute bars (a 1-minute day is resampled)."""
    if group == "next_day" and len(b.m) > 1 and np.min(np.diff(b.m)) < 5:
        return b.resample(5)
    return b


def entry_day_exit(b: Bars, entry: Mapping[str, Any]) -> tuple[bool, float]:
    """(stopped on the entry day, exit price): the stop checked bar by bar from `start` to
    the close; not stopped = the entry day's close."""
    _, s1 = b.session()
    start, stop, side = entry["start"], entry["stop"], entry["side"]
    if start < s1:
        hit = b.lo[start:s1] <= stop if side > 0 else b.h[start:s1] >= stop
        k = np.flatnonzero(hit)
        if len(k):
            o = b.o[start + int(k[0])]
            return True, float(min(o, stop) if side > 0 else max(o, stop))
    return False, float(b.c[s1 - 1]) if s1 > 0 else np.nan
