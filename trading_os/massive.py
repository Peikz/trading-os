"""Massive (formerly Polygon.io) grouped daily bars, rate limited (SPEC §2, Phase 2).

One call returns every US stock for one session. The API key travels in the Authorization
header, never in a URL, so it can't end up in a log line or an exception message.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable

import pandas as pd
import requests

from trading_os.history import BAR_COLUMNS

GROUPED_DAILY = "/v2/aggs/grouped/locale/us/market/stocks/{day}"
_FIELD_MAP = {
    "T": "ticker",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "vw": "vwap",
    "n": "trades",
}
_OK_STATUSES = {"OK", "DELAYED"}


class MassiveError(RuntimeError):
    """Massive answered, but not with usable data."""


class RateLimiter:
    """At most `calls_per_minute` calls, spaced evenly."""

    def __init__(
        self,
        calls_per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = 60.0 / calls_per_minute
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


class MassiveClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        limiter: RateLimiter,
        *,
        session: requests.Session | None = None,
        timeout: float = 30,
    ) -> None:
        if not api_key:
            raise ValueError("Massive API key is empty")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._base = base_url.rstrip("/")
        self._limiter = limiter
        self._http = session or requests.Session()
        self._timeout = timeout

    def grouped_daily(self, day: dt.date, *, adjusted: bool = True) -> pd.DataFrame:
        """All US stocks' bars for `day`, in the history bars shape. Empty if none yet."""
        self._limiter.wait()
        response = self._http.get(
            self._base + GROUPED_DAILY.format(day=day.isoformat()),
            params={"adjusted": "true" if adjusted else "false"},
            headers=self._headers,
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") not in _OK_STATUSES:
            raise MassiveError(f"grouped daily {day}: status {body.get('status')!r}")
        return to_bars(body.get("results") or [], day, bool(body.get("adjusted", adjusted)))


def to_bars(results: list[dict], day: dt.date, adjusted: bool) -> pd.DataFrame:
    raw = pd.DataFrame(results, columns=list(_FIELD_MAP))
    bars = raw.rename(columns=_FIELD_MAP)
    bars["ticker"] = bars["ticker"].astype("string")
    bars["volume"] = bars["volume"].astype("float64")
    bars["trades"] = bars["trades"].astype("Int64")
    bars["session_date"] = day
    bars["source"] = "massive"
    bars["adjusted"] = adjusted
    bars["fetched_ts"] = pd.Timestamp.now(tz="UTC")
    return bars[BAR_COLUMNS]
