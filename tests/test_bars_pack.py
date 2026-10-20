"""The compact 2-year bars file (synthetic data only)."""

import datetime as dt

import pandas as pd

from trading_os import bars_pack, history


def test_pack_keeps_the_newest_sessions_slim_and_sorted(tmp_path):
    days = [dt.date(2026, 10, d) for d in (13, 14, 15, 16)]
    for day in days:
        path = history.bars_path(tmp_path, "massive", day)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "session_date": [day, day, day],
                "ticker": ["ZZQ", "AAQ", "AAQQW"],  # a 5-letter W: a warrant, left out
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 10.0,
                "vwap": 1.0,
                "source": "massive",
                "fetched_ts": pd.Timestamp("2026-10-17", tz="UTC"),
            }
        ).to_parquet(path)
    packed = bars_pack.pack(tmp_path, sessions=3)
    assert sorted(set(packed["session_date"])) == days[1:]
    assert packed["ticker"].tolist()[:3] == ["AAQ", "AAQ", "AAQ"]  # sorted by ticker
    assert "AAQQW" not in set(packed["ticker"]) and list(packed.columns) == bars_pack.COLUMNS
    assert str(packed["close"].dtype) == "float32"
