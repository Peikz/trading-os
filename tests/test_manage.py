"""Position manager: each open position's plan, the day's exits, 20-day MA closes, earnings,
R and risk (synthetic data only)."""

import datetime as dt

import pandas as pd

from trading_os import manage
from trading_os.config import load_config

A, B, C, D = (
    "".join(["S", "R", "F"]), "".join(["K", "L", "M"]), "".join(["Q", "X", "Z"]),
    "".join(["W", "V", "Y"]),
)  # fmt: skip
DAYS = list(pd.bdate_range("2026-09-01", periods=60).date)


def positions():
    return pd.DataFrame(
        [
            # EP 10:30, entered 21 sessions before DAYS[30]: today is its exit day
            {"ticker": A, "direction": "long", "entry_date": DAYS[9], "entry_avg": 10.0,
             "order_stop": 9.0, "open_quantity": 100, "setup": "ep_am"},
            # MA-surf that closed under its 20-day MA
            {"ticker": B, "direction": "long", "entry_date": DAYS[25], "entry_avg": 20.0,
             "order_stop": 19.0, "open_quantity": 50, "setup": "ma_surf"},
            # parabolic short that closed over its 20-day MA
            {"ticker": C, "direction": "short", "entry_date": DAYS[28], "entry_avg": 5.0,
             "order_stop": 5.5, "open_quantity": 200, "setup": "parabolic_short"},
            # a stock with earnings tomorrow and no known plan
            {"ticker": D, "direction": "long", "entry_date": DAYS[29], "entry_avg": 8.0,
             "order_stop": 7.6, "open_quantity": 100, "setup": None},
        ]
    )  # fmt: skip


def market():
    return pd.DataFrame(
        {
            "ticker": [A, B, C, D],
            "close": [12.0, 19.5, 5.2, 8.2],
            "ma20": [11.0, 19.8, 5.1, 8.0],
            "earnings_date_next": [None, None, None, pd.Timestamp(DAYS[31])],
        }
    )


def test_the_morning_names_the_exit_day_and_earnings():
    grading = load_config().grading
    table = manage.review(positions(), market(), DAYS[30], DAYS, grading, "pm").set_index("ticker")
    assert table.loc[A, "held"] == 21 and table.loc[A, "hold"] == 21
    assert table.loc[A, "action"] == "day 21/21: the plan sells at today's close"
    assert table.loc[A, "r_now"] == 2.0 and table.loc[A, "risk_to_stop"] == 300.0
    assert table.loc[B, "action"] == ""  # MA closes are an evening check
    assert table.loc[D, "earnings"] == DAYS[31] and pd.isna(table.loc[D, "rule"])
    assert round(table.loc[C, "r_now"], 6) == -0.4  # a short: up is a loss


def test_the_evening_names_tomorrows_exit_and_ma_closes():
    grading = load_config().grading
    table = manage.review(positions(), market(), DAYS[29], DAYS, grading, "eod").set_index("ticker")
    assert table.loc[A, "action"] == "day 20/21: the plan sells at tomorrow's close"
    assert table.loc[B, "action"] == "closed under the 20-day MA: the plan's exit"
    assert table.loc[C, "action"] == "closed over the 20-day MA: the plan covers"


def test_push_lines_put_actions_first():
    grading = load_config().grading
    table = manage.review(positions(), market(), DAYS[30], DAYS, grading, "pm")
    lines = manage.push_lines(table)
    assert lines[0].startswith("💼 4 open · ")
    assert lines[1] == f"▸ {A} +2.0R · 🔔 day 21/21: the plan sells at today's close"
    assert any(line.startswith(f"▸ {D}") and "📢 earnings" in line for line in lines)
    empty = manage.review(pd.DataFrame(), market(), DAYS[30], DAYS, grading, "pm")
    assert manage.push_lines(empty) == []


def test_unknown_setups_have_no_plan():
    assert manage.plan("tight_bases", {}) == (None, None)
    assert manage.plan("luk_flush", load_config().grading) == (manage.HOLD, 21)
    assert isinstance(dt.date.today(), dt.date)
