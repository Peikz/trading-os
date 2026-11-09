"""Step 4 of the backtest module (docs/backlog/backtest.md §4, §6): play every signal through
every exit variant (E0-E3) and stop variant (K0, K1) on daily bars.

Day 0 is the fill day. Close-fill setups enter at the signal day's close (or the next open when
`engine.fill` is `next_open`); B0 fills intraday at its buy stop and, if its close check fails,
exits at that close (`fail_sold`). From day 1 on, each session is checked in this order:
1. open at or through the stop -> out at the open (`gap_stop`);
2. low at or through the stop -> out at the stop (`stop`, or `breakeven` once the stop sits at
   the entry);
3. at the close: a close through the trail MA -> out at the close (`trail`); otherwise the
   partial (E0: a third on day 3-5 if the close beats the entry; E1/E3: 15 % at the first close
   >= +3R), after which the stop moves to the entry;
4. `max_hold_days` reached -> out at the close (`time`); data ends or the stock delists -> out at
   its last close (`end`).
K1 raises the stop to the entry-day low (the high for shorts) from day 1 when that is tighter.
Shorts run the same code on mirrored prices. `r_no_partial` replays the trade with no partial
(so no break-even move) and the same trail and stop variant.

R = (exit - entry) x side / (entry - initial stop) x side, weighted over the partial and the
rest. Costs: (slippage + commission) per side, both sides, as a share of the entry price,
turned into R. The $1 commission minimum needs a position size and comes in the portfolio step.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trading_os.backtest.config import BacktestConfig, EngineConfig, ExitConfig

STOP_EXITS = {"stop", "gap_stop", "breakeven"}


@dataclass
class Played:
    exit_k: int
    exit_price: float  # weighted over the partial and the rest
    reason: str
    r_gross: float
    partial_k: int | None


def play(
    o: np.ndarray,
    h: np.ndarray,
    low: np.ndarray,
    c: np.ndarray,
    trail: np.ndarray,
    f: int,
    entry: float,
    stop0: float,
    ex: ExitConfig,
    raise_stop: bool,
    max_hold: int,
    partial: bool = True,
    fail_at_close: bool = False,
) -> Played:
    """One long trade on one ticker's arrays (shorts pass mirrored arrays). `f` is the fill
    day's index; the entry happened during day f."""
    risk = entry - stop0
    stop = stop0
    at_be = False
    sold, banked = 0.0, 0.0  # fraction sold in the partial, and its exit price x fraction
    pk = None

    def done(k: int, px: float, why: str) -> Played:
        rest = 1.0 - sold
        avg = banked + rest * px
        return Played(k, avg, why, (avg - entry) / risk, pk)

    if fail_at_close:
        return done(f, c[f], "fail_sold")
    if raise_stop and low[f] > stop:
        stop = low[f]
    n = len(c)
    last = f
    for d in range(1, max_hold + 1):
        k = f + d
        if k >= n or np.isnan(c[k]):
            return done(last, c[last], "end")
        last = k
        if o[k] <= stop:
            return done(k, o[k], "gap_stop")
        if low[k] <= stop:
            return done(k, stop, "breakeven" if at_be else "stop")
        if c[k] < trail[k]:
            return done(k, c[k], "trail")
        if partial and pk is None and ex.partial != "none":
            hit = (
                ex.partial_day_min <= d <= ex.partial_day_max and c[k] > entry
                if ex.partial == "day"
                else c[k] >= entry + ex.partial_r * risk
            )
            if hit:
                sold, banked, pk = ex.partial_frac, ex.partial_frac * c[k], k
                if stop < entry:
                    stop, at_be = entry, True
        if d == max_hold:
            return done(k, c[k], "time")
    return done(last, c[last], "end")


def _shakeout(c: np.ndarray, k: int, entry: float, days: int) -> bool:
    nxt = c[k + 1 : k + 1 + days]
    return bool(np.any(nxt[~np.isnan(nxt)] > entry))


