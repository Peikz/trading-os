"""Pre-market job (SPEC §3: 07:30 New York, 13:30 Copenhagen).

uv run python scripts/premarket.py --data-dir ../trading-os-data             # scheduled
uv run python scripts/premarket.py --data-dir ../trading-os-data --force --no-push   # manual
"""

from trading_os.job import main

if __name__ == "__main__":
    raise SystemExit(main("pm", "Pre-market", __doc__.splitlines()[0]))
