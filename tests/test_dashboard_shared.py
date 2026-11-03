"""The dashboard logic both front ends share (`board_data`, `positions_view`, `journal_view`,
`my_watchlists.add_checked`), with hand-computed examples. Synthetic tickers only."""

import math

import pandas as pd
import pytest

from trading_os import board_data, journal_view, my_watchlists, positions_view
from trading_os.config import load_config

A, B = ("".join([x, "Q", "Z", x]) for x in "WX")


def test_alert_default_is_the_pivot_then_the_entry_then_the_stop():
    assert board_data.alert_default({"pivot": 12.0, "plan_entry": 10.0}) == 12.0
    assert board_data.alert_default({"pivot": math.nan, "plan_entry": 10.0}) == 10.0
    assert board_data.alert_default({"pivot": None, "plan_stop": 9.0}) == 9.0
    assert board_data.alert_default({"pivot": "x"}) == 0.0


def test_tradingview_list_qualifies_known_exchanges_only():
    out = board_data.tradingview_list([A, B, A], {A: "NASDAQ", B: math.nan})
    assert out == f"NASDAQ:{A},{B}"
    assert board_data.tradingview_url(A, "NYSE").endswith(f"symbol=NYSE%3A{A}")


def test_the_risk_multiple_comes_from_the_grade():
    cfg = load_config()
    assert board_data.risk_mult({"grade": "A+"}, cfg) == (2.0, True)
    assert board_data.risk_mult({"grade": "C"}, cfg) == (1.0, False)  # sized as a B
    assert board_data.risk_mult({"grade_risk_mult": 1.5, "grade": "C"}, cfg) == (1.5, True)


def test_a_position_card_by_hand():
    p = {"ticker": A, "direction": "long", "entry_avg": 10.0, "order_stop": 9.0,
         "open_quantity": 100, "last_close": 12.0, "setup": "ep_day"}  # fmt: skip
    info = {"rule": "hold", "held": 3, "hold": 21, "action": "", "earnings": None}
    c = positions_view.card(p, info, None)
    assert c["price"] == 12.0 and c["move_pct"] == pytest.approx(20.0)
    assert c["open_r"] == pytest.approx(2.0) and c["pnl"] == pytest.approx(200.0)
    assert c["to_stop_pct"] == pytest.approx(25.0)  # (12 - 9) / 12
    assert c["facts"] == ["Plan: sell at the close after 21 sessions · day 3 of 21"]
    live = positions_view.card(p, {}, 11.0)  # a live price wins over the close
    assert live["open_r"] == pytest.approx(1.0) and live["facts"] == []
    short = positions_view.card(p | {"direction": "short", "order_stop": 11.0}, {}, 8.0)
    assert short["open_r"] == pytest.approx(2.0) and short["pnl"] == pytest.approx(200.0)
    nostop = positions_view.card(p | {"order_stop": None}, {}, None)
    assert math.isnan(nostop["open_r"]) and math.isnan(nostop["to_stop_pct"])


def test_plan_facts_show_the_action_and_earnings():
    info = {"rule": "trail_ma20", "action": "closed under the 20-day MA: the plan's exit",
            "earnings": "2026-11-04"}  # fmt: skip
    assert positions_view.plan_facts(info) == [
        "Plan: trail the 20-day MA, out on a close under it",
        "⚠️ closed under the 20-day MA: the plan's exit",
        "📅 Earnings 2026-11-04",
    ]


def test_live_prices_need_both_keys():
    assert positions_view.live_prices([A], {}) == ({}, positions_view.CLOSE_SOURCE)
    assert positions_view.live_prices([A], {"ALPACA_API_KEY_ID": "x"})[0] == {}


def test_closed_stats_and_the_r_curve():
    trades = pd.DataFrame(
        {"pnl": [100.0, -50.0, 30.0], "r_multiple": [2.0, -1.0, None],
         "exit_date": ["2026-06-03", "2026-06-01", "2026-06-02"]}
    )  # fmt: skip
    stats = journal_view.closed_stats(trades)
    assert stats["trades"] == 3 and stats["win_rate"] == pytest.approx(200 / 3)
    assert stats["avg_r"] == pytest.approx(0.5) and stats["pnl"] == 80.0
    assert journal_view.r_curve(trades).tolist() == [-1.0, 1.0]  # by exit date
    assert journal_view.closed_stats(trades.iloc[0:0])["avg_r"] is None


def test_add_checked_reports_added_already_and_unknown(tmp_path):
    known = {A, B}.__contains__
    first = my_watchlists.add_checked(tmp_path, "Mine", [A, "QQQZQ"], known)
    assert first["kind"] == "warning" and first["added"] == [A]
    assert first["lines"] == [f"✅ Added to **Mine**: {A}", "❌ Not found, not added: QQQZQ"]
    second = my_watchlists.add_checked(tmp_path, "Mine", [A, B], known)
    assert second["kind"] == "success" and second["added"] == [B] and second["already"] == [A]
    assert my_watchlists.add_checked(tmp_path, "Mine", ["QQQZQ"], known)["kind"] == "error"
    assert my_watchlists.add_checked(tmp_path, "", [A], known)["lines"][0].startswith("Give")
    members = my_watchlists.current(my_watchlists.load(tmp_path))
    assert sorted(members["ticker"]) == sorted([A, B])
