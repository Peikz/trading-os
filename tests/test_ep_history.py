"""EP history study against a hand-built stock: 80 quiet sessions, a gap, then a run and a fade."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import ep_history
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
