"""Market diary: the day's market context as data in the private data repo (facts only).

uv run python scripts/market_diary.py --data-dir ../trading-os-data [--date D] [--from A --to B]
"""

from trading_os.market_diary import main

if __name__ == "__main__":
    raise SystemExit(main())
