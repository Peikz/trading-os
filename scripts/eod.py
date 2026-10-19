"""End-of-day job (SPEC §3: 16:20 New York, 22:20 Copenhagen).

uv run python scripts/eod.py --data-dir ../trading-os-data             # scheduled behaviour
uv run python scripts/eod.py --data-dir ../trading-os-data --force --no-push   # manual test
"""

from trading_os.job import main

if __name__ == "__main__":
    raise SystemExit(main("eod", "EOD", __doc__.splitlines()[0]))
