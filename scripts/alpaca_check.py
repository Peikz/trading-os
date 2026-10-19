"""Alpaca market data access check (counts only): history depth, minute bars, delisted names.

ALPACA_API_KEY_ID=... ALPACA_API_SECRET_KEY=... uv run python scripts/alpaca_check.py
"""

import sys

from trading_os.alpaca import main

if __name__ == "__main__":
    raise SystemExit(main(["--check", *sys.argv[1:]]))
