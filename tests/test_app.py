"""Smoke test of the dashboard: every page renders without an exception on a small data repo.

Needs the `app` dependency group (Streamlit); skipped otherwise (e.g. in CI).
"""

import datetime as dt
import os
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")

os.environ["TRADING_OS_NO_LIVE"] = "1"  # the Market page's live sector data
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
PAGES = [
    "Today",
    "Screens",
    "Scans",
    "Chart",
    "Watchlists",
    "Journal",
    "Market",
    "Research",
    "Live results",
    "System health",
    "Guide",
]
SECTIONS = [  # (page, its section picker's key, section)
    ("Research", "research_section", "Strategy rules"),
    ("Research", "research_section", "How it was tested"),
    ("Research", "research_section", "Grades"),
    ("Research", "research_section", "History"),
    ("Research", "research_section", "Entries & exits"),
    ("Research", "research_section", "Market regime"),
    ("Live results", "live_section", "Grades live vs study"),
    ("Live results", "live_section", "All signals"),
    ("Live results", "live_section", "Signals you graded"),
    ("System health", "health_section", "Jobs and data"),
    ("System health", "health_section", "Validation against TradingView"),
]


@pytest.fixture()
def data_repo(tmp_path):
    root = tmp_path / "trading-os-data"
    cands = pd.DataFrame(
        {
            "signal_id": ["s1"],
            "session_date": [pd.Timestamp("2026-10-19")],
            "slot": ["eod"],
            "scan": ["ep_day"],
            "ticker": ["AAA"],
            "rank": [1],
            "tier": ["alert"],
            "pushed": [True],
            "gap_pct": [12.0],
            "rvol50": [4.0],
        }
    )
    path = root / "data" / "candidates" / "2026" / "2026-10-19_eod.parquet"
    path.parent.mkdir(parents=True)
    cands.to_parquet(path)
    uni = root / "data" / "universe" / "2026" / "2026-10-19_eod.parquet"
    uni.parent.mkdir(parents=True)
    pd.DataFrame({"ticker": ["AAA"], "gap_pct": [12.0]}).to_parquet(uni)
    return root


@pytest.mark.parametrize(("page", "key", "section"), SECTIONS)
def test_every_section_renders(data_repo, monkeypatch, page, key, section):
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value(page).run()
    at.radio(key=key).set_value(section).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.header[0].value == page


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(data_repo, monkeypatch, page):
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, at.exception
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.header[0].value  # each page has a header


def test_journal_tabs_render_with_trades_positions_and_plans(data_repo, monkeypatch):
    import datetime as dt

    from trading_os import journal, plans
    from trading_os.config import load_config

    cfg = load_config()
    day, later = dt.date(2026, 10, 19), dt.date(2026, 10, 20)
    for fill, stop in (
        (journal.manual_fill(day, "AAA", "buy", 100, 10.0, setup="ep_day"), 9.5),
        (journal.manual_fill(later, "AAA", "sell", 100, 11.0), None),
        (journal.manual_fill(later, "BBB", "buy", 50, 20.0, setup="vcp_breakout"), 19.0),
    ):
        journal.log_manual(data_repo, cfg, fill, stop)
    plans.create(data_repo, later, "CCC", "long", 5.0, 4.8, 100, "breakout_watch")
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Journal").run()
    assert not at.exception, [e.value for e in at.exception]
    texts = " ".join(str(m.value) for m in at.metric)
    assert "1" in texts  # one closed trade, one open position
    assert any("CCC" in str(df.value) for df in at.dataframe)  # the plan is listed


def test_my_watchlists_render(data_repo, monkeypatch):
    from trading_os import my_watchlists

    my_watchlists.add(data_repo, "Leaders", ["AAA", "BBB"])
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Watchlists").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("AAA" in str(df.value) for df in at.dataframe)


def test_study_grades_show_in_the_tables_blocks_and_their_page(data_repo, monkeypatch):
    import json

    path = data_repo / "data" / "candidates" / "2026" / "2026-10-19_eod.parquet"
    graded = pd.read_parquet(path).assign(
        scan="luk_flush",  # a scan that pushes at EOD (EP-Day, EP9M saved only since 21 Oct)
        grade="A",
        grade_score=0.42,
        grade_why="few scan hits (+0.71)",
        grade_entry_rule="close",
        grade_hold_sessions=21,
        grade_stat_trades=1234,
        grade_stat_win_pct=55.0,
        grade_stat_mean_r=0.31,
        grade_stat_median_r=-0.2,
        grade_stat_years=8,
        grade_stat_years_pos=7,
        grade_stat_days_median=12.0,
    )
    graded.to_parquet(path)
    stats = {
        "source": "docs/research/grading.md",
        "period": "out of sample 2019-2026",
        "strategies": {"ep": {"grades": {"A": {"trades": 1234, "win_pct": 55.0, "mean_r": 0.31}}}},
    }
    (data_repo / "data" / "grading").mkdir(parents=True)
    (data_repo / "data" / "grading" / "grade_stats.json").write_text(json.dumps(stats))
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not any("Study A" in str(m.value) for m in at.markdown)  # tables off: not built
    at.toggle(key="today_all_scans").set_value(True).run()
    assert any("Study A" in str(m.value) for m in at.markdown)  # Today's grade block
    at.sidebar.radio[0].set_value("Research").run()
    at.radio(key="research_section").set_value("Grades").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("1234" in str(df.value) for df in at.dataframe)  # the history behind A


