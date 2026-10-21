"""Portfolio simulation (Emil, 20 Oct 2026): what the graded setups would have done to one
account, day by day, with position limits and sizing from the account's risk. Research code
for the report; facts about the rules, not advice.

Each candidate trade comes from the grading study with its plan already played out: entry
day, entry minute, entry price and stop, side, grade, and one or two exit legs (sessions
after the entry day, fraction of the position, R of that leg). The simulation decides which
trades the account could take and how big:

- risk per trade = equity x the grade's risk %, times the trade's own `risk_mult` when the
  trades have one (e.g. bigger in a cool market), cut in a drawdown (`dd_steps`);
- shares = risk / (entry - stop), then capped by the largest position (% of equity), the
  stock's liquidity (% of its 20-day average dollar volume) and the room left under the
  gross exposure cap (100 % = no margin);
- at most `max_positions` open and `max_new_per_day` new a day, one position per stock;
- same-day candidates in order of entry time, then priority (grade, predicted R);
- costs: the trade's round-trip cost % (half at entry, the rest pro rata at the exits),
  margin interest on borrowed money;
- every open position is marked to the day's close.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}


@dataclass(frozen=True)
class Rules:
    risk_pct: Mapping[str, float]  # % of equity risked per grade (0 = not taken)
    max_positions: int = 12
    max_new_per_day: int = 4
    max_position_pct: float = 20.0
    max_gross_pct: float = 100.0
    liquidity_pct: float = 1.0
    min_position_usd: float = 500.0
    dd_steps: tuple = ((10.0, 0.5), (20.0, 0.25))  # (drawdown % at least, risk multiplier)
    margin_rate_pct: float = 8.0  # yearly, on money borrowed for longs
    start_equity: float = 100_000.0
    r_cap: float = 50.0  # R per leg (data errors); real winners stay under it
    by_grade_extra: Mapping[str, float] = field(default_factory=dict)
    # at most this many open positions of a grade, leaving room for the better ones
    max_by_grade: Mapping[str, int] = field(default_factory=dict)


@dataclass
class Position:
    trade: int
    ticker: str
    side: int
    shares: float
    entry: float
    risk_ps: float
    legs: list  # [(exit session index, fraction of the first size, R)]
    orig_shares: float
    exit_cost: float
    pnl: float = 0.0
    grade: str = ""


def _legs(row: Mapping, t: int) -> list:
    legs = []
    for k in (1, 2):
        frac = row.get(f"frac_{k}", 0.0)
        if frac and frac > 0 and not math.isnan(row.get(f"r_{k}", np.nan)):
            legs.append((t + int(row[f"days_{k}"]), float(frac), float(row[f"r_{k}"])))
    return legs


def simulate(
    trades: pd.DataFrame, closes: np.ndarray, sessions: list, tickers: list, rules: Rules
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(daily equity table, trades taken). `closes`: sessions x tickers (adjusted, like the
    trade prices), forward-filled inside so a delisted stock keeps its last close."""
    closes = pd.DataFrame(closes).ffill().to_numpy()
    index = {d: i for i, d in enumerate(sessions)}
    col = {t: j for j, t in enumerate(tickers)}
    trades = trades[trades["session_date"].isin(index) & trades["ticker"].isin(col)].copy()
    trades["t"] = trades["session_date"].map(index)
    trades["rank"] = trades["grade"].map(GRADE_RANK).fillna(9)
    trades = trades.sort_values(["t", "entry_minute", "rank", "priority"], ascending=[1, 1, 1, 0])
    by_day = {t: part.to_dict("records") for t, part in trades.groupby("t")}

    cash, peak = rules.start_equity, rules.start_equity
    equity = rules.start_equity
    open_pos: list[Position] = []
    taken, rows, records = [], [], {}
    for t in range(len(sessions)):
        dd = (1 - equity / peak) * 100 if peak > 0 else 0.0
        mult = 1.0
        for level, m in rules.dd_steps:
            if dd >= level:
                mult = m
        held = {p.ticker for p in open_pos}
        gross = sum(abs(p.shares) * _px(closes, t - 1, col[p.ticker], p.entry) for p in open_pos)
        new_today = 0
        for row in by_day.get(t, []):
            if len(open_pos) >= rules.max_positions or new_today >= rules.max_new_per_day:
                break
            risk_pct = rules.risk_pct.get(row["grade"], 0.0)
            own = row.get("risk_mult", 1.0)  # the trade's own multiple; NaN or none: 1
            risk_pct *= 1.0 if own is None or own != own else float(own)
            if risk_pct <= 0 or row["ticker"] in held:
                continue
            cap = rules.max_by_grade.get(row["grade"])
            if cap is not None and sum(p.grade == row["grade"] for p in open_pos) >= cap:
                continue
            price, stop = float(row["price"]), float(row["stop"])
            risk_ps = abs(price - stop)
            if not risk_ps > 0 or not price > 0:
                continue
            value = equity * risk_pct / 100 * mult / risk_ps * price
            dvol = row.get("d_dvol20", np.nan)
            caps = [
                equity * rules.max_position_pct / 100,
                equity * rules.max_gross_pct / 100 - gross,
            ]
            if dvol == dvol and dvol > 0:
                caps.append(dvol * rules.liquidity_pct / 100)
            value = min(value, *caps)
            if value < rules.min_position_usd:
                continue
            side = int(row["side"])
            shares = value / price
            cost = value * float(row.get("cost_pct", 0.0)) / 100
            cash -= side * value + cost / 2
            pos = Position(
                trade=int(row["trade_id"]),
                ticker=row["ticker"],
                side=side,
                shares=shares,
                entry=price,
                risk_ps=risk_ps,
                legs=_legs(row, t),
                orig_shares=shares,
                exit_cost=cost / 2,
                pnl=-cost / 2,
                grade=row["grade"],
            )
            open_pos.append(pos)
            held.add(pos.ticker)
            gross += value
            new_today += 1
            records[pos.trade] = rec = {
                "trade_id": pos.trade,
                "session_date": sessions[t],
                "ticker": pos.ticker,
                "strategy": row.get("strategy"),
                "grade": row["grade"],
                "side": side,
                "value": value,
                "risk_usd": shares * risk_ps,
                "equity_at_entry": equity,
            }
            taken.append(rec)
        still = []
        for p in open_pos:  # exits whose day has come (the entry day too)
            due = [leg for leg in p.legs if leg[0] <= t]
            for _, frac, r in due:
                px = p.entry + p.side * min(r, rules.r_cap) * p.risk_ps
                sh = p.orig_shares * frac
                leg_cost = p.exit_cost * frac
                cash += p.side * sh * px - leg_cost
                p.pnl += p.side * sh * (px - p.entry) - leg_cost
                p.shares -= sh
            p.legs = [leg for leg in p.legs if leg[0] > t]
            if p.legs and p.shares > 1e-9:
                still.append(p)
            else:
                record = records[p.trade]
                record["pnl"], record["exit_date"] = p.pnl, sessions[t]
                record["r_realized"] = p.pnl / (p.orig_shares * p.risk_ps)
        open_pos = still
        long_value = sum(
            p.shares * _px(closes, t, col[p.ticker], p.entry) for p in open_pos if p.side > 0
        )
        short_value = sum(
            p.shares * _px(closes, t, col[p.ticker], p.entry) for p in open_pos if p.side < 0
        )
        equity = cash + long_value - short_value
        borrowed = max(0.0, long_value - max(equity, 0.0))
        interest = borrowed * rules.margin_rate_pct / 100 / 252
        cash -= interest
        equity -= interest
        peak = max(peak, equity)
        rows.append(
            {
                "session_date": sessions[t],
                "equity": equity,
                "positions": len(open_pos),
                "long_pct": long_value / equity * 100 if equity > 0 else np.nan,
                "short_pct": short_value / equity * 100 if equity > 0 else np.nan,
                "new": new_today,
            }
        )
        if equity <= 0:
            break
    return pd.DataFrame(rows), pd.DataFrame(taken)


