"""Position sizing, hand-computed: 500,000 DKK, 0.5 % risk, USD/DKK 6.667."""

import pandas as pd
import pytest

from trading_os import sizing
from trading_os.config import load_config

ACCOUNT = sizing.Account(currency="DKK", size=500_000, risk_pct=0.5, max_position_pct=100)
RATE = 6.667  # DKK per USD
RISK_USD = 2_500 / RATE  # 374.98


@pytest.fixture(scope="module")
def rules():
    return load_config().sizing


def test_risk_budget_in_usd():
    assert ACCOUNT.risk_usd(RATE) == pytest.approx(374.98, abs=0.01)
    assert ACCOUNT.size_usd(RATE) == pytest.approx(74_996.25, abs=0.01)


def test_ep_day_stop_at_day_low(rules):
    row = {"close": 10.0, "low": 9.5, "adr20_usd": 0.8}
    entry, stop, basis = sizing.plan(row, "ep_day", rules)
    assert (entry, stop, basis) == (10.0, 9.5, "day low")
    sized = sizing.size(entry, stop, RISK_USD, ACCOUNT.size_usd(RATE), 100)
    # 374.98 / 0.50 = 749 shares; position 7,490; risk 374.50
    assert sized["plan_shares"] == 749
    assert sized["plan_position_usd"] == pytest.approx(7_490)
    assert sized["plan_risk_usd"] == pytest.approx(374.5)


def test_ep_day_stop_capped_at_one_adr(rules):
    # Day low 8.00 is 2.5 ADR away: stop moves up to 10 − 0.8 = 9.20.
    entry, stop, basis = sizing.plan({"close": 10.0, "low": 8.0, "adr20_usd": 0.8}, "ep_day", rules)
    assert stop == pytest.approx(9.2) and basis == "1 ADR"


def test_premarket_and_breakout_rules(rules):
    pm = sizing.plan({"pm_price": 20.0, "adr20_usd": 1.0}, "ep_pm", rules)
    assert pm[:2] == (20.0, 19.0) and pm[2].startswith("1 ADR")
    bo = sizing.plan({"close": 15.6, "order_stop": 14.88}, "breakout_trigger", rules)
    assert bo == (15.6, 14.88, "order stop")
    watch = sizing.plan({"pivot": 15.12, "order_stop": 14.88}, "breakout_watch", rules)
    assert watch[:2] == (15.12, 14.88)
    assert sizing.plan({"close": 1.0}, "mb_up", rules)[2] == ""


def test_after_hours_entry_is_the_post_market_price(rules):
    ah = sizing.plan({"ah_price": 22.0, "close": 20.0, "adr20_usd": 1.0}, "ep_ah", rules)
    assert ah[:2] == (22.0, 21.0)
    no_price = {"ah_price": float("nan"), "close": 20.0, "ah_change_pct": 10.0, "adr20_usd": 1.0}
    assert sizing.plan(no_price, "ep_ah", rules)[0] == pytest.approx(22.0)


def test_position_cap_and_bad_stops():
    # A 1-cent stop on a $5 stock would mean 37,498 shares ($187k): capped at the account.
    sized = sizing.size(5.0, 4.99, RISK_USD, ACCOUNT.size_usd(RATE), 100)
    assert sized["plan_capped"] and sized["plan_shares"] == 14_999  # 74,996 / 5
    assert sizing.size(10.0, 10.0, RISK_USD, 75_000, 100) is None  # no risk per share
    assert sizing.size(float("nan"), 9.0, RISK_USD, 75_000, 100) is None


def test_add_plans_and_plan_line(rules):
    hits = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "close": [10.0, 12.0],
            "low": [9.5, 11.0],
            "adr20_usd": [0.8, 0.5],
        }
    )
    out = sizing.add_plans({"ep_day": hits, "mb_up": hits}, rules, ACCOUNT, RATE)
    assert "plan_shares" not in out["mb_up"]
    row = out["ep_day"].iloc[0].to_dict()
    assert (
        sizing.plan_line(row) == "   buy 10.00 · stop 9.50 (day low) · 749 sh · $7.5k · risk $374"
    )
    assert sizing.plan_line({"plan_shares": None}) is None


def test_load_account_from_private_settings(tmp_path):
    assert sizing.load_account(tmp_path) is None
    path = sizing.account_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("currency: dkk\nsize: 500000\nrisk_pct: 0.5\n", encoding="utf-8")
    account = sizing.load_account(tmp_path)
    assert account == sizing.Account("DKK", 500_000.0, 0.5, 100.0)


def test_ep_close_at_the_low_keeps_a_minimum_stop(rules):
    # Closed 1 cent above the day low; ADR 0.40 -> stop at least 0.10 below entry.
    entry, stop, basis = sizing.plan(
        {"close": 3.43, "low": 3.42, "adr20_usd": 0.40}, "ep_day", rules
    )
    assert stop == pytest.approx(3.33) and basis == "0.25 ADR min"
