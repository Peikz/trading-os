"""One retry for transient network errors (TradingView, ntfy).

A single blip should not break the "10 trading days without manual intervention" goal
(SPEC §9), but jobs never loop on an external service (CLAUDE.md, rate limits).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import requests

from trading_os.logsafe import status


def once_more[T](
    call: Callable[[], T],
    *,
    label: str,
    wait_s: float,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `call`; on a requests error wait `wait_s` seconds and try exactly once more."""
    try:
        return call()
    except requests.RequestException as exc:
        status(f"{label}: {type(exc).__name__}, retrying once in {wait_s:.0f}s")
        sleep(wait_s)
        return call()
