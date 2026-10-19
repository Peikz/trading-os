"""Hand-logged trades, plans, trade review and system health (synthetic data only)."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import health, journal, plans, review
from trading_os.config import load_config

CFG = load_config()
A = "".join(["T", "R", "D"])
MON, TUE, WED = dt.date(2026, 10, 19), dt.date(2026, 10, 20), dt.date(2026, 10, 21)


def test_manual_fills_build_a_trade_with_setup_stop_and_r(tmp_path):
    buy = journal.manual_fill(MON, A, "buy", 100, 10.0, setup="ep_day")
    trades, open_ = journal.log_manual(tmp_path, CFG, buy, stop=9.5)
    assert trades.empty and len(open_) == 1 and open_["order_stop"].iloc[0] == 9.5
    sell = journal.manual_fill(WED, A, "sell", 100, 11.0)
    trades, open_ = journal.log_manual(tmp_path, CFG, sell)
    t = trades.iloc[0]
    assert open_.empty and t["setup"] == "ep_day" and bool(t["manual"])
    assert t["r_multiple"] == pytest.approx(2.0)  # +1.00 on 0.50 risk


def test_a_broker_fill_replaces_its_hand_logged_twin():
    manual = journal.manual_fill(MON, A, "buy", 100, 10.0, setup="ep_day")
    broker = pd.DataFrame(
        [
            {
                "fill_id": "b1",
                "trade_date": MON,
                "ticker": A,
                "side": "buy",
                "quantity": 100.0,
                "price": 10.04,
                "fees": 1.0,
                "source": "broker",
                "setup": None,
            }
        ]
    )
    kept = journal.reconcile(pd.concat([manual, broker], ignore_index=True))
    assert kept["fill_id"].tolist() == ["b1"]
    other = journal.manual_fill(MON, A, "buy", 50, 10.0)  # different size: both stay
    assert len(journal.reconcile(pd.concat([other, broker], ignore_index=True))) == 2


def test_plan_status_follows_the_fills(tmp_path):
    pid = plans.create(tmp_path, MON, A, "long", 10.0, 9.5, 200, "ep_day")
    fills = pd.DataFrame(
        {"trade_date": [TUE], "ticker": [A], "side": ["buy"], "quantity": [200.0], "price": [10.1]}
    )
    events = plans.load(tmp_path)
    filled = plans.status(events, fills, CFG.schedule, 5, WED).iloc[0]
    assert filled["status"] == "filled" and filled["plan_id"] == pid
    assert filled["slippage_pct"] == pytest.approx(1.0) and filled["slippage_r"] == pytest.approx(
        0.2
    )
    empty = fills.iloc[0:0]
    assert plans.status(events, empty, CFG.schedule, 5, WED).iloc[0]["status"] == "open"
    late = dt.date(2026, 11, 2)  # more than 5 sessions after the plan
    assert plans.status(events, empty, CFG.schedule, 5, late).iloc[0]["status"] == "expired"
    plans.cancel(tmp_path, pid)
    gone = plans.status(plans.load(tmp_path), empty, CFG.schedule, 5, WED).iloc[0]
    assert gone["status"] == "cancelled"
    with pytest.raises(ValueError):
        plans.create(tmp_path, MON, A, "long", 10.0, 10.5, 1)  # stop above a long entry


def test_shares_for_risk_and_the_position_cap():
    assert plans.shares_for(10.0, 9.5, 100, 1e6, 100)["shares"] == 200
    capped = plans.shares_for(10.0, 9.99, 100, 10_000, 20)
    assert capped["shares"] == 200 and capped["capped"]  # 20 % of 10k = 2,000 $ = 200 shares
    assert plans.shares_for(10.0, 10.5, 100, 1e6, 100)["shares"] == 200  # a short


def test_excursions_skip_the_entry_day_and_measure_in_r():
    trades = pd.DataFrame(
        [
            {
                "ticker": A,
                "direction": "long",
                "entry_date": MON,
                "exit_date": WED,
                "entry_avg": 10.0,
                "order_stop": 9.0,
                "r_multiple": 1.0,
            }
        ]
    )
    bars = pd.DataFrame(
        {
            "ticker": A,
            "session_date": [MON, TUE, WED],
            "high": [20.0, 13.0, 12.0],  # MON's 20 is the entry day: left out
            "low": [1.0, 9.5, 10.5],
            "close": [10, 12, 11.0],
        }
    )
    row = review.excursions(trades, bars).iloc[0]
    assert row["mfe_r"] == pytest.approx(3.0) and row["mae_r"] == pytest.approx(-0.5)
    assert row["exit_efficiency"] == pytest.approx(1 / 3) and row["sessions_held"] == 2


def test_open_risk_values_positions_at_the_last_close():
    pos = pd.DataFrame(
        [
            {
                "ticker": A,
                "direction": "long",
                "entry_avg": 10.0,
                "open_quantity": 100.0,
                "order_stop": 9.0,
            }
        ]
    )
    last = pd.DataFrame({"ticker": [A, A], "session_date": [MON, TUE], "close": [10.5, 11.0]})
    row = review.open_risk(pos, last, account_usd=10_000).iloc[0]
    assert row["open_pnl"] == 100 and row["open_r"] == pytest.approx(1.0)
    assert row["at_risk_usd"] == 200 and row["at_risk_pct"] == pytest.approx(2.0)


def test_real_vs_study_puts_your_r_next_to_the_study():
    trades = pd.DataFrame(
        {"setup": ["ep_day", "ep_day", None], "r_multiple": [2.0, -1.0, 0.5], "pnl": [1, 2, 3]}
    )
    study = {"ep_day": pd.DataFrame({"r_21d": [1.0, -1.0, 0.5], "r_trail_ma20": [0.2, 0.4, 0.0]})}
    table = review.real_vs_study(trades, study).set_index("setup")
    assert table.loc["ep_day", "your_mean_R"] == pytest.approx(0.5)
    assert table.loc["ep_day", "study_R_21d"] == pytest.approx(1 / 6)
    assert "untagged" in table.index


def test_minutes_late_counts_from_the_cron_before_the_start():
    crons = [(14, 17), (15, 17)]
    start = dt.datetime(2026, 10, 19, 19, 53, tzinfo=dt.UTC)
    assert health.minutes_late(start, crons) == pytest.approx(276)
    assert health.minutes_late(dt.datetime(2026, 10, 19, 1, 0, tzinfo=dt.UTC), crons) > 0
