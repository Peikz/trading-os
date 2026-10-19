"""Strategy history (Emil, 19 Oct 2026): every scan's alert-tier hits over the Massive bars,
with the market that day and what happened after. Takes about 20 minutes.

uv run python scripts/strategy_history.py --data-dir ../trading-os-data
"""

from trading_os.strategy_history import main

if __name__ == "__main__":
    raise SystemExit(main())
