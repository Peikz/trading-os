"""MA-surf graded A with SPY over its 200-day, at 0.75 % risk (Emil, 23 Oct 2026). Its own
plan: buy-stop at the pivot, the scan's order stop, trail the 20-day MA. Synthetic data only."""

import copy

import pandas as pd
import pytest
import yaml

from trading_os import grade_live, notify
from trading_os.config import DEFAULT_PATH, ConfigError, load_config, parse_config
from trading_os.sizing import Account

A = "".join(["S", "R", "F"])


def hits():
    return pd.DataFrame(
        [
            {
                "ticker": A,
                "tier": "alert",
                "close": 20.0,
                "pivot": 20.4,
                "order_stop": 19.2,
                "adr20_usd": 0.8,
                "adr20_pct": 4.0,
                "avg_dollar_volume_20d": 3e7,
            }
        ]
    )


def graded(spy_above: float) -> pd.DataFrame:
    cfg = load_config()
    market = {"mkt_spy_above_ma200": spy_above}
    return grade_live.grade_hits(hits(), "ma_surf", cfg, market, pd.DataFrame(), slot="eod")


def test_a_with_spy_over_its_200_day_on_its_own_plan():
    row = graded(1.0).iloc[0]
    assert row["grade"] == "A" and row["grade_strategy"] == "qm_surf"
    assert row["grade_risk_mult"] == 1.5  # A: 1.5 x the account's 0.5 % = 0.75 %
    assert row["grade_entry"] == 20.4 and row["grade_stop"] == 19.2  # pivot, order stop
    assert row["grade_entry_rule"] == "pivot_1000" and row["grade_exit"] == "trail_ma20"
    assert row["grade_stop_basis"] == "order stop, buy-stop at pivot"
    assert pd.isna(row["grade_hold_sessions"])


def test_c_with_spy_under_it():
    row = graded(0.0).iloc[0]
    assert row["grade"] == "C" and row["grade_risk_mult"] == 0.0


def test_the_plan_is_sized_at_the_pivot_with_the_order_stop():
    account = Account(currency="USD", size=100_000, risk_pct=0.5, max_position_pct=20)
    row = grade_live.resize(graded(1.0), account, 1.0).iloc[0].to_dict()
    assert row["plan_entry"] == 20.4 and row["plan_stop"] == 19.2
    assert row["plan_shares"] == 625  # $750 risk / $1.20 a share
    assert notify.plan_lines(row)[0] == "Buy-stop 20.40 · 🛑 19.20 (order stop)"
    ticket = notify.saxo_line(row, "ma_surf")
    assert ticket == (
        "🎫 Saxo: Buy 625 · Stop if traded 20.40 from 10:00 · Day · stop loss 19.20 GTC"
    )


def test_the_push_names_the_point_the_entry_and_the_trail():
    row = graded(1.0).iloc[0].to_dict()
    text = " ".join(notify.grade_lines(row))
    assert "🅰 Study A · 1 of 1 quality points" in text
    assert "✅ SPY > 200-day" in text
    assert notify.ENTRY_TEXT["pivot_1000"] in text
    assert "trail the 20-day MA" in text and "sessions" not in text


def test_an_own_plan_rule_takes_only_the_order_stop_and_the_trail():
    with open(DEFAULT_PATH, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    bad = copy.deepcopy(raw)
    bad["grading"]["quality"]["qm_surf"]["exit"] = "hold_21d"
    with pytest.raises(ConfigError, match="qm_surf.exit"):
        parse_config(bad)
    bad = copy.deepcopy(raw)
    bad["grading"]["quality"]["qm_surf"]["hold_sessions"] = 21
    with pytest.raises(ConfigError, match="unknown keys"):
        parse_config(bad)
