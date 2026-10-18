"""Log hygiene for public Actions logs (SPEC §2, CLAUDE.md hard rules).

Jobs print counts and status only. On failure the public log gets the exception type and the
code location; the exception message, which could quote a ticker or price, goes to the
private data repo only.
"""

from __future__ import annotations

import datetime as dt
import sys
import traceback
from collections.abc import Callable
from pathlib import Path


def status(message: str) -> None:
    """Print a status line. Callers pass counts and states, never tickers or prices."""
    print(message, flush=True)


def redacted_traceback(exc: BaseException) -> str:
    """Traceback frames and the exception type, without the exception message."""
    frames = traceback.format_list(traceback.extract_tb(exc.__traceback__))
    return "Traceback (most recent call last):\n" + "".join(frames) + type(exc).__name__


def run_guarded(main: Callable[[], int], log_dir: Path | None, job: str) -> int:
    """Run `main`; on failure print a redacted traceback and save the full one privately."""
    try:
        return main()
    except Exception as exc:  # noqa: BLE001 - every failure must be reported the same way
        status(f"{job}: FAILED ({type(exc).__name__})")
        print(redacted_traceback(exc), file=sys.stderr, flush=True)
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%SZ")
            path = log_dir / f"{stamp}_{job.lower()}.log"
            path.write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
            status(f"{job}: full traceback saved to the data repo")
        return 1
