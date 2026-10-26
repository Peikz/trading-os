"""EP9M anchored-VWAP re-entry, live (Emil, 26 Oct 2026; data repo
docs/research/2026-10-25-third-period-2006-2015.md). A stock that was an EP9M A+ (the 10:15 or
12:00 pace check) gets a second entry when, 2-15 sessions after that day, it comes back to the
VWAP anchored at that day's open and holds it: the day's low at or under the AVWAP, the close
over it. The AVWAP uses each day's typical price (high + low + close) / 3, since the stored
bars have no VWAP (the study gave the same result both ways). The first such day only. Bought
at the next open, stop under the signal day's low (at most 2 ADR), out after 21 sessions.
Graded B (half the A+ size): a clear edge per trade, but its gain on top of the A+ package
wasn't robust to small changes (real VWAP vs typical price).

In the 2016-26 study: +0.41 / +0.45R a trade (2016-21 / 2022-26) and, added to the live
package, 20.4 -> about 25 %/yr and 33.4 -> about 37 %/yr, against 20.9 / 25.3 % for random
second entries. Robust to the window (2-8 to 2-25) and the stop; 2024-26 was flat, so the
monthly live check is its kill switch.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import clock, history
from trading_os.enrich import todays_bars

FIRST_DAY, LAST_DAY = 2, 15  # sessions after the EP9M day
ANCHOR_SCANS = ("ep9m_pace",)
ANCHOR_GRADE = "A+"
PRICE_MIN, DVOL_MIN = 5.0, 5_000_000


def anchors(data_dir: Path, sessions: list[dt.date]) -> pd.DataFrame:
    """EP9M A+ signals (ticker, anchor) on `sessions` (no manual runs)."""
    folder = Path(data_dir) / "data" / "candidates"
    frames = []
    for day in sessions:
        for path in sorted(folder.glob(f"{day.year}/{day.isoformat()}_*.parquet")):
            cand = pd.read_parquet(path, columns=None)
            if {"scan", "grade", "ticker"} <= set(cand.columns):
                hit = cand[cand["scan"].isin(ANCHOR_SCANS) & (cand["grade"] == ANCHOR_GRADE)]
                frames.append(pd.DataFrame({"ticker": hit["ticker"].astype(str), "anchor": day}))
    if not frames:
        return pd.DataFrame(columns=["ticker", "anchor"])
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def touch_today(bars: pd.DataFrame, k: int) -> tuple[bool, float]:
    """(signal today, today's AVWAP): `bars` are the anchor day (row 0) to today (row k), one row
    a session. The AVWAP for day j is from the anchor's open through day j-1. A signal is a
    low at or under it with the close over it, on day k and on no day 2..k-1 before."""
    tp = ((bars["high"] + bars["low"] + bars["close"]) / 3).to_numpy(dtype=float)
    vol = bars["volume"].to_numpy(dtype=float)
    lo, cl = bars["low"].to_numpy(dtype=float), bars["close"].to_numpy(dtype=float)
    cum_pv, cum_v = np.cumsum(tp * vol), np.cumsum(vol)
    avwap = np.full(len(bars), np.nan)
    avwap[1:] = cum_pv[:-1] / np.where(cum_v[:-1] > 0, cum_v[:-1], np.nan)
    touched = (lo <= avwap) & (avwap < cl)
    if any(touched[FIRST_DAY:k]):
        return False, float(avwap[k])
    return bool(touched[k]), float(avwap[k])


def attach(df: pd.DataFrame, data_dir: Path, cfg, session: dt.date) -> pd.DataFrame:
    """`df` plus `ep9m_avwap` (bool), `avwap_level`, `avwap_anchor` and `avwap_day`."""
    out = df.assign(ep9m_avwap=False)
    sessions = list(clock.sessions_back(cfg.schedule, session, LAST_DAY + 1))
    anchor_days = sessions[: len(sessions) - FIRST_DAY]  # the EP9M day is 2-15 sessions back
    found = anchors(data_dir, anchor_days)
    found = found[found["ticker"].isin(set(out["ticker"].astype(str)))]
    if found.empty:
        return out
    tickers = set(found["ticker"])
    today = out[out["ticker"].astype(str).isin(tickers)]
    past = history.load_bars(data_dir, [s for s in sessions[:-1] if s >= min(found["anchor"])])
    past = past[past["ticker"].astype(str).isin(tickers)]
    bars = pd.concat([past, todays_bars(today, session)], ignore_index=True)
    bars["ticker"] = bars["ticker"].astype(str)
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    bars = bars.drop_duplicates(["ticker", "session_date"], keep="last")
    hits: dict[str, dict] = {}
    for rec in found.sort_values("anchor").to_dict("records"):
        k = len(sessions) - 1 - sessions.index(rec["anchor"])
        mine = bars[(bars["ticker"] == rec["ticker"]) & (bars["session_date"] >= rec["anchor"])]
        if len(mine) != k + 1:  # a missing session would shift the window: skip, never guess
            continue
        signal, level = touch_today(mine.sort_values("session_date").reset_index(drop=True), k)
        if signal:
            hits[rec["ticker"]] = {"avwap_level": level, "avwap_anchor": rec["anchor"],
                                   "avwap_day": k}  # fmt: skip
    if not hits:
        return out
    key = out["ticker"].astype(str)
    liquid = (out["close"] >= PRICE_MIN) & (out["avg_dollar_volume_20d"] >= DVOL_MIN)
    out["ep9m_avwap"] = key.isin(hits) & liquid
    for column in ("avwap_level", "avwap_anchor", "avwap_day"):
        out[column] = key.map({t: h[column] for t, h in hits.items()})
    return out
