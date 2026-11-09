"""Step 5 of the backtest module (docs/backlog/backtest.md §7): the account.

`simulate` takes one exit x stop variant's trades (from `engine.run`) for one setup group and
plays them through an account day by day:
- start equity 100,000; risk `risk_pct` of the equity at the prior close per trade;
- shares = risk $ / |entry - stop|, cut to the position cap (25 % of equity) and to what the
  gross cap (100 %, no margin) leaves; fewer than one share is no trade;
- P0: at most 3 open positions; P1: at most 8, and total open risk <= 2 % of equity, where a
  position counts zero risk once its partial has moved the stop to break-even. A signal that
  would break the open-risk budget is skipped, not shrunk;
- one position per ticker; when signals outnumber the free slots, the highest `rank_by`
  (perf63 on the signal day) goes first;
- circuit breaker: after `losses_in_row` losing trades in a row, risk is halved until a trade
  closes at >= `reset_win_r` R;
- costs in dollars: slippage per side on the notional, commission max($1, 0.08 % x notional)
  per side, also on the partial.

Each day: exits and partials of positions opened earlier, then new entries (ranked), then
same-day exits of those new entries (B0's `fail_sold`), then the mark at the close. Shorts are
negative shares: equity = cash + sum(shares x close).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from trading_os.backtest.config import BacktestConfig, SizingConfig

NEEDED = [
    "setup",
    "ticker",
    "side",
    "entry_date",
    "entry",
    "stop",
    "exit_date",
    "partial_date",
    "partial_frac",
    "partial_price",
    "rest_price",
    "r",
]


@dataclass
class Position:
    i: int  # row in the trades frame
    ticker: str
    shares: float  # signed: negative for shorts
    per_share_risk: float
    at_be: bool = False
    cash_flow: float = 0.0  # every dollar in or out for this trade, costs included


@dataclass
class Breaker:
    enabled: bool
    n: int
    factor: float
    reset_r: float
    losses: int = 0
    active: bool = False
    log: list = field(default_factory=list)

    def close(self, r: float) -> None:
        if not self.enabled:
            return
        if r >= self.reset_r:
            self.losses, self.active = 0, False
        elif r < 0:
            self.losses += 1
            if self.losses >= self.n:
                self.active = True
        else:
            self.losses = 0

    @property
    def mult(self) -> float:
        return self.factor if self.active else 1.0


def attach_rank(trades: pd.DataFrame, ind: dict, name: str) -> pd.DataFrame:
    """The ranking value (e.g. perf63) on each trade's signal day."""
    frame = ind[name]
    rows = frame.index.get_indexer(trades["signal_date"])
    cols = frame.columns.get_indexer(trades["ticker"])
    vals = frame.to_numpy(dtype="float64")[rows, cols]
    return trades.assign(rank_value=np.where((rows >= 0) & (cols >= 0), vals, np.nan))


