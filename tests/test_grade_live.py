"""Study grades on live hits and in the push (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import clock, grade_live, history, notify, sizing
from trading_os.config import load_config
from trading_os.scans.history_scans import luk_flush
from trading_os.store import RunContext

CFG = load_config()
A, B, C = ("".join(["A", "A", "Q"]), "".join(["B", "B", "Q"]), "".join(["C", "C", "Q"]))
SESSION = dt.date(2026, 10, 16)


def market_row(**kw):
    row = {
        "light": "GREEN",
        "qqq_trend": "up",
        "breadth_state": "neutral",
        "scan_count": 10,
        "ratio_10d": 1.2,
        "spy_close": 500.0,
        "spy_sma200": 450.0,
        "qqq_close": 400.0,
        "qqq_sma50": 410.0,
    }
    return row | kw


def test_market_features_from_the_breadth_row():
    f = grade_live.market_features(market_row())
    assert f["mkt_light"] == "GREEN" and f["mkt_scan_count"] == 10
    assert f["mkt_spy_above_ma200"] == 1.0 and f["mkt_qqq_above_ma50"] == 0.0
    assert grade_live.market_features(None) == {}


def test_stock_features_come_from_the_asof_close_only():
    days = clock.sessions_back(CFG.schedule, SESSION, 80)
    close = np.linspace(10, 12, len(days))
    bars = pd.DataFrame(
        {
            "session_date": days,
            "ticker": A,
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": 1e6,
        }
    )
    asof = days[-2]
    feats = grade_live.stock_features(bars, asof, list(days))
    expected = (close[-2] / close[-7] - 1) * 100
    assert feats.loc[A, "d_ret_5"] == pytest.approx(expected)


def hit(ticker, close=20.0, **kw):
    return {
        "ticker": ticker,
        "tv_ticker": f"NASDAQ:{ticker}",
        "close": close,
        "low": close * 0.95,
        "adr20_usd": close * 0.05,
        "adr20_pct": 5.0,
        "avg_dollar_volume_20d": 60e6,
        "gap_pct": 12.0,
        "rvol50": 4.0,
        "volume": 2e6,
        "dollar_volume": 40e6,
        "earnings_flag": False,
        "tier": "alert",
        "rank": 1,
    } | kw


def test_a_scan_with_a_scorecard_is_graded_and_others_are_c():
    hits = pd.DataFrame([hit(A)])
    market = grade_live.market_features(market_row(scan_count=10, light="GREEN"))
    graded = grade_live.grade_hits(hits, "ep_close", CFG, market, pd.DataFrame())
    row = graded.iloc[0]
    assert row["grade_strategy"] == "ep" and row["grade"] in ("A", "B", "C")
    assert row["grade_stop"] == pytest.approx(19.0)  # 1 ADR under 20.0
    assert row["grade_entry_rule"] == "close" and row["grade_hold_sessions"] == 21
    other = grade_live.grade_hits(hits, "breakout_trigger", CFG, market, pd.DataFrame())
    assert other.iloc[0]["grade"] == "C" and "no edge" in other.iloc[0]["grade_why"]


def test_the_study_plan_sizes_from_the_grade():
    hits = pd.DataFrame([hit(A)]).assign(
        grade="A", grade_strategy="ep", grade_stop=19.0, grade_risk_mult=1.5
    )
    account = sizing.Account("USD", 100_000, 0.5, 25)
    out = grade_live.resize(hits, account, 1.0)
    # 0.5 % x 1.5 = 750 risk on a 1.00 stop: 750 shares, $15k (under the 25 % cap)
    assert out.iloc[0]["plan_shares"] == 750 and out.iloc[0]["plan_stop"] == 19.0
    assert out.iloc[0]["plan_stop_basis"] == "1 ADR (study plan)"


def test_add_grades_reads_bars_and_the_market_row(monkeypatch):
    days = clock.sessions_back(CFG.schedule, SESSION, 80)
    close = np.full(len(days), 20.0)
    bars = pd.DataFrame(
        {
            "session_date": days,
            "ticker": A,
            "open": close,
            "high": close * 1.03,
            "low": close * 0.97,
            "close": close,
            "volume": 1e6,
        }
    )
    monkeypatch.setattr(history, "load_bars", lambda data_dir, sessions: bars)
    results = {"ep_close": pd.DataFrame([hit(A)]), "ep_pm": pd.DataFrame([hit(B)])}
    out = grade_live.add_grades(results, ".", CFG, SESSION, "close", market_row())
    assert out["ep_close"].iloc[0]["grade_strategy"] == "ep"
    assert not pd.isna(out["ep_close"].iloc[0]["grade_score"])
    assert out["ep_pm"].iloc[0]["grade"] == "C"


def test_push_shows_a_full_block_b_on_one_line_and_counts_c():
    stats = {
        "grade_stat_trades": 1099,
        "grade_stat_win_pct": 37.1,
        "grade_stat_mean_r": 0.459,
        "grade_stat_median_r": -1.08,
        "grade_stat_years_pos": 6,
        "grade_stat_years": 8,
        "grade_stat_days_median": 11,
    }
    common = {
        "grade_strategy": "ep",
        "grade_entry_rule": "close",
        "grade_hold_sessions": 21,
        "grade_why": "",
    }
    rows = [
        hit(A, rank=2) | common | stats | {"grade": "A", "grade_score": 0.52},
        hit(B, rank=1) | common | {"grade": "B", "grade_score": 0.18},
        hit(C, rank=3) | {"grade": "C", "grade_score": -0.2},
    ]
    results = {"ep_close": pd.DataFrame(rows)}
    selected = notify.select_for_push(results, CFG)
    assert selected["ep_close"]["ticker"].tolist() == [A, B]  # A first; C stays out
    ctx = RunContext(
        session=SESSION, slot="close", run_ts=pd.Timestamp.now(tz="UTC"), run_kind="scheduled"
    )
    body = notify.build_message(ctx, results, selected, CFG).body
    assert "Study A · +0.52R" in body and "1,099 trades" in body and "6/8 yrs +" in body
    assert "buy 15:45-15:58 NY" in body and "B +0.18R" in body
    assert "Study C, saved: EP close 1" in body


def test_luk_flush_takes_the_flagged_rows():
    df = pd.DataFrame([hit(A, luk_flush=True), hit(B, luk_flush=False), hit(C, luk_flush=None)])
    out = luk_flush(df, CFG.scans["luk_flush"])
    assert out["ticker"].tolist() == [A] and out["rank"].tolist() == [1]
    assert luk_flush(df.drop(columns="luk_flush"), CFG.scans["luk_flush"]).empty


def test_earnings_facts_count_sessions_since_the_last_report():
    import datetime as dt

    rec = {"earnings_flag": True, "earnings_date_last": pd.Timestamp("2026-10-12", tz="UTC")}
    out = grade_live.earnings_facts(rec, CFG.schedule, dt.date(2026, 10, 16))
    assert out["is_earnings_reaction_day"] is True and out["sessions_since_earnings"] == 4
    assert "sessions_since_earnings" not in grade_live.earnings_facts({}, CFG.schedule, SESSION)


def test_after_hours_grades_from_todays_close_and_the_post_market_price():
    assert grade_live.asof_session(CFG, SESSION, "ah") == SESSION
    assert grade_live.asof_session(CFG, SESSION, "am") == clock.previous_session(
        CFG.schedule, SESSION
    )
    rec = {"close": 20.0, "ah_price": 22.0, "ah_change_pct": 10.0}
    assert grade_live.entry_price(rec, "ep_ah") == 22.0
    assert grade_live.entry_price(rec | {"ah_price": None}, "ep_ah") == pytest.approx(22.0)
    assert grade_live.entry_price(rec, "ep_am") == 20.0


def test_ep9m_names_found_at_noon_take_the_noon_plan():
    hits = pd.DataFrame([hit(A)])
    morning = grade_live.grade_hits(hits, "ep9m_pace", CFG, {}, pd.DataFrame(), slot="am")
    noon = grade_live.grade_hits(hits, "ep9m_pace", CFG, {}, pd.DataFrame(), slot="mid")
    assert morning["grade_entry_rule"].iloc[0] == "t_1015"
    assert noon["grade_entry_rule"].iloc[0] == "t_1200"
    assert noon["grade_basis"].iloc[0] == "quality"


def test_quality_grades_show_their_own_entrys_history():
    stats = {
        "ep": {
            "grades": {"B": {"trades": 1335, "mean_r": 0.28}},
            "quality": {"t_1030": {"B": {"trades": 1256, "mean_r": 0.12}}},
        }
    }
    hits = pd.DataFrame(
        {
            "grade_strategy": ["ep", "ep", None],
            "grade": ["B", "B", "C"],
            "grade_entry_rule": ["t_1030", "close", None],
            "grade_basis": ["quality", "scorecard", None],
        }
    )
    out = grade_live.with_stats(hits, stats)
    assert out["grade_stat_trades"].iloc[:2].tolist() == [1256, 1335]
    assert pd.isna(out["grade_stat_trades"].iloc[2])


def test_push_shows_quality_points_not_r():
    row = hit(A) | {
        "grade": "A+",
        "grade_score": 5.0,
        "grade_why": "5 of 6 quality points",
        "grade_entry_rule": "pm_0915",
        "grade_hold_sessions": 21,
    }
    lines = notify.grade_lines(row)
    assert lines[0].endswith("Study A+ · 5 of 6 quality points")
    assert "pre-market ~09:15 NY" in " ".join(lines)
