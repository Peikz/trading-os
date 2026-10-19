"""EP entry study (Emil, 19 Oct 2026): when is the best time to buy an EP? Facts, not advice.

For every EP-Day event with Massive minute bars (`ep_enrich`), the same trade is entered at
different times and measured the same way afterwards:

- after-hours the evening before (18:00 ET), pre-market (08:00 and 09:15 ET), the open,
  an opening-range-high breakout after 1, 5, 15, 30 and 60 minutes (a buy-stop at the
  range high: no break, no trade), 10:30, 12:00 and 15:30 ET, the close, and the next
  day's open and 5-minute range high;
- two stops for each: 1.5 ADR below the entry (the same distance for every entry, so the
  timing is all that differs), and the low so far (the opening-range low for a breakout,
  the day's low up to the entry otherwise; at least 0.25 ADR away);
- after the entry: the rest of that day minute by minute, then daily bars; R after 5, 21
  and 63 sessions, and a trailing exit at the first close under the 20-day MA (from the
  third session).

Times are New York (the minute bars come in UTC). The regular session is 09:30-16:00.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os.metrics import NEW_YORK

ENTRY_TIMES = {"ah_1800": "18:00", "pm_0800": "08:00", "pm_0915": "09:15"}
CLOCK_ENTRIES = {"t_1030": "10:30", "t_1200": "12:00", "t_1530": "15:30"}
OPENING_RANGES = (1, 5, 15, 30, 60)
HORIZONS = (5, 21, 63)
STOPS = ("adr", "low")
WIDE_STOP_ADR = 1.5
MIN_STOP_ADR = 0.25


def to_ny(minutes: pd.DataFrame) -> pd.DataFrame:
    out = minutes.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True).dt.tz_convert(NEW_YORK)
    out["day"] = out["ts"].dt.date
    out["clock"] = out["ts"].dt.strftime("%H:%M")
    return out.sort_values("ts").reset_index(drop=True)


def _last_at(day: pd.DataFrame, hhmm: str) -> tuple[float, int] | None:
    """Last traded price at or before `hhmm` that day, and its row position."""
    before = day[day["clock"] <= hhmm]
    if before.empty:
        return None
    return float(before["close"].iloc[-1]), int(before.index[-1])


def _session(day: pd.DataFrame) -> pd.DataFrame:
    return day[(day["clock"] >= "09:30") & (day["clock"] < "16:00")]


def entries(minutes: pd.DataFrame, prev: dt.date, ep: dt.date, nxt: dt.date | None):
    """name -> (price, minute row where the trade starts, low-so-far stop or None)."""
    days = {d: g for d, g in minutes.groupby("day")}
    out: dict[str, tuple[float, int, float | None]] = {}
    before = days.get(prev)
    if before is not None:
        evening = before[(before["clock"] >= "16:00")]
        found = _last_at(evening, ENTRY_TIMES["ah_1800"])
        if found and not evening[evening["clock"] <= "18:00"].empty:
            out["ah_1800"] = (*found, None)
    today = days.get(ep)
    if today is None:
        return out
    pre = today[today["clock"] < "09:30"]
    for name in ("pm_0800", "pm_0915"):
        found = _last_at(pre, ENTRY_TIMES[name])
        if found and not pre[pre["clock"] <= ENTRY_TIMES[name]].empty:
            low = float(pre[pre["clock"] <= ENTRY_TIMES[name]]["low"].min())
            out[name] = (found[0], found[1], low)
    session = _session(today)
    if session.empty:
        return out
    first = session.iloc[0]
    out["open"] = (float(first["open"]), int(session.index[0]), None)
    for name, hhmm in CLOCK_ENTRIES.items():
        found = _last_at(session, hhmm)
        if found:
            low = float(session.loc[: found[1], "low"].min())
            out[name] = (found[0], found[1], low)
    last = session.iloc[-1]
    out["close"] = (float(last["close"]), int(session.index[-1]), float(session["low"].min()))
    out |= _breakouts(session, "orh")
    if nxt is not None and nxt in days:
        nxt_session = _session(days[nxt])
        if not nxt_session.empty:
            out["next_open"] = (float(nxt_session.iloc[0]["open"]), int(nxt_session.index[0]), None)
            out |= {"next_" + k: v for k, v in _breakouts(nxt_session, "orh", (5,)).items()}
    return out


def _breakouts(session: pd.DataFrame, prefix: str, ranges=OPENING_RANGES) -> dict:
    """Buy-stop at the high of the first N minutes, filled at the high (or the open of the
    bar that gaps over it); the range low is the stop."""
    out = {}
    start = session["ts"].iloc[0]
    for n in ranges:
        inside = session[session["ts"] < start + pd.Timedelta(minutes=n)]
        after = session[session["ts"] >= start + pd.Timedelta(minutes=n)]
        if inside.empty or after.empty:
            continue
        high, low = float(inside["high"].max()), float(inside["low"].min())
        crossed = after[after["high"] > high]
        if crossed.empty:
            continue
        bar = crossed.iloc[0]
        fill = max(float(bar["open"]), high)
        out[f"{prefix}_{n}m"] = (fill, int(crossed.index[0]), low)
    return out


class Daily:
    """One stock's daily bars as arrays (the outcome loop runs on these, not on pandas)."""

    def __init__(self, bars: pd.DataFrame) -> None:
        bars = bars.sort_values("session_date").reset_index(drop=True)
        self.index = {d: i for i, d in enumerate(bars["session_date"])}
        self.o, self.h, self.lo, self.c = (
            bars[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close")
        )
        self.ma20 = bars["close"].rolling(20).mean().to_numpy(dtype=float)


def simulate(
    minutes: pd.DataFrame,
    start_row: int,
    entry: float,
    stop: float,
    daily: Daily,
    entry_day: dt.date,
) -> dict[str, Any]:
    """R for one entry: the rest of the entry day minute by minute, then daily bars. Holding
    5/21/63 sessions with the stop, a trailing exit at the first close under the 20-day MA
    (from the third session), and the managed exits (a third after 3 days, the rest on the
    20-day MA; out after 3 or 5 days; +8 % within 5 days)."""
    from trading_os import exits

    risk = entry - stop
    t = daily.index.get(entry_day)
    if not risk > 0 or t is None:
        return {}
    rest = minutes.loc[start_row + 1 :]
    rest = rest[(rest["day"] == entry_day) & (rest["clock"] < "16:00")]
    hit = rest[rest["low"] <= stop]
    names = [f"r_{h}d" for h in HORIZONS] + ["r_trail_ma20", "r_q3_ma20", "r_time3d"]
    names += ["r_time5d", "r_target8_5d"]
    if len(hit):
        r = (min(float(hit.iloc[0]["open"]), stop) - entry) / risk
        return dict.fromkeys(names, r) | {"stopped_entry_day": True}
    o, h, lo, c = daily.o, daily.h, daily.lo, daily.c
    out: dict[str, Any] = {"stopped_entry_day": False}
    n = len(c)
    stopped_at = None
    for d in range(t + 1, min(n, t + 1 + max(HORIZONS))):
        if lo[d] <= stop:
            stopped_at = d
            break
    stop_r = (min(o[stopped_at], stop) - entry) / risk if stopped_at is not None else None
    for horizon in HORIZONS:
        end = t + horizon
        if stopped_at is not None and stopped_at <= end:
            out[f"r_{horizon}d"] = stop_r
        elif end < n:
            out[f"r_{horizon}d"] = (c[end] - entry) / risk
    trail = None
    for d in range(t + 1, min(n, t + 127)):
        if lo[d] <= stop:
            trail = (min(o[d], stop) - entry) / risk
            break
        if d - t >= 3 and c[d] < daily.ma20[d]:
            trail = (c[d] - entry) / risk
            break
    if trail is None and t + 1 < n:
        trail = (c[min(n - 1, t + 126)] - entry) / risk
    out["r_trail_ma20"] = trail
    out["r_q3_ma20"] = exits.partial_trail(
        o, h, lo, c, daily.ma20, t, entry, stop, 1, 3, 1 / 3, 126
    )[0]
    out["r_time3d"] = exits.time_exit(o, h, lo, c, t, entry, stop, 1, 3)
    out["r_time5d"] = exits.time_exit(o, h, lo, c, t, entry, stop, 1, 5)
    out["r_target8_5d"] = exits.target_exit(o, h, lo, c, t, entry, stop, 1, 8, 5)
    return out


def study_event(
    minutes: pd.DataFrame,
    daily,
    prev: dt.date,
    ep: dt.date,
    nxt: dt.date | None,
    adr_usd: float,
) -> list[dict[str, Any]]:
    """Every entry x stop for one EP."""
    daily = daily if isinstance(daily, Daily) else Daily(daily)
    rows = []
    for name, (price, row, low) in entries(minutes, prev, ep, nxt).items():
        day = minutes.loc[row, "day"]
        floor = MIN_STOP_ADR * adr_usd
        stops = {"adr": price - WIDE_STOP_ADR * adr_usd}
        if low is not None:
            stops["low"] = min(low, price - floor)
        for kind, stop in stops.items():
            result = simulate(minutes, row, price, stop, daily, day)
            if result:
                rows.append(
                    {"entry": name, "stop_rule": kind, "price": price, "stop": stop} | result
                )
    return rows


def summary(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Per entry and stop rule: trades, win rate and mean R (capped at 20) per horizon."""
    keys = ["entry", "stop_rule", *(by or [])]
    rows = []
    for key, part in df.groupby(keys, dropna=False, observed=True):
        row: dict[str, Any] = dict(
            zip(keys, key if isinstance(key, tuple) else (key,), strict=True)
        )
        row["trades"] = len(part)
        row["stopped_same_day%"] = part["stopped_entry_day"].mean() * 100
        for h in HORIZONS:
            r = part[f"r_{h}d"].dropna()
            row[f"win_{h}d%"] = (r > 0).mean() * 100 if len(r) else np.nan
            row[f"R_{h}d"] = r.clip(upper=20).mean() if len(r) else np.nan
        trail = part["r_trail_ma20"].dropna()
        row["R_trail_ma20"] = trail.clip(upper=20).mean() if len(trail) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def run(events: pd.DataFrame, minutes_for, bars: pd.DataFrame, sessions: list) -> pd.DataFrame:
    """`events`: EP rows with session_date, ticker, adr20_pct, close (+ any grouping columns).
    `minutes_for(day, ticker)` gives each event's minute bars (or None)."""
    index = {d: i for i, d in enumerate(sessions)}
    by_ticker = {t: Daily(g) for t, g in bars.groupby("ticker")}
    rows = []
    for event in events.to_dict("records"):
        raw = minutes_for(event["session_date"], event["ticker"])
        if raw is None or raw.empty:
            continue
        i = index.get(event["session_date"])
        if not i:
            continue
        prev = sessions[i - 1]
        nxt = sessions[i + 1] if i + 1 < len(sessions) else None
        adr_usd = event["adr20_pct"] * event["close"] / 100
        daily = by_ticker.get(event["ticker"])
        if daily is None or not adr_usd > 0:
            continue
        keep = {k: event.get(k) for k in ("session_date", "ticker", "earnings", "earnings_timing")}
        for row in study_event(to_ny(raw), daily, prev, event["session_date"], nxt, adr_usd):
            rows.append(keep | row)
    return pd.DataFrame(rows)


def label(entry: str) -> str:
    names: Mapping[str, str] = {
        "ah_1800": "after-hours the evening before (18:00)",
        "pm_0800": "pre-market 08:00",
        "pm_0915": "pre-market 09:15",
        "open": "the open",
        "t_1030": "10:30",
        "t_1200": "12:00",
        "t_1530": "15:30",
        "close": "the close",
        "next_open": "next day's open",
        "next_orh_5m": "next day's 5-minute range high",
    }
    if entry.startswith("orh_"):
        return f"{entry[4:-1]}-minute opening-range high"
    return names.get(entry, entry)


def minute_source(data_dir):
    """Minute bars per (EP day, ticker): Alpaca's monthly files in `data/ep_minutes/`
    (downloaded from the data repo's "ep-minutes" release) first, else Massive's per-event
    files from `ep_enrich`."""
    from pathlib import Path

    from trading_os import ep_enrich

    months: dict[str, dict] = {}
    folder = Path(data_dir) / "data" / "ep_minutes"

    def month(key: str) -> dict:
        if key not in months:
            path = folder / f"{key}.parquet"
            frame = pd.read_parquet(path) if path.exists() and path.stat().st_size else None
            months.clear()  # one month in memory at a time
            months[key] = (
                {}
                if frame is None or frame.empty
                else {
                    (pd.Timestamp(d).date(), t): g.drop(columns=["event_date"])
                    for (d, t), g in frame.groupby(["event_date", "ticker"])
                }
            )
        return months[key]

    def minutes_for(day, ticker):
        found = month(f"{day:%Y-%m}").get((day, ticker))
        if found is not None:
            return found
        path = ep_enrich.minutes_path(data_dir, day, ticker)
        return pd.read_parquet(path) if path.exists() else None

    return minutes_for


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from trading_os import history
    from trading_os.logsafe import status
    from trading_os.store import PARQUET_OPTIONS

    parser = argparse.ArgumentParser(description="EP entry timing study on the minute bars")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    built = sorted((args.data_dir / "data" / "ep_history").glob("ep_history_*.parquet"))
    if not built:
        status("Entry study: no EP history yet")
        return 1
    study = pd.read_parquet(built[-1])
    study["session_date"] = pd.to_datetime(study["session_date"]).dt.date
    events = study[study["is_ep_day"] & (study["tier"] == "alert")].sort_values("session_date")
    files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
    sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
    bars = history.load_bars(args.data_dir, sessions)
    bars = bars[bars["ticker"].isin(set(events["ticker"]))]
    result = run(events, minute_source(args.data_dir), bars, sessions)
    if result.empty:
        status("Entry study: no minute bars yet")
        return 0
    out = args.data_dir / "data" / "ep_enrich" / f"entry_study_{built[-1].stem[11:]}.parquet"
    result.to_parquet(out, **PARQUET_OPTIONS)
    status(f"Entry study: {result['ticker'].nunique()} EPs, {len(result)} entries, saved")
    return 0
