"""Intraday checks: EP9M pace and the EP gap at 10:15, EP9M pace at 12:00, EP after hours at 16:50
New York (Emil, 19-21 Oct 2026); the 15:45 EP close check runs by hand only.

uv run python scripts/intraday.py --data-dir ../trading-os-data      # scheduled: slot by time
uv run python scripts/intraday.py --data-dir ../trading-os-data --slot mid --force --no-push
"""

import argparse
import datetime as dt

from trading_os import clock
from trading_os.config import INTRADAY_SLOTS, load_config
from trading_os.job import main
from trading_os.notify import SLOT_LABELS


def pick_slot(argv: list[str] | None = None) -> tuple[str, list[str]]:
    """`--slot` if given, else the check whose New York window contains now (else 10:15,
    which the time guard then turns away)."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--slot", choices=INTRADAY_SLOTS)
    known, rest = parser.parse_known_args(argv)
    if known.slot:
        return known.slot, rest
    schedule, now = load_config().schedule, dt.datetime.now(dt.UTC)
    slot = next((s for s in INTRADAY_SLOTS if clock.in_window(schedule, s, now)), "am")
    return slot, rest


if __name__ == "__main__":
    slot, rest = pick_slot()
    raise SystemExit(main(slot, SLOT_LABELS[slot], __doc__.splitlines()[0], rest))
