"""EP history study against a hand-built stock: 80 quiet sessions, a gap, then a run and a fade."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import ep_history, sec_bulk
from trading_os.config import load_config

TICKER = "".join(["EP", "HX"])  # built at runtime, like real data
FLAT = 80  # sessions at $10 before the gap


def sessions(n):
    days, day = [], dt.date(2025, 1, 2)
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def bars():
    """Quiet at $10 on 500K shares; gap day: open 11.5, low 11.2, high 12.5, close 12.2 on 3M
    shares; then 8 sessions up to 15.4 and a fade below the 10-day MA."""
    rows = []
    path = [12.2 + 0.4 * i for i in range(1, 9)] + [13.0, 12.0, 11.5, 11.0] + [10.5] * 30
    days = sessions(FLAT + 1 + len(path))
    for i, day in enumerate(days):
        if i < FLAT:
            o = h = lo = c = 10.0
            h, lo, v = 10.2, 9.8, 500_000
        elif i == FLAT:
            o, h, lo, c, v = 11.5, 12.5, 11.2, 12.2, 3_000_000
        else:
            c = path[i - FLAT - 1]
            o, h, lo, v = c, c * 1.01, c * 0.99, 800_000
        rows.append(
            {"session_date": day, "ticker": TICKER, "open": o, "high": h, "low": lo}
            | {"close": c, "volume": v}
        )
    return pd.DataFrame(rows), days


@pytest.fixture(scope="module")
def study():
    frame, days = bars()
    return ep_history.find(frame, days, load_config()), days


def test_the_gap_day_is_found_with_point_in_time_features(study):
    df, days = study
    [row] = df.to_dict("records")
    assert row["session_date"] == days[FLAT] and row["variant"] == "ep_day"
    assert row["gap_pct"] == pytest.approx(15.0)
    assert row["rvol50"] == pytest.approx(6.0)  # 3M vs the prior 50-day 500K
    assert row["months_sideways"] == pytest.approx(FLAT / 21)  # every close at the pre-gap $10
    assert row["ret_before_63d"] == pytest.approx(0.0)
    assert row["tier"] == "alert"  # $36.6M traded, 500K average volume
    assert row["c1_gap"] and row["c2_volume"] and row["c4_neglect"]


def test_entry_stop_and_outcomes(study):
    df, _ = study
    row = df.iloc[0]
    assert row["plan_entry"] == 12.2
    # ADR 20 days = mean(high/low - 1) -> mostly 0.2/9.8; 1 ADR caps the 1.0 day-low distance.
    adr_usd = row["adr20_pct"] * 12.2 / 100
    assert row["plan_stop"] == pytest.approx(12.2 - adr_usd)
    assert row["lod_stop_adr"] == pytest.approx(1.0 / adr_usd)
    assert row["ret_5d"] == pytest.approx((14.2 / 12.2 - 1) * 100)
    assert not row["stop_hit_5d"]
    assert row["r_5d"] == pytest.approx((14.2 - 12.2) / (12.2 - row["plan_stop"]))
    # The fade takes it through the stop within a month, filled at the stop or, on a gap
    # through it, at that day's open (worse than -1R).
    frame, _ = bars()
    after = frame.iloc[FLAT + 1 :]
    hit = after[after["low"] <= row["plan_stop"]].iloc[0]
    fill = min(hit["open"], row["plan_stop"])
    risk = 12.2 - row["plan_stop"]
    assert row["stop_hit_21d"] and row["r_21d"] == pytest.approx((fill - 12.2) / risk)
    assert row["r_21d"] <= -1.0
    assert np.isnan(row["ret_252d"])  # the data ends before a year


def test_trailing_exit_at_the_first_close_under_the_10_day_ma(study):
    df, _ = study
    row = df.iloc[0]
    # Up 8 sessions to 15.4, then 13.0 closes under the 10-day MA (about 13.4) on day 9.
    assert row["days_trail_ma10"] == 9
    assert row["r_trail_ma10"] == pytest.approx((13.0 - 12.2) / (12.2 - row["plan_stop"]))
    assert not row["open_trail_ma10"]


def test_market_context_counts_up_days(study):
    df, _ = study
    assert df.iloc[0]["mkt_up4"] == 1  # the gap day itself, on rising volume


def test_quarter_matching_by_reporting_rhythm():
    last = pd.Timestamp("2026-08-01")
    assert ep_history.infer_quarter(pd.Timestamp("2026-08-03"), last, 10) == (0, True)
    assert ep_history.infer_quarter(pd.Timestamp("2026-05-05"), last, 10) == (1, True)
    # Mid-quarter: the last report before the gap is the one known that day.
    assert ep_history.infer_quarter(pd.Timestamp("2026-06-20"), last, 10) == (1, False)


def test_fundamentals_c3_and_the_sheet_layout(study):
    df, _ = study
    details = pd.DataFrame(
        {
            # Latest first: the gap's quarter is ~6 quarters back from Aug 2026.
            "eps_hist": [[float(x) for x in range(30, 0, -1)]],
            "rev_hist": [[100.0] * 30],
            "earnings_date_last": [pd.Timestamp("2026-08-01", tz="UTC")],
            "float_shares": [19e6],
        },
        index=pd.Index([TICKER], name="ticker"),
    )
    out = ep_history.add_fundamentals(df, details, load_config())
    row = out.iloc[0]
    assert row["float_m_now"] == 19.0 and row["sales_growth_yoy"] == 0.0
    assert row["eps_growth_yoy"] > 0 and isinstance(row["earnings_inferred"], bool)
    sheet = ep_history.sheet_frame(out)
    headers = [h for h, _, _ in ep_history.SHEET_COLUMNS]
    assert list(sheet.columns[: len(headers)]) == headers
    first = sheet.iloc[0]
    assert first["Gap %"] == pytest.approx(0.15) and first["Variant"] == "Day-1 Classic"
    assert (
        first["Found Forward?"] == "No (history)"
        and first["Catalyst — the surprise in one sentence"] == ""
    )
    assert "x_r_21d" in sheet.columns  # extras keep their values behind the sheet's columns


def test_summary_counts_only_matured_horizons(study):
    df, _ = study
    table = ep_history.summary(df).set_index("horizon_d")
    assert table.loc[5, "n"] == 1 and table.loc[5, "win_rate_pct"] == 100.0
    assert table.loc[252, "n"] == 0 and np.isnan(table.loc[252, "mean_r"])


def _sec_tables():
    """One US filer in the sec-10y layout: Q1 announced at 07:00 ET on 8 May 2025 (the
    submissions JSON shows it at 11:00 ET, UTC plus the offset again), Q2 at 16:05 ET on 6 Aug."""
    utc = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
    day = dt.date
    ticker_cik = pd.DataFrame(
        {
            "ticker": [TICKER],
            "cik": pd.array([30], dtype="Int64"),
            "valid_from": [None],
            "valid_to": [None],
        }
    )
    events = pd.DataFrame(
        {
            "cik": [30, 30],
            "form": ["8-K", "8-K"],
            "accepted": [utc("2025-05-08 11:00"), utc("2025-08-06 20:05")],
            "accepted_json": ["2025-05-08T15:00:00.000Z", "2025-08-06T20:05:00.000Z"],
            "time_basis": ["header", "json"],
            "reaction_session": [day(2025, 5, 8), day(2025, 8, 7)],
            "timing": ["pre-market", "after-close"],
        }
    )
    quarterly = pd.DataFrame(
        {
            "cik": [30, 30],
            "fiscal_year": [2025, 2025],
            "fiscal_quarter": [1, 2],
            "period_end": [day(2025, 3, 31), day(2025, 6, 30)],
            "accepted": [utc("2025-05-12 20:30"), utc("2025-08-11 20:30")],  # the 10-Qs
            "known_at": [utc("2025-05-08 11:00"), utc("2025-08-06 20:05")],  # the releases
            "eps": [1.4, 2.0],
            "eps_prior": [1.0, 1.0],
            "revenue": [130.0, 120.0],
            "revenue_prior": [100.0, 100.0],
        }
    )
    shares = pd.DataFrame(
        {
            "cik": [30],
            "accepted": [utc("2025-05-12 20:30")],
            "as_of": [day(2025, 5, 1)],
            "shares": [1000.0],
            "source": ["dei"],
        }
    )
    companies = pd.DataFrame(
        {
            "cik": [30],
            "sic": pd.array([7372], dtype="Int64"),
            "sector": ["Information Technology"],
            "is_spac": [False],
            "spac_until": [None],
        }
    )
    return sec_bulk.Tables(ticker_cik, events, quarterly, shares, companies)


def test_sec_earnings_timing_uses_the_corrected_acceptance_times():
    foreign = "".join(["FO", "RN"])  # no SEC filings: keeps the TradingView estimate
    df = pd.DataFrame(
        {
            "ticker": [TICKER, TICKER, TICKER, foreign],
            "session_date": [dt.date(2025, 5, 8), dt.date(2025, 8, 6)] + [dt.date(2025, 8, 7)] * 2,
            "earnings_inferred": [False, False, False, True],
            "eps_growth_yoy": [60.0, 60.0, 60.0, 80.0],  # TradingView's estimates
            "sales_growth_yoy": [0.0, 0.0, 0.0, 0.0],
        }
    )
    out = ep_history.add_sec(df, _sec_tables(), sessions(170), 50)
    # 07:00 ET is pre-market; the JSON's 11:00 ET read as UTC would have said mid-session.
    assert out.loc[0, "earnings_sec"] is True and out.loc[0, "earnings_timing"] == "pre-market"
    # 16:05 ET is after that day's close, so it is the next session's earnings, not this one's.
    assert out.loc[1, "earnings_sec"] is False and out.loc[1, "earnings_timing"] is None
    assert out.loc[2, "earnings_sec"] is True
    assert out.loc[2, "earnings_timing"] == "after prior close"
    # Growth of the latest quarter announced before the EP-day open replaces TradingView's.
    assert list(out["eps_growth_sec"].iloc[:3]) == pytest.approx([40, 40, 100])
    assert list(out["sales_growth_sec"].iloc[:3]) == pytest.approx([30, 30, 20])
    assert list(out["eps_growth_yoy"]) == pytest.approx([40, 40, 100, 80])
    assert list(out["eps_growth_yoy_tv"]) == pytest.approx([60, 60, 60, 80])
    assert list(out["c3_growth"]) == [False, False, True, True]
    assert list(out["fundamentals_source"]) == ["sec", "sec", "sec", "inferred"]
    assert out.loc[3, "earnings_sec"] is None and out.loc[3, "earnings"]
