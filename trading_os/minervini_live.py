"""Mark Minervini's Trend Template and VCP as live end-of-day scans (Emil, 22 Oct 2026: "add the
momentum strategies to scan and push"; SPEC §6.2). The rules are `minervini.py`'s, unchanged
(config `minervini:`, from his books, the reading proposed).

- minervini_tt: the stock passes the Trend Template at today's close (a list, ranked by RS).
- vcp: a Trend Template stock whose base at today's close is a VCP (2-6 shrinking contractions,
  the last tight, volume drying up) and still under its pivot: tomorrow's buy-stop at the
  pivot, the study's entry (it measured the breakout day, bought as the pivot is crossed).
  The study's stop: 1 ADR under the pivot, at least 1 %.

RS is ranked within the alert tier here (the study ranked the whole universe), so it reads a
little higher. The scan reads `SESSIONS` of the stored daily bars plus today's; flags go on the
universe under their own names, never over another scan's pivot.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import clock, history, minervini
from trading_os import history_metrics as hm
from trading_os.enrich import todays_bars

SESSIONS = 300  # 252 for the 52-week range + 22 for the rising 200-day + room
STOP_FLOOR_PCT = 1.0


def attach(df: pd.DataFrame, data_dir: Path, cfg, session: dt.date) -> pd.DataFrame:
    """`df` plus `minervini_tt`, `vcp_watch` and the VCP base's levels (alert tier)."""
    out = df.assign(minervini_tt=False, vcp_watch=False)
    alert = df[df["tier"] == "alert"] if "tier" in df else df
    if alert.empty:
        return out
    sessions = list(clock.sessions_back(cfg.schedule, session, SESSIONS))
    tickers = set(alert["ticker"].astype(str))
    past = history.load_bars(data_dir, sessions[:-1])
    past = past[past["ticker"].astype(str).isin(tickers)]
    bars = pd.concat([past, todays_bars(alert, session)], ignore_index=True)
    bars["ticker"] = bars["ticker"].astype(str)
    g, names = hm.grids(bars, sessions)
    conf = cfg.minervini
    rs = minervini.rs_rating(g["close"])
    tt = minervini.trend_template(g, rs, conf)
    last = len(sessions) - 1
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    with np.errstate(divide="ignore", invalid="ignore"):
        adr_pct = hm.rolling_mean((high / low - 1) * 100, hm.ADR_DAYS)
        avg50 = hm.rolling_mean(volume, 50)
    rows = []
    for j in np.nonzero(tt[last])[0]:
        row = {"ticker": names[j], "mm_rs": float(rs[last, j])}
        base = minervini.vcp(
            last, high[:, j], low[:, j], volume[:, j], avg50[:, j], adr_pct[last, j], conf
        )
        if base is not None and close[last, j] < base["pivot"]:
            pivot = float(base["pivot"])
            adr_usd = adr_pct[last, j] * close[last, j] / 100
            stop = pivot - max(adr_usd, pivot * STOP_FLOOR_PCT / 100)
            row |= {
                "vcp": True,
                "vcp_pivot": pivot,
                "vcp_order_stop": stop,
                "vcp_risk_adr": (pivot - stop) / adr_usd if adr_usd > 0 else np.nan,
                "vcp_contractions": base["contractions"],
                "vcp_depths": base["depths"],
                "vcp_base_len": base["base_len"],
                "vcp_dryup": base["dryup_ratio"],
                "vcp_pivot_dist_pct": (pivot / close[last, j] - 1) * 100,
            }
        rows.append(row)
    if not rows:
        return out
    found = pd.DataFrame(rows).set_index("ticker")
    key = out["ticker"].astype(str)
    out["minervini_tt"] = key.isin(found.index)
    out["vcp_watch"] = key.map(found["vcp"]).fillna(False).astype(bool) if "vcp" in found else False
    for column in found.columns.drop("vcp", errors="ignore"):
        out[column] = key.map(found[column])
    return out
