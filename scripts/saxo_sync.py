"""Read your Saxo positions and working stop orders into the data repo (Emil, 22 Oct 2026;
docs/SAXO.md). Read-only: nothing is sent to Saxo but GET requests.

uv run python scripts/saxo_sync.py --check                              # does the token work?
uv run python scripts/saxo_sync.py --data-dir ../trading-os-data        # save them

Needs SAXO_TOKEN (and SAXO_ENV=sim for the simulation account). Prints counts only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

from trading_os import saxo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    parser.add_argument("--check", action="store_true", help="test the token, save nothing")
    args = parser.parse_args(argv)
    if not os.environ.get("SAXO_TOKEN"):
        print("No SAXO_TOKEN: see docs/SAXO.md.")
        return 1
    client = saxo.client_from_env(dict(os.environ))
    client.me()
    positions = saxo.positions_frame(client.positions())
    stops = saxo.stop_orders(client.orders())
    print(f"Saxo: connected · {len(positions)} positions · {len(stops)} stop orders")
    if args.check:
        return 0
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required to save")
    saxo.save(args.data_dir, positions, stops, dt.datetime.now())
    print("Saxo: saved to data/journal/broker/ (use Save & push on the dashboard)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
