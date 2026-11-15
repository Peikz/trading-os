"""Resumable options-volume collector (Massive), see trading_os/options_volume.py.

uv run python scripts/options_volume.py --data-dir ../trading-os-data --minutes 330
Needs MASSIVE_API_KEY. Runs on GitHub (options-volume.yml), chaining itself until done.
"""

from trading_os.options_volume import main

if __name__ == "__main__":
    raise SystemExit(main())
