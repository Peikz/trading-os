"""Breadth and Market Light (SPEC §6.2, §6.5) — the owner's rules, case by case."""

import datetime as dt
import math

import pandas as pd
import pytest

from trading_os import breadth, history
from trading_os.config import load_config

NAN = math.nan


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def ml(cfg):
    return cfg.market_light


# --- 1. QQQ trend: up, then down, else sideways
@pytest.mark.parametrize(
    ("close", "sma10", "sma20", "sma50", "before", "expected"),
    [
        (105, 103, 100, 110, NAN, "up"),  # close > SMA20 and SMA10 > SMA20 (checked first)
        (90, 92, 95, 100, 96, "down"),  # close < SMA50 and SMA20 below 5 sessions ago
        (90, 92, 95, 100, 94, "sideways"),  # close < SMA50 but SMA20 still rising
        (99, 98, 100, 97, NAN, "sideways"),  # neither
        (90, 92, 95, 100, NAN, None),  # can't tell down from sideways yet
    ],
)
def test_qqq_trend(close, sma10, sma20, sma50, before, expected):
    assert breadth.qqq_trend(close, sma10, sma20, sma50, before) == expected


# --- 2. Breadth state
@pytest.mark.parametrize(
    ("r10", "r5", "up25", "down25", "expected"),
    [
        (1.5, 1.0, 300, 200, "strong"),
        (1.5, 1.0, 200, 300, "neutral"),  # ratio fine but more stocks down 25 % in a quarter
        (0.99, 1.0, 200, 300, "weak"),
        (0.99, 2.01, 200, 300, "neutral"),  # breadth thrust lifts weak to neutral
        (0.99, 2.0, 200, 300, "weak"),  # thrust needs > 2
        (1.2, 1.0, 300, 200, "neutral"),
        (NAN, 1.0, 300, 200, None),
    ],
)
def test_breadth_state(ml, r10, r5, up25, down25, expected):
    assert breadth.breadth_state(r10, r5, up25, down25, ml["breadth"]) == expected


# --- 4. The light, first matching row wins
@pytest.mark.parametrize(
    ("trend", "state", "count", "expected"),
    [
        ("down", "weak", 100, "STOP"),
        ("up", "strong", 4, "STOP"),  # scan count < 5
        ("down", "neutral", 100, "RED"),
        ("up", "weak", 100, "RED"),
        ("up", "strong", 14, "RED"),  # scan count < 15
        ("up", "neutral", 50, "GREEN"),
        ("up", "strong", 49, "YELLOW"),
        ("sideways", "strong", 80, "YELLOW"),
    ],
)
def test_light(ml, trend, state, count, expected):
    assert breadth.light(trend, state, count, ml["thresholds"]) == (expected, [])


def test_light_needs_every_input(ml):
    assert breadth.light(None, "strong", 30, ml["thresholds"]) == (None, ["QQQ trend"])
    assert breadth.light("up", None, None, ml["thresholds"]) == (None, ["breadth", "scan count"])


def test_ratio_needs_full_window():
    counts = pd.DataFrame({"up4": [10, 20, 30], "mb_up": [5, 5, 5], "down4": [10, 10, 10]})
    assert breadth.ratio(counts, "up4", 3) == pytest.approx(60 / 30)
    assert math.isnan(breadth.ratio(counts, "up4", 5))


def stock(ticker, **kw):
    base = {
        "ticker": ticker,
        "close": 20.0,
        "volume": 500_000,
        "prev_volume": 400_000,
        "chg_pct": 5.0,
        "close_loc": 0.9,
        "ret_63": 30.0,
        "ma20": 19.0,
        "ma40": 21.0,
        "ma50": 18.0,
        "country": "United States",
        "avg_volume_30d_tv": 600_000.0,
        "perf_3m_tv": 55.0,
    }
    return base | kw


def test_day_counts_and_rules(cfg):
    df = pd.DataFrame(
        [
            stock("UP"),
            stock("UPWEAK", close_loc=0.5),  # up 4 % but closes low: not an MB up
            stock("QUIET", prev_volume=600_000),  # volume below yesterday: not counted
            stock("DOWN", chg_pct=-6.0),
            stock("CHEAP", close=4.99),  # outside the breadth universe
        ]
    )
    counts = breadth.day_counts(df, cfg)
    assert counts == {"breadth_n": 4, "up4": 2, "mb_up": 1, "down4": 1}


def test_scan_count_screen(cfg):
    df = pd.DataFrame(
        [
            stock("HIT"),
            stock("FOREIGN", country="Canada"),
            stock("PRICE5", close=5.0),  # price must be > $5
            stock("THIN", avg_volume_30d_tv=500_000.0),
            stock("SLOW", perf_3m_tv=49.9),
            stock("BELOW", ma20=21.0),
        ]
    )
    assert breadth.scan_count(df, cfg) == 1


