"""Qullamaggie's MA-surf as a live end-of-day scan (Emil, 21 Oct 2026: "I will use this
strategy more"; SPEC §6.2). Grade C (no grade of its own), pushed anyway as a watch for the
next session with the study's plan: from 10:00 New York, over the pivot buy, under it a
buy-stop at the pivot; the order stop under the base's right side; out on a close under the
20-day MA.

The rules are `qm_setups.py`'s, unchanged (config `qm_surf:`, every value proposed): a stock
with ADR >= 4 % after a 30 %+ move rests 5-40 sessions surfing its rising 10- or 20-day MA,
back near it, with a tight, dry, higher-low right side and the pivot within 1 ADR. The scan
reads `SURF_SESSIONS` of the stored daily bars plus today's. The flags go on the universe
under `surf_` names, so they never overwrite the breakout scans' pivot and stop.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from trading_os import clock, history, qm_setups
from trading_os import history_metrics as hm
from trading_os.enrich import todays_bars

SURF_SESSIONS = 160  # 63-session prior move + 40-session base + the 50-day volume average
COLUMNS = {
    "pivot": "surf_pivot",
    "order_stop": "surf_order_stop",
    "risk_adr": "surf_risk_adr",
    "surf_ma": "surf_ma",
    "surf_days": "surf_days",
    "base_len": "surf_base_len",
    "day_in_setup": "surf_day_in_setup",
    "prior_move_pct": "surf_prior_move_pct",
    "ma_stacked": "surf_ma_stacked",
}


def attach(df: pd.DataFrame, data_dir: Path, cfg, session: dt.date) -> pd.DataFrame:
    """`df` plus `ma_surf` (bool) and the setup's levels, for the alert-tier rows."""
    out = df.assign(ma_surf=False)
    alert = df[df["tier"] == "alert"] if "tier" in df else df
    if alert.empty:
        return out
    sessions = list(clock.sessions_back(cfg.schedule, session, SURF_SESSIONS))
    tickers = set(alert["ticker"].astype(str))
    past = history.load_bars(data_dir, sessions[:-1])
    past = past[past["ticker"].astype(str).isin(tickers)]
    bars = pd.concat([past, todays_bars(alert, session)], ignore_index=True)
    bars["ticker"] = bars["ticker"].astype(str)
    g, names = hm.grids(bars, sessions)
    found = qm_setups.find(g, names, sessions, cfg.qm_surf)
    found = found[found["session_date"] == session]
    if found.empty:
        return out
    levels = found.set_index("ticker")[list(COLUMNS)].rename(columns=COLUMNS)
    key = out["ticker"].astype(str)
    out["ma_surf"] = key.isin(levels.index)
    for column in levels.columns:
        out[column] = key.map(levels[column])
    return out
