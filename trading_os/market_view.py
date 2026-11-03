"""The Market page's data, without any UI (React dashboard phase 3, Nov 2026): moved from
`app/streamlit_app.py` so the Streamlit and the React Market pages show the same things.

The market as tiles (the newest breadth row, the IBD state, the heat), the IBD state's last 30
sessions, the setups at a market heat (the Sunday scan count's band), indexes / sectors /
themes with their rotation quadrant, the industries' rank moves, and the breadth history.
Facts about past rules, not advice. Read-only.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import board_data, dashboard, heat, ibd, sectors, tv

IBD_CAPTION = (
    "🟢 Healthy uptrend: 0-3 sell days. 🟡 Uptrend under pressure: 4-5, a correction is 1-2 "
    "sell days away. 🔴 Correction: 6 or more, until a follow-through day. O'Neil: a sell "
    "(distribution) day is SPY down 0.2 %+ on more volume; 6 in 25 start a correction, a "
    "follow-through day (day 4+ of a rally, SPY +1.25 % on more volume) starts an uptrend. "
    "Every signal carries the state; the monthly live check splits the live trades by it. "
    "Grades don't use it (it wasn't proven blind)."
)
HEAT_CAPTION = (
    "Each setup's study plan on the signal days at this heat (the Sunday scan count, the one "
    "market variable that held up when tested blind): net R a trade after costs, capped at "
    "20R, separately on 2016–2021 and 2022–2026. 'day r' averages each signal day first, so a "
    "day with many hits counts once. Held: made money per trade and per signal day in both "
    "periods, with {min_trades}+ trades in each. Lost: lost per trade in both. A = an A+ / A "
    "grade; B = the B grade (an edge per trade, half size); C = no grade. In the account, "
    "adding the C setups that held in a cool market lowered the return every way it was tried "
    "(data repo docs/research/how-we-test.md). Facts about past rules, not advice. Built "
    "{built}."
)
SECTOR_CAPTION = (
    "{source}. Quadrant: Leading = ahead of SPY over the month and this week; Weakening = "
    "ahead over the month, behind this week; Lagging = behind on both; Improving = behind over "
    "the month, ahead this week (money moving in)."
)
INDUSTRY_CAPTION = (
    "Industries ranked by their stocks' median 1- and 3-month returns (the EOD job). A big "
    "climb is money moving into a group before it reaches the top. Needs {n} saved EOD runs "
    "for the move column."
)
PERIODS = {"Today": "chg_pct", "1 week": "ret_1w", "1 month": "ret_1m", "3 months": "ret_3m",
           "Year to date": "ret_ytd"}  # fmt: skip
GROUPS = ("Index", "Sector", "Theme")
BREADTH_COLUMNS = [
    "session_date", "qqq_light", "light", "qqq_trend", "breadth_state", "scan_count", "up4",
    "down4", "ratio_5d", "ratio_10d", "up25q", "down25q",
]  # fmt: skip
INDUSTRY_COLUMNS = ["industry_rank", "industry", "sector", "moved", "med_ret_22", "members"]


def tiles(data_dir: Path, history: pd.DataFrame, today: dt.date | None = None):
    """The tiles from the newest breadth row, the IBD state today and the heat line."""
    if history.empty:
        return [], None
    last = history.iloc[-1].to_dict()
    try:
        ibd_now = ibd.state_at(Path(data_dir), today or dt.date.today())
    except Exception:  # noqa: BLE001 - the tile shows n/a
        ibd_now = None
    line = heat.short_line(heat.load(Path(data_dir)), last.get("scan_count"))
    return board_data.tiles(last, ibd_now, line[0].replace("🌡 ", "") if line else None), last


def ibd_recent(data_dir: Path, today: dt.date | None = None, n: int = 30) -> pd.DataFrame:
    """The IBD state's last `n` sessions, newest first (empty without SPY's daily bars)."""
    try:
        spy = ibd.spy_daily(Path(data_dir), today or dt.date.today())
        states = ibd.states(spy) if len(spy) > ibd.DIST_WINDOW else pd.DataFrame()
    except Exception:  # noqa: BLE001 - the section says what it needs
        return pd.DataFrame()
    if states.empty:
        return states
    recent = states.tail(n).iloc[::-1]
    recent = recent.assign(
        market=[ibd.words(s, c) for s, c in zip(recent["state"], recent["dist_count"], strict=True)]
    )
    out = recent[["session_date", "market", "close", "dist", "dist_count"]]
    return out.rename(
        columns={"close": "SPY", "dist": "sell day", "dist_count": "sell days (25)"}
    ).round(2)


def heat_view(data_dir: Path, history: pd.DataFrame, band: str | None = None) -> dict | None:
    """The setups at a heat band (today's by default): the bands, today's, the table."""
    stats = heat.load(Path(data_dir))
    counts = history["scan_count"].dropna() if "scan_count" in history else pd.Series()
    if not stats or not len(counts):
        return None
    bands = [name for _, name in stats["bands"]]
    now = heat.band(counts.iloc[-1], stats["bands"])
    pick = band if band in bands else now
    shown = heat.table(stats, pick).drop(columns=["short"])
    shown["verdict"] = shown["verdict"].map(lambda v: f"{heat.VERDICT_ICONS[v]} {v}")
    shown = shown.rename(columns=lambda c: c.replace("_", " ").replace("2016-21", "2016–21"))
    shown = shown.rename(columns=lambda c: c.replace("2022-26", "2022–26"))
    return {
        "bands": [{"band": b, "label": stats["band_labels"][b]} for b in bands],
        "now": now,
        "count": int(counts.iloc[-1]),
        "band": pick,
        "table": shown.round(2),
        "caption": HEAT_CAPTION.format(min_trades=stats["min_trades"], built=stats["built"]),
    }


def sector_table(
    data_dir: Path, details: Callable | None = None, env=None
) -> tuple[pd.DataFrame, str]:
    """The ETFs of `sectors.py` now (one TradingView request), else the last EOD's saved rows.
    Returns (table with the rotation columns, where it came from)."""
    env = os.environ if env is None else env
    try:
        if env.get("TRADING_OS_NO_LIVE"):  # the tests: no network
            raise RuntimeError("live data off")
        table, source = sectors.fetch(details or tv.fetch_details), "live from TradingView"
    except Exception:  # noqa: BLE001 - offline: the last saved day
        files = sorted((Path(data_dir) / "data" / "sectors").glob("*/*.parquet"))
        if not files:
            return pd.DataFrame(columns=sectors.COLUMNS), "not available"
        table, source = pd.read_parquet(files[-1]), f"saved {files[-1].stem.split('_')[0]}"
    return sectors.rotation(table), source


def sector_view(table: pd.DataFrame, period: str, groups) -> pd.DataFrame:
    """The table for one return period and groups, best first, as the page shows it."""
    col = PERIODS.get(period, "ret_1m")
    view = table[table["group"].isin(groups)].sort_values(col, ascending=False)
    keep = ["name", "ticker", "group", col, "vs_spy_1m", "vs_spy_1w", "quadrant", "trend", "rvol"]
    return view[[c for c in keep if c in view]].rename(
        columns={col: f"{period} %", "vs_spy_1m": "1M vs SPY", "vs_spy_1w": "1W vs SPY",
                 "rvol": "RVOL"}
    )  # fmt: skip


def rotation_points(table: pd.DataFrame, groups) -> list[dict[str, Any]]:
    """Each ETF as a point: 1 month vs SPY (x), 1 week vs SPY (y), for the rotation chart."""
    view = table[table["group"].isin(groups)].dropna(subset=["vs_spy_1m", "vs_spy_1w"])
    return [
        {"ticker": r["ticker"], "name": r.get("name"), "group": r["group"],
         "x": float(r["vs_spy_1m"]), "y": float(r["vs_spy_1w"])}
        for r in view.to_dict("records")
    ]  # fmt: skip


def industry_files(data_dir: Path) -> list[Path]:
    return sorted((Path(data_dir) / "data" / "industries").glob("*/*.parquet"))


def industries(data_dir: Path, back: str = "1 week") -> dict | None:
    """The top 15 industries now and the 15 climbing most since a week or a month ago."""
    files = industry_files(data_dir)
    if not files:
        return None
    offset = 5 if back == "1 week" else 21
    latest = pd.read_parquet(files[-1])
    earlier = pd.read_parquet(files[-1 - offset]) if len(files) > offset else pd.DataFrame()
    moves = sectors.industry_moves(latest, earlier)
    names = {"industry_rank": "rank", "moved": f"moved ({back})", "med_ret_22": "median 1M %"}
    cols = [c for c in INDUSTRY_COLUMNS if c in moves]
    top = moves.head(15)[cols].rename(columns=names).round(1)
    climbing = moves.dropna(subset=["moved"]) if "moved" in moves else moves.iloc[0:0]
    climbing = climbing.sort_values("moved", ascending=False).head(15)[cols]
    return {
        "top": top,
        "climbing": climbing.rename(columns=names).round(1),
        "caption": INDUSTRY_CAPTION.format(n=offset + 1),
    }


def breadth(history: pd.DataFrame) -> pd.DataFrame:
    """The breadth history, newest first."""
    return history[[c for c in BREADTH_COLUMNS if c in history]].iloc[::-1]


def ratio_curve(history: pd.DataFrame) -> list[dict[str, Any]]:
    """The 5- and 10-day up/down ratios over time, oldest first."""
    out = []
    for r in history.to_dict("records"):
        out.append({"time": pd.Timestamp(r["session_date"]).strftime("%Y-%m-%d"),
                    "ratio_5d": r.get("ratio_5d"), "ratio_10d": r.get("ratio_10d")})  # fmt: skip
    return out


def history_of(data_dir: Path) -> pd.DataFrame:
    return dashboard.breadth_history(Path(data_dir))