def simulate(
    trades: pd.DataFrame, close: pd.DataFrame, cfg: BacktestConfig, sizing: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily equity and the trades taken (shares, dollars) for one variant and one group."""
    pc, eng = cfg.portfolio, cfg.engine
    sz: SizingConfig = pc.sizing[sizing]
    slip, comm, comm_min = eng.slippage_pct / 100, eng.commission_pct / 100, eng.commission_min_usd
    t = trades.reset_index(drop=True)
    if "rank_value" not in t:
        t = t.assign(rank_value=np.nan)
    dates = close.index
    marks = close.ffill().to_numpy(dtype="float64")
    col_of = {c: j for j, c in enumerate(close.columns)}
    by_entry = {
        d: g.sort_values("rank_value", ascending=False, na_position="last").index.tolist()
        for d, g in t.groupby("entry_date")
    }
    part_on = {
        d: set(g.index) for d, g in t.dropna(subset=["partial_date"]).groupby("partial_date")
    }
    exit_on = {d: set(g.index) for d, g in t.groupby("exit_date")}
    cash = pc.start_equity
    equity_prev = pc.start_equity
    open_pos: dict[int, Position] = {}
    brk = Breaker(
        pc.circuit_breaker.enabled,
        pc.circuit_breaker.losses_in_row,
        pc.circuit_breaker.risk_factor,
        pc.circuit_breaker.reset_win_r,
    )
    taken, curve = [], []
    taken_at: dict[int, int] = {}  # trades-frame row -> its entry in `taken`

    def cost(notional: float) -> float:
        return notional * slip + max(comm_min, notional * comm)

    def trade_out(p: Position, frac: float, price: float) -> float:
        n = abs(p.shares) * frac
        notional = n * price
        side = 1 if p.shares > 0 else -1
        flow = side * notional - cost(notional)
        p.shares -= side * n
        p.cash_flow += flow
        return flow

    def close_out(i: int) -> None:
        nonlocal cash
        p = open_pos.pop(i)
        cash += trade_out(p, 1.0, float(t.at[i, "rest_price"]))
        brk.close(float(t.at[i, "r"]))
        taken[taken_at[i]]["pnl"] = p.cash_flow

    for k, d in enumerate(dates):
        # 1. partials and exits of positions opened before today
        for i in sorted(part_on.get(d, set()) & open_pos.keys()):
            p = open_pos[i]
            cash += trade_out(p, float(t.at[i, "partial_frac"]), float(t.at[i, "partial_price"]))
            p.at_be = True
        for i in sorted(exit_on.get(d, set()) & open_pos.keys()):
            close_out(i)
        # 2. new entries, best rank first
        gross_now = sum(
            abs(p.shares) * marks[max(k - 1, 0), col_of[p.ticker]] for p in open_pos.values()
        )
        risk_now = sum(
            0.0 if p.at_be else abs(p.shares) * p.per_share_risk for p in open_pos.values()
        )
        held = {p.ticker for p in open_pos.values()}
        new = []
        for i in by_entry.get(d, []):
            if len(open_pos) >= sz.max_positions:
                break
            row = t.loc[i]
            if row["ticker"] in held or row["ticker"] not in col_of:
                continue
            psr = abs(float(row["entry"]) - float(row["stop"]))
            risk_usd = equity_prev * pc.risk_pct / 100 * brk.mult
            shares = np.floor(risk_usd / psr)
            px = float(row["entry"])
            shares = min(shares, np.floor(equity_prev * pc.position_cap_pct / 100 / px))
            room = equity_prev * pc.gross_max_pct / 100 - gross_now
            shares = min(shares, np.floor(max(room, 0) / px))
            if shares < 1:
                continue
            if sz.open_risk_max_pct is not None and (
                risk_now + shares * psr > equity_prev * sz.open_risk_max_pct / 100 + 1e-9
            ):
                continue
            side = int(row["side"])
            notional = shares * px
            flow = -side * notional - cost(notional)
            cash += flow
            p = Position(i, row["ticker"], side * shares, psr, cash_flow=flow)
            open_pos[i] = p
            held.add(row["ticker"])
            gross_now += notional
            risk_now += shares * psr
            taken_at[i] = len(taken)
            taken.append(
                {
                    "i": i,
                    "shares": shares,
                    "notional": notional,
                    "risk_usd": shares * psr,
                    "risk_mult": brk.mult,
                    "pnl": np.nan,
                }
            )
            new.append(i)
        # 3. same-day exits of today's entries
        for i in new:
            if t.at[i, "exit_date"] == d:
                close_out(i)
        # 4. mark at the close
        value = sum(p.shares * marks[k, col_of[p.ticker]] for p in open_pos.values())
        gross = sum(abs(p.shares) * marks[k, col_of[p.ticker]] for p in open_pos.values())
        equity = cash + value
        curve.append(
            {
                "date": d,
                "equity": equity,
                "gross_pct": gross / equity * 100 if equity else np.nan,
                "open_positions": len(open_pos),
                "open_risk_pct": sum(
                    0.0 if p.at_be else abs(p.shares) * p.per_share_risk for p in open_pos.values()
                )
                / equity
                * 100
                if equity
                else np.nan,
                "breaker": brk.active,
            }
        )
        equity_prev = equity
    eq = pd.DataFrame(curve).set_index("date")
    tk = pd.DataFrame(taken)
    if len(tk):
        tk = t.loc[tk["i"]].reset_index(drop=True).join(tk.drop(columns="i"))
    return eq, tk


def groups(cfg: BacktestConfig, setups_present) -> dict[str, tuple[str, ...]]:
    """Each setup on its own, plus the configured long groups."""
    out = {s: (s,) for s in sorted(setups_present)}
    out.update(cfg.portfolio.groups)
    return out
