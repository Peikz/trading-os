import math

import pandas as pd
import pytest

from trading_os.config import load_config
from trading_os.scans.weekly import growth_bucket_1, growth_bucket_2, qm_gainers


@pytest.fixture(scope="module")
def scans():
    return load_config().scans


def gainer_universe():
    # 100 names with returns 0..99 on every window: the top 2 % are the two highest (98, 99).
    rows = []
    for i in range(100):
        rows.append(
            {
                "ticker": f"N{i:03d}",
                "ret_22": float(i),
                "ret_63": float(i),
                "ret_126": float(i),
                "adr20_pct": 5.0,
                "avg_dollar_volume_20d": 20_000_000.0,
                "close": 20.0,
            }
        )
    return pd.DataFrame(rows)


def test_qm_gainers_top_two_percent_of_the_universe(scans):
    hits = qm_gainers(gainer_universe(), scans["qm_gainers"])
    assert hits["ticker"].tolist() == ["N099", "N098"]
    assert hits["qm_lists"].tolist() == ["22d,63d,126d"] * 2
    assert hits["rank"].tolist() == [1, 2]


def test_qm_gainers_floors_apply_after_the_percentile(scans):
    df = gainer_universe()
    df.loc[df["ticker"] == "N099", "adr20_pct"] = 3.99
    df.loc[df["ticker"] == "N098", "close"] = 5.0  # price must be > $5
    assert qm_gainers(df, scans["qm_gainers"]).empty  # N097 doesn't move up into the top 2 %
    df = gainer_universe()
    df.loc[df["ticker"] == "N099", "avg_dollar_volume_20d"] = 9_999_999
    assert qm_gainers(df, scans["qm_gainers"])["ticker"].tolist() == ["N098"]


def test_qm_gainers_merges_lists(scans):
    df = gainer_universe()
    df.loc[df["ticker"] == "N000", "ret_22"] = 500.0  # top on 1M only
    hits = qm_gainers(df, scans["qm_gainers"]).set_index("ticker")
    assert hits.loc["N000", "qm_lists"] == "22d"
    assert hits.loc["N000", "qm_list_count"] == 1
    assert hits.index[0] == "N099"  # more lists rank first


def growth_row(ticker, **kw):
    base = {
        "ticker": ticker,
        "close": 10.01,
        "avg_volume_20d": 200_001,
        "revenue_ttm": 25_000_001,
        "rev_growth_q": 40.0,
        "rev_growth_q_prev": 40.0,
        "eps_growth_q": 40.0,
        "eps_growth_q_prev": 40.0,
    }
    return base | kw


def tickers(fn, scan, *rows):
    return fn(pd.DataFrame(list(rows)), scan)["ticker"].tolist()


def test_growth_bucket_1(scans):
    s = scans["growth_bucket_1"]
    assert tickers(growth_bucket_1, s, growth_row("EDGE")) == ["EDGE"]
    assert tickers(growth_bucket_1, s, growth_row("P10", close=10.0)) == []  # price > $10
    assert tickers(growth_bucket_1, s, growth_row("VOL", avg_volume_20d=100_000)) == []
    assert tickers(growth_bucket_1, s, growth_row("REV", revenue_ttm=25_000_000)) == []
    assert tickers(growth_bucket_1, s, growth_row("Q0", rev_growth_q=39.9)) == []
    assert tickers(growth_bucket_1, s, growth_row("Q1", rev_growth_q_prev=39.9)) == []
    # Previous quarter missing: latest only, recorded as 1 quarter checked.
    hits = growth_bucket_1(pd.DataFrame([growth_row("ONE", rev_growth_q_prev=math.nan)]), s)
    assert hits["growth_quarters_checked"].tolist() == [1]
    assert growth_bucket_1(pd.DataFrame([growth_row("TWO")]), s)[
        "growth_quarters_checked"
    ].tolist() == [2]


def test_growth_bucket_2(scans):
    s = scans["growth_bucket_2"]
    row = growth_row("EDGE", rev_growth_q=20.0, rev_growth_q_prev=20.0)
    assert tickers(growth_bucket_2, s, row) == ["EDGE"]
    assert tickers(growth_bucket_2, s, row | {"avg_volume_20d": 200_000}) == []
    assert tickers(growth_bucket_2, s, row | {"eps_growth_q_prev": 39.9}) == []
    assert tickers(growth_bucket_2, s, row | {"rev_growth_q": 19.9}) == []
    hits = growth_bucket_2(pd.DataFrame([row | {"eps_growth_q_prev": math.nan}]), s)
    assert hits["growth_quarters_checked"].tolist() == [1]
