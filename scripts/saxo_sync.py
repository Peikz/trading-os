"""Read your Saxo positions and working stop orders into the data repo (Emil, 22 Oct 2026;
docs/SAXO.md). Read-only: nothing is sent to Saxo but GET requests.

uv run python scripts/saxo_sync.py --check                              # does the token work?
uv run python scripts/saxo_sync.py --data-dir ../trading-os-data        # save them
uv run python scripts/saxo_sync.py --data-dir ../trading-os-data --every 30   # keep going

Needs SAXO_TOKEN, or a sign-in from scripts/saxo_login.py (refreshed here as needed; `--every`
keeps the session alive while it runs). SAXO_ENV=sim for the simulation account. Prints counts
only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import time
from pathlib import Path

import requests

from trading_os import saxo, saxo_auth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    parser.add_argument("--check", action="store_true", help="test the token, save nothing")
    parser.add_argument(
        "--every", type=int, metavar="MIN", help="sync again every MIN minutes (under 40 keeps the "
        "sign-in alive) until stopped"
    )  # fmt: skip
    args = parser.parse_args(argv)
    if args.every and not args.check and args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required to save")
    if args.every is not None and not 1 <= args.every < 40:
        parser.error("--every must be 1-39 minutes: Saxo's refresh token lasts 40")
    while True:
        try:
            code = sync(args, parser)
        except requests.RequestException as exc:  # a network blip: the session may still be fine
            if not args.every:
                raise
            print(f"Saxo: {type(exc).__name__}, trying again in {args.every} min")
            code = 0
        if code or not args.every or args.check:
            return code
        time.sleep(args.every * 60)


def sync(args, parser) -> int:
    try:
        client = saxo.client_from_env(dict(os.environ))
    except saxo_auth.SignInNeeded as exc:
        print(f"Saxo: {exc}")
        return 1
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
