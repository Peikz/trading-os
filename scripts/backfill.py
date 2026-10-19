"""Massive grouped-daily backfill (Phase 2). Needs MASSIVE_API_KEY.

uv run python scripts/backfill.py --data-dir ../trading-os-data --max-calls 10
uv run python scripts/backfill.py --data-dir ../trading-os-data --catchup
"""

from trading_os.backfill import main

if __name__ == "__main__":
    raise SystemExit(main())
