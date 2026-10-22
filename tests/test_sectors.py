"""Indexes and sectors: one fetch, returns against SPY, the rotation quadrant and industry rank
moves (synthetic data only)."""

import pandas as pd

from trading_os import sectors


def fake_details(symbols, fields):
    rows = {
        "AMEX:SPY": {"close": 600, "change": 0.5, "Perf.W": 1.0, "Perf.1M": 2.0, "SMA50": 590,
                     "SMA200": 550},
        "AMEX:XLK": {"close": 250, "change": 1.0, "Perf.W": 3.0, "Perf.1M": 6.0, "SMA50": 240,
                     "SMA200": 220},
        "AMEX:XLP": {"close": 80, "change": -0.2, "Perf.W": 2.0, "Perf.1M": -1.0, "SMA50": 82,
                     "SMA200": 78},
        "AMEX:XLE": {"close": 90, "change": -1.0, "Perf.W": -2.0, "Perf.1M": 5.0, "SMA50": 85,
                     "SMA200": 95},
        "AMEX:XLU": {"close": 70, "change": -0.5, "Perf.W": -1.0, "Perf.1M": -3.0, "SMA50": 72,
                     "SMA200": 74},
    }  # fmt: skip
    assert len(symbols) == len(sectors.ETFS)  # one request for all of them
    return pd.DataFrame.from_dict(rows, orient="index")


def test_rotation_quadrants_against_spy():
    table = sectors.rotation(sectors.fetch(fake_details)).set_index("ticker")
    assert table.loc["XLK", "quadrant"] == "Leading"  # ahead on the month and the week
    assert table.loc["XLE", "quadrant"] == "Weakening"  # ahead on the month, behind this week
    assert table.loc["XLU", "quadrant"] == "Lagging"
    assert table.loc["XLP", "quadrant"] == "Improving"  # behind on the month, ahead this week
    assert table.loc["XLK", "vs_spy_1m"] == 4.0
    assert table.loc["XLE", "trend"] == "over 50d, under 200d"


def test_industry_rank_moves():
    now = pd.DataFrame(
        {"industry": ["a", "b", "c"], "sector": ["s"] * 3, "industry_rank": [1, 2, 3],
         "members": [5] * 3, "med_ret_22": [9.0, 5.0, 1.0], "med_ret_63": [20.0, 10.0, 2.0]}
    )  # fmt: skip
    before = pd.DataFrame({"industry": ["a", "b", "c"], "industry_rank": [3, 2, 1]})
    moved = sectors.industry_moves(now, before).set_index("industry")["moved"]
    assert moved.to_dict() == {"a": 2, "b": 0, "c": -2}
