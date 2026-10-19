"""Build <data-dir>/trading_os.duckdb with views over the Parquet files (local use).

uv run --group analysis python scripts/build_duckdb.py --data-dir ../trading-os-data
"""

from trading_os.duckdb_views import main

if __name__ == "__main__":
    raise SystemExit(main())
