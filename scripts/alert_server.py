"""Price alerts as a server service (deploy/docker-compose.yml, service `alerts`; Hetzner prep,
Nov 2026). One long-running process: it sleeps until the next regular NYSE session, runs the
same watcher as the GitHub job (`scripts/alert_watch.py`) from 09:25 New York to the close
(13:00 on an early close), then commits and pushes what fired to the data repo, under the
clone's git lock so it never races the `data-sync` service or the API's Save & push.

Off unless ALERTS_ENABLED is true: the server and the GitHub job must never both push the same
alert (deploy/DEPLOY.md, "Price alerts on the server"). Off, it says so once and idles.

uv run python scripts/alert_server.py --data-dir /data            # the service
uv run python scripts/alert_server.py --data-dir /data --check    # next session, then exit

Needs ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY and NTFY_TOPIC (deploy/.env). Prints times and
counts only; nothing places orders.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from trading_os import alert_schedule, dashboard
from trading_os.config import load_config
from trading_os.logsafe import status

ON = {"1", "true", "yes", "on"}
NAP_S = 900.0  # wake at least every 15 minutes while waiting (a clock jump, a restart)
RETRY_S = 60.0  # after the watcher crashed, try again a minute later
COMMIT_PATHS = ("data/my_alerts",)  # what the GitHub job's "Commit what fired" step adds


def enabled(env: Mapping[str, str]) -> bool:
    return env.get("ALERTS_ENABLED", "").strip().lower() in ON


def load_watcher():
    """scripts/alert_watch.py, the GitHub job's watcher (scripts/ is not a package)."""
    path = Path(__file__).resolve().parent / "alert_watch.py"
    spec = importlib.util.spec_from_file_location("alert_watch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def commit_fired(data_dir: Path, session: dt.date, sleep=time.sleep) -> bool:
    ok, out = dashboard.commit_and_push(
        data_dir, COMMIT_PATHS, f"alerts {session}: fired (server)", attempts=3, sleep=sleep
    )
    if out == "nothing new to save":
        status("Data: nothing new to commit")
    else:
        status(f"Data: {'committed and pushed' if ok else 'push FAILED'}")
    return ok


def serve(
    data_dir: Path,
    schedule,
    watch: Callable[[list[str]], int],
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    sleep: Callable[[float], None] = time.sleep,
    commit: Callable[[Path, dt.date], bool] = commit_fired,
) -> int:
    """Wait for each session's window, watch it, commit what fired. Returns only when the
    watcher refuses to start (missing keys)."""
    while True:
        moment = now()
        start, end = alert_schedule.next_window(schedule, moment)
        if moment < start:
            status(f"Alerts server: next watch {start:%a %d %b %H:%M} to {end:%H:%M} NY")
            sleep(min((start - moment).total_seconds(), NAP_S))
            continue
        status(f"Alerts server: watching until {end:%H:%M} NY")
        try:
            code = watch(["--data-dir", str(data_dir), "--until", f"{end:%H:%M}"])
        except Exception as exc:  # noqa: BLE001 - restart the watch, the session goes on
            status(f"Alerts server: watcher FAILED ({type(exc).__name__}), again in a minute")
            commit(data_dir, start.date())
            sleep(RETRY_S)
            continue
        commit(data_dir, start.date())
        if code != 0:
            return code
        if now() < end:  # it stopped early without an error: don't spin
            sleep(RETRY_S)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    parser.add_argument("--check", action="store_true", help="print the next watch and exit")
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")
    env = os.environ if env is None else env
    cfg = load_config()
    watcher = load_watcher()
    start, end = alert_schedule.next_window(cfg.schedule, dt.datetime.now(dt.UTC))
    state = "on" if enabled(env) else "off"
    status(f"Alerts server: {state}; next watch {start:%a %d %b %H:%M} to {end:%H:%M} NY")
    if args.check:
        return 0
    if not enabled(env):
        status("Alerts server: ALERTS_ENABLED is not true, idle (the GitHub job sends alerts)")
        while True:
            sleep(86400)
    return serve(args.data_dir, cfg.schedule, watcher.main, sleep=sleep)


if __name__ == "__main__":
    raise SystemExit(main())
