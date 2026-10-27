"""Editing scans from the dashboard: values change in place, comments stay, every edit is
validated like the jobs validate it, and the push uses your name and note."""

import datetime as dt
import shutil

import pandas as pd
import pytest
import yaml

from trading_os import notify, scan_editor
from trading_os.config import DEFAULT_PATH, ConfigError, load_config, parse_config
from trading_os.store import RunContext


@pytest.fixture()
def config_copy(tmp_path):
    path = tmp_path / "scans.yaml"
    shutil.copy(DEFAULT_PATH, path)
    return path


def test_values_change_in_place_and_comments_stay(config_copy):
    old = config_copy.read_text(encoding="utf-8")
    shown = scan_editor.save(
        "ep_day", {"gap_min_pct": 12, "label": "EP day one", "note": "Heads-up, #1"},
        config_copy,
    )  # fmt: skip
    new = config_copy.read_text(encoding="utf-8")
    assert "-     gap_min_pct: 10" in shown and "gap_min_pct: 12" in shown
    assert len(new.splitlines()) == len(old.splitlines()) + 2  # the two text keys, own lines
    assert sum(1 for ln in new.splitlines() if ln.lstrip().startswith("#")) == sum(
        1 for ln in old.splitlines() if ln.lstrip().startswith("#")
    )
    scan = load_config(config_copy).scans["ep_day"]
    assert scan["gap_min_pct"] == 12
    assert scan.params["label"] == "EP day one" and scan.params["note"] == "Heads-up, #1"


def test_lists_booleans_and_the_push_switch(config_copy):
    scan_editor.save("luk_flush", {"push_slot": ["pm"], "enabled": False}, config_copy)
    scan_editor.save("parabolic_long", {"action": "log"}, config_copy)
    cfg = load_config(config_copy)
    assert cfg.scans["luk_flush"].params["push_slot"] == ("pm",)
    assert not cfg.scans["luk_flush"].enabled
    assert cfg.scans["parabolic_long"].action == "log"
    assert cfg.scans["ep9m"].action == load_config().scans["ep9m"].action  # others untouched


def test_bad_edits_are_refused_and_nothing_is_written(config_copy):
    before = config_copy.read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        scan_editor.save("ep_pm", {"action": "shout"}, config_copy)
    with pytest.raises(ConfigError):
        scan_editor.save("ep_pm", {"price_min": "cheap"}, config_copy)
    with pytest.raises(ConfigError):
        scan_editor.save("no_such_scan", {"enabled": False}, config_copy)
    assert config_copy.read_text(encoding="utf-8") == before


def test_the_push_uses_your_name_and_note(config_copy):
    scan_editor.save("ma_surf", {"label": "Qulla surf", "note": "Only A-grade bases"}, config_copy)
    cfg = parse_config(yaml.safe_load(config_copy.read_text(encoding="utf-8")))
    ctx = RunContext(
        session=dt.date(2026, 10, 22),
        slot="ah",  # MA-surf pushes after hours since 27 Oct 2026
        run_ts=dt.datetime(2026, 10, 22, 20, 50, tzinfo=dt.UTC),
        run_kind="scheduled",
    )
    hits = pd.DataFrame(
        [{"ticker": "AAA", "tier": "alert", "rank": 1, "grade": "C", "surf_ma": 10.0,
          "surf_days": 12.0, "surf_base_len": 8.0}]
    )  # fmt: skip
    selected = notify.select_for_push({"ma_surf": hits}, cfg, "ah")
    body = notify.build_message(ctx, {"ma_surf": hits}, selected, cfg).body
    assert "Qulla surf" in body and "Only A-grade bases" in body


def test_the_sunday_lists_are_shown_in_full_not_counted():
    cfg = load_config()
    hits = pd.DataFrame([{"ticker": "AAA", "tier": "alert", "rank": 1, "grade": "C"}])
    assert notify.push_modes(cfg, hits, cfg.scans["qm_gainers"]).tolist() == ["full"]
    assert notify.push_modes(cfg, hits, cfg.scans["pivot_watch"]).tolist() == ["count"]


def test_tables_put_the_best_quality_on_top():
    hits = pd.DataFrame(
        {"ticker": ["c0", "c3", "aplus", "c1", "a"], "rank": [1, 2, 3, 4, 5],
         "grade": ["C", "C", "A+", "C", "A"], "grade_score": [0, 3, 6, 1, 2]}
    )  # fmt: skip
    assert notify.best_first(hits)["ticker"].tolist() == ["aplus", "a", "c3", "c1", "c0"]
    plain = pd.DataFrame({"ticker": ["b", "a"], "rank": [2, 1]})
    assert notify.best_first(plain)["ticker"].tolist() == ["a", "b"]
