import datetime as dt

import pandas as pd
import pytest

from trading_os import history
from trading_os.store import AlreadyWritten

D1, D2, D3 = dt.date(2026, 10, 14), dt.date(2026, 10, 15), dt.date(2026, 10, 16)


def massive_bars(session, close):
    return pd.DataFrame(
        {
            "session_date": [session],
            "ticker": ["AAA"],
            "open": [close - 1],
            "high": [close + 1],
            "low": [close - 2],
            "close": [close],
            "volume": [1_000.0],
            "vwap": [close],
            "trades": pd.array([10], dtype="Int64"),
            "source": ["massive"],
            "adjusted": [True],
            "fetched_ts": [pd.Timestamp("2026-10-18 12:00", tz="UTC")],
        }
    )


def write_snapshot(data_dir, session, close):
    snap = pd.DataFrame(
        {
            "run_ts": [pd.Timestamp(f"{session} 20:17", tz="UTC")],
            "session_date": [pd.Timestamp(session)],
            "ticker": ["AAA"],
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "volume": [500],
            "gap_pct": [0.0],
        }
    )
    path = history.universe_snapshot_path(data_dir, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    snap.to_parquet(path, index=False)


def test_write_bars_is_append_only(tmp_path):
    history.write_bars(tmp_path, "massive", D1, massive_bars(D1, 10.0))
    assert history.have_bars(tmp_path, "massive", D1)
    with pytest.raises(AlreadyWritten):
        history.write_bars(tmp_path, "massive", D1, massive_bars(D1, 11.0))


def test_load_prefers_massive_then_snapshots_and_skips_gaps(tmp_path):
    history.write_bars(tmp_path, "massive", D1, massive_bars(D1, 10.0))
    write_snapshot(tmp_path, D1, 99.0)  # ignored: Massive wins for D1
    write_snapshot(tmp_path, D3, 12.0)  # D2 has neither source
    bars = history.load_bars(tmp_path, [D1, D2, D3])
    assert bars["session_date"].tolist() == [D1, D3]
    assert bars["close"].tolist() == [10.0, 12.0]
    assert bars["source"].tolist() == ["massive", "tradingview"]
    assert list(bars.columns) == history.BAR_COLUMNS


def test_load_with_no_data_is_empty(tmp_path):
    bars = history.load_bars(tmp_path, [D1])
    assert bars.empty and list(bars.columns) == history.BAR_COLUMNS
