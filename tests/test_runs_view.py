"""Lab → Runs: config/runs.yaml loads and is checked, the overview, and the edit of a run's
times and on/off (Emil, 4 Nov 2026)."""

import datetime as dt

import pytest

from trading_os import config, runs_view, timer

CFG = config.load_config()
WINDOWS = CFG.schedule.windows_et
TEXT = timer.RUNS_PATH.read_text(encoding="utf-8")


def test_every_run_in_the_file_starts_inside_its_window():
    assert timer.outside_windows(timer.JOBS, WINDOWS) == []
    assert len({j.key for j in timer.JOBS}) == len(runs_view.keys())


def test_the_overview_lists_each_run_with_its_scans_and_pushes():
    rows = {r["key"]: r for r in runs_view.overview(CFG, today=dt.date(2026, 11, 4))}
    assert rows["pm"]["starts (NY · CPH)"] == "07:17 NY · 13:17 CPH"
    assert rows["pm"]["second start"] == "07:35 NY · 13:35 CPH"
    assert "EP-PM" in rows["pm"]["pushes"]
    assert rows["eod"]["pushes"] == "Market lines"
    assert rows["weekly"]["days"] == "Sat"
    assert runs_view.keys()[-1] == "weekly"  # Saturday after the weekday runs


def test_a_run_edit_changes_only_its_own_lines_and_reads_back():
    new = runs_view.apply(TEXT, "pm", {"first": "07:20", "second": "07:40"}, WINDOWS)
    changed = [b for a, b in zip(TEXT.splitlines(), new.splitlines(), strict=True) if a != b]
    assert len(changed) == 2 and all("key: pm," in line for line in changed)
    jobs = timer.parse(new)
    assert [j.at for j in jobs if j.key == "pm"] == ["07:20", "07:40"]
    assert new.count("#") == TEXT.count("#")  # the comments stay


def test_off_turns_both_lines_of_a_run_off_and_the_timer_drops_them():
    new = runs_view.apply(TEXT, "am", {"enabled": False}, WINDOWS)
    jobs = timer.parse(new)
    assert not any(j.on for j in jobs if j.key == "am")
    assert all(j.key != "am" for j in timer.active(jobs))


@pytest.mark.parametrize(
    ("key", "changes", "says"),
    [
        ("pm", {"first": "08:30"}, "outside its window"),
        ("eod", {"first": "4pm"}, "not HH:MM"),
        ("nope", {"first": "07:20"}, "no such run"),
    ],
)
def test_a_bad_edit_is_refused(key, changes, says):
    with pytest.raises(timer.RunsError, match=says):
        runs_view.apply(TEXT, key, changes, WINDOWS)


def test_a_run_off_exits_when_scheduled_but_runs_by_hand(monkeypatch):
    jobs = timer.parse(runs_view.apply(TEXT, "outcomes", {"enabled": False}, WINDOWS))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.delenv("RUN_TRIGGER", raising=False)
    assert timer.switched_off("outcomes", jobs)
    assert not timer.switched_off("eod", jobs)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert not timer.switched_off("outcomes", jobs)  # by hand
    monkeypatch.setenv("RUN_TRIGGER", "timer")
    assert timer.switched_off("outcomes", jobs)


def test_the_file_refuses_mixed_on_off_and_unknown_keys():
    mixed = TEXT.replace(
        'at: "07:35", days: weekdays, retry: true, enabled: true',
        'at: "07:35", days: weekdays, retry: true, enabled: false',
    )
    with pytest.raises(timer.RunsError, match="on or off together"):
        timer.parse(mixed)
    with pytest.raises(timer.RunsError, match="unknown"):
        timer.parse(TEXT.replace("enabled: true}", "enabeld: true}", 1))


def test_saving_writes_the_file_and_returns_the_diff(tmp_path):
    path = tmp_path / "runs.yaml"
    path.write_text(TEXT, encoding="utf-8")
    shown = runs_view.save("mid", {"first": "12:05"}, WINDOWS, path)
    assert '+  - {key: mid, workflow: intraday.yml, name: Intraday, at: "12:05"' in shown
    assert runs_view.save("mid", {"first": "12:05"}, WINDOWS, path) == ""  # nothing changed
