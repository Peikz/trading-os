import datetime as dt

import pandas as pd
import pytest

from trading_os import duckdb_views

duckdb = pytest.importorskip("duckdb")  # analysis dependency group


def test_views_union_schemas_and_join_outcomes(tmp_path):
    cand_dir = tmp_path / "data" / "candidates" / "2026"
    cand_dir.mkdir(parents=True)
    pd.DataFrame({"signal_id": ["a"], "scan": ["ep_day"], "ticker": ["AAA"]}).to_parquet(
        cand_dir / "2026-10-19_eod.parquet"
    )
    # A later file with an extra column: union_by_name keeps both.
    pd.DataFrame(
        {"signal_id": ["b"], "scan": ["ep9m"], "ticker": ["BBB"], "rvol50": [3.1]}
    ).to_parquet(cand_dir / "2026-10-20_eod.parquet")
    out_dir = tmp_path / "data" / "outcomes" / "2026"
    out_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "signal_id": ["a"],
            "horizon": [5],
            "close_ret_pct": [12.5],
            "max_gain_pct": [20.0],
            "max_drawdown_pct": [-3.0],
            "hit_order_stop": pd.array([pd.NA], dtype="boolean"),
            "computed_ts": [pd.Timestamp(dt.datetime(2026, 10, 26, 22, tzinfo=dt.UTC))],
        }
    ).to_parquet(out_dir / "2026-10-26.parquet")
    db = tmp_path / "t.duckdb"
    created = duckdb_views.build(tmp_path, db)
    assert created == ["candidates", "outcomes", "signals_with_outcomes"]
    with duckdb.connect(str(db)) as con:
        rows = con.sql(
            "select ticker, rvol50, ret_5d from signals_with_outcomes order by ticker"
        ).fetchall()
    assert rows == [("AAA", None, 12.5), ("BBB", 3.1, None)]
