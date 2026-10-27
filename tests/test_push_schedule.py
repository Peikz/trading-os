"""The push schedule since 27 Oct 2026 (Emil): pre-market (EP-PM only), morning, midday (only
when there is something new) and after hours (EP-AH, the close's setups and the market line);
the close and weekly runs save without a push; a tap opens the dashboard."""

import datetime as dt

import pandas as pd

from trading_os import clock, job, notify, store
from trading_os.config import load_config

GAPPER = "".join(["GP", "QX"])  # built at runtime, like real data
QUIET = "".join(["QT", "ZZ"])


def _saved(tmp_path, session, slot, frame):
    ctx = store.RunContext(
        session=session, slot=slot, run_ts=dt.datetime.now(dt.UTC), run_kind="scheduled"
    )
    path = store.run_paths(tmp_path, ctx)["candidates"]
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)


def test_what_pushes_and_when():
    cfg = load_config()
    pushing = {
        name: notify.push_slots(scan)
        for name, scan in cfg.scans.items()
        if scan.enabled and scan.action == "push" and name != "breadth"
    }
    assert pushing == {
        "ep_pm": ("pm",),
        "ep_am": ("am",),
        "ep9m_pace": ("am", "mid"),
        "ep_ah": ("ah",),
        "luk_flush": ("ah",),
        "ep9m_avwap": ("ah",),
        "ma_surf": ("ah",),
        "parabolic_long": ("ah",),
        "parabolic_short": ("ah",),
    }
    assert job.SILENT_SLOTS == ("eod", "weekly") and job.QUIET_WHEN_EMPTY == ("mid",)
    assert cfg.schedule.weekly_weekday == 5  # Saturday


def test_after_hours_takes_the_close_runs_setups(tmp_path):
    cfg = load_config()
    session = dt.date(2026, 10, 27)
    frame = pd.DataFrame(
        {"scan": ["luk_flush", "mb_up"], "ticker": [GAPPER, QUIET], "tier": ["alert"] * 2}
    )
    _saved(tmp_path, session, "eod", frame)
    uni = pd.DataFrame({"ticker": [GAPPER], "ah_price": [12.0], "ah_change_pct": [4.0]})
    carried = job._from_last_close(tmp_path, cfg, session, uni, "ah")
    # every scan pushing after hours from the close, empty ones too ("nothing new"); MB up is
    # saved only
    assert set(carried) == {"luk_flush", "ep9m_avwap", "ma_surf", "parabolic_long",
                            "parabolic_short"}  # fmt: skip
    assert [n for n, h in carried.items() if len(h)] == ["luk_flush"]
    row = carried["luk_flush"].iloc[0]
    assert row["ticker"] == GAPPER and row["carried_from"] == "eod"
    assert row["ah_change_pct"] == 4.0


def test_the_morning_push_reminds_of_the_luk_buy(tmp_path):
    cfg = load_config()
    session = dt.date(2026, 10, 28)
    last = clock.previous_session(cfg.schedule, session)
    frame = pd.DataFrame(
        {
            "scan": ["luk_flush", "luk_flush"],
            "ticker": [GAPPER, QUIET],
            "tier": ["alert", "alert"],
            "grade": ["A", "C"],
        }
    )
    _saved(tmp_path, last, "eod", frame)
    assert job._planned_today(tmp_path, cfg, session) == [
        f"🗓 Planned today: Luk flush {GAPPER} (buy 10:30 New York)"
    ]
    assert job._planned_today(tmp_path, cfg, dt.date(2026, 11, 5)) == []  # no run that day


def test_a_tap_opens_today_on_the_pushed_stocks(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "http://dash.example/")
    selected = {
        "ep_ah": pd.DataFrame({"ticker": [GAPPER]}),
        "luk_flush": pd.DataFrame({"ticker": [QUIET, GAPPER]}),
    }
    url = notify.dashboard_url(dt.date(2026, 10, 27), "ah", selected)
    assert url == f"http://dash.example/?push=ah&session=2026-10-27&t={GAPPER}%2C{QUIET}"
    monkeypatch.delenv("DASHBOARD_URL")
    assert notify.dashboard_url(dt.date(2026, 10, 27), "ah", selected) is None
