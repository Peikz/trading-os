"""The cron-job.org timer: its jobs, their API payloads, the sync plan and the on-time check."""

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from trading_os import job, timer

WINDOWS = {
    "pm": (dt.time(7, 15), dt.time(7, 55)),
    "am": (dt.time(10, 10), dt.time(11, 30)),
    "mid": (dt.time(11, 55), dt.time(13, 30)),
    "eod": (dt.time(16, 15), dt.time(23, 59)),
}


def utc(*args):
    return dt.datetime(*args, tzinfo=dt.UTC)


def by_title(title_part):
    return next(j for j in timer.JOBS if title_part in j.title)


def test_titles_are_unique_and_every_workflow_takes_the_timer_input():
    titles = [j.title for j in timer.JOBS]
    assert len(set(titles)) == len(titles)
    for j in timer.JOBS:
        text = (Path(__file__).parents[1] / ".github" / "workflows" / j.workflow).read_text(
            encoding="utf-8"
        )
        assert "      timer:\n" in text, j.workflow
        for name in j.inputs:
            assert f"      {name}:\n" in text, (j.workflow, name)


def test_payload_posts_a_dispatch_at_the_new_york_time():
    p = timer.payload(by_title("mid 12:03"), "tok")
    assert p["url"].endswith("/repos/Peikz/trading-os/actions/workflows/intraday.yml/dispatches")
    assert p["requestMethod"] == 1 and p["enabled"]
    assert p["schedule"]["timezone"] == "America/New_York"
    assert (p["schedule"]["hours"], p["schedule"]["minutes"]) == ([12], [3])
    assert p["schedule"]["wdays"] == [1, 2, 3, 4, 5]
    assert p["extendedData"]["headers"]["Authorization"] == "Bearer tok"
    body = json.loads(p["extendedData"]["body"])
    assert body == {"ref": "main", "inputs": {"slot": "mid", "timer": "true"}}


def test_plan_creates_updates_and_deletes_only_our_jobs():
    first, second = timer.JOBS[0], timer.JOBS[1]
    existing = [
        {"jobId": 1, "title": first.title},
        {"jobId": 2, "title": f"{timer.PREFIX}pm 07:16 ET"},  # an old time
        {"jobId": 3, "title": "someone else's job"},
    ]
    create, update, delete = timer.plan(existing)
    assert update == [(1, first)] and delete == [2]
    assert second in create and len(create) == len(timer.JOBS) - 1


def test_last_fire_follows_new_york_time_and_the_job_days():
    pm = by_title("pm 07:17")
    # 2 Nov 2026: New York is on winter time (UTC-5) since 1 Nov
    assert timer.last_fire(pm, utc(2026, 11, 2, 13, 0)) == utc(2026, 11, 2, 12, 17)
    assert timer.last_fire(pm, utc(2026, 10, 20, 12, 0)) == utc(2026, 10, 20, 11, 17)  # EDT
    assert timer.last_fire(pm, utc(2026, 10, 24, 15, 0)) == utc(2026, 10, 23, 11, 17)  # Sat
    weekly = by_title("weekly")
    assert timer.last_fire(weekly, utc(2026, 10, 21, 0, 0)) == utc(2026, 10, 18, 16, 0)


def test_check_says_on_time_late_missed_or_due():
    now = utc(2026, 10, 20, 15, 0)  # 11:00 New York
    runs = pd.DataFrame(
        {
            "workflowName": ["Pre-market", "Backfill", "Bars pack", "Pre-market"],
            "createdAt": [
                "2026-10-20T11:17:40Z",  # 07:17 ET: on time
                "2026-10-20T09:58:00Z",  # 05:58 ET: 28 minutes late
                "2026-10-20T13:00:00Z",  # after its 2-hour grace: missed
                "2026-10-20T15:39:00Z",  # GitHub's late cron, after the window: ignored
            ],
        }
    )
    out = timer.check(runs, WINDOWS, now).set_index("job")["status"]
    assert out["pm (Pre-market)"] == "✅ on time"
    assert out["backfill (Backfill)"] == "🟡 28 min late"
    assert out["bars-pack (Bars pack)"] == "❌ missed"
    assert out["am (Intraday)"] == "⏳ due"  # fired 10:17, window open until 11:30
    assert len(out) == len([j for j in timer.JOBS if not j.retry])
    assert (timer.check(pd.DataFrame(), WINDOWS, now)["status"] != "✅ on time").all()


def test_timer_runs_count_as_scheduled(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.delenv("RUN_TRIGGER", raising=False)
    assert job.run_kind() == "manual"
    monkeypatch.setenv("RUN_TRIGGER", "timer")
    assert job.run_kind() == "scheduled"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.delenv("RUN_TRIGGER")
    assert job.run_kind() == "scheduled"


def _setup_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "timer_setup", Path(__file__).resolve().parents[1] / "scripts" / "timer_setup.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_the_sync_takes_both_keys_from_the_environment_and_never_prompts(monkeypatch):
    script = _setup_script()

    def no_prompt(*_):
        raise AssertionError("asked for a key in CI")

    calls = []
    monkeypatch.setattr(script.getpass, "getpass", no_prompt)
    monkeypatch.setattr(script, "_github_ok", lambda token: token == "gh-test")
    monkeypatch.setattr(script, "sync", lambda key, token: calls.append(("sync", key, token)))
    monkeypatch.setattr(script, "list_jobs", lambda key: calls.append(("list", key)))
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)
    monkeypatch.delenv("TIMER_GITHUB_TOKEN", raising=False)
    assert script.main(["--no-prompt"]) == 1 and not calls  # no secrets: nothing changes
    monkeypatch.setenv("CRONJOB_API_KEY", "cj-test")
    monkeypatch.setenv("TIMER_GITHUB_TOKEN", "gh-test")
    assert script.main(["--no-prompt"]) == 0
    assert calls == [("sync", "cj-test", "gh-test"), ("list", "cj-test")]


def test_the_daily_job_line_names_missed_and_failed_runs():
    now = utc(2026, 10, 22, 21, 0)  # 17:00 New York, after the EOD start
    jobs = [j for j in timer.JOBS if not j.retry]

    def run(job, conclusion="success"):
        fired = timer.last_fire(job, now).isoformat()
        return {"workflowName": job.name, "createdAt": fired, "conclusion": conclusion}

    rows = [run(j) for j in jobs if j.key not in ("weekly", "mid", "am")]
    rows += [run(j, "failure") for j in jobs if j.key == "am"]
    line = timer.health_line(pd.DataFrame(rows), WINDOWS, now)
    assert "am ❌ failed" in line and "mid ❌ missed" in line and "weekly" not in line
    rows = [run(j) for j in jobs if j.key != "weekly"]
    assert timer.health_line(pd.DataFrame(rows), WINDOWS, now).startswith("🩺 All ")
