"""Volume build (Emil, 4 Nov 2026: "in the scans as a column", "also add to card and a
watchlist"; data repo docs/research/2026-11-04-volume-build.md): the average volume of 5 sessions
over the average of the 50 sessions before those, and whether the price stayed quiet over them
(the 5-session close change within 1 ADR(20)).

- `vol_build` / `vol_quiet`: the 5 sessions *before* the run's session, on every stock and so
  on every scan hit. The session's own volume never counts (an EP's own volume isn't in it), the
  way the study measured it before a setup.
- `vol_build_now` / `vol_quiet_now` (EOD only): the 5 sessions up to this close, for the
  Screener's "Volume building, price quiet" list of what may move next.

Facts, not grades. A build of 2x or more with a quiet price made an EP-like day in the next two
weeks 3-5 times as likely, but buying it made about 0R and lagged the market; EP / EP9M A+ after
one made about 0R a signal day against about +0.5R for the rest, and skipping them did no better
in the account than skipping random A+.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import clock, history

SHORT, LONG = 5, 50
MIN_LONG = 40  # sessions with volume among the 50 (the study's floor)
ADR_DAYS = 20
WATCH_MIN = 2.0  # the card's note and the watchlist screen
STUDY_NOTE = "EP / EP9M A+ after a build made about 0R in the study"


def facts(bars: pd.DataFrame, sessions: list) -> pd.DataFrame:
    """Per ticker, as of the last of `sessions` (oldest first): `build` = its last 5 sessions'
    average volume / the 50 before them, `quiet` = the 5-session close change within 1 ADR."""
    if bars.empty:
        return pd.DataFrame(columns=["build", "quiet"], index=pd.Index([], name="ticker"))

    def grid(col: str) -> pd.DataFrame:
        wide = bars.pivot_table(index="session_date", columns="ticker", values=col, aggfunc="last")
        return wide.reindex(sessions)

    vol = grid("volume")
    short, long = vol.iloc[-SHORT:], vol.iloc[-(SHORT + LONG) : -SHORT]
    ok = (short.notna().sum() == SHORT) & (long.notna().sum() >= MIN_LONG)
    base = long.mean()
    build = (short.mean() / base.where(base > 0)).where(ok)
    quiet = pd.Series(np.nan, index=vol.columns)
    if {"high", "low", "close"} <= set(bars.columns) and len(sessions) > SHORT:
        hi, lo, cl = grid("high"), grid("low"), grid("close")
        adr = ((hi / lo - 1) * 100).iloc[-ADR_DAYS:]
        adr = adr.mean().where(adr.notna().sum() == ADR_DAYS)
        chg = (cl.iloc[-1] / cl.iloc[-(SHORT + 1)] - 1) * 100
        known = chg.notna() & adr.notna()
        quiet = (chg.abs() <= adr).where(known)
    out = pd.DataFrame({"build": build, "quiet": quiet}).replace([np.inf, -np.inf], np.nan)
    out.index = out.index.astype(str)
    out.index.name = "ticker"
    return out


def attach(
    df: pd.DataFrame, data_dir: Path, cfg, session: dt.date, today: pd.DataFrame | None = None
) -> pd.DataFrame:
    """`df` plus `vol_build` / `vol_quiet` (the sessions before `session`) and, with `today`
    (this close's bars, EOD), `vol_build_now` / `vol_quiet_now`. NaN without 5 + 40 sessions."""
    sessions = clock.sessions_back(cfg.schedule, session, SHORT + LONG + 1)
    before = [s for s in sessions if s < session][-(SHORT + LONG) :]
    names = set(df["ticker"].astype(str))
    bars = history.load_bars(data_dir, before)
    if not bars.empty:
        bars = bars[bars["ticker"].astype(str).isin(names)]
    tick = df["ticker"].astype(str)
    prior = facts(bars, before)
    out = df.assign(
        vol_build=tick.map(prior["build"]).astype(float).to_numpy(),
        vol_quiet=tick.map(prior["quiet"]).astype("boolean").to_numpy(),
    )
    if today is not None and len(today):
        now_days = [*before[1:], session]
        now_bars = pd.concat([bars[bars["session_date"] != session], today], ignore_index=True)
        now = facts(now_bars, now_days)
        out["vol_build_now"] = tick.map(now["build"]).astype(float).to_numpy()
        out["vol_quiet_now"] = tick.map(now["quiet"]).astype("boolean").to_numpy()
    return out


def card_tag(row) -> str | None:
    """The card's line for a build of 2x or more before the signal day."""
    vb = row.get("vol_build")
    if vb is None or pd.isna(vb) or vb < WATCH_MIN:
        return None
    text = f"📈 Volume built up {vb:.1f}x in the 5 days before"
    if row.get("grade") in ("A+++", "A++", "A+") and row.get("grade_strategy") in ("ep", "ep9m"):
        text += f" ({STUDY_NOTE})"
    return text
