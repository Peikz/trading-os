"""The Journal page's tables, without any UI (React dashboard, Nov 2026): moved from
`app/streamlit_app.py` so the Streamlit and the React dashboards show the same numbers.

Closed trades with their grade and MFE/MAE, the stats over them and the R curve; the plans
with their status; the planned hits a new plan can start from; your real R next to the
studies'. The writes stay in `journal` and `plans`. Facts, not advice.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import (
    board_data,
    clock,
    dashboard,
    intraday_study,
    journal,
    luk,
    minervini,
    plans,
    review,
    strategy_history,
)

OPEN_COLUMNS = [
    "ticker", "direction", "entry_date", "entry_avg", "open_quantity", "order_stop",
    "last_close", "last_date", "open_pnl", "open_r", "at_risk_usd", "at_risk_pct", "setup",
]  # fmt: skip
PLAN_CHECK_COLUMNS = ["ticker", "setup", "rule", "held", "hold", "r_now", "earnings", "action"]
PLAN_COLUMNS = [
    "status", "session_date", "ticker", "direction", "setup", "entry", "stop", "shares",
    "risk_usd", "fill_date", "fill_price", "slippage_pct", "slippage_r", "note", "plan_id",
]  # fmt: skip
CLOSED_COLUMNS = [
    "ticker", "direction", "setup", "entry_date", "exit_date", "entry_avg", "exit_avg",
    "quantity", "pnl", "r_multiple", "mfe_r", "mae_r", "exit_efficiency", "sessions_held",
    "signal_scan", "grade",
]  # fmt: skip
MFE_CAPTION = (
    "MFE/MAE: best and worst price from the session after entry to the exit, in R. "
    "Exit efficiency: the R you took as a share of the MFE."
)
REAL_CAPTION = (
    "Study = the history replay of the same strategy (entry at the signal, its stop): "
    "21-session hold and 20-day MA trail; minute best = the minute study's best "
    "entry, stop and exit. The gap between your R and the study's is execution "
    "(entries, exits, selection). Facts, not advice."
)
PLAN_CHECK_CAPTION = (
    "hold: sell at the close after `hold` sessions · trail_ma20: out on a close "
    "under the 20-day MA · cover_ma20: a short covers on a close over it. The "
    "same lines come in the pre-market and EOD pushes."
)


def setup_names(cfg) -> list[str]:
    """Live scans and the study-only setups, for tagging trades and plans."""
    return sorted({*cfg.scans, *luk.STRATEGIES, *minervini.STRATEGIES} - {"breadth"})


def latest_hits(runs, read: Callable[[str], pd.DataFrame] = pd.read_parquet) -> pd.DataFrame:
    """Planned hits (entry, stop) of the newest run, for starting a plan from a scan."""
    if not runs:
        return pd.DataFrame()
    cands = read(str(runs[0].candidates))
    if "plan_entry" not in cands:
        return pd.DataFrame()
    keep = cands.dropna(subset=["plan_entry", "plan_stop"])
    return keep.sort_values(["scan", "rank"])[["ticker", "scan", "plan_entry", "plan_stop"]]


def hit_label(r: dict[str, Any]) -> str:
    return f"{r['ticker']} · {r['scan']} · buy {r['plan_entry']:.2f} stop {r['plan_stop']:.2f}"


def ny_today(cfg) -> dt.date:
    return clock.ny_time(cfg.schedule, dt.datetime.now(dt.UTC)).date()


def plan_table(data_dir: Path, cfg, today: dt.date | None = None) -> pd.DataFrame:
    """Every plan with its status (open, filled with slippage, expired, cancelled)."""
    fills = journal.reconcile(journal.load_fills(data_dir))
    return plans.status(
        plans.load(data_dir),
        fills,
        cfg.schedule,
        cfg.journal["plan_valid_sessions"],
        today or ny_today(cfg),
    )


def suggest_shares(entry: float, stop: float, account, usd_rate: float | None):
    """Shares from your risk per trade (`plans.shares_for`); None without an account."""
    if not (account and usd_rate and entry and stop):
        return None
    return plans.shares_for(
        entry,
        stop,
        account.risk_usd(usd_rate),
        account.size_usd(usd_rate),
        account.max_position_pct,
    )


def suggestion_text(s: dict[str, Any]) -> str:
    return (
        f"Suggested: {s['shares']:,} shares · ${s['position_usd']:,.0f}"
        f" · risk ${s['risk_usd']:,.0f}" + (" (capped by max position)" if s["capped"] else "")
    )


def trade_bars(
    data_dir: Path, trades: pd.DataFrame, bars: Callable[[str], pd.DataFrame] | None = None
) -> pd.DataFrame:
    """Daily bars of the traded tickers (2 years, the compact file)."""
    if trades.empty:
        return pd.DataFrame()
    get = bars or (lambda t: board_data.daily_bars(Path(data_dir), t))
    tickers = sorted(set(trades["ticker"]))
    frames = [get(t).assign(ticker=t) for t in tickers]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def closed_trades(
    data_dir: Path, bars: Callable[[str], pd.DataFrame] | None = None
) -> pd.DataFrame:
    """Closed trades from the newest journal rebuild, with your grade and MFE/MAE."""
    trades = dashboard.latest_journal(data_dir)
    if trades.empty:
        return trades
    notes = dashboard.notes_state(data_dir)
    graded = notes[notes["kind"] == "trade"].set_index("ref_id")["grade"].to_dict()
    trades = trades.assign(grade=trades["trade_id"].map(graded).fillna(""))
    return review.excursions(trades, trade_bars(data_dir, trades, bars))


def closed_stats(trades: pd.DataFrame) -> dict[str, Any]:
    """Closed trades, win rate, average R and total P&L."""
    if trades.empty:
        return {"trades": 0, "win_rate": None, "avg_r": None, "pnl": 0.0}
    with_r = trades["r_multiple"].dropna()
    return {
        "trades": int(len(trades)),
        "win_rate": float((trades["pnl"] > 0).mean() * 100),
        "avg_r": float(with_r.mean()) if len(with_r) else None,
        "pnl": float(trades["pnl"].sum()),
    }


def r_curve(trades: pd.DataFrame) -> pd.Series:
    """The cumulative R by exit date (trades with an R)."""
    if trades.empty or "r_multiple" not in trades:
        return pd.Series(dtype=float)
    curve = trades.dropna(subset=["r_multiple"]).sort_values("exit_date")
    return curve.set_index("exit_date")["r_multiple"].cumsum()


def trade_label(t: dict[str, Any]) -> str:
    return f"{t['ticker']} {t['entry_date']} → {t['exit_date']} ({t['pnl']:,.0f})"


def study_by_strategy(data_dir: Path) -> dict[str, pd.DataFrame]:
    """History-study trades per strategy (EP-Day from the EP study, alert tier)."""
    hist = strategy_history.load(data_dir)
    out = {k: v for k, v in hist.groupby("strategy")} if len(hist) else {}
    built = sorted((Path(data_dir) / "data" / "ep_history").glob("ep_history_*.parquet"))
    if built:
        ep = pd.read_parquet(built[-1], columns=["is_ep_day", "tier", "r_21d", "r_trail_ma20"])
        out["ep_day"] = ep[ep["is_ep_day"] & (ep["tier"] == "alert")]
    return out


def minute_best(data_dir: Path) -> pd.DataFrame | None:
    """The minute study's best entry/stop/exit per strategy (the intraday-2y release); None
    when it can't be fetched."""
    from trading_os import remote_data

    with contextlib.suppress(Exception):  # offline: the table goes without it
        repo = remote_data.repo_of(Path(data_dir))
        remote_data.fetch(repo, "intraday-2y", "summary_none.parquet")
    files = sorted((remote_data.CACHE / "intraday-2y").glob("summary_none*"))
    return intraday_study.best(pd.read_parquet(files[0]), 50) if files else None


def real_vs_study(data_dir: Path, trades: pd.DataFrame) -> pd.DataFrame:
    """Your real R per setup next to the studies' (`review.real_vs_study`)."""
    if trades.empty:
        return pd.DataFrame()
    return review.real_vs_study(trades, study_by_strategy(data_dir), minute_best(data_dir))
