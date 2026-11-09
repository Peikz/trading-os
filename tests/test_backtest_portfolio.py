"""Backtest step 5: the account simulation, on hand-made trades."""

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os.backtest import portfolio as pf
from trading_os.backtest.config import load_config

BASE = load_config()
DAYS = [dt.date(2022, 1, 3) + dt.timedelta(days=i) for i in range(10)]


def cfg(risk=0.25, breaker=False, costs=False, **pc):
    eng = (
        BASE.engine
        if costs
        else dataclasses.replace(
            BASE.engine, slippage_pct=0.0, commission_pct=0.0, commission_min_usd=0.0
        )
    )
    cb = dataclasses.replace(BASE.portfolio.circuit_breaker, enabled=breaker)
    port = dataclasses.replace(BASE.portfolio, risk_pct=risk, circuit_breaker=cb, **pc)
    return dataclasses.replace(BASE, engine=eng, portfolio=port)


def closes(**series):
    return pd.DataFrame({k: np.asarray(v, float) for k, v in series.items()}, index=DAYS)


def trade(
    ticker,
    entry_day,
    exit_day,
    entry=10.0,
    stop=9.0,
    rest=10.0,
    r=0.0,
    side=1,
    rank=0.0,
    partial_day=None,
    partial_frac=0.0,
    partial_price=np.nan,
    setup="L2",
):
    return {
        "setup": setup,
        "ticker": ticker,
        "side": side,
        "signal_date": DAYS[entry_day],
        "entry_date": DAYS[entry_day],
        "entry": entry,
        "stop": stop,
        "exit_date": DAYS[exit_day],
        "rest_price": rest,
        "r": r,
        "rank_value": rank,
        "partial_date": DAYS[partial_day] if partial_day is not None else None,
        "partial_frac": partial_frac,
        "partial_price": partial_price,
    }


def test_risk_sizing_and_dollar_pnl():
    c = closes(AAA=[10, 11, 12, 12, 12, 12, 12, 12, 12, 12])
    t = pd.DataFrame([trade("AAA", 0, 2, rest=12.0, r=2.0)])
    eq, tk = pf.simulate(t, c, cfg(), "P0")
    assert tk["shares"].iloc[0] == 250  # 0.25 % of 100,000 / 1.00 risk a share
    assert tk["pnl"].iloc[0] == pytest.approx(500)
    assert eq["equity"].iloc[1] == pytest.approx(100_250)  # marked at 11
    assert eq["equity"].iloc[-1] == pytest.approx(100_500)
    assert eq["open_positions"].iloc[-1] == 0


def test_position_cap_and_gross_cap():
    c = closes(**{t: [10] * 10 for t in "ABCDE"})
    rows = [trade(x, 0, 5, stop=9.99) for x in "ABCDE"]  # tiny stops want huge positions
    eq, tk = pf.simulate(pd.DataFrame(rows), c, cfg(), "P1")
    assert (tk["notional"] <= 25_000 + 1e-6).all()  # 25 % position cap
    assert tk["notional"].sum() <= 100_000 + 1e-6  # no margin
    assert len(tk) == 4  # the fifth finds no room
    assert eq["gross_pct"].iloc[0] == pytest.approx(100)


def test_p0_takes_the_best_ranked_three():
    c = closes(**{t: [10] * 10 for t in "ABCD"})
    rows = [trade(x, 0, 5, rank=rk) for x, rk in zip("ABCD", [5, 40, 20, 30], strict=True)]
    _, tk = pf.simulate(pd.DataFrame(rows), c, cfg(), "P0")
    assert sorted(tk["ticker"]) == ["B", "C", "D"]


def test_p1_open_risk_budget_and_break_even_frees_it():
    c = closes(**{t: [10] * 10 for t in "ABCDEF"})
    rows = [trade(x, 0, 8) for x in "ABCD"]  # 0.5 % each fills the 2 % budget
    rows.append(trade("E", 1, 8))  # no budget left on day 1
    rows[0].update(partial_date=DAYS[2], partial_frac=0.15, partial_price=10.0)
    rows.append(trade("F", 3, 8))  # A at break-even frees 0.5 %
    _, tk = pf.simulate(pd.DataFrame(rows), c, cfg(risk=0.5), "P1")
    assert sorted(tk["ticker"]) == ["A", "B", "C", "D", "F"]


def test_one_position_per_ticker():
    c = closes(A=[10] * 10)
    rows = [trade("A", 0, 5), trade("A", 2, 6)]
    _, tk = pf.simulate(pd.DataFrame(rows), c, cfg(), "P1")
    assert len(tk) == 1


def test_circuit_breaker_halves_risk_until_a_2r_win():
    c = closes(**{f"T{i}": [10] * 10 for i in range(8)})
    rows = [trade(f"T{i}", i, i, rest=9.0, r=-1.0) for i in range(5)]  # five losers in a row
    rows.append(trade("T5", 5, 5, rest=12.0, r=2.0))  # halved, then resets
    rows.append(trade("T6", 6, 7))
    _, tk = pf.simulate(pd.DataFrame(rows), c, cfg(breaker=True), "P0")
    assert tk["risk_mult"].tolist() == [1, 1, 1, 1, 1, 0.5, 1]
    _, off = pf.simulate(pd.DataFrame(rows), c, cfg(breaker=False), "P0")
    assert set(off["risk_mult"]) == {1.0}


def test_short_accounting():
    c = closes(S=[20, 19, 18, 18, 18, 18, 18, 18, 18, 18])
    t = pd.DataFrame([trade("S", 0, 2, entry=20.0, stop=21.0, rest=18.0, r=2.0, side=-1)])
    eq, tk = pf.simulate(t, c, cfg(), "P0")
    assert tk["shares"].iloc[0] == 250
    assert eq["equity"].iloc[1] == pytest.approx(100_250)  # short marked at 19
    assert tk["pnl"].iloc[0] == pytest.approx(500)


def test_partial_and_costs_in_dollars():
    c = closes(A=[10, 13, 13, 13, 13, 13, 13, 13, 13, 13])
    t = pd.DataFrame(
        [trade("A", 0, 3, rest=12.0, r=2.1, partial_day=1, partial_frac=0.2, partial_price=13.0)]
    )
    _, tk = pf.simulate(t, c, cfg(costs=True), "P0")
    n = 250
    buy, part, rest = n * 10, 0.2 * n * 13, 0.8 * n * 12

    def cost(x):
        return x * 0.001 + max(1.0, x * 0.0008)

    expected = -buy - cost(buy) + part - cost(part) + rest - cost(rest)
    assert tk["pnl"].iloc[0] == pytest.approx(expected)


def test_same_day_fail_sold_exits_after_entry():
    c = closes(A=[10, 10, 10, 10, 10, 10, 10, 10, 10, 10])
    t = pd.DataFrame([trade("A", 1, 1, rest=9.8, r=-0.2, setup="B0")])
    eq, tk = pf.simulate(t, c, cfg(), "P0")
    assert tk["pnl"].iloc[0] == pytest.approx(-50)
    assert eq["open_positions"].max() == 0


def test_attach_rank_reads_the_signal_day():
    ind = {"perf63": pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]}, index=DAYS[:2])}
    t = pd.DataFrame({"signal_date": [DAYS[1], DAYS[0], DAYS[5]], "ticker": ["B", "A", "A"]})
    out = pf.attach_rank(t, ind, "perf63")
    assert out["rank_value"].tolist()[:2] == [4.0, 1.0]
    assert np.isnan(out["rank_value"].iloc[2])
