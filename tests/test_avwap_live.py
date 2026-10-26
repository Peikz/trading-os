import datetime as dt

import pandas as pd

from trading_os import avwap_live, clock, grader
from trading_os.config import load_config
from trading_os.scans import REGISTRY


def bars(rows):
    """rows: (high, low, close) per session; volume 1,000 each."""
    return pd.DataFrame([{"high": h, "low": lo, "close": c, "volume": 1000.0} for h, lo, c in rows])


def test_touch_today_needs_the_low_at_the_avwap_and_the_close_over_it():
    # anchor day typical price 20; the stock runs up, then comes back
    run = [(21, 19, 20), (24, 21, 23), (26, 23, 25)]
    assert avwap_live.touch_today(bars([*run, (25, 19.5, 23)]), 3)[0]  # low under 22.44, close over
    assert not avwap_live.touch_today(bars([*run, (25, 23.5, 24)]), 3)[0]  # never reached it
    assert not avwap_live.touch_today(bars([*run, (25, 18, 19)]), 3)[0]  # closed under it


def test_only_the_first_touch_counts():
    rows = [(21, 19, 20), (24, 21, 23), (24, 19.9, 22), (25, 20.5, 23)]
    first, _ = avwap_live.touch_today(bars(rows[:3]), 2)
    again, _ = avwap_live.touch_today(bars(rows), 3)
    assert first and not again


def test_attach_flags_a_recent_ep9m_a_plus_back_at_its_avwap(tmp_path, monkeypatch):
    cfg = load_config()
    session = dt.date(2026, 10, 23)
    sessions = clock.sessions_back(cfg.schedule, session, 16)
    anchor = sessions[-4]  # 3 sessions before today
    folder = tmp_path / "data" / "candidates" / "2026"
    folder.mkdir(parents=True)
    cand = pd.DataFrame({"scan": ["ep9m_pace", "ep9m_pace"], "grade": ["A+", "C"],
                         "ticker": ["AAA", "BBB"]})  # fmt: skip
    cand.to_parquet(folder / f"{anchor.isoformat()}_am.parquet")
    past = pd.DataFrame(
        {
            "session_date": sessions[-4:-1],
            "ticker": "AAA",
            "open": [20, 23, 25],
            "high": [21, 24, 26],
            "low": [19, 21, 23],
            "close": [20, 23, 25],
            "volume": [1000.0] * 3,
        }
    )
    monkeypatch.setattr(avwap_live.history, "load_bars", lambda d, s: past)
    uni = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "open": [25, 10],
            "high": [25, 11],
            "low": [19.5, 9],
            "close": [23, 10],
            "volume": [1000.0, 1000.0],
            "avg_dollar_volume_20d": [9e6, 9e6],
            "dollar_volume": [8e6, 8e6],
        }
    )
    out = avwap_live.attach(uni, tmp_path, cfg, session)
    assert out["ep9m_avwap"].tolist() == [True, False]
    assert out.loc[0, "avwap_day"] == 3 and out.loc[0, "avwap_anchor"] == anchor
    hits = REGISTRY["ep9m_avwap"](out, cfg.scans["ep9m_avwap"])
    assert hits["ticker"].tolist() == ["AAA"]


def test_every_hit_is_graded_b_with_the_next_open_plan():
    g = grader.quality_grade("ep9m_avwap", {}, load_config().grading)
    assert g.grade == "B" and g.plan["entry"] == "next_open" and g.plan["stop"] == "signal_low"
    assert g.note == "the setup's own grade"


def test_signal_low_stop_is_capped_at_two_adr():
    from trading_os.grade_live import signal_low_stop

    assert signal_low_stop(22.0, 19.5, 2.0) == 19.5
    assert signal_low_stop(22.0, 15.0, 2.0) == 18.0  # 2 ADR under the entry
    assert signal_low_stop(22.0, None, 2.0) != signal_low_stop(22.0, None, 2.0)  # NaN