def test_breadth_row_from_snapshot_history(cfg, tmp_path):
    session = dt.date(2026, 10, 16)
    sessions = [
        dt.date(2026, 10, d) for d in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14, 15)
    ]  # 11 sessions before the 16th: 10 days of counts + one for prior-day values
    for i, day in enumerate(sessions):
        snap = pd.DataFrame(
            {
                "run_ts": [pd.Timestamp(f"{day} 20:17", tz="UTC")] * 2,
                "session_date": [pd.Timestamp(day)] * 2,
                "ticker": ["UP", "DOWN"],
                "open": [20.0, 20.0],
                "high": [20.0 * 1.06**i, 20.0],
                "low": [19.0, 20.0 * 0.94**i],
                "close": [20.0 * 1.05**i, 20.0 * 0.95**i],  # +5 % / −5 % every day
                "volume": [100_000.0 + 10_000 * i] * 2,  # rising volume
            }
        )
        path = history.universe_snapshot_path(tmp_path, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        snap.to_parquet(path, index=False)
    uni = pd.DataFrame([stock("UP"), stock("DOWN", chg_pct=-5.0)])
    qqq = {"close": 100.0, "sma10": 99.0, "sma20": 98.0, "sma50": 95.0}
    row = breadth.breadth_row(uni, qqq, cfg, tmp_path, session)
    # Past days: UP has close ≥ $5 and rises 5 % on rising volume; DOWN drops below $5 later.
    assert row["ratio_days_available"] == 10
    assert not math.isnan(row["ratio_10d"])
    assert row["qqq_trend"] == "up"
    assert row["scan_count_basis"] == "eod-bootstrap"
    lines = breadth.push_lines(row)
    assert lines[0] == "⛔ Market Light STOP"  # today's bootstrap count of 1 stock
    assert lines[1].startswith("QQQ up · breadth ")
    assert lines[2].startswith("4%: ▲")
    assert lines[3].startswith("Qtr 25%: ▲") and " · Mo 25%: ▲" in lines[3]
    assert lines[4].endswith("34d 13%: n/a")  # no 34-day history yet
    assert lines[5].startswith("Above MA20 ")


def test_premarket_lines_use_last_close_light_and_pm_movers(cfg, tmp_path):
    last = {
        "session_date": pd.Timestamp("2026-10-16"),
        "light": "YELLOW",
        "light_missing": "",
        "qqq_trend": "sideways",
        "breadth_state": "neutral",
        "scan_count": 30,
        "up4": 22,
        "mb_up": 20,
        "down4": 203,
        "up_count_rule": "stockbee_4pct",
        "ratio_5d": 0.5,
        "ratio_10d": 0.8,
        "up25q": 280,
        "down25q": 354,
        "pct_above_ma20": 46.0,
    }
    path = tmp_path / "data" / "breadth" / "2026" / "2026-10-16_eod.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([last]).to_parquet(path)
    assert breadth.latest_eod_row(tmp_path, dt.date(2026, 10, 19))["light"] == "YELLOW"
    assert breadth.latest_eod_row(tmp_path, dt.date(2026, 10, 16)) is None  # same day isn't "last"

    uni = pd.DataFrame(
        [
            stock("GAPUP", pm_change_pct=6.0),
            stock("GAPDOWN", pm_change_pct=-5.0),
            stock("FLAT", pm_change_pct=1.0),
            stock("PENNY", close=3.0, pm_change_pct=20.0),  # outside the breadth universe
        ]
    )
    row = breadth.premarket_row(uni, {"pm_change_pct": 0.42}, cfg, dt.date(2026, 10, 19), last)
    assert (row["pm_up4"], row["pm_down4"], row["pm_breadth_n"]) == (1, 1, 3)
    lines = breadth.premarket_lines(row, last)
    assert lines == [
        "🟡 Market Light YELLOW (from the 10-16 close)",
        "QQQ sideways · breadth neutral · count 30",
        "Last close 4%: ▲22 ▼203 · 5d 0.50 · 10d 0.80",
        "Pre-market 4%: ▲1 ▼1 · QQQ +0.4%",
    ]


def test_premarket_lines_before_any_eod(cfg):
    uni = pd.DataFrame([stock("A", pm_change_pct=5.0)])
    row = breadth.premarket_row(uni, {}, cfg, dt.date(2026, 10, 19), None)
    lines = breadth.premarket_lines(row, None)
    assert lines == ["⚪ Market Light n/a (needs an EOD run)", "Pre-market 4%: ▲1 ▼0"]


def test_market_monitor_counts_month_and_34_day_moves():
    rules = load_config().scans["breadth"]
    uni = pd.DataFrame(
        {
            "ret_22": [25.0, 24.9, 50.0, -25.0, -50.0, 0.0],
            "hist_ret_34": [13.0, 12.9, -13.0, None, None, None],
        }
    )
    m = breadth.market_monitor(uni, rules)
    assert (m["up25m"], m["down25m"], m["up50m"], m["down50m"]) == (2, 2, 1, 1)
    assert (m["up13_34d"], m["down13_34d"], m["mid_rows"]) == (1, 1, 3)
    row = {**m, "breadth_n": 6, "up25q": 9, "down25q": 4}
    assert breadth.monitor_lines(row) == [
        "Qtr 25%: ▲9 ▼4 · Mo 25%: ▲2 ▼2",
        "Mo 50%: ▲1 ▼1 · 34d 13%: ▲1 ▼1",
    ]
    assert breadth.monitor_lines(row | {"mid_rows": 2})[1].endswith("34d 13%: n/a")  # thin
    old = {"up25q": 9, "down25q": 4}  # rows stored before 19 Oct
    assert breadth.monitor_lines(old) == ["Qtr 25%: ▲9 ▼4"]
