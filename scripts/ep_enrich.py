"""Massive extras for the EP history study, fetched slowly and resumably (Emil, 19 Oct 2026).

uv run python scripts/ep_enrich.py --data-dir ../trading-os-data --max-calls 1700 --minutes 340
Needs MASSIVE_API_KEY. Runs nightly on GitHub (ep-enrich.yml) until everything is in.
"""

from trading_os.ep_enrich import main

if __name__ == "__main__":
    raise SystemExit(main())
