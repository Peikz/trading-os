"""Extra data for the EP history study from Massive (Emil, 19 Oct 2026), fetched slowly.

The free plan allows 5 calls a minute, so this job works through a priority list, saves as it
goes, and picks up where it stopped on the next run (nightly on GitHub, outside the scan
windows). Everything lands in the private data repo under `data/ep_enrich/`:

- `tickers.parquet`: every stock ticker, active and delisted (type, exchange, CIK, dates)
- `minutes/YYYY/<date>_<ticker>.parquet`: 1-minute bars incl. pre/post-market for the session
  before the EP, the EP day and the session after (the intraday entry study)
- `short_interest/`, `details/`, `news/`: short interest history per ticker; market cap and
  shares as of the session before each EP; the headlines from the prior close to the EP close

Priority: the alert-tier EP-Day events first, then the rest of EP-Day. EP9M (mostly mega caps
every day) is left out.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pandas as pd
import requests

from trading_os.logsafe import status
from trading_os.metrics import NEW_YORK
from trading_os.store import PARQUET_OPTIONS

KINDS = ("tickers", "minutes", "short_interest", "details", "news")
# Minute bars now come from Alpaca (alpaca.ep_minutes: whole days in a few requests); Massive's
# 5 calls a minute go to what only Massive has.
FETCH_MINUTES = False
FLUSH_EVERY = 100


def root(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "ep_enrich"


def minutes_path(data_dir: Path, day: dt.date, ticker: str) -> Path:
    safe = ticker.replace("/", "-").replace(".", "-")
    return root(data_dir) / "minutes" / str(day.year) / f"{day.isoformat()}_{safe}.parquet"


def latest_study(data_dir: Path) -> pd.DataFrame:
    built = sorted((Path(data_dir) / "data" / "ep_history").glob("ep_history_*.parquet"))
    if not built:
        return pd.DataFrame()
    df = pd.read_parquet(built[-1], columns=["session_date", "ticker", "is_ep_day", "tier"])
    df["session_date"] = pd.to_datetime(df["session_date"]).dt.date
    return df


def events(study: pd.DataFrame) -> pd.DataFrame:
    """EP-Day events in fetch order: alert tier first, newest first within a tier."""
    ep = study[study["is_ep_day"]].copy()
    ep["order"] = (ep["tier"] != "alert").astype(int)
    return ep.sort_values(["order", "session_date"], ascending=[True, False]).reset_index(drop=True)


def _done_keys(folder: Path, columns: list[str]) -> set[tuple]:
    files = list(folder.glob("*.parquet"))
    if not files:
        return set()
    seen = pd.concat([pd.read_parquet(f, columns=columns) for f in files], ignore_index=True)
    if "session_date" in seen:
        seen["session_date"] = pd.to_datetime(seen["session_date"]).dt.date
    return set(map(tuple, seen[columns].drop_duplicates().itertuples(index=False)))


class Batch:
    """Rows for one kind, written as `<run>_<part>.parquet` every FLUSH_EVERY items."""

    def __init__(self, folder: Path, run: str) -> None:
        self.folder, self.run, self.rows, self.part = folder, run, [], 0

    def add(self, rows: list[dict]) -> None:
        self.rows += rows
        if len(self.rows) >= FLUSH_EVERY:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{self.run}_{self.part:03d}.parquet"
        frame = pd.DataFrame(self.rows)
        for column in frame.columns:  # mixed None/str columns stay strings for parquet
            if frame[column].dtype == object:
                frame[column] = frame[column].astype("string")
        tmp = path.with_name(path.name + ".tmp")
        frame.to_parquet(tmp, **PARQUET_OPTIONS)
        tmp.rename(path)
        self.rows, self.part = [], self.part + 1


def _news_window(day: dt.date, previous: dt.date) -> tuple[str, str]:
    """From the prior session's close to the EP day's close, in UTC ISO."""
    start = pd.Timestamp(f"{previous} 16:00", tz=NEW_YORK).tz_convert("UTC")
    end = pd.Timestamp(f"{day} 16:00", tz=NEW_YORK).tz_convert("UTC")
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def tasks(data_dir: Path, study: pd.DataFrame, sessions: list[dt.date]) -> Iterator[tuple]:
    """(kind, payload) still to fetch, in priority order."""
    base = root(data_dir)
    if not (base / "tickers.parquet").exists():
        yield "tickers", None
    ep = events(study)
    index = {d: i for i, d in enumerate(sessions)}
    alert, rest = ep[ep["tier"] == "alert"], ep[ep["tier"] != "alert"]
    shorts_done = {k[0] for k in _done_keys(base / "short_interest", ["ticker"])}
    details_done = _done_keys(base / "details", ["ticker", "session_date"])
    news_done = _done_keys(base / "news", ["ticker", "session_date"])

    def around(day):
        i = index.get(day)
        if i is None or i == 0:
            return None
        return sessions[i - 1], sessions[min(i + 1, len(sessions) - 1)]

    for part in (alert, rest):
        for row in part.itertuples():
            span = around(row.session_date)
            fresh = not minutes_path(data_dir, row.session_date, row.ticker).exists()
            if FETCH_MINUTES and span and fresh:
                yield "minutes", (row.ticker, row.session_date, *span)
        if part is alert:
            for ticker in dict.fromkeys(part["ticker"]):
                if ticker not in shorts_done:
                    yield "short_interest", ticker
        for row in part.itertuples():
            span = around(row.session_date)
            if span and (row.ticker, row.session_date) not in details_done:
                yield "details", (row.ticker, row.session_date, span[0])
        for row in part.itertuples():
            span = around(row.session_date)
            if span and (row.ticker, row.session_date) not in news_done:
                yield "news", (row.ticker, row.session_date, span[0])
    for ticker in dict.fromkeys(rest["ticker"]):
        if ticker not in shorts_done and ticker not in set(alert["ticker"]):
            yield "short_interest", ticker


def run(
    data_dir: Path,
    client,
    sessions: list[dt.date],
    *,
    max_calls: int,
    deadline: float,
    clock: Callable[[], float] = time.time,
) -> dict[str, int]:
    """Fetch until the call budget or the deadline; returns items done per kind."""
    study = latest_study(data_dir)
    if study.empty:
        status("EP enrich: no EP history built yet")
        return {}
    base = root(data_dir)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S")
    batches = {k: Batch(base / k, stamp) for k in ("short_interest", "details", "news")}
    done = dict.fromkeys(KINDS, 0)
    failed = 0
    calls = 0
    for kind, payload in tasks(data_dir, study, sessions):
        if calls >= max_calls or clock() >= deadline:
            break
        try:
            if kind == "tickers":
                rows = client.tickers(active=True) + client.tickers(active=False)
                calls += max(2, len(rows) // 1000 + 2)
                frame = pd.DataFrame(rows)
                base.mkdir(parents=True, exist_ok=True)
                for column in frame.columns:
                    if frame[column].dtype == object:
                        frame[column] = frame[column].astype("string")
                frame.to_parquet(base / "tickers.parquet", **PARQUET_OPTIONS)
            elif kind == "minutes":
                ticker, day, start, end = payload
                bars = client.minute_bars(ticker, start, end)
                calls += 1
                path = minutes_path(data_dir, day, ticker)
                path.parent.mkdir(parents=True, exist_ok=True)
                bars.to_parquet(path, **PARQUET_OPTIONS)  # empty file = nothing traded
            elif kind == "short_interest":
                rows = [{**r, "ticker": payload} for r in client.short_interest(payload)]
                calls += 1
                batches[kind].add(rows or [{"ticker": payload, "settlement_date": None}])
            elif kind == "details":
                ticker, day, as_of = payload
                info = client.ticker_details(ticker, as_of)
                calls += 1
                keep = {
                    k: info.get(k)
                    for k in (
                        "market_cap",
                        "share_class_shares_outstanding",
                        "weighted_shares_outstanding",
                        "list_date",
                        "sic_description",
                        "type",
                        "primary_exchange",
                        "cik",
                    )
                }
                batches[kind].add([{"ticker": ticker, "session_date": day, "as_of": as_of} | keep])
            elif kind == "news":
                ticker, day, previous = payload
                start, end = _news_window(day, previous)
                items = client.news_between(ticker, start, end)
                calls += 1
                rows = [{"ticker": ticker, "session_date": day} | item for item in items]
                batches[kind].add(rows or [{"ticker": ticker, "session_date": day, "title": None}])
            done[kind] += 1
        except requests.HTTPError as exc:
            calls += 1
            failed += 1
            code = exc.response.status_code if exc.response is not None else "?"
            if code in (404,):  # unknown ticker or date: record it so it isn't asked again
                if kind == "details":
                    ticker, day, as_of = payload
                    batches[kind].add([{"ticker": ticker, "session_date": day, "as_of": as_of}])
                elif kind == "minutes":
                    path = minutes_path(data_dir, payload[1], payload[0])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    pd.DataFrame(columns=["ticker", "ts"]).to_parquet(path, **PARQUET_OPTIONS)
            elif failed > 20:
                status(f"EP enrich: stopping after {failed} errors (last HTTP {code})")
                break
    for batch in batches.values():
        batch.flush()
    status(f"EP enrich: {done} in {calls} calls, {failed} errors")
    return done


def deadline(now: float, minutes: float, until: str | None) -> float:
    """The earlier of now + `minutes` and the next `until` (UTC HH:MM), as a timestamp."""
    end = now + minutes * 60
    if until:
        hour, minute = (int(x) for x in until.split(":"))
        today = dt.datetime.fromtimestamp(now, dt.UTC).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        stop = today if today.timestamp() > now else today + dt.timedelta(days=1)
        end = min(end, stop.timestamp())
    return end


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from trading_os.config import load_config
    from trading_os.massive import MassiveClient, RateLimiter

    parser = argparse.ArgumentParser(description="Massive extras for the EP history study")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, default=1700)
    parser.add_argument("--minutes", type=float, default=340, help="stop after this many")
    parser.add_argument("--until", help="stop at this UTC time (HH:MM), whichever comes first")
    args = parser.parse_args(argv)
    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        status("EP enrich: MASSIVE_API_KEY not set")
        return 1
    cfg = load_config()
    client = MassiveClient(
        key, cfg.history["massive_base_url"], RateLimiter(cfg.history["calls_per_minute"])
    )
    files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
    sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
    from trading_os.logsafe import run_guarded

    def fetch() -> int:
        run(
            args.data_dir,
            client,
            sessions,
            max_calls=args.max_calls,
            deadline=deadline(time.time(), args.minutes, args.until),
        )
        return 0

    # Errors can carry a URL with a ticker in it: logs are public, so redact.
    return run_guarded(fetch, args.data_dir / "logs", "EP enrich")
