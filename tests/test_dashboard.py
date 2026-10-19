import datetime as dt

import pandas as pd
import pytest

from trading_os import dashboard


def touch_run(root, stem, manual_stamp=None):
    year = stem[:4]
    cands = pd.DataFrame({"scan": ["ep_day"], "ticker": ["AAA"], "tier": ["alert"]})
    if manual_stamp:
        folder = root / "data" / "manual" / f"{stem}_{manual_stamp}"
        folder.mkdir(parents=True)
        cands.to_parquet(folder / "candidates.parquet")
        (folder / "charts").mkdir()
        (folder / "charts" / "ep_day_AAA.png").write_bytes(b"png")
    else:
        path = root / "data" / "candidates" / year / f"{stem}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        cands.to_parquet(path)


def test_list_runs_newest_first_with_manual(tmp_path):
    touch_run(tmp_path, "2026-10-16_eod")
    touch_run(tmp_path, "2026-10-19_pm")
    touch_run(tmp_path, "2026-10-19_eod")
    touch_run(tmp_path, "2026-10-16_eod", manual_stamp="203000")
    runs = dashboard.list_runs(tmp_path)
    assert [r.label for r in runs] == [
        "2026-10-19 · eod",
        "2026-10-19 · pm",
        "2026-10-16 · eod",
        "2026-10-16 · eod (manual 203000)",
    ]
    assert len(dashboard.list_runs(tmp_path, include_manual=False)) == 3
    manual = runs[-1]
    assert dashboard.chart_for(manual, "ep_day", "AAA").name == "ep_day_AAA.png"
    assert dashboard.chart_for(manual, "ep_day", "ZZZ") is None


def test_notes_are_append_only_and_latest_wins(tmp_path):
    t1 = dt.datetime(2026, 11, 2, 21, tzinfo=dt.UTC)
    t2 = dt.datetime(2026, 11, 3, 21, tzinfo=dt.UTC)
    dashboard.save_note(tmp_path, "trade", "tr1", "B", "late entry", "ep", [], now=t1)
    dashboard.save_note(tmp_path, "trade", "tr1", "A", "re-read: all five", "ep", ["x.png"], now=t2)
    dashboard.save_note(tmp_path, "signal", "s9", "C", "", "", [], now=t1)
    state = dashboard.notes_state(tmp_path).set_index(["kind", "ref_id"])
    assert state.loc[("trade", "tr1"), "grade"] == "A"
    assert state.loc[("trade", "tr1"), "attachments"] == "x.png"
    assert state.loc[("signal", "s9"), "grade"] == "C"
    assert len(list((tmp_path / "data" / "journal" / "notes").rglob("*.parquet"))) == 3


def test_note_validation(tmp_path):
    with pytest.raises(ValueError):
        dashboard.save_note(tmp_path, "trade", "x", "D", "", "", [])
    with pytest.raises(ValueError):
        dashboard.save_note(tmp_path, "other", "x", "A", "", "", [])


def test_attachment_paths_are_safe_and_relative(tmp_path):
    rel = dashboard.save_attachment(
        tmp_path, "tr/1", "my shot (1).png", b"img", now=dt.datetime(2026, 11, 2, tzinfo=dt.UTC)
    )
    assert rel == "data/journal/attachments/tr_1/20261102T000000_my_shot_1_.png"
    assert (tmp_path / rel).read_bytes() == b"img"


def test_git_save_and_push_roundtrip(tmp_path):
    remote, local = tmp_path / "remote.git", tmp_path / "clone"
    assert dashboard.git(tmp_path, "init", "--bare", "-q", str(remote))[0]
    assert dashboard.git(tmp_path, "clone", "-q", str(remote), str(local))[0]
    dashboard.git(local, "config", "user.email", "t@example.com")
    dashboard.git(local, "config", "user.name", "t")
    (local / "README.md").write_text("x")
    dashboard.git(local, "add", "README.md")
    dashboard.git(local, "commit", "-qm", "init")
    dashboard.git(local, "push", "-q", "origin", "HEAD")
    dashboard.save_note(local, "trade", "tr1", "A", "n", "", [])
    ok, out = dashboard.save_and_push(local)
    assert ok, out
    assert dashboard.save_and_push(local) == (True, "nothing new to save")
