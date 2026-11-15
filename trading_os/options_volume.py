"""Options volume around signal days from Massive (Emil, 15 Nov 2026), fetched slowly.

Input (private data repo): `data/research/options_targets.parquet` with ticker, day, ref_price.
For each target, oldest day first: one contract list (the 3 nearest expirations within 60 days,
strikes within 20 % of the reference price), then one daily-bars call per contract for the 30
days up to the target day. Output: `data/research/options_volume/{day}_{ticker}.parquet`; a
target with nothing still gets an empty file so it is not retried. Resumable: existing files
are skipped. This repo is public: logs carry counts only.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import requests

from trading_os.logsafe import status
from trading_os.store import PARQUET_OPTIONS

COLUMNS = [
    "contract",
    "underlying",
    "day",
    "contract_type",
    "strike",
    "expiration",
    "bar_date",
    "volume",
    "close",
    "vwap",
    "transactions",
]
NEAREST_EXPIRATIONS = 3
EXPIRY_WINDOW_DAYS = 60
STRIKE_BAND = 0.2
BAR_LOOKBACK_DAYS = 30


def targets_path(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "research" / "options_targets.parquet"


def out_path(data_dir: Path, day: str, ticker: str) -> Path:
    safe = ticker.replace("/", "-").replace(".", "-")
    return Path(data_dir) / "data" / "research" / "options_volume" / f"{day}_{safe}.parquet"


def contract_params(ticker: str, day: dt.date, ref_price: float) -> dict:
    return {
        "underlying_ticker": ticker,
        "as_of": day.isoformat(),
        "expiration_date.gt": day.isoformat(),
        "expiration_date.lte": (day + dt.timedelta(days=EXPIRY_WINDOW_DAYS)).isoformat(),
        "strike_price.gte": round((1 - STRIKE_BAND) * ref_price, 4),
        "strike_price.lte": round((1 + STRIKE_BAND) * ref_price, 4),
        "limit": 1000,
    }


def nearest_expirations(contracts: list[dict], count: int = NEAREST_EXPIRATIONS) -> list[dict]:
    """Keep the contracts of the `count` earliest expiration dates."""
    keep = set(sorted({c["expiration_date"] for c in contracts})[:count])
    return [c for c in contracts if c["expiration_date"] in keep]


def pending(data_dir: Path) -> list[tuple[str, str, float]]:
    """(day, ticker, ref_price) without an output file yet, oldest day first."""
    path = targets_path(data_dir)
    if not path.exists():
        return []
    df = pd.read_parquet(path, columns=["ticker", "day", "ref_price"])
    df = df.drop_duplicates(["ticker", "day"]).sort_values(["day", "ticker"], kind="stable")
    return [
        (str(r.day), str(r.ticker), float(r.ref_price))
        for r in df.itertuples()
        if not out_path(data_dir, str(r.day), str(r.ticker)).exists()
    ]


def _write(path: Path, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows, columns=COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    frame.to_parquet(tmp, **PARQUET_OPTIONS)
    tmp.replace(path)


def fetch_target(client, day: str, ticker: str, ref_price: float) -> tuple[list[dict], int]:
    """Rows and calls used for one target."""
    when = dt.date.fromisoformat(day)
    contracts, calls = client.option_contracts(contract_params(ticker, when, ref_price))
    rows: list[dict] = []
    start = when - dt.timedelta(days=BAR_LOOKBACK_DAYS)
    for contract in nearest_expirations(contracts):
        symbol = contract["ticker"]
        try:
            bars = client.daily_bars(symbol, start, when)
        except requests.HTTPError as exc:
            calls += 1
            if exc.response is not None and exc.response.status_code == 403:
                continue  # outside the plan's history window: zero bars
            raise
        calls += 1
        for bar in bars:
            bar_date = dt.datetime.fromtimestamp(bar["t"] / 1000, dt.UTC).date().isoformat()
            rows.append(
                {
                    "contract": symbol,
                    "underlying": ticker,
                    "day": day,
                    "contract_type": contract.get("contract_type"),
                    "strike": contract.get("strike_price"),
                    "expiration": contract.get("expiration_date"),
                    "bar_date": bar_date,
                    "volume": bar.get("v"),
                    "close": bar.get("c"),
                    "vwap": bar.get("vw"),
                    "transactions": bar.get("n"),
                }
            )
    return rows, calls


def run(
    data_dir: Path,
    client,
    *,
    deadline: float,
    clock: Callable[[], float] = time.time,
) -> tuple[int, int, int]:
    """Fetch until the deadline (checked between targets); returns (done, calls, remaining)."""
    todo = pending(data_dir)
    done = calls = 0
    for day, ticker, ref_price in todo:
        if clock() >= deadline:
            break
        rows, used = fetch_target(client, day, ticker, ref_price)
        _write(out_path(data_dir, day, ticker), rows)
        done += 1
        calls += used
    remaining = len(todo) - done
    status(f"Options volume: {done} targets done this run, {calls} calls, {remaining} targets left")
    return done, calls, remaining


def main(argv: list[str] | None = None) -> int:
    import argparse

    from trading_os.config import load_config
    from trading_os.logsafe import run_guarded
    from trading_os.massive import MassiveClient, RateLimiter

    parser = argparse.ArgumentParser(description="Options volume collector (Massive)")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=330, help="stop starting targets after")
    args = parser.parse_args(argv)
    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        status("Options volume: MASSIVE_API_KEY not set")
        return 1
    cfg = load_config()
    client = MassiveClient(
        key, cfg.history["massive_base_url"], RateLimiter(cfg.history["calls_per_minute"])
    )

    def fetch() -> int:
        _, _, remaining = run(args.data_dir, client, deadline=time.time() + args.minutes * 60)
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as handle:
                handle.write(f"remaining={remaining}\n")
        return 0

    # Errors can carry a URL with a ticker in it: logs are public, so redact.
    return run_guarded(fetch, args.data_dir / "logs", "Options volume")