def run(
    sig: pd.DataFrame, w: dict, ind: dict, cfg: BacktestConfig, exits=None, stops=None
) -> pd.DataFrame:
    """Every unskipped signal x exit variant x stop variant, one row each."""
    eng: EngineConfig = cfg.engine
    exits = exits or list(eng.exits)
    stops = stops or list(eng.stops)
    dates = w["close"].index
    row_of = {d: i for i, d in enumerate(dates)}
    col_of = {t: j for j, t in enumerate(w["close"].columns)}
    arr = {k: w[k].to_numpy(dtype="float64") for k in ("open", "high", "low", "close")}
    trails = {ex.trail: ind[ex.trail].to_numpy(dtype="float64") for ex in eng.exits.values()}
    regime = ind.get("regime")
    breadth = ind["breadth"]["tag"] if "breadth" in ind else None
    cost_frac = 2 * (eng.slippage_pct + eng.commission_pct) / 100
    rows = []
    for s in sig[~sig["skip"].astype(bool)].itertuples(index=False):
        t, j, side = row_of[s.session_date], col_of[s.ticker], int(s.side)
        o, h, low, c = (arr[k][:, j] for k in ("open", "high", "low", "close"))
        b0 = s.setup == "B0"
        f, entry = t, float(s.entry)
        if not b0 and eng.fill == "next_open":
            f = t + 1
            if f >= len(dates) or np.isnan(o[f]):
                continue
            entry = float(o[f])
        stop0 = float(s.stop)
        if (entry - stop0) * side <= 0:
            continue  # a next-open fill at or through the stop: no trade
        if side == 1:
            mo, mh, ml, mc, m_entry, m_stop = o, h, low, c, entry, stop0
        else:  # mirror: a short is a long on negated prices, high and low swapped
            mo, mh, ml, mc, m_entry, m_stop = -o, -low, -h, -c, -entry, -stop0
        fail = b0 and not bool(s.close_ok)
        # a next-open fill can be stopped the same day: the open came first
        fail_day_stop = bool(not b0 and eng.fill == "next_open" and ml[f] <= m_stop)
        risk_frac = abs(entry - stop0) / entry
        cost_r = cost_frac / risk_frac
        for ename in exits:
            ex = eng.exits[ename]
            tr = trails[ex.trail][:, j] * side
            for kv in stops:
                kw = dict(
                    f=f,
                    entry=m_entry,
                    stop0=m_stop,
                    ex=ex,
                    raise_stop=kv == "K1",
                    max_hold=eng.max_hold_days,
                    fail_at_close=fail,
                )
                if fail_day_stop:
                    p = Played(f, m_stop, "stop", -1.0, None)
                    q = p
                else:
                    p = play(mo, mh, ml, mc, tr, **kw)
                    q = play(mo, mh, ml, mc, tr, partial=False, **kw)
                px = p.exit_price * side
                rows.append(
                    {
                        "setup": s.setup,
                        "ticker": s.ticker,
                        "signal_date": s.session_date,
                        "side": side,
                        "exit_variant": ename,
                        "stop_variant": kv,
                        "entry_date": dates[f],
                        "entry": entry,
                        "stop": stop0,
                        "risk_pct": risk_frac * 100,
                        "exit_date": dates[p.exit_k],
                        "exit_price": px,
                        "hold_days": p.exit_k - f,
                        "exit_reason": p.reason,
                        "partial_date": dates[p.partial_k] if p.partial_k is not None else None,
                        "r_gross": p.r_gross,
                        "cost_r": cost_r,
                        "r": p.r_gross - cost_r,
                        "r_no_partial": q.r_gross - cost_r,
                        "day1_stop": p.reason in STOP_EXITS and p.exit_k - f == 1,
                        "shakeout": p.reason in STOP_EXITS
                        and _shakeout(mc, p.exit_k, m_entry, eng.shakeout_days),
                        "regime": regime.iloc[t] if regime is not None else None,
                        "breadth": breadth.iloc[t] if breadth is not None else None,
                    }
                )
    return pd.DataFrame(rows)
