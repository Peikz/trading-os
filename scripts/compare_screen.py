"""Compare a scan with a TradingView screener CSV export. LOCAL USE ONLY (prints tickers).

    uv run python scripts/compare_screen.py \
        --run ../trading-os-data/data/candidates/2026/2026-10-19_eod.parquet \
        --csv ~/Downloads/ep_day.csv --append-to ../trading-os-data/docs/validation.md
"""

from trading_os.validation import main

if __name__ == "__main__":
    raise SystemExit(main())
