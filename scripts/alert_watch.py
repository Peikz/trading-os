"""Price-alert watcher (Emil, 22 Oct 2026): every minute of the regular session, live prices for
last close's BO-Watch and MA-surf pivots, your open positions' stops and your own dashboard
alerts; one ntfy push per event (`trading_os/alerts.py`). Runs on the PC for now, later on the
server: `scripts\\start_alerts.ps1`. Facts only; nothing places orders.

uv run python scripts/alert_watch.py --data-dir ../trading-os-data          # runs until stopped
uv run python scripts/alert_watch.py --data-dir ../trading-os-data --once   # one check now

Needs ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY and NTFY_TOPIC in the environment
(`scripts\\set_local_secrets.ps1`). Prints times and counts only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import time
from pathlib import Path

import pandas as pd

from trading_os import alerts, clock, dashboard, notify
from trading_os.alpaca import AlpacaClient
from trading_os.config import load_config
from trading_os.logsafe import status

OPEN, CLOSE = dt.time(9, 30), dt.time(16, 0)  # the regular session, New York
REFRESH_S = 300  # the watch list is rebuilt every 5 minutes (new alerts, a journal rebuild)


def last_close_candidates(data_dir: Path, cfg, session: dt.date) -> pd.DataFrame:
    last = clock.previous_session(cfg.schedule, session)
    path = Path(data_dir) / "data" / "candidates" / str(last.year) / f"{last}_eod.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def watch_list(data_dir: Path, cfg, session: dt.date) -> pd.DataFrame:
    return pd.concat(
        [
            alerts.pivot_items(last_close_candidates(data_dir, cfg, session), session),
            alerts.stop_items(dashboard.latest_positions(data_dir), session),
            alerts.own_items(alerts.current(data_dir)),
        ],
        ignore_index=True,
    )


def check(data_dir: Path, cfg, client, session: dt.date, items: pd.DataFrame, push) -> int:
    """One pass: prices, new hits, one push each. Returns how many fired."""
    if items.empty:
        return 0
    prices = client.latest_prices(items["ticker"])
    done = {h["key"] for h in alerts.fired(data_dir, session)}
    found = alerts.hits(items, prices, done)
    now = dt.datetime.now(dt.UTC)
    for hit in found.to_dict("records"):
        title, body = alerts.message(hit, clock.both_times(now))
        push(title, body)
        alerts.record(data_dir, session, hit | {"fired_ts": now.isoformat()})
        if hit["kind"] == "mine":
            alerts.end(data_dir, hit["key"].removeprefix("mine:"), action="fired")
    return len(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    parser.add_argument("--once", action="store_true", help="one check now, then stop")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")
    keys = [os.environ.get(k, "") for k in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")]
    topic = os.environ.get("NTFY_TOPIC", "")
    if not all(keys) or not (topic or args.no_push):
        print("Missing keys: run scripts\\set_local_secrets.ps1 first.")
        return 1
    cfg = load_config()
    client = AlpacaClient(*keys, per_minute=60)

    def push(title: str, body: str) -> None:
        if args.no_push:
            return
        notify.send(cfg.notify["server"], topic, notify.Message(f"Trading OS · {title}", body))

    items, built, day = pd.DataFrame(), 0.0, None
    while True:
        now = clock.ny_time(cfg.schedule, dt.datetime.now(dt.UTC))
        session = now.date()
        live = clock.is_session(cfg.schedule, session) and OPEN <= now.time() < CLOSE
        if session != day:  # a new day: last night's EOD hits and today's journal
            ok, _ = dashboard.pull(args.data_dir)
            status(f"Alerts {now:%Y-%m-%d}: data repo {'pulled' if ok else 'pull FAILED'}")
            day, built = session, 0.0
        if live or args.once:
            if time.monotonic() - built > REFRESH_S:
                items, built = watch_list(args.data_dir, cfg, session), time.monotonic()
                kinds = items["kind"].value_counts().to_dict() if len(items) else {}
                status(f"Alerts {now:%H:%M} NY: watching {len(items)} {kinds}")
            try:
                n = check(args.data_dir, cfg, client, session, items, push)
                if n:
                    status(f"Alerts {now:%H:%M} NY: {n} sent")
            except Exception as exc:  # noqa: BLE001 - one missed minute; try the next one
                status(f"Alerts {now:%H:%M} NY: check FAILED ({type(exc).__name__})")
        if args.once:
            return 0
        time.sleep(args.interval if live else 60)


if __name__ == "__main__":
    raise SystemExit(main())