def test_the_grade_rules_read_from_config_in_words():
    import importlib.util

    from trading_os.config import load_config

    cfg = load_config()
    quality = cfg.grading.get("quality")
    if not quality:
        pytest.skip("no quality grades in config")
    spec = importlib.util.spec_from_file_location("app_helpers", APP)
    assert spec is not None  # the helpers are plain functions in the app module
    src = APP.read_text(encoding="utf-8")
    start, end = src.index("FEATURE_TEXT = {"), src.index("def grade_blocks(")
    import pandas as pd_  # noqa: F401  (the helpers use pd)

    from trading_os import notify, report

    scope = {"pd": pd, "notify": notify, "report": report}
    exec(src[start:end], scope)
    table = scope["quality_rules"](cfg.grading)
    assert len(table) == len(quality)
    first = table.iloc[0]
    assert "1." in first["Points (one each)"] and "= C" in first["Grade by points"]
    assert "ADR" in first["Stop"] and "sessions" in first["Exit"]


def test_the_market_page_shows_the_setups_at_todays_heat(data_repo, monkeypatch):
    import json

    path = data_repo / "data" / "breadth" / "2026" / "2026-10-19_eod.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [{"session_date": pd.Timestamp("2026-10-19"), "light": "STOP", "qqq_trend": "down",
          "breadth_state": "weak", "scan_count": 60, "up4": 100, "down4": 200,
          "ratio_5d": 0.7, "ratio_10d": 0.73, "up25q": 10, "down25q": 20}]
    ).to_parquet(path)  # fmt: skip
    one = {"trades": 40, "signal_days": 30, "mean_r": 0.5, "day_mean_r": 0.4, "win_pct": 30.0,
           "years_up": 3, "years": 4}  # fmt: skip
    stats = {
        "built": "2026-10-21",
        "bands": [[18, "cool"], [45, "mild"], [81, "warm"], [None, "hot"]],
        "band_labels": {"cool": "under 18", "mild": "18-44", "warm": "45-80", "hot": "over 80"},
        "min_trades": 30,
        "setups": [
            {
                "key": "surf",
                "label": "MA-surf",
                "short": "MA-surf",
                "kind": "C",
                "side": "long",
                "plan": "10:00 over the pivot",
            }
        ],  # fmt: skip
        "rows": [
            {"setup": "surf", "heat": "warm", "period": p, **one} for p in ("2016-21", "2022-26")
        ],
    }
    (data_repo / "data" / "grading").mkdir(parents=True)
    (data_repo / "data" / "grading" / "heat_stats.json").write_text(json.dumps(stats))
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Market").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Warm market: scan count 60" in s.value for s in at.subheader)
    assert any("held" in str(df.value) for df in at.dataframe)


def test_chart_notes_show_old_notes_and_save_new_ones(data_repo, monkeypatch):
    import datetime as dt

    from trading_os import stock_notes

    stock_notes.add(data_repo, "AAA", "base looked loose", dt.date(2025, 6, 2))
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Chart").run()
    at.text_input(key="ch_ticker").input("AAA").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("base looked loose" in t.value for t in at.text)
    at.text_area(key="ch_note_text").input("tight flag, watch the pivot")
    next(b for b in at.button if b.label == "Save note").click().run()
    assert not at.exception, [e.value for e in at.exception]
    saved = stock_notes.current(data_repo, "AAA")["text"].tolist()
    assert saved == ["tight flag, watch the pivot", "base looked loose"]
    assert any("tight flag" in t.value for t in at.text)


def test_a_tagged_daily_note_shows_in_the_journal_and_on_the_chart(data_repo, monkeypatch):
    from trading_os import daily_notes

    daily_notes.add(data_repo, "Gap held into the close on $AAA", dt.date(2026, 10, 19))
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Journal").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Gap held" in t.value for t in at.text)
    at.sidebar.radio[0].set_value("Chart").run()
    at.text_input(key="ch_ticker").set_value("AAA").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("From your daily notes" in m.value for m in at.markdown)


def test_live_minute_bars_ask_for_the_keys_when_missing(data_repo, monkeypatch):
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Chart").run()
    at.text_input(key="ch_ticker").set_value("AAA").run()
    at.toggle(key="ch_intraday_on").set_value(True).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Alpaca keys" in i.value for i in at.info)
