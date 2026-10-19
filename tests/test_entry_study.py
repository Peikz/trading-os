"""EP entry timing against a hand-built EP: an evening print, pre-market, an opening range
broken at 09:40, then a steady climb."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import entry_study as es

PREV, EP, NXT = dt.date(2026, 10, 14), dt.date(2026, 10, 15), dt.date(2026, 10, 16)
ADR = 0.5  # dollars


def bar(day, hhmm, o, h, lo, c):
    ts = pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC")
    return {"ticker": "EPX", "ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": 1e4}


def minutes():
    rows = [bar(PREV, "15:59", 10, 10, 10, 10), bar(PREV, "17:30", 11, 11, 11, 11)]
    rows += [bar(EP, "07:00", 11.5, 11.5, 11.4, 11.5), bar(EP, "09:10", 11.8, 11.8, 11.7, 11.8)]
    # Opening range 09:30-09:34: high 12.3, low 11.9. 09:40 trades through 12.3.
    rows += [bar(EP, f"09:3{i}", 12.0, 12.3 if i == 2 else 12.1, 11.9, 12.0) for i in range(5)]
    rows += [bar(EP, "09:40", 12.2, 12.6, 12.2, 12.5), bar(EP, "10:30", 13.0, 13.0, 12.9, 13.0)]
    rows += [bar(EP, "15:59", 12.8, 12.8, 12.8, 12.8)]
    rows += [bar(NXT, "09:30", 13.0, 13.1, 12.9, 13.0), bar(NXT, "09:36", 13.2, 13.4, 13.2, 13.3)]
    return es.to_ny(pd.DataFrame(rows))


def daily():
    days = pd.bdate_range("2026-10-14", periods=80).date
    closes = [10.0, 12.8] + [13.0 + 0.1 * i for i in range(78)]
    return pd.DataFrame(
        {
            "session_date": days,
            "open": closes,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
        }
    )


def test_entries_at_each_time():
    found = es.entries(minutes(), PREV, EP, NXT)
    assert found["ah_1800"][0] == 11.0
    assert found["pm_0800"][0] == 11.5 and found["pm_0915"][0] == 11.8
    assert found["open"][0] == 12.0
    assert found["orh_5m"][0] == 12.3 and found["orh_5m"][2] == 11.9  # fill at the high
    # The first hour's high is 12.6 (09:40); the 10:30 bar opens at 13.0 above it: fill 13.0.
    assert found["orh_60m"][0] == 13.0
    assert found["t_1030"][0] == 13.0 and found["close"][0] == 12.8
    assert found["next_open"][0] == 13.0 and found["next_orh_5m"][0] == pytest.approx(13.2)


def test_outcomes_use_the_minutes_then_daily_bars():
    rows = pd.DataFrame(es.study_event(minutes(), daily(), PREV, EP, NXT, ADR))
    orb = rows[(rows["entry"] == "orh_5m") & (rows["stop_rule"] == "low")].iloc[0]
    risk = 12.3 - 11.9
    # Five sessions after the EP day the daily close is 13.0 + 0.1 * 4 = 13.4.
    assert orb["r_5d"] == pytest.approx((13.4 - 12.3) / risk)
    assert not orb["stopped_entry_day"]
    wide = rows[(rows["entry"] == "open") & (rows["stop_rule"] == "adr")].iloc[0]
    assert wide["stop"] == pytest.approx(12.0 - 1.5 * ADR)


def test_a_stop_hit_on_the_entry_day_is_minus_one_or_worse():
    m = minutes()
    m.loc[m["clock"] == "10:30", ["low", "open"]] = [11.0, 12.9]  # dumps through 11.9
    rows = pd.DataFrame(es.study_event(m, daily(), PREV, EP, NXT, ADR))
    orb = rows[(rows["entry"] == "orh_5m") & (rows["stop_rule"] == "low")].iloc[0]
    assert orb["stopped_entry_day"] and orb["r_5d"] == pytest.approx(-1.0)


def test_summary_counts_trades_per_entry():
    rows = pd.DataFrame(es.study_event(minutes(), daily(), PREV, EP, NXT, ADR))
    table = es.summary(rows).set_index(["entry", "stop_rule"])
    assert table.loc[("orh_5m", "low"), "trades"] == 1
    assert table.loc[("orh_5m", "low"), "win_5d%"] == 100.0
    assert es.label("orh_15m") == "15-minute opening-range high"
