"""Daily job-openings snapshot (`trading_os.jobs_log`; Emil, 25 Oct 2026). Reads the matched
boards from data/jobs/boards.parquet and writes today's counts once. Public logs: counts only.

uv run python scripts/jobs_log.py --data-dir ../trading-os-data
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

import pandas as pd

from trading_os import jobs_log
from trading_os.logsafe import run_guarded, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")

    def run() -> int:
        today = dt.datetime.now(dt.UTC).date()
        out = jobs_log.snapshot_path(args.data_dir, today)
        if out.exists():
            status("Jobs log: today already saved")
            return 0
        boards = pd.read_parquet(Path(args.data_dir) / "data" / "jobs" / "boards.parquet")
        snap = jobs_log.snapshot(boards, today)
        out.parent.mkdir(parents=True, exist_ok=True)
        snap.to_parquet(out, index=False)
        got = int(snap["open_jobs"].notna().sum())
        status(f"Jobs log: {got} of {len(snap)} boards answered, saved")
        return 0

    return run_guarded(run, Path(args.data_dir) / "logs", "jobs-log")


if __name__ == "__main__":
    raise SystemExit(main())
