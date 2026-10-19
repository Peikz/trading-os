"""Ten-year history plumbing: year windows, loading, the newest snapshot (synthetic data)."""

import datetime as dt

import pandas as pd

from trading_os import long_history as lh
from trading_os.config import load_config

CFG = load_config()


def test_a_year_runs_with_lead_and_tail_sessions():
    sessions, inside = lh.window(CFG.schedule, 2019, dt.date(2026, 10, 16))
    assert inside[0] == dt.date(2019, 1, 2) and inside[-1] == dt.date(2019, 12, 31)
    assert len(sessions) == lh.LEAD + len(inside) + lh.TAIL
    assert sessions[lh.LEAD] == inside[0]


def test_the_newest_year_has_no_tail_past_the_data():
    sessions, inside = lh.window(CFG.schedule, 2026, dt.date(2026, 10, 16))
    assert inside[-1] == dt.date(2026, 10, 16) and sessions[-1] == inside[-1]


def test_load_years_reads_the_yearly_files(tmp_path):
    for year in (2018, 2019):
        pd.DataFrame(
            {
                "session_date": [dt.date(year, 3, 1)],
                "ticker": ["LHQ"],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [5],
                "vwap": [1.0],
                "source": ["alpaca"],
            }
        ).to_parquet(tmp_path / f"{year}.parquet")
    bars = lh.load_years(tmp_path, 2017, 2019)
    assert bars["session_date"].tolist() == [dt.date(2018, 3, 1), dt.date(2019, 3, 1)]
    assert list(bars.columns) == lh.BAR_COLUMNS and bars["volume"].dtype == "float64"


def test_newest_universe_goes_by_the_date_in_the_name(tmp_path):
    def snap(path, cap):
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {"ticker": ["LHQ"], "tv_ticker": ["NYSE:LHQ"], "market_cap": [cap]}
        ).to_parquet(path)

    snap(tmp_path / "data" / "universe" / "2026" / "2026-10-19_eod.parquet", 2.0)
    snap(tmp_path / "data" / "manual" / "2026-10-16_eod_133954" / "universe.parquet", 1.0)
    assert lh.newest_universe(tmp_path)["market_cap"].tolist() == [2.0]
