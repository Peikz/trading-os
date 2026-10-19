"""Import broker fills into the trade journal (Phase 4). LOCAL USE ONLY.

    uv run python scripts/import_fills.py --csv ~/Downloads/fills.csv \
        --data-dir ../trading-os-data [--stops stops.csv]
"""

from trading_os.journal import main

if __name__ == "__main__":
    raise SystemExit(main())
