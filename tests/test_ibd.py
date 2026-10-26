import datetime as dt

import pandas as pd

from trading_os import ibd, live_tracking

START = dt.date(2026, 1, 2)


def bars(changes, volumes, lows=None):
    """Synthetic SPY: closes from daily % changes, one session per calendar day."""
    close, rows = 100.0, []
    for k, (chg, vol) in enumerate(zip(changes, volumes, strict=True)):
        close *= 1 + chg / 100
        low = close * 0.99 if lows is None else lows[k]
        rows.append(
            {
                "session_date": START + dt.timedelta(days=k),
                "close": close,
                "low": low,
                "volume": vol,
            }
        )
    return pd.DataFrame(rows)


def test_distribution_day_needs_a_drop_and_more_volume():
    s = ibd.states(bars([0, -0.3, -0.1, -0.5, -0.5], [100, 120, 130, 90, 95]))
    # -0.3 % on more volume: yes; -0.1 %: too small; -0.5 % on less volume: no; on more: yes
    assert s["dist"].tolist() == [False, True, False, False, True]


def test_six_distribution_days_start_a_correction():
    changes, vols = [0.0], [100]
    for _ in range(6):  # alternate: a distribution day, then a quiet up day
        changes += [-0.5, 0.3]
        vols += [vols[-1] + 50, vols[-1] - 10]
    s = ibd.states(bars(changes, vols))
    first = s.index[s["state"] == "correction"][0]
    assert s.loc[first, "dist_count"] == 6
    assert (s.loc[: first - 1, "state"] == "uptrend").all()


def test_follow_through_day_ends_the_correction_and_resets_the_count():
    changes, vols = [0.0], [100]
    for _ in range(6):
        changes += [-0.5, 0.3]
        vols += [vols[-1] + 50, vols[-1] - 10]
    n = len(changes)
    # the low is the last distribution day; then three quiet days and a +1.5 % day on volume
    changes += [0.2, 0.2, 0.2, 1.5]
    vols += [vols[-1] - 20, vols[-1] - 30, vols[-1] - 40, vols[-1] + 100]
    lows = [c * 0.99 for c in bars(changes, vols)["close"]]
    lows[n:] = [lows[n - 1] + 1] * 4  # the correction low is not undercut
    s = ibd.states(bars(changes, vols, lows))
    assert s["state"].iloc[-2] == "correction"
    assert s["state"].iloc[-1] == "uptrend"
    assert s["dist_count"].iloc[-1] == 0


def test_spy_daily_joins_the_seed_and_the_breadth_rows(tmp_path):
    seed = bars([0.1] * 30, [100] * 30)
    (tmp_path / "data" / "market").mkdir(parents=True)
    seed.to_parquet(tmp_path / ibd.SEED)
    after = START + dt.timedelta(days=30)
    folder = tmp_path / "data" / "breadth" / str(after.year)
    folder.mkdir(parents=True)
    row = {"session_date": after, "spy_close": 99.0, "spy_low": 98.0, "spy_volume": 500.0}
    pd.DataFrame([row]).to_parquet(folder / f"{after.isoformat()}_eod.parquet")
    today = {
        "session_date": after + dt.timedelta(days=1),
        "spy_close": 98.0,
        "spy_low": 97.0,
        "spy_volume": 600.0,
    }
    spy = ibd.spy_daily(tmp_path, after + dt.timedelta(days=1), today)
    assert len(spy) == 32 and spy["close"].iloc[-1] == 98.0
    info = ibd.state_at(tmp_path, after + dt.timedelta(days=1), today)
    assert info["state"] == "uptrend" and info["dist_count"] == 2
    assert ibd.tag(info) == "IBD 🟢 Healthy uptrend (2 of 6 sell days)"
    assert ibd.line(None) == [] and ibd.state_at(tmp_path, START) is None


def test_plain_words_for_the_state():
    assert ibd.words("uptrend", 3) == "🟢 Healthy uptrend"
    assert ibd.words("uptrend", 4) == "🟡 Uptrend under pressure"
    assert ibd.words("correction", 7) == "🔴 Correction"
    assert ibd.words(None, 0) is None
    assert ibd.sell_days("correction", 7) == "7 sell days"
    old = pd.DataFrame(
        {
            "ibd_state": ["uptrend", None],
            "ibd_dist": [5, None],
            "ibd_tag": ["IBD uptrend (5 dist.)", None],
        }
    )
    new = ibd.relabel(old)["ibd_tag"]
    assert new.iloc[0] == "IBD 🟡 Uptrend under pressure (5 of 6 sell days)"
    assert pd.isna(new.iloc[1])


def test_live_check_splits_closed_trades_by_state():
    res = pd.DataFrame(
        {
            "grade_strategy": ["ep9m"] * 4,
            "grade": ["A+"] * 4,
            "status": ["closed", "closed", "closed", "open"],
            "r_net": [1.0, -1.0, 2.0, 0.5],
            "ibd_state": ["uptrend", "correction", None, "uptrend"],
        }
    )
    out = live_tracking.by_market(res).set_index("ibd_state")
    assert out.loc["uptrend", "closed"] == 1 and out.loc["uptrend", "live_mean_r"] == 1.0
    assert out.loc["unknown", "live_mean_r"] == 2.0
    assert out.loc["correction", "live_win_pct"] == 0.0
