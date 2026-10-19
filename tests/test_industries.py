"""Industry ranking, RS percentile, earnings countdown and the new facts in the lines."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import breadth, clock, context, industries, metrics, sizing
from trading_os.config import load_config
from trading_os.scans.intraday import pivot_watch

DOT = "·"


def stock(ticker, industry, r1, r3, **kw):
    base = {
        "ticker": ticker,
        "industry": industry,
        "sector": "Tech",
        "ret_22": r1,
        "ret_63": r3,
        "ret_126": r3,
        "adr20_pct": 6.0,
        "avg_dollar_volume_20d": 50e6,
        "close": 20.0,
    }
    return base | kw


def universe():
    rows = [stock(f"S{i}", "Semis", 10.0 + i, 40.0) for i in range(5)]
    rows += [stock("S5", "Semis", 200.0, 200.0)]  # medians stay 12.5 / 40; the QM top name
    rows += [stock(f"B{i}", "Banks", 1.0, 2.0) for i in range(5)]
    rows += [stock(f"T{i}", "Tiny", 90.0, 90.0) for i in range(3)]  # too few to rank
    rows += [stock("X", "", 50.0, 50.0)]
    return pd.DataFrame(rows)


def test_rank_by_median_returns_with_qm_members():
    cfg = load_config()
    table = industries.rank(universe(), cfg)
    assert table["industry"].tolist() == ["Semis", "Banks"]
    semis = table.iloc[0]
    assert semis["med_ret_22"] == pytest.approx(12.5) and semis["med_ret_63"] == 40
    assert (semis["industry_rank"], semis["industry_of"], semis["members"]) == (1, 2, 6)
    assert semis["qm_members"] == 1 and table.iloc[1]["qm_members"] == 0
    ranked = industries.add_rank(universe(), table).set_index("ticker")
    assert industries.label(ranked.loc["S0"]) == "Semis #1/2"
    assert industries.label(ranked.loc["T0"]) == "Tiny"  # shown, not ranked
    assert industries.label(ranked.loc["X"]) is None
    lines = industries.lines(table, 5)
    assert lines[0].startswith("Leading industries")
    assert lines[1].startswith("1. Semis  +12% / +40%  QM ")
    assert industries.lines(table.iloc[0:0], 5) == []


def test_rs_percentile_spans_1_to_99():
    df = pd.DataFrame({f"ret_{d}": [1.0, 2.0, 3.0] for d in (22, 63, 126)})
    assert metrics.rs_percentile(df, [22, 63, 126]).tolist() == [34.0, 66.0, 99.0]


def test_sessions_until_counts_trading_days():
    schedule = load_config().schedule
    monday = dt.date(2026, 10, 19)
    days = pd.Series(
        [monday, dt.date(2026, 10, 23), dt.date(2026, 10, 26), dt.date(2026, 10, 16), None]
    )
    out = clock.sessions_until(schedule, monday, days).tolist()
    assert out[:3] == [0.0, 4.0, 5.0] and pd.isna(out[3]) and pd.isna(out[4])
    # Thanksgiving (26 Nov) is not a session.
    thanks = clock.sessions_until(
        schedule, dt.date(2026, 11, 25), pd.Series([dt.date(2026, 11, 27)])
    )
    assert thanks.tolist() == [1.0]


def test_facts_show_rs_earnings_soon_ath_and_industry_rank():
    row = {
        "earnings_flag": False,
        "close": 50.0,
        "high_52w": 50.2,
        "high_all_tv": 50.3,
        "rs_pct": 97.0,
        "earnings_in_sessions": 4.0,
        "earnings_soon": True,
        "industry": "Semis",
        "industry_rank": 3.0,
        "industry_of": 120.0,
    }
    line = context.ep_line(row)
    assert line.endswith(
        f"at all-time high {DOT} RS 97 {DOT} 📅 earnings in 4 days {DOT} Semis #3/120"
    )
    later = context.ep_line(row | {"earnings_soon": False, "high_all_tv": 80.0})
    assert "earnings in" not in later and "at 52w high" in later
    today = context.breakout_line(row | {"earnings_in_sessions": 0.0}, "breakout_watch")
    assert "earnings today" in today and "at all-time high" in today


def test_index_line_for_close_and_premarket():
    quotes = {
        "spy": {
            "close": 767.59,
            "chg_pct": 0.57,
            "pm_change_pct": 0.3,
            "sma10": 770.0,
            "sma20": 768.0,
            "sma50": 750.0,
            "sma200": 700.0,
        },
        "vix": {"close": 18.58, "chg_pct": -7.07, "pm_change_pct": float("nan")}
        | {f"sma{w}": 20.0 for w in (10, 20, 50, 200)},
    }
    row = breadth.index_fields(quotes)
    assert breadth.index_lines(row) == [
        "SPY 767.59 🟢 +0.6% · VIX 18.6 -7.1%",
        "SPY above MA50, 200 · below 10, 20",
    ]
    assert breadth.index_lines(row, premarket=True) == ["SPY pre-market 🟢 +0.3% · VIX 18.6 -7.1%"]
    assert breadth.index_lines({}) == []


def pivot_rows():
    base = {"on_bo_watch": True, "pivot": 45.20, "order_stop": 42.10, "chg_pct": 3.0}
    return pd.DataFrame(
        [
            base | {"ticker": "OVER", "close": 45.60, "rvol_at_time_tv": 1.5},
            base | {"ticker": "NEAR", "close": 44.80, "rvol_at_time_tv": 3.0},  # -0.9 %
            base | {"ticker": "FAR", "close": 44.00, "rvol_at_time_tv": 5.0},  # -2.7 %
            base | {"ticker": "OFFL", "close": 46.00, "on_bo_watch": False},
            base | {"ticker": "NOPV", "close": 46.00, "pivot": None},
        ]
    )


def test_pivot_watch_hits_over_and_near_the_pivot_ranked_by_volume():
    scan = load_config().scans["pivot_watch"]
    hits = pivot_watch(pivot_rows(), scan)
    assert hits["ticker"].tolist() == ["NEAR", "OVER"]
    assert hits["pivot_crossed"].tolist() == [False, True]
    assert hits["pivot_dist_pct"].iloc[0] == pytest.approx((44.80 / 45.20 - 1) * 100)
    assert pivot_watch(pd.DataFrame({"ticker": ["A"], "close": [1.0]}), scan).empty


def test_pivot_watch_sizing_buys_now_over_the_pivot():
    rules = load_config().sizing
    over = {"close": 45.60, "pivot": 45.20, "order_stop": 42.10}
    assert sizing.plan(over, "pivot_watch", rules) == (45.60, 42.10, "order stop")
    under = over | {"close": 44.80}
    assert sizing.plan(under, "pivot_watch", rules) == (
        45.20,
        42.10,
        "order stop, buy-stop at pivot",
    )
