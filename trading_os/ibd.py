"""IBD market state (O'Neil; Emil, 25 Oct 2026): tracked on every signal, not a rule.

In the 2016-26 study MA-surf A made +1.17 / +0.77R a trade in an IBD uptrend against +0.07 /
-0.44R in a correction, and EP9M A+ +0.61 / +0.94R against +0.38 / +0.28R. The setups were picked
with both periods in view and 2006-15 did not confirm it, so the live check splits the live
A+ / A results by this state until there are enough trades to decide (data repo
docs/research/2026-10-25-third-period-2006-2015.md).

- Distribution day: SPY closes down at least 0.2 % on more volume than the day before.
- Correction: from 6 distribution days in the last 25 sessions, counting only days after the
  last follow-through day.
- Follow-through day: in a correction, on day 4 or later of a rally off the correction's low
  (the low not undercut since), SPY up at least 1.25 % on more volume than the day before. It
  starts an uptrend.

SPY's daily close, low and volume: a seed file of history (data/market/spy_daily_seed.parquet,
from Alpaca) and, after it, the EOD breadth rows (spy_close, spy_low, spy_volume).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DIST_DROP_PCT = 0.2
DIST_WINDOW = 25
CORRECTION_DIST = 6
FTD_MIN_DAY = 4
FTD_GAIN_PCT = 1.25
SEED = Path("data") / "market" / "spy_daily_seed.parquet"
COLUMNS = ["session_date", "close", "low", "volume"]


def states(spy: pd.DataFrame) -> pd.DataFrame:
    """Per session: `dist` (a distribution day), `dist_count` (in the window, since the last
    follow-through day) and `state` ("uptrend" / "correction"). Starts as an uptrend."""
    s = spy[COLUMNS].sort_values("session_date").reset_index(drop=True)
    close, low, vol = (s[c].to_numpy(dtype=float) for c in ("close", "low", "volume"))
    prev_close, prev_vol = np.r_[np.nan, close[:-1]], np.r_[np.nan, vol[:-1]]
    dist = (close < prev_close * (1 - DIST_DROP_PCT / 100)) & (vol > prev_vol)
    state, rally_low, low_day, ftd = "uptrend", np.inf, -1, -1
    out_state, out_count = [], []
    for k in range(len(s)):
        count = int(dist[max(k - DIST_WINDOW + 1, ftd + 1) : k + 1].sum())
        if state == "uptrend" and count >= CORRECTION_DIST:
            state, rally_low, low_day = "correction", low[k], k
        elif state == "correction":
            if low[k] < rally_low:
                rally_low, low_day = low[k], k
            elif (
                k - low_day >= FTD_MIN_DAY - 1
                and close[k] >= prev_close[k] * (1 + FTD_GAIN_PCT / 100)
                and vol[k] > prev_vol[k]
            ):
                state, ftd = "uptrend", k
                count = 0
        out_state.append(state)
        out_count.append(count)
    return s.assign(dist=dist, dist_count=out_count, state=out_state)


def spy_daily(
    data_dir: Path, upto: dt.date, today: Mapping[str, Any] | None = None
) -> pd.DataFrame:
    """SPY's daily bars up to `upto`: the seed, then the stored EOD breadth rows, then
    `today` (an EOD breadth row not written yet)."""
    data_dir = Path(data_dir)
    seed_path = data_dir / SEED
    seed = pd.read_parquet(seed_path) if seed_path.exists() else pd.DataFrame(columns=COLUMNS)
    seed["session_date"] = pd.to_datetime(seed["session_date"]).dt.date
    last_seed = max(seed["session_date"]) if len(seed) else dt.date.min
    rows = []
    for path in sorted((data_dir / "data" / "breadth").glob("*/*_eod.parquet")):
        day = dt.date.fromisoformat(path.name[:10])
        if last_seed < day <= upto:
            rows.append(pd.read_parquet(path).iloc[0].to_dict())
    if today is not None:
        rows.append(dict(today))
    stored = pd.DataFrame(
        [
            {
                "session_date": pd.Timestamp(r["session_date"]).date(),
                "close": r.get("spy_close"),
                "low": r.get("spy_low"),
                "volume": r.get("spy_volume"),
            }
            for r in rows
        ],
        columns=COLUMNS,
    )
    stored = stored[stored["session_date"] <= upto].dropna()
    both = pd.concat([seed[seed["session_date"] <= upto], stored], ignore_index=True)
    return both.drop_duplicates("session_date", keep="last").sort_values("session_date")


def state_at(
    data_dir: Path, upto: dt.date, today: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """{"state", "dist_count", "session_date"} at the last SPY close up to `upto`; None
    without data."""
    spy = spy_daily(data_dir, upto, today)
    if len(spy) < DIST_WINDOW + 1:
        return None
    last = states(spy).iloc[-1]
    return {
        "state": last["state"],
        "dist_count": int(last["dist_count"]),
        "session_date": last["session_date"],
    }


def tag(info: Mapping[str, Any] | None) -> str | None:
    """`IBD uptrend (2 dist.)` / `IBD correction (6 dist.)`."""
    if not info:
        return None
    return f"IBD {info['state']} ({info['dist_count']} dist.)"


def line(info: Mapping[str, Any] | None) -> list[str]:
    """The report's market line: tracked, not a rule."""
    if not info:
        return []
    return [
        f"📊 IBD market: {info['state']} · {info['dist_count']} distribution days in 25 "
        f"(SPY close {info['session_date']:%d %b}; tracked, not a rule)"
    ]
