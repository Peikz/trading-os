"""Create or update the cron-job.org jobs that start the timed workflows (trading_os.timer).

uv run python scripts/timer_setup.py           # asks for the two keys, then syncs the jobs
uv run python scripts/timer_setup.py --list    # our jobs at cron-job.org: last result, next start

The keys (never shown or printed):
- cron-job.org API key: Console -> Settings -> API.
- GitHub token: a fine-grained token for Peikz/trading-os only, permission Actions: read and
  write. It goes into the cron-job.org jobs' request header.
Taken from the environment when set (CRONJOB_API_KEY, TIMER_GITHUB_TOKEN), else asked for.
The `timer-sync.yml` workflow (Emil, 21 Oct 2026) runs this with both keys from the repo's
secrets whenever `trading_os/timer.py` changes on main, so nobody has to re-run it by hand.
With a new GitHub token: update the secret TIMER_GITHUB_TOKEN and start that workflow.
"""

from __future__ import annotations

import argparse
import getpass
import os
import time

import requests

from trading_os import timer

API = "https://api.cron-job.org"
CREATE_PAUSE = 13  # seconds: cron-job.org allows 5 new jobs a minute


def _call(method: str, path: str, key: str, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    reply = requests.request(method, API + path, headers=headers, json=body, timeout=30)
    if reply.status_code != 200:
        raise SystemExit(f"cron-job.org: {method} {path} answered {reply.status_code}")
    return reply.json() if reply.content else {}


def _github_ok(token: str) -> bool:
    """The token can see this repo's workflows (a start needs Actions: write as well)."""
    reply = requests.get(
        f"https://api.github.com/repos/{timer.REPO}/actions/workflows",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    return reply.status_code == 200


def list_jobs(key: str) -> None:
    jobs = [j for j in _call("GET", "/jobs", key)["jobs"] if j["title"].startswith(timer.PREFIX)]
    for j in sorted(jobs, key=lambda j: j["title"]):
        last = j.get("lastStatus")
        state = "on" if j.get("enabled") else "OFF"
        print(f"{j['title']:<36} {state:<4} last status {last}  next {j.get('nextExecution')}")
    print(f"{len(jobs)} of {len(timer.JOBS)} jobs at cron-job.org")


def sync(key: str, token: str) -> None:
    create, update, delete = timer.plan(_call("GET", "/jobs", key)["jobs"])
    for job_id, job in update:
        _call("PATCH", f"/jobs/{job_id}", key, {"job": timer.payload(job, token)})
        print(f"updated  {job.title}")
    for job_id in delete:
        _call("DELETE", f"/jobs/{job_id}", key)
        print(f"deleted  job {job_id} (no longer in timer.JOBS)")
    for k, job in enumerate(create):
        if k:
            time.sleep(CREATE_PAUSE)
        _call("PUT", "/jobs", key, {"job": timer.payload(job, token)})
        print(f"created  {job.title}")
    print(f"Timer: {len(create)} created, {len(update)} updated, {len(delete)} deleted")


def _secret(name: str, prompt: str, ask: bool) -> str:
    """The key from the environment, else typed at a prompt (never in CI: `ask` is False)."""
    value = os.environ.get(name, "").strip()
    if value or not ask:
        return value
    return getpass.getpass(prompt).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="show our jobs at cron-job.org")
    parser.add_argument(
        "--no-prompt", action="store_true", help="take both keys from the environment only (CI)"
    )
    args = parser.parse_args(argv)
    ask = not args.no_prompt
    key = _secret("CRONJOB_API_KEY", "cron-job.org API key: ", ask)
    if not key:
        print("Timer: no cron-job.org API key (secret CRONJOB_API_KEY); nothing changed.")
        return 1
    if args.list:
        list_jobs(key)
        return 0
    token = _secret("TIMER_GITHUB_TOKEN", "GitHub token (Actions read/write on trading-os): ", ask)
    if not token:
        print("Timer: no GitHub token (secret TIMER_GITHUB_TOKEN); nothing changed.")
        return 1
    if not _github_ok(token):
        print("GitHub didn't accept that token for this repo; nothing changed.")
        return 1
    sync(key, token)
    list_jobs(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
