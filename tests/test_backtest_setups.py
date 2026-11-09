"""Backtest step 3: one hand-built chart per setup that must fire on a known day, and a
no-lookahead test for the signals."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os.backtest import indicators as ind
from trading_os.backtest import setups as st
from trading_os.backtest.config import load_config

CFG = load_config()
P = CFG.setups


def chart(close, spread=0.3, volume=1_000_000, opens=None, highs=None, lows=None):
    """One ticker's bars: high/low = close +/- spread unless given; open = prior close."""
    c = np.asarray(close, float)
    n = len(c)
    sp = np.broadcast_to(np.asarray(spread, float), (n,))
    h = c + sp if highs is None else np.asarray(highs, float)
    low = c - sp if lows is None else np.asarray(lows, float)
    o = np.r_[c[0], c[:-1]] if opens is None else np.asarray(opens, float)
    v = np.broadcast_to(np.asarray(volume, float), (n,)).copy()
    idx = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    frames = {
        k: pd.DataFrame({"XYZ": a}, index=idx)
        for k, a in {"open": o, "high": h, "low": low, "close": c, "volume": v}.items()
    }
    frames["in_universe"] = pd.DataFrame({"XYZ": True}, index=idx)
    return frames


def run(w, setup, leader=None):
    i = ind.compute(w, CFG)
    if leader is not None:
        i["leader"] = pd.DataFrame({"XYZ": leader}, index=w["close"].index)
    return st.SETUPS[setup](w, i, P[setup.lower()]), i


def one(rows, day):
    hit = rows[rows["session_date"] == day]
    assert len(hit) == 1, rows[["session_date", "entry", "stop", "skip"]]
    return hit.iloc[0]


def test_b0_breakout_fires_on_the_trigger_day():
    flat = [10.0] * 150  # the prior-move window needs 2 x 63 sessions of history
    rise = list(np.linspace(10.05, 14.0, 30))  # +40 % in 30 sessions
    drift = list(np.linspace(13.4, 13.75, 15))
    tight = [13.9] * 5
    close = flat + rise + drift + tight + [14.5]
    n = len(close)
    vol = np.full(n, 1_000_000.0)
    vol[-6:-1] = 600_000  # quiet right side
    vol[-1] = 3_000_000
    highs = np.array(close) + 0.15
    lows = np.array(close) - 0.15
    opens = np.r_[close[0], close[:-1]]
    t = n - 1
    opens[t], highs[t], lows[t] = 13.95, 14.6, 13.9
    w = chart(close, volume=vol, opens=opens, highs=highs, lows=lows)
    rows, i = run(w, "B0")
    r = one(rows, w["close"].index[t])
    base_len = int(r["base_len"])
    assert 10 <= base_len <= 40
    assert r["pivot"] == pytest.approx(highs[t - base_len : t].max())
    trigger = r["pivot"] * 1.001
    assert r["trigger"] == pytest.approx(trigger)
    assert r["entry"] == pytest.approx(max(opens[t], trigger))
    adr = i["adr_usd"]["XYZ"].iloc[t - 1]
    assert r["stop"] == pytest.approx(max(lows[t - 10 : t].min(), r["pivot"] - adr))
    assert bool(r["close_ok"]) and not bool(r["skip"])
    assert r["side"] == 1
    # the same chart without the volume on the trigger day fails the close check
    w2 = chart(close, volume=np.r_[vol[:-1], 100_000], opens=opens, highs=highs, lows=lows)
    assert not bool(one(run(w2, "B0")[0], w2["close"].index[t])["close_ok"])


def test_l1_pullback_fires_after_a_3_to_7_day_dip():
    close = [10.0] * 80 + list(np.linspace(10.1, 14.2, 60)) + [14.4, 14.3, 14.1, 14.0, 14.1, 14.45]
    close = np.array(close)
    highs, lows = close + 0.3, close - 0.3
    t = len(close) - 1
    lows[t - 4 : t + 1] = close[t - 4 : t + 1] - 0.1  # shallow pullback lows
    highs[t] = 14.6  # under the high 5 sessions back (14.7)
    w = chart(close, highs=highs, lows=lows)
    rows, i = run(w, "L1", leader=np.ones(len(close), bool))
    r = one(rows, w["close"].index[t])
    assert r["anchor_age"] == 5  # the high came 5 sessions before the trigger
    assert r["entry"] == pytest.approx(close[t])
    assert r["stop"] == pytest.approx(lows[t - 4 : t + 1].min())
    assert not bool(r["skip"])
    # no leader, no signal
    assert len(run(w, "L1", leader=np.zeros(len(close), bool))[0]) == 0


def test_l2_undercut_and_reclaim():
    close = np.array([10.0] * 60 + list(np.linspace(10.1, 14.0, 60)) + [14.0] * 10 + [13.9])
    highs, lows = close + 0.4, close - 0.4
    t = len(close) - 1
    opens = np.r_[close[0], close[:-1]]
    opens[t], highs[t], lows[t] = 13.5, 14.0, 13.3  # under the 10-day low (13.6), back over it
    w = chart(close, highs=highs, lows=lows, opens=opens)
    rows, _ = run(w, "L2", leader=np.ones(len(close), bool))
    r = one(rows, w["close"].index[t])
    assert r["pivot"] == pytest.approx(13.6)  # the level undercut
    assert r["stop"] == pytest.approx(13.3)
    assert not bool(r["skip"])


