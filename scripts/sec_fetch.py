"""SEC EDGAR extras for the EP history study: exact earnings dates and EPS/revenue as filed.

uv run python scripts/sec_fetch.py --data-dir ../trading-os-data --check
uv run python scripts/sec_fetch.py --data-dir ../trading-os-data
"""

from trading_os.sec import main

if __name__ == "__main__":
    raise SystemExit(main())
