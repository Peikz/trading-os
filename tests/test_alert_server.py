"""The server's price-alert service (scripts/alert_server.py, trading_os/alert_schedule.py):
when it watches, how it sleeps, and how it commits what fired. Synthetic data only; the dates
are real XNYS sessions, holidays and early closes from exchange_calendars."""

import datetime as dt
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trading_os import alert_schedule, alerts, dashboard, gitlock
from trading_os.config import load_config

NY = ZoneInfo("America/New_York")
SCHEDULE = load_config().schedule
TICKER = "".join(["Q", "Z", "X"])  # synthetic


def ny(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=NY)


def utc(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=dt.UTC)


def server():
    path = Path(__file__).resolve().parents[1] / "scripts" / "alert_server.py"
    spec = importlib.util.spec_from_file_location("alert_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- the schedule


def test_inside_a_session_it_watches_until_the_close():
    now = ny(2026, 10, 22, 11, 0)  # a Thursday
    start, end = alert_schedule.next_window(SCHEDULE, now)
    assert (start, end) == (ny(2026, 10, 22, 9, 25), ny(2026, 10, 22, 16, 0))
    assert alert_schedule.watching(SCHEDULE, now)
    assert alert_schedule.watching(SCHEDULE, ny(2026, 10, 22, 9, 25))


def test_outside_a_session_it_waits_for_the_next_one():
    assert not alert_schedule.watching(SCHEDULE, ny(2026, 10, 22, 9, 24))
    assert alert_schedule.next_window(SCHEDULE, ny(2026, 10, 22, 7, 0))[0] == ny(
        2026, 10, 22, 9, 25
    )
    # The close itself is outside: the next watch is the next morning
    assert not alert_schedule.watching(SCHEDULE, ny(2026, 10, 22, 16, 0))
    after = alert_schedule.next_window(SCHEDULE, ny(2026, 10, 22, 16, 0))
    assert after[0] == ny(2026, 10, 23, 9, 25)
    # Friday evening and the weekend: Monday
    for moment in (ny(2026, 10, 23, 18, 0), ny(2026, 10, 24, 12, 0), ny(2026, 10, 25, 23, 0)):
        assert alert_schedule.next_window(SCHEDULE, moment)[0] == ny(2026, 10, 26, 9, 25)
        assert not alert_schedule.watching(SCHEDULE, moment)


def test_a_holiday_is_skipped_and_an_early_close_ends_at_13():
    assert alert_schedule.window(SCHEDULE, dt.date(2026, 11, 26)) is None  # Thanksgiving
    start, end = alert_schedule.next_window(SCHEDULE, ny(2026, 11, 25, 16, 30))
    assert start == ny(2026, 11, 27, 9, 25)
    assert end == ny(2026, 11, 27, 13, 0)  # the day after Thanksgiving closes early
    assert not alert_schedule.watching(SCHEDULE, ny(2026, 11, 27, 13, 30))
    assert alert_schedule.next_window(SCHEDULE, ny(2026, 11, 27, 13, 30))[0] == ny(
        2026, 11, 30, 9, 25
    )
    assert alert_schedule.window(SCHEDULE, dt.date(2026, 12, 25)) is None  # Christmas


def test_summer_and_winter_time_move_the_utc_start():
    # US winter time from Sunday 1 Nov 2026: 09:25 New York is 13:25 UTC before, 14:25 after
    friday = alert_schedule.next_window(SCHEDULE, utc(2026, 10, 30, 12, 0))
    assert friday[0].astimezone(dt.UTC) == utc(2026, 10, 30, 13, 25)
    assert friday[1].astimezone(dt.UTC) == utc(2026, 10, 30, 20, 0)
    monday = alert_schedule.next_window(SCHEDULE, utc(2026, 10, 30, 21, 0))
    assert monday[0].astimezone(dt.UTC) == utc(2026, 11, 2, 14, 25)
    assert monday[1].astimezone(dt.UTC) == utc(2026, 11, 2, 21, 0)
    # Summer time from Sunday 8 Mar 2026: the other way
    before = alert_schedule.next_window(SCHEDULE, utc(2026, 3, 6, 12, 0))
    assert before[0].astimezone(dt.UTC) == utc(2026, 3, 6, 14, 25)
    after = alert_schedule.next_window(SCHEDULE, utc(2026, 3, 6, 22, 0))
    assert after[0].astimezone(dt.UTC) == utc(2026, 3, 9, 13, 25)
    # 14:00 UTC is before the watch in summer time and inside it in winter time
    assert alert_schedule.watching(SCHEDULE, utc(2026, 10, 30, 14, 0))
    assert not alert_schedule.watching(SCHEDULE, utc(2026, 11, 2, 14, 0))


# ---------------------------------------------------------------- the loop


class Stop(BaseException):  # not caught by the crash handler
    pass


class FakeClock:
    def __init__(self, start: dt.datetime):
        self.now = start
        self.naps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.naps.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


def test_the_loop_sleeps_watches_each_session_to_its_close_and_commits():
    mod = server()
    clock = FakeClock(ny(2026, 11, 25, 8, 0))  # Wednesday before Thanksgiving
    watched, commits = [], []

    def watch(argv):
        until = argv[argv.index("--until") + 1]
        watched.append((clock.now.astimezone(NY), until))
        if len(watched) == 2:
            raise Stop
        hour, minute = map(int, until.split(":"))
        clock.now = clock.now.astimezone(NY).replace(hour=hour, minute=minute)
        return 0

    with pytest.raises(Stop):
        mod.serve(
            Path("/data"),
            SCHEDULE,
            watch,
            now=lambda: clock.now,
            sleep=clock.sleep,
            commit=lambda d, s: commits.append(s) or True,
        )
    assert watched[0] == (ny(2026, 11, 25, 9, 25), "16:00")
    assert watched[1] == (ny(2026, 11, 27, 9, 25), "13:00")  # Thanksgiving skipped
    assert commits == [dt.date(2026, 11, 25)]
    assert max(clock.naps) <= mod.NAP_S


def test_a_crashed_watcher_is_restarted_and_missing_keys_stop_the_service():
    mod = server()
    clock = FakeClock(ny(2026, 10, 22, 10, 0))
    calls, commits = [], []

    def watch(argv):
        calls.append(clock.now)
        if len(calls) == 1:
            raise RuntimeError("synthetic")
        return 1  # what alert_watch returns without keys

    code = mod.serve(
        Path("/data"),
        SCHEDULE,
        watch,
        now=lambda: clock.now,
        sleep=clock.sleep,
        commit=lambda d, s: commits.append(s) or True,
    )
    assert code == 1
    assert clock.naps == [mod.RETRY_S]
    assert commits == [dt.date(2026, 10, 22)] * 2


def test_off_by_default_it_idles_and_never_watches(monkeypatch, capsys):
    mod = server()
    assert not mod.enabled({})
    assert not mod.enabled({"ALERTS_ENABLED": "false"})
    assert mod.enabled({"ALERTS_ENABLED": "True"}) and mod.enabled({"ALERTS_ENABLED": "1"})
    monkeypatch.setattr(mod, "serve", lambda *a, **k: pytest.fail("watched while off"))

    def sleep(seconds):
        raise Stop

    with pytest.raises(Stop):
        mod.main(["--data-dir", "/data"], env={}, sleep=sleep)
    assert "off" in capsys.readouterr().out
    assert mod.main(["--data-dir", "/data", "--check"], env={}) == 0


# ---------------------------------------------------------------- committing what fired


def clone(tmp_path: Path) -> tuple[Path, Path]:
    remote, local = tmp_path / "remote.git", tmp_path / "clone"
    assert dashboard.git(tmp_path, "init", "--bare", "-q", str(remote))[0]
    assert dashboard.git(tmp_path, "clone", "-q", str(remote), str(local))[0]
    dashboard.git(local, "config", "user.email", "t@example.invalid")
    dashboard.git(local, "config", "user.name", "t")
    (local / "README.md").write_text("x")
    dashboard.git(local, "add", "README.md")
    dashboard.git(local, "commit", "-qm", "init")
    dashboard.git(local, "push", "-q", "origin", "HEAD")
    return remote, local


def test_what_fired_is_committed_and_pushed_once(tmp_path):
    mod = server()
    remote, local = clone(tmp_path)
    session = dt.date(2026, 10, 22)
    assert mod.commit_fired(local, session)  # nothing fired: nothing to commit
    alerts.record(local, session, {"key": f"pivot:{TICKER}", "kind": "pivot", "ticker": TICKER})
    (local / "data" / "journal").mkdir(parents=True)
    (local / "data" / "journal" / "other.txt").write_text("not the alerts'")
    assert mod.commit_fired(local, session, sleep=lambda s: None)
    pushed = dashboard.git(remote, "ls-tree", "-r", "--name-only", "HEAD")[1]
    assert "data/my_alerts/fired/2026-10-22.jsonl" in pushed
    assert "data/journal" not in pushed  # only data/my_alerts, as the GitHub job
    log = dashboard.git(remote, "log", "-1", "--format=%s")[1]
    assert log == "alerts 2026-10-22: fired (server)"


def test_a_failed_push_is_tried_three_times(tmp_path, monkeypatch):
    _, local = clone(tmp_path)
    alerts.record(local, dt.date(2026, 10, 22), {"key": "k", "kind": "pivot"})
    real, pushes, naps = dashboard.git, [], []

    def git(data_dir, *args):
        if args[0] == "push":
            pushes.append(1)
            return False, "synthetic failure"
        return real(data_dir, *args)

    monkeypatch.setattr(dashboard, "git", git)
    ok, _ = dashboard.commit_and_push(
        local, ("data/my_alerts",), "m", attempts=3, sleep=naps.append
    )
    assert not ok and len(pushes) == 3 and naps == [10, 20]


# ---------------------------------------------------------------- the git lock


def test_the_git_lock_is_reentrant_and_lives_in_dot_git(tmp_path):
    _, local = clone(tmp_path)
    assert gitlock.lock_path(local) == local / ".git" / gitlock.LOCK_NAME
    with gitlock.held(local), gitlock.held(local):  # save_and_push calls pull inside it
        pass
    assert dashboard.git(local, "status", "--porcelain")[1] == ""  # never tracked


@pytest.mark.skipif(gitlock.fcntl is None, reason="no fcntl (Windows)")
def test_the_git_lock_waits_for_another_holder(tmp_path):
    _, local = clone(tmp_path)
    fcntl = gitlock.fcntl
    with gitlock.lock_path(local).open("a") as other:  # data-sync's flock, say
        fcntl.flock(other, fcntl.LOCK_EX)
        with pytest.raises(TimeoutError), gitlock.held(local, wait_s=0.3, poll_s=0.05):
            pass
        fcntl.flock(other, fcntl.LOCK_UN)
    with gitlock.held(local, wait_s=0.3):
        pass