def test_l3_gap_up_on_volume_after_neglect():
    close = np.array([10.0] * 150 + [12.1])
    highs, lows = close + 0.4, close - 0.4
    opens = np.r_[close[0], close[:-1]]
    t = len(close) - 1
    opens[t], highs[t], lows[t] = 11.5, 12.2, 11.4  # +15 % gap, green, upper half
    vol = np.full(len(close), 1_000_000.0)
    vol[t] = 5_000_000
    w = chart(close, volume=vol, highs=highs, lows=lows, opens=opens)
    rows, i = run(w, "L3")
    r = one(rows, w["close"].index[t])
    assert r["stop"] == pytest.approx(11.4)
    assert r["adr_usd"] == pytest.approx(i["adr_usd"]["XYZ"].iloc[t - 1])  # the pre-gap ADR
    assert not bool(r["skip"])
    # a 5 % gap is not an EP
    opens2 = opens.copy()
    opens2[t] = 10.5
    assert len(run(chart(close, volume=vol, highs=highs, lows=lows, opens=opens2), "L3")[0]) == 0


def test_s1_weak_bounce_short():
    up = list(np.linspace(10, 20, 100))
    down = list(np.linspace(19.8, 18.0, 15))
    close = np.array(up + down + [17.0, 16.8, 17.2, 17.6, 17.9, 17.2])
    n = len(close)
    highs, lows = close + 0.6, close - 0.6
    bd = n - 6  # the breakdown day
    t = n - 1
    lows[bd + 1] = 16.5
    highs[bd + 2 : bd + 5] = close[bd + 2 : bd + 5] + 0.2  # a weak bounce
    highs[t] = 17.9
    vol = np.full(n, 1_000_000.0)
    vol[bd] = 3_000_000
    vol[bd + 2 : bd + 5] = 500_000
    lead = np.zeros(n, bool)
    lead[60:100] = True
    w = chart(close, volume=vol, highs=highs, lows=lows)
    rows, _ = run(w, "S1", leader=lead)
    r = one(rows, w["close"].index[t])
    assert r["side"] == -1
    assert r["stop"] == pytest.approx(highs[bd + 2 : t + 1].max())
    assert r["entry"] == pytest.approx(close[t])
    assert not bool(r["skip"])


def test_s2_parabolic_first_failure_day():
    close = np.array([10.0] * 100 + [11.5, 13, 14.5, 16, 17.5, 19, 20.5, 19.5])
    n = len(close)
    sp = np.full(n, 0.2)
    sp[100:] = 1.0
    highs, lows = close + sp, close - sp
    opens = np.r_[close[0], close[:-1]]
    t = n - 1
    opens[t], highs[t] = 21.0, 21.3  # red day under the prior close
    w = chart(close, highs=highs, lows=lows, opens=opens)
    rows, _ = run(w, "S2")
    r = one(rows, w["close"].index[t])
    assert r["side"] == -1
    assert r["stop"] == pytest.approx(21.3)
    assert not bool(r["skip"])
    assert len(rows) == 1  # only the first failure day


def test_signals_combines_and_sorts():
    close = [10.0] * 150 + [12.1]
    w = chart(
        close,
        opens=[10.0] * 150 + [11.5],
        volume=[1e6] * 150 + [5e6],
        highs=[10.4] * 150 + [12.2],
        lows=[9.6] * 150 + [11.4],
    )
    out = st.signals(w, ind.compute(w, CFG), P)
    assert list(out.columns) == st.ROW_COLUMNS
    assert out["setup"].tolist() == ["L3"]


@pytest.mark.parametrize("t", [130, 170, 198])
def test_setups_no_lookahead(t):
    """Rewriting every bar after day t changes no signal on or before t."""
    rng = np.random.default_rng(7)
    n, m = 200, 30
    close = 20 * np.exp(np.cumsum(rng.normal(0.002, 0.04, (n, m)), axis=0))
    idx = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    cols = [f"T{i}" for i in range(m)]
    high = close * (1 + rng.uniform(0, 0.06, (n, m)))
    low = close * (1 - rng.uniform(0, 0.06, (n, m)))
    opn = low + (high - low) * rng.uniform(0, 1, (n, m))
    vol = rng.lognormal(14, 0.8, (n, m))
    w = {
        k: pd.DataFrame(a, index=idx, columns=cols)
        for k, a in {"open": opn, "high": high, "low": low, "close": close, "volume": vol}.items()
    }
    w["in_universe"] = pd.DataFrame(True, index=idx, columns=cols)
    cfg_rows = st.signals(w, ind.compute(w, CFG), P)
    w2 = {k: v.copy() for k, v in w.items()}
    for k in ("open", "high", "low", "close", "volume"):
        w2[k].iloc[t + 1 :] *= rng.uniform(0.3, 3, w2[k].iloc[t + 1 :].shape)
    moved = st.signals(w2, ind.compute(w2, CFG), P)
    cut = idx[t]
    a = cfg_rows[cfg_rows["session_date"] <= cut].reset_index(drop=True)
    b = moved[moved["session_date"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert len(cfg_rows) > 0  # the random market does produce signals