def _px(closes: np.ndarray, t: int, j: int, fallback: float) -> float:
    if t < 0:
        return fallback
    v = closes[t, j]
    return fallback if v != v else float(v)


def summary(curve: pd.DataFrame, taken: pd.DataFrame) -> dict:
    """CAGR, max drawdown, MAR, daily Sharpe, exposure, trades a year, win rate."""
    if curve.empty:
        return {}
    eq = curve["equity"].to_numpy()
    years = len(curve) / 252
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if eq[-1] > 0 and years > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    max_dd = float(((peak - eq) / peak).max())
    daily = pd.Series(eq).pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else np.nan
    done = taken.dropna(subset=["pnl"]) if "pnl" in taken else taken.iloc[0:0]
    return {
        "start": curve["session_date"].iloc[0],
        "end": curve["session_date"].iloc[-1],
        "final_equity": float(eq[-1]),
        "cagr_pct": cagr * 100,
        "max_dd_pct": max_dd * 100,
        "mar": cagr / max_dd if max_dd > 0 else np.nan,
        "sharpe": sharpe,
        "avg_long_pct": float(curve["long_pct"].mean()),
        "avg_positions": float(curve["positions"].mean()),
        "trades": int(len(taken)),
        "trades_per_year": len(taken) / years if years else np.nan,
        "win_pct": float((done["pnl"] > 0).mean() * 100) if len(done) else np.nan,
    }


def yearly(curve: pd.DataFrame) -> pd.DataFrame:
    """Return and max drawdown per calendar year."""
    c = curve.assign(year=pd.to_datetime(curve["session_date"]).dt.year)
    rows = []
    prev = None
    for y, part in c.groupby("year"):
        eq = part["equity"].to_numpy()
        start = prev if prev is not None else eq[0]
        peak = np.maximum.accumulate(np.concatenate([[start], eq]))
        rows.append(
            {
                "year": y,
                "return_pct": (eq[-1] / start - 1) * 100,
                "max_dd_pct": float(((peak - np.concatenate([[start], eq])) / peak).max() * 100),
            }
        )
        prev = eq[-1]
    return pd.DataFrame(rows)
