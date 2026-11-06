"""Live tracking: plan results of live signals, the verdict against the study, execution."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import live_tracking as lt

A = "".join(["C", "H", "Q"])
DAYS = list(pd.bdate_range("2026-10-01", periods=40).date)


def bars(closes, lows=None, opens=None, ticker=A, highs=None):
    n = len(closes)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "session_date": DAYS[:n],
            "open": opens if opens is not None else closes,
            "high": highs if highs is not None else [c + 0.1 for c in closes],
            "low": lows if lows is not None else [c - 0.1 for c in closes],
            "close": closes,
        }
    )


def signal(**kw):
    base = {
        "signal_id": "s1",
        "session_date": DAYS[0],
        "scan": "ep_am",
        "ticker": A,
        "grade": "A+",
        "grade_strategy": "ep",
        "grade_entry_rule": "t_1030",
        "grade_entry": 10.0,
        "grade_stop": 9.0,
        "grade_hold_sessions": 3,
        "grade_cost_r": np.nan,
        "grade_stat_mean_r": 0.5,
        "grade_stat_win_pct": 30.0,
    }
    return pd.DataFrame([base | kw])


def test_play_out_stop_gap_hold_and_open():
    path = pd.DataFrame({"open": [10.5, 9.5], "low": [8.9, 9.4], "close": [9.2, 9.6]})
    assert lt.play_out(10, 9, 21, path)["exit"] == 9  # the low touched the stop
    gap = pd.DataFrame({"open": [8.0], "low": [7.5], "close": [8.2]})
    assert lt.play_out(10, 9, 21, gap)["exit"] == 8.0  # opened under the stop
    up = pd.DataFrame({"open": [11, 12, 13], "low": [10.5, 11.5, 12.5], "close": [11, 12, 13]})
    done = lt.play_out(10, 9, 3, up)
    assert done == {"status": "closed", "exit": 13.0, "sessions": 3}
    assert lt.play_out(10, 9, 21, up)["status"] == "open"


def test_plan_results_net_of_the_study_cost_and_next_day_entries():
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    out = lt.plan_results(signal(), bars(closes))
    row = out.iloc[0]
    assert row["status"] == "closed" and row["exit"] == 13.0  # 3 sessions after the gap day
    assert row["r_gross"] == pytest.approx(3.0)
    assert row["r_net"] == pytest.approx(3.0 - lt.STUDY_COST_R["t_1030"])
    nxt = lt.plan_results(signal(grade_entry_rule="next_1030"), bars(closes)).iloc[0]
    assert nxt["exit"] == 14.0  # bought the session after the signal
    c = lt.plan_results(signal(grade="C"), bars(closes))
    assert c.empty  # only A+ and A are tracked


SURF = {"qm_surf": "trail_ma20", "ep": "hold"}


def surf(**kw):
    return signal(
        scan="ma_surf",
        grade="A",
        grade_strategy="qm_surf",
        grade_entry_rule="pivot_1000",
        grade_hold_sessions=np.nan,
        **kw,
    ).assign(session_date=DAYS[lt.MA_SESSIONS])


def test_ma_surf_needs_the_pivot_next_session_and_trails_the_20_day_ma():
    flat = [10.0] * lt.MA_SESSIONS  # the 20-day MA sits at 10 before the signal
    # signal day, then a session whose high stays under the pivot: no trade
    miss = bars([*flat, 9.8, 9.9, 9.7], highs=[*[10.1] * 20, 9.9, 9.95, 9.8])
    row = lt.plan_results(surf(grade_entry=10.5, grade_stop=9.5), miss, SURF).iloc[0]
    assert row["status"] == "not filled" and np.isnan(row["r_net"])
    # filled the next session, up for two sessions, then a close under the 20-day MA
    up = bars([*flat, 10.4, 10.6, 11.0, 11.5, 9.9], opens=[*flat, 10.4, 10.3, 11.0, 11.5, 10.5])
    row = lt.plan_results(surf(grade_entry=10.5, grade_stop=9.5), up, SURF).iloc[0]
    assert (row["status"], row["exit"], row["sessions"]) == ("closed", 9.9, 3)
    assert row["entry"] == 10.5
    # opened over the pivot: bought at the open
    gap = bars([*flat, 10.4, 11.0, 11.2], opens=[*flat, 10.4, 11.0, 11.2])
    row = lt.plan_results(surf(grade_entry=10.5, grade_stop=9.5), gap, SURF).iloc[0]
    assert row["entry"] == 11.0 and row["status"] == "open"
    # without the exit rules the old fixed hold applies
    held = lt.plan_results(surf(grade_entry=10.5, grade_stop=9.5), up).iloc[0]
    assert held["status"] == "open"
    table = lt.compare(lt.plan_results(surf(grade_entry=10.5, grade_stop=9.5), miss, SURF))
    assert table.iloc[0]["not_filled"] == 1 and table.iloc[0]["closed"] == 0


def test_exit_rules_read_the_grading_config():
    from trading_os.config import load_config

    rules = lt.exit_rules(load_config().grading)
    assert rules["qm_surf"] == "trail_ma20"
    assert rules["ep"] != "trail_ma20"


def test_verdict_needs_trades_and_both_measures():
    study = 0.5
    assert lt.verdict(pd.Series([1.0] * 5), study, 30) == "too few trades yet"
    bad = pd.Series([-1.0] * 25 + [0.5] * 3)
    assert lt.verdict(bad, study, 30) == "below the study"
    ok = pd.Series([-1.0] * 18 + [4.0] * 8)
    assert lt.verdict(ok, study, 30) == "on track"


def test_compare_and_push_lines():
    res = pd.DataFrame(
        {
            "grade_strategy": ["ep9m"] * 3,
            "entry_rule": ["t_1015"] * 3,
            "grade": ["A+"] * 3,
            "status": ["closed", "closed", "open"],
            "r_net": [1.0, -1.0, np.nan],
            "study_mean_r": [0.56] * 3,
            "study_win_pct": [27.0] * 3,
        }
    )
    table = lt.compare(res)
    row = table.iloc[0]
    assert (row["closed"], row["open"], row["verdict"]) == (2, 1, "too few trades yet")
    line = lt.push_lines(table, {"ep9m": "EP9M"})[0]
    assert line.startswith("EP9M t_1015 A+ · 2 closed +0.00R (study +0.56R)")


def test_execution_matches_your_trade_to_its_signal():
    res = lt.plan_results(signal(), bars([10.0, 11.0, 12.0, 13.0]))
    trades = pd.DataFrame(
        {
            "ticker": [A, A],
            "entry_date": [DAYS[1], DAYS[10]],  # the second is too late for this signal
            "r_multiple": [1.5, 2.0],
        }
    )
    out = lt.execution(res, trades, DAYS)
    assert len(out) == 1 and out.iloc[0]["your_r"] == 1.5
    assert out.iloc[0]["gap_r"] == pytest.approx(1.5 - res.iloc[0]["r_net"])
    assert isinstance(out.iloc[0]["signal_session"], dt.date)


def test_the_monthly_check_runs_on_a_small_data_repo(tmp_path):
    import importlib.util
    from pathlib import Path

    from trading_os import history

    spec = importlib.util.spec_from_file_location(
        "live_check", Path(__file__).resolve().parents[1] / "scripts" / "live_check.py"
    )
    live_check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_check)
    days = list(pd.bdate_range("2026-09-01", periods=30).date)
    cand = signal(session_date=pd.Timestamp(days[0]), slot="eod").assign(
        plan_entry=10.0, signal_id="s1"
    )
    path = tmp_path / "data" / "candidates" / "2026" / f"{days[0]}_eod.parquet"
    path.parent.mkdir(parents=True)
    cand.to_parquet(path)
    for k, day in enumerate(days):
        price = 10.0 + 0.2 * k
        bar = pd.DataFrame(
            [{"session_date": pd.Timestamp(day), "ticker": A, "open": price, "high": price + 0.1,
              "low": price - 0.1, "close": price, "volume": 1e6, "run_ts": pd.Timestamp(day)}]
        )  # fmt: skip
        snap = history.universe_snapshot_path(tmp_path, day)
        snap.parent.mkdir(parents=True, exist_ok=True)
        bar.to_parquet(snap)
    lines, pushes, counts = live_check.build(tmp_path, days[-1])
    assert counts["signals"] == 1 and counts["closed"] == 1
    assert any("study +0.50R" in p for p in pushes)
    assert any(line.startswith("| ep | t_1030 | A+ | 1 |") for line in lines)


BASKET_DAYS = list(pd.bdate_range("2026-01-02", periods=90).date)


def basket_bars(closes, ticker=A):
    return pd.DataFrame(
        {"ticker": ticker, "session_date": BASKET_DAYS[: len(closes)], "close": closes}
    )


def plan_row(**kw):
    base = {
        "session_date": BASKET_DAYS[0],
        "ticker": A,
        "grade": "A+",
        "grade_strategy": "ep",
        "entry_rule": "t_1030",
        "entry": 10.0,
        "stop": 9.5,
        "status": "closed",
        "r_gross": 1.0,
        "r_net": 0.9,
    }
    return base | kw


def test_basket_sells_at_the_first_review_under_the_entry():
    closes = [10.0] + [11.0] * 9 + [9.0] + [12.0] * 70  # session 10 after the entry under 10
    out = lt.basket_results(pd.DataFrame([plan_row()]), basket_bars(closes))
    assert out["status"].iloc[0] == "closed" and out["sessions"].iloc[0] == 10
    # cost: 0.1R x 5 % risk + 0.10 % = 0.6 %
    assert out["net_pct"].iloc[0] == pytest.approx(-10.0 - 0.6)


def test_basket_holds_63_sessions_and_skips_signals_on_a_held_stock():
    closes = [10.0] + [11.0] * 62 + [13.0] + [13.0] * 10
    rows = [plan_row(), plan_row(session_date=BASKET_DAYS[5], grade_strategy="ep9m")]
    out = lt.basket_results(pd.DataFrame(rows), basket_bars(closes))
    assert len(out) == 1
    assert out["sessions"].iloc[0] == 63 and out["net_pct"].iloc[0] == pytest.approx(30.0 - 0.6)


def test_basket_takes_only_its_grades_and_keeps_open_trades_open():
    rows = [plan_row(), plan_row(ticker="X", grade="B", grade_strategy="ep9m"),
            plan_row(ticker="Y", grade_strategy="qm_surf", grade="A")]  # fmt: skip
    out = lt.basket_results(pd.DataFrame(rows), basket_bars([10.0] + [11.0] * 30))
    assert list(out["ticker"]) == [A] and out["status"].iloc[0] == "open"
    summary = lt.basket_summary(out, pd.DataFrame(rows))
    assert summary["closed"] == 0 and summary["open"] == 1
    assert summary["verdict"] == "too few trades yet"


def test_basket_cut_under_the_entry_day_low():
    closes = [10.0] + [10.5] * 4 + [9.4] + [12.0] * 70  # session 5 closes under the entry-day low
    bars_ = basket_bars(closes).assign(low=[9.5] + [10.0] * 75)
    out = lt.basket_results(pd.DataFrame([plan_row()]), bars_)
    assert out["sessions"].iloc[0] == 5 and out["net_pct"].iloc[0] == pytest.approx(-6.0 - 0.6)


def test_basket_lets_a_19_pct_winner_run_to_126():
    closes = [10.0] + [12.0] * 20 + [12.5] * 110  # session 21 at +20 %, never under its close
    days = list(pd.bdate_range("2026-01-02", periods=131).date)
    bars_ = pd.DataFrame({"ticker": A, "session_date": days, "close": closes, "low": 9.9})
    out = lt.basket_results(pd.DataFrame([plan_row(session_date=days[0])]), bars_)
    assert out["sessions"].iloc[0] == 126 and out["net_pct"].iloc[0] == pytest.approx(25.0 - 0.6)
    closes[63] = 11.0  # under the session-21 close at session 63: out there
    bars_["close"] = closes
    out = lt.basket_results(pd.DataFrame([plan_row(session_date=days[0])]), bars_)
    assert out["sessions"].iloc[0] == 63
