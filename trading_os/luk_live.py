"""Martin Luk's AVWAP flush as a live end-of-day scan (Emil, 20 Oct 2026; SPEC §6.2). The
10-year grading study found it one of three setups with an edge after costs (grade A/B,
bought the next session around 10:30 New York, 1-ADR stop, out after 21 sessions).

The rules are `luk.py`'s, unchanged: a leader (up >= 30 % over 1/3/6 months, ADR >= 5 %,
EMA 9 > EMA 21 rising) on a base of 40+ sessions above its AVWAP from the 250-session
high flushes at least 0.5 ADR under the prior close into the AVWAP and EMA 9/21 zone and
holds it at the close. The levels come from the day before; the AVWAP needs 250 sessions,
so the scan reads `LUK_SESSIONS` of the stored daily bars plus today's.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from trading_os import clock, history, luk
from trading_os import history_metrics as hm
from trading_os.enrich import todays_bars

LUK_SESSIONS = 300
COLUMNS = {"level": "luk_level", "avwap": "luk_avwap", "base_days": "base_days"}


def attach(df: pd.DataFrame, data_dir: Path, cfg, session: dt.date) -> pd.DataFrame:
    """`df` plus `luk_flush` (bool) and the flush's levels, for the alert-tier rows."""
    out = df.assign(luk_flush=False, luk_pullback=False)
    alert = df[df["tier"] == "alert"] if "tier" in df else df
    if alert.empty:
        return out
    sessions = list(clock.sessions_back(cfg.schedule, session, LUK_SESSIONS))
    tickers = set(alert["ticker"].astype(str))
    past = history.load_bars(data_dir, sessions[:-1])
    past = past[past["ticker"].astype(str).isin(tickers)]
    bars = pd.concat([past, todays_bars(alert, session)], ignore_index=True)
    bars["ticker"] = bars["ticker"].astype(str)
    g, names = hm.grids(bars, sessions)
    found = luk.find(g, names, sessions, cfg.luk)
    today = found[found["session_date"] == session]
    key = out["ticker"].astype(str)
    # The pullback (Emil, 22 Oct 2026): a leader that dips to its EMA 9 or 21 and closes back
    # over it; pushed the next morning (study plan: bought at that close, 1-ADR stop, 21 days).
    pullbacks = today[today["strategy"] == "luk_pullback"].drop_duplicates("ticker")
    out["luk_pullback"] = key.isin(set(pullbacks["ticker"]))
    if len(pullbacks):
        out["luk_pb_level"] = key.map(pullbacks.set_index("ticker")["level"])
    flushes = today[today["strategy"] == "luk_avwap_flush"]
    if flushes.empty:
        return out
    levels = flushes.set_index("ticker")[list(COLUMNS)].rename(columns=COLUMNS)
    out["luk_flush"] = key.isin(levels.index)
    for column in levels.columns:
        out[column] = key.map(levels[column])
    return out
