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
NEWS = "/v2/reference/news"
MINUTE_AGGS = "/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}"
TICKERS = "/v3/reference/tickers"
TICKER_DETAILS = "/v3/reference/tickers/{ticker}"
SHORT_INTEREST = "/stocks/v1/short-interest"
RATE_LIMIT_PAUSE_S = 60
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
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("Massive API key is empty")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._base = base_url.rstrip("/")
        self._limiter = limiter
        self._http = session or requests.Session()
        self._timeout = timeout
        self._sleep = sleep

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

    def _get(self, url: str, params: dict | None = None) -> dict:
        """One rate-limited GET (a full `next_url` or a path); a 429 waits a minute, once."""
        for attempt in (1, 2):
            self._limiter.wait()
            full = url if url.startswith("http") else self._base + url
            response = self._http.get(
                full, params=params or {}, headers=self._headers, timeout=self._timeout
            )
            if response.status_code == 429 and attempt == 1:
                self._sleep(RATE_LIMIT_PAUSE_S)
                continue
            response.raise_for_status()
            return response.json()
        raise MassiveError("rate limited twice")

    def _pages(self, path: str, params: dict, max_pages: int) -> list[dict]:
        """Results across `next_url` pages (each page is one call)."""
        body, out = self._get(path, params), []
        out += body.get("results") or []
        for _ in range(max_pages - 1):
            if not body.get("next_url"):
                break
            body = self._get(body["next_url"])
            out += body.get("results") or []
        return out

    def minute_bars(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        """1-minute bars, pre- and post-market included, `start` to `end` (one call)."""
        body = self._get(
            MINUTE_AGGS.format(ticker=ticker, start=start.isoformat(), end=end.isoformat()),
            {"adjusted": "true", "sort": "asc", "limit": 50_000},
        )
        rows = body.get("results") or []
        frame = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "vw", "n"])
        frame = frame.rename(columns={**_FIELD_MAP, "t": "ts"}).drop(columns=["T"], errors="ignore")
        frame["ts"] = pd.to_datetime(frame["ts"], unit="ms", utc=True)
        frame.insert(0, "ticker", ticker)
        return frame

    def tickers(self, *, active: bool, max_pages: int = 60) -> list[dict]:
        """The stock ticker list (1,000 a page), active or delisted: type, exchange, CIK."""
        params = {"market": "stocks", "active": "true" if active else "false", "limit": 1000}
        return self._pages(TICKERS, params, max_pages)

    def short_interest(self, ticker: str, max_pages: int = 5) -> list[dict]:
        """FINRA short interest history (settlement date, shares short, days to cover)."""
        return self._pages(SHORT_INTEREST, {"ticker": ticker, "limit": 50_000}, max_pages)

    def ticker_details(self, ticker: str, day: dt.date) -> dict:
        """Details as of `day`: market cap, shares outstanding, list date, SIC, CIK."""
        return (
            self._get(TICKER_DETAILS.format(ticker=ticker), {"date": day.isoformat()}).get(
                "results"
            )
            or {}
        )

    def news_between(self, ticker: str, start: str, end: str, limit: int = 10) -> list[dict]:
        """Headlines published between two ISO timestamps, oldest first."""
        body = self._get(
            NEWS,
            {
                "ticker": ticker,
                "published_utc.gte": start,
                "published_utc.lte": end,
                "order": "asc",
                "sort": "published_utc",
                "limit": limit,
            },
        )
        return [
            {
                "title": item.get("title", ""),
                "publisher": (item.get("publisher") or {}).get("name", ""),
                "published_utc": item.get("published_utc", ""),
                "url": item.get("article_url", ""),
            }
            for item in body.get("results") or []
        ]

    def probe(self, path: str, params: dict | None = None) -> tuple[int, int]:
        """(HTTP status, number of results) for an endpoint; to see what the plan includes."""
        self._limiter.wait()
        response = self._http.get(
            self._base + path, params=params or {}, headers=self._headers, timeout=self._timeout
        )
        if not response.ok:
            return response.status_code, 0
        results = response.json().get("results")
        count = len(results) if isinstance(results, list) else int(results is not None)
        return response.status_code, count

    def news(self, ticker: str, limit: int = 3) -> list[dict]:
        """Latest headlines for a ticker: title, publisher, published time, url."""
        self._limiter.wait()
        response = self._http.get(
            self._base + NEWS,
            params={"ticker": ticker, "limit": limit, "order": "desc", "sort": "published_utc"},
            headers=self._headers,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return [
            {
                "title": item.get("title", ""),
                "publisher": (item.get("publisher") or {}).get("name", ""),
                "published_utc": item.get("published_utc", ""),
                "url": item.get("article_url", ""),
            }
            for item in response.json().get("results") or []
        ]


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
