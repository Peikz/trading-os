"""EP history study (Emil, 19 Oct 2026): every EP in the Massive bars, with its features and
what happened after, written to the private data repo. LOCAL OR MANUAL RUN.

uv run python scripts/ep_history.py --data-dir ../trading-os-data
uv run python scripts/ep_history.py --data-dir ../trading-os-data --no-fundamentals
"""

from trading_os.ep_history import main

if __name__ == "__main__":
    raise SystemExit(main())
