"""Volume build: hand-computed ratios and the quiet-price check on synthetic bars."""

import datetime as dt

import pandas as pd

from trading_os import board_data, clock, history, screens, volume_build
from trading_os.config import load_config

CFG = load_config()
SESSION = dt.date(2026, 11, 4)
BEFORE = [s for s in clock.sessions_back(CFG.schedule, SESSION, 56) if s < SESSION][-55:]


def bars(volumes: dict[str, list], sessions: list, close: float = 10.0) -> pd.DataFrame:
    rows = [
        {"session_date": day, "ticker": t, "volume": vol, "high": close * 1.02,
         "low": close * 0.98, "close": close}
        for t, vols in volumes.items()
        for day, vol in zip(sessions, vols, strict=True)
        if vol is not None  # a missing bar is a missing row, as in the stored bars
    ]  # fmt: skip
    return pd.DataFrame(rows)


def test_ratio_is_the_last_5_sessions_over_the_50_before_them():
    f = volume_build.facts(bars({"AAA": [1e6] * 50 + [3e6] * 5, "BBB": [2e6] * 55}, BEFORE), BEFORE)
    assert f.loc["AAA", "build"] == 3.0 and f.loc["BBB", "build"] == 1.0
    assert bool(f.loc["AAA", "quiet"])  # flat price: within 1 ADR (about 4 %)


def test_too_little_history_or_a_missing_day_is_unknown():
    short = volume_build.facts(bars({"AAA": [None] * 11 + [1e6] * 39 + [3e6] * 5}, BEFORE), BEFORE)
    assert pd.isna(short.loc["AAA", "build"])  # 39 of the 50 sessions: under 40
    gap = volume_build.facts(bars({"AAA": [1e6] * 50 + [3e6] * 4 + [None]}, BEFORE), BEFORE)
    assert pd.isna(gap.loc["AAA", "build"])  # a day missing among the last 5


def test_a_moving_price_is_not_quiet():
    frame = bars({"AAA": [1e6] * 55}, BEFORE)
    frame.loc[frame.index[-1], "close"] = 11.0  # +10 % in 5 sessions on a ~4 % ADR
    assert not bool(volume_build.facts(frame, BEFORE).loc["AAA", "quiet"])


def test_before_leaves_the_session_out_and_now_adds_this_close(monkeypatch):
    seen = {}

    def load(data_dir, sessions):
        seen["sessions"] = list(sessions)
        return bars({"AAA": [1e6] * 50 + [2e6] * 5}, BEFORE)

    monkeypatch.setattr(history, "load_bars", load)
    uni = pd.DataFrame({"ticker": ["AAA", "ZZZ"]})
    out = volume_build.attach(uni, None, CFG, SESSION)
    assert seen["sessions"] == BEFORE and SESSION not in seen["sessions"]
    assert out["vol_build"].iloc[0] == 2.0 and pd.isna(out["vol_build"].iloc[1])
    assert "vol_build_now" not in out  # intraday: no close yet
    today = bars({"AAA": [12e6]}, [SESSION])
    now = volume_build.attach(uni, None, CFG, SESSION, today)
    # up to this close: (4 x 2M + 12M) / 5 = 4M, over the 50 before them (49 x 1M and one 2M)
    assert now["vol_build"].iloc[0] == 2.0
    assert abs(now["vol_build_now"].iloc[0] - 4e6 / ((49 * 1e6 + 2e6) / 50)) < 1e-9


def test_the_card_names_a_build_and_the_study_fact_on_an_ep_a_plus():
    row = {"vol_build": 2.4, "grade": "A+", "grade_strategy": "ep9m"}
    assert "2.4x" in volume_build.card_tag(row) and "about 0R" in volume_build.card_tag(row)
    assert "about 0R" not in volume_build.card_tag(row | {"grade_strategy": "qm_surf"})
    assert volume_build.card_tag({"vol_build": 1.5}) is None
    assert ("Vol build", "2.4x") in board_data.key_stats(row)
    assert any("Volume built up" in t for t in board_data.tags(row))


def test_the_watchlist_screen_finds_a_quiet_build():
    snap = pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"], "close": [20.0, 20.0, 20.0],
        "avg_dollar_volume_20d": [9e6] * 3, "vol_build_now": [3.0, 3.0, 1.1],
        "vol_quiet_now": [True, False, True],
    })  # fmt: skip
    spec = screens.EXAMPLES["Volume building, price quiet"]
    hits = screens.run(snap, spec["filters"], spec["sort"], spec["descending"])
    assert list(hits["ticker"]) == ["AAA"]
