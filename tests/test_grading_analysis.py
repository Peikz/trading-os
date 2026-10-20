"""Grading analysis and portfolio simulation on hand-computed examples (synthetic data)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import grading_analysis as ga
from trading_os import portfolio_sim as ps

A, B = "".join(["A", "A", "Q"]), "".join(["B", "B", "Q"])


def test_slippage_by_liquidity_with_a_one_cent_floor():
    out = ga.slippage_pct(np.array([60e6, 20e6, 5e6, 1e6, 60e6]), np.array([50, 50, 50, 50, 2.0]))
    assert out.tolist() == pytest.approx([0.05, 0.10, 0.25, 0.50, 0.50])  # 1 cent of $2 = 0.5 %


def test_costs_in_r_grow_as_the_stop_tightens():
    df = pd.DataFrame(
        {
            "price": [50.0, 50.0],
            "stop": [49.0, 45.0],  # 2 % and 10 % stops
            "entry": ["t_1030", "t_1030"],
            "adr_usd": [2.0, 2.0],
            "prev_close": [50.0, 50.0],
            "d_dvol20": [60e6, 60e6],
        }
    )
    out = ga.add_costs(df)
    # 2 x 0.08 commission + 0.05 entry + (0.05 + 0.05 x 4 % ADR) exit = 0.46 %
    assert out["cost_pct"].tolist() == pytest.approx([0.46, 0.46])
    assert out["cost_r"].tolist() == pytest.approx([0.23, 0.046])


def test_scorecard_finds_a_planted_bucket_and_walk_forward_uses_the_past_only():
    rng = np.random.default_rng(0)
    n = 6000
    df = pd.DataFrame({"x": rng.uniform(0, 1, n), "noise": rng.normal(size=n)})
    df["year"] = np.repeat([2016, 2017, 2018, 2019, 2020, 2021], n // 6)
    y = np.where(df["x"] > 0.8, 1.0, -0.2) + rng.normal(0, 0.5, n)
    target = pd.Series(y, index=df.index)
    card = ga.fit_scorecard(df, target, ["x", "noise"])
    pred = card.predict(df)
    assert pred[df["x"] > 0.85].mean() > pred[df["x"] < 0.5].mean() + 0.8
    oos = ga.walk_forward_scores(df, target, ["x", "noise"], first_test=2019)
    assert oos[df["year"] < 2019].isna().all() and oos[df["year"] >= 2019].notna().all()
    # Change the future: the 2019 scores don't move.
    later = target.copy()
    later[df["year"] >= 2020] = 5.0
    oos2 = ga.walk_forward_scores(df, later, ["x", "noise"], first_test=2019)
    assert np.allclose(oos[df["year"] == 2019], oos2[df["year"] == 2019])


def test_grades_follow_the_cutoffs():
    pred = pd.Series([0.6, 0.35, 0.15, -0.2, np.nan])
    out = ga.grade(pred, {"A+": 0.5, "A": 0.3, "B": 0.1})
    assert out.tolist() == ["A+", "A", "B", "C", None]


def test_walk_forward_plan_choice_scores_the_next_year():
    rows = []
    for year in (2016, 2017, 2018, 2019):
        for k in range(200):
            rows.append(
                {
                    "strategy": "s",
                    "entry": "e",
                    "stop_rule": "lod",
                    "year": year,
                    "r_hold_1d": 1.0,
                    "r_hold_5d": 0.5 if year < 2019 else -1.0,
                    "cost_r": 0.0,
                }
            )
    out = ga.walk_forward_plans(pd.DataFrame(rows), first_test=2018)
    last = out[out["year"] == 2019].iloc[0]
    assert last["exit"] == "hold_1d" and last["test_r"] == pytest.approx(1.0)


def sessions(n):
    return [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(n)]


def trade(**kw):
    base = {
        "trade_id": 1,
        "session_date": sessions(1)[0],
        "ticker": A,
        "side": 1,
        "entry_minute": 600,
        "price": 10.0,
        "stop": 9.0,
        "grade": "A",
        "priority": 0.5,
        "frac_1": 1.0,
        "days_1": 2,
        "r_1": 2.0,
        "cost_pct": 0.0,
        "d_dvol20": 1e9,
        "strategy": "s",
    }
    return base | kw


def run(trades, closes, **rules):
    days = sessions(len(closes))
    arr = np.array(closes, dtype=float)
    arr = arr[:, None] if arr.ndim == 1 else arr
    tickers = [A, B][: arr.shape[1]]
    r = ps.Rules(risk_pct={"A+": 1.0, "A": 1.0, "B": 0.5}, start_equity=100_000.0, **rules)
    return ps.simulate(pd.DataFrame(trades), arr, days, tickers, r)


def test_a_long_is_sized_from_its_risk_and_marked_to_the_close():
    curve, taken = run([trade()], [10, 11, 12, 12])
    # 1 % of 100k = 1,000 risk on a 1.00 stop: 1,000 shares, 10,000 position.
    assert taken["value"].iloc[0] == pytest.approx(10_000)
    assert curve["equity"].tolist()[:3] == pytest.approx([100_000, 101_000, 102_000])
    assert taken["pnl"].iloc[0] == pytest.approx(2_000) and taken["r_realized"].iloc[0] == 2


def test_caps_and_two_legs():
    t = trade(frac_1=1 / 3, days_1=1, r_1=1.0, frac_2=2 / 3, days_2=2, r_2=2.0)
    _, taken = run([t], [10, 11, 12, 12], max_position_pct=5.0)
    assert taken["value"].iloc[0] == pytest.approx(5_000)  # capped at 5 % of equity
    assert taken["pnl"].iloc[0] == pytest.approx(500 * (1 / 3 * 1 + 2 / 3 * 2))


def test_a_short_profits_when_it_falls_and_held_names_are_skipped():
    short = trade(side=-1, stop=11.0, r_1=1.0, days_1=1)
    again = trade(trade_id=2, entry_minute=700)
    curve, taken = run([short, again], [10, 9, 9, 9])
    assert len(taken) == 1 and taken["pnl"].iloc[0] == pytest.approx(1_000)
    assert curve["equity"].iloc[-1] == pytest.approx(101_000)


def test_drawdown_cuts_the_risk():
    loser = trade(r_1=-1.0, days_1=0, stop=9.0)  # -1R the same day: equity 99,000
    later = trade(trade_id=2, session_date=sessions(3)[2], r_1=0.0, days_1=1)
    _, taken = run([loser, later], [10, 10, 10, 10], dd_steps=((0.5, 0.5),))
    assert taken["risk_usd"].tolist() == pytest.approx([1_000, 495])
