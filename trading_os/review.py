"""Trade review (Emil, 20 Oct 2026): what each trade did between entry and exit, the risk in
open positions now, and your real R next to the studies' R for the same setup. Facts, not
advice. LOCAL USE ONLY: reads the journal in the private data repo.

- Excursions use daily bars from the session after the entry to the exit session; the entry
  day is left out because the bars can't tell whether its low came before or after the fill.
  MFE = the best price reached (in % and R), MAE = the worst; exit efficiency = the R taken
  as a share of the MFE in R.
- Open positions are valued at the latest daily close in the data repo (not live prices).
- Real vs study: per setup, your closed trades against the history studies' trades of the same
  strategy (entry at the signal, its stop): the 21-session hold and the 20-day MA trail, and
  the minute study's best entry/stop/exit when it exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

# Journal setup -> (daily study strategy, minute study strategy). EP-Day lives in the EP study.
STUDY_NAMES = {
    "ep_day": ("ep_day", "ep"),
    "ep_pm": ("ep_day", "ep"),
    "ep_ah": ("ep_day", "ep"),
    "ep9m": ("ep9m", "ep9m"),
    "ep9m_pace": ("ep9m", "ep9m"),
    "breakout_trigger": ("breakout_trigger", "breakout"),
    "breakout_watch": ("breakout_watch", "breakout"),
    "pivot_watch": ("breakout_watch", "breakout"),
}


def _sign(direction: str) -> int:
    return 1 if direction == "long" else -1


def excursions(trades: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """MAE/MFE in % and R, exit efficiency and sessions held for each closed trade."""
    out = trades.copy()
    for column in ("mfe_pct", "mae_pct", "mfe_r", "mae_r", "exit_efficiency", "sessions_held"):
        out[column] = np.nan
    if out.empty or bars.empty:
        return out
    by_ticker = {t: g.sort_values("session_date") for t, g in bars.groupby("ticker")}
    for i, t in out.iterrows():
        g = by_ticker.get(t["ticker"])
        if g is None or t["exit_date"] is None or pd.isna(t["exit_date"]):
            continue
        held = g[(g["session_date"] > t["entry_date"]) & (g["session_date"] <= t["exit_date"])]
        out.at[i, "sessions_held"] = len(held)
        if held.empty:
            continue
        entry, sign = t["entry_avg"], _sign(t["direction"])
        best = held["high"].max() if sign > 0 else held["low"].min()
        worst = held["low"].min() if sign > 0 else held["high"].max()
        out.at[i, "mfe_pct"] = (best / entry - 1) * 100 * sign
        out.at[i, "mae_pct"] = (worst / entry - 1) * 100 * sign
        stop = pd.to_numeric(t.get("order_stop"), errors="coerce")
        risk = (entry - stop) * sign if stop == stop else np.nan
        if risk > 0:
            out.at[i, "mfe_r"] = (best - entry) * sign / risk
            out.at[i, "mae_r"] = (worst - entry) * sign / risk
            if out.at[i, "mfe_r"] > 0 and t.get("r_multiple") == t.get("r_multiple"):
                out.at[i, "exit_efficiency"] = t["r_multiple"] / out.at[i, "mfe_r"]
    return out


def open_risk(
    positions: pd.DataFrame,
    last: pd.DataFrame,
    account_usd: float | None = None,
) -> pd.DataFrame:
    """Open positions at the latest close: open P&L ($ and R) and what is still at risk to the
    stop ($ and % of the account). `last`: ticker, session_date, close."""
    out = positions.copy()
    if out.empty:
        return out
    latest = last.sort_values("session_date").drop_duplicates("ticker", keep="last")
    marks = latest.set_index("ticker")[["close", "session_date"]]
    out["last_close"] = out["ticker"].map(marks["close"])
    out["last_date"] = out["ticker"].map(marks["session_date"])
    sign = np.where(out["direction"] == "long", 1, -1)
    qty = out["open_quantity"].abs()
    stop = pd.to_numeric(out.get("order_stop"), errors="coerce")
    out["open_pnl"] = (out["last_close"] - out["entry_avg"]) * sign * qty
    risk_per_share = (out["entry_avg"] - stop) * sign
    out["open_r"] = ((out["last_close"] - out["entry_avg"]) * sign / risk_per_share).where(
        risk_per_share > 0
    )
    out["at_risk_usd"] = ((out["last_close"] - stop) * sign * qty).clip(lower=0)
    if account_usd:
        out["at_risk_pct"] = out["at_risk_usd"] / account_usd * 100
    return out


def _stats(r: pd.Series) -> dict[str, Any]:
    r = r.dropna()
    return {
        "trades": len(r),
        "win%": (r > 0).mean() * 100 if len(r) else np.nan,
        "mean_R": r.clip(upper=20).mean() if len(r) else np.nan,
    }


def real_vs_study(
    trades: pd.DataFrame,
    daily: Mapping[str, pd.DataFrame],
    minute_best: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per setup: your trades next to the study. `daily`: strategy -> its history rows (with
    r_21d and r_trail_ma20); `minute_best`: intraday_study.best() output."""
    rows = []
    if trades.empty:
        return pd.DataFrame()
    for setup, part in trades.groupby(trades["setup"].fillna("untagged")):
        mine = _stats(part["r_multiple"])
        row = {"setup": setup, "your_trades": len(part), "your_win%": mine["win%"]}
        row["your_mean_R"] = mine["mean_R"]
        row["your_pnl"] = part["pnl"].sum()
        daily_name, minute_name = STUDY_NAMES.get(setup, (setup, setup))
        hist = daily.get(daily_name)
        if hist is not None and len(hist):
            hold = _stats(hist["r_21d"]) if "r_21d" in hist else {}
            trail = _stats(hist["r_trail_ma20"]) if "r_trail_ma20" in hist else {}
            row |= {
                "study_trades": hold.get("trades"),
                "study_win%_21d": hold.get("win%"),
                "study_R_21d": hold.get("mean_R"),
                "study_R_trail_ma20": trail.get("mean_R"),
            }
        if minute_best is not None and len(minute_best):
            top = minute_best[minute_best["strategy"] == minute_name].head(1)
            if len(top):
                best = top.iloc[0]
                row["minute_best"] = f"{best['entry']} · {best['stop_rule']} · {best['exit']}"
                row["minute_best_R"] = best["mean_R"]
        rows.append(row)
    return pd.DataFrame(rows)
