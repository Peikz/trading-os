"""Breakout hand-audit sheet from a replay over Massive history (Phase 2). LOCAL USE ONLY.

uv run python scripts/audit_breakouts.py --data-dir ../trading-os-data [--n 20 --replay-days 60]
"""

from trading_os.audit import main

if __name__ == "__main__":
    raise SystemExit(main())
