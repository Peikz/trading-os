"""Outcomes job (SPEC §3, Phase 3): daily after the EOD job.

uv run python scripts/outcomes.py --data-dir ../trading-os-data
"""

from trading_os.outcomes import main

if __name__ == "__main__":
    raise SystemExit(main())
