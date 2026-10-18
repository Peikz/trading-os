import math

import pandas as pd
import pytest

from trading_os.config import load_config
from trading_os.scans import run_scans
from trading_os.scans.ep import ep_day


@pytest.fixture(scope="module")
def scan():
    return load_config().scans["ep_day"]


def row(ticker, **overrides):
    # Exactly on every EP-Day threshold: gap 10 %, RVOL 3, 300K shares, $1, $50M.
    base = {
        "ticker": ticker,
        "gap_pct": 10.0,
        "rvol50": 3.0,
        "volume": 300_000,
        "close": 1.0,
        "market_cap": 50_000_000,
    }
    return base | overrides


def tickers(df, scan):
    return ep_day(pd.DataFrame(df), scan)["ticker"].tolist()


def test_thresholds_are_inclusive(scan):
    assert tickers([row("EDGE")], scan) == ["EDGE"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"gap_pct": 9.99},
        {"rvol50": 2.99},
        {"rvol50": math.nan},
        {"volume": 299_999},
        {"close": 0.99},
        {"market_cap": 49_999_999},
    ],
)
def test_each_filter_rejects(scan, overrides):
    assert tickers([row("MISS", **overrides)], scan) == []


def test_ranked_by_gap(scan):
    df = [row("B", gap_pct=12.0), row("A", gap_pct=25.0), row("C", gap_pct=12.0)]
    hits = ep_day(pd.DataFrame(df), scan)
    assert hits["ticker"].tolist() == ["A", "B", "C"]
    assert hits["rank"].tolist() == [1, 2, 3]


def test_run_scans_picks_enabled_eod_scans():
    results = run_scans(pd.DataFrame([row("X")]), load_config(), "eod")
    assert list(results) == ["ep_day"]
    assert run_scans(pd.DataFrame([row("X")]), load_config(), "pm") == {}
