"""Backtest step 2: hand-computed fixtures for every §3 definition, and the no-lookahead test."""

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from trading_os.backtest import indicators as ind
from trading_os.backtest.config import parse_config

CONFIG = Path(__file__).resolve().parent.parent / "config" / "backtest.yaml"


def cfg(**changes):
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for key, value in changes.items():
        raw["indicators"][key] = value
    return parse_config(raw)


def days(n, start=dt.date(2021, 1, 4)):
    return [start + dt.timedelta(days=i) for i in range(n)]


def grid(values, tickers=("AAA",)):
    a = np.array(values, dtype=float)
    if a.ndim == 1:
        a = a[:, None]
    return pd.DataFrame(a, index=days(len(a)), columns=list(tickers))


def test_adr_pct_and_usd():
    high = grid([11, 12, 11])
    low = grid([10, 10, 10])
    out = ind.adr_pct(high, low, 2)
    # (high/low - 1) x 100 = 10, 20, 10 -> 2-day means NaN, 15, 15
    assert np.isnan(out.iloc[0, 0])
    assert out.iloc[1, 0] == pytest.approx(15)
    assert out.iloc[2, 0] == pytest.approx(15)


def test_ema_by_hand():
    out = ind.ema(grid([1, 2, 3, 4]), 3)  # alpha = 2 / (3 + 1) = 0.5
    # 1 -> 1.5 -> 2.25 -> 3.125, NaN until 3 sessions exist
    assert out.iloc[:2, 0].isna().all()
    assert out.iloc[2, 0] == pytest.approx(2.25)
    assert out.iloc[3, 0] == pytest.approx(3.125)


def test_sma_perf_rising_falling():
    c = grid([10, 11, 12, 9, 15])
    s = ind.sma(c, 2)
    assert s.iloc[1:, 0].tolist() == pytest.approx([10.5, 11.5, 10.5, 12.0])
    p = ind.perf(c, 2)
    assert p.iloc[2, 0] == pytest.approx(20.0)  # 12 / 10 - 1
    assert p.iloc[4, 0] == pytest.approx(25.0)  # 15 / 12 - 1
    r = ind.rising(s, 1)
    assert r.iloc[:, 0].tolist() == [False, False, True, False, True]
    f = ind.falling(s, 1)
    assert f.iloc[:, 0].tolist() == [False, False, False, True, False]


def test_leader_top_share_and_sma():
    c = cfg(leader={"top_pct": 30, "above_sma": 2})
    close = grid([[10, 10, 10, 10], [11, 12, 13, 20]], tickers=list("ABCD"))
    uni = close.notna() & True
    uni["D"] = False  # D is the best performer but not in the universe
    perfs = {1: ind.perf(close, 1)}
    out = ind.leader(close, uni, perfs, c.indicators)
    # among A, B, C only C is in the top 30 %; C closes above its 2-day SMA
    assert out.iloc[1].tolist() == [False, False, True, False]
    assert not out.iloc[0].any()  # no perf yet


def test_avwap_anchor_by_hand():
    w = {
        "high": grid([10, 12, 13, 12, 14]),
        "low": grid([8, 10, 11, 10, 12]),
        "close": grid([9, 11, 12, 11, 13]),
        "volume": grid([100, 300, 200, 500, 100]),
    }
    out = ind.avwap(w, 3)
    tp = np.array([9, 11, 12, 11, 13], float)  # (H+L+C)/3 equals the close here
    v = np.array([100, 300, 200, 500, 100], float)
    # up days: 2, 3, 5 (day 4 is down, though its volume is the largest)
    assert np.isnan(out.iloc[0, 0])  # day 1 has no prior close, so no up day yet
    assert out.iloc[1, 0] == pytest.approx(11)  # anchor day 2
    assert out.iloc[2, 0] == pytest.approx((tp[1:3] @ v[1:3]) / v[1:3].sum())  # still day 2
    assert out.iloc[3, 0] == pytest.approx((tp[1:4] @ v[1:4]) / v[1:4].sum())
    # day 5: window days 3-5, up days 3 (200) and 5 (100) -> anchor day 3
    assert out.iloc[4, 0] == pytest.approx((tp[2:5] @ v[2:5]) / v[2:5].sum())


def test_avwap_tie_takes_the_latest_day():
    w = {
        k: grid(vals)
        for k, vals in {
            "high": [10, 11, 12],
            "low": [10, 11, 12],
            "close": [10, 11, 12],
            "volume": [5, 7, 7],
        }.items()
    }
    out = ind.avwap(w, 3)
    assert out.iloc[2, 0] == pytest.approx(12)  # days 2 and 3 tie at 7: anchor day 3


def test_regime_tags():
    c = cfg(
        regime={"ticker": "QQQ", "fast_sma": 2, "mid_sma": 3, "slow_sma": 4, "slope_lookback": 1}
    )
    close = pd.Series([10, 10, 10, 10, 12, 14, 9, 7, 6], index=days(9), dtype=float)
    out = ind.regime(close, c.indicators)
    # day 5: SMA3 = 10.67, SMA2 = 11 > SMA3, close 12 > SMA3 -> up
    assert out.iloc[4] == "up"
    # day 9: SMA4 = 9 (14, 9, 7, 6), close 6 < 9; SMA3 7.33 < 10 the day before -> down
    assert out.iloc[8] == "down"
    assert out.iloc[0] == "sideways"  # warming up


def test_breadth_tags():
    c = cfg(
        breadth={"perf_window": 1, "move_pct": 25, "strong_ratio_min": 1.5, "weak_ratio_below": 1.0}
    )
    close = grid(
        [[10, 10, 10, 10, 10], [13, 13, 13, 7, 20], [13, 9, 9, 7, 20], [13, 9, 9, 7, 20]],
        tickers=list("ABCDE"),
    )
    uni = close.notna() & True
    uni["E"] = False  # out of the universe: not counted
    out = ind.breadth(close, uni, c.indicators)
    assert out.loc[out.index[1], ["up", "down"]].tolist() == [3, 1]
    assert out["tag"].iloc[1] == "strong"  # 3 / 1
    assert out.loc[out.index[2], ["up", "down"]].tolist() == [0, 2]  # 9 / 13 - 1 = -30.8 %
    assert out["tag"].iloc[2] == "weak"
    assert out["tag"].iloc[3] == "neutral"  # nothing moved
    assert out["tag"].iloc[0] == "neutral"


def synthetic(n_days=200, n_tickers=40, seed=1):
    rng = np.random.default_rng(seed)
    close = 20 * np.exp(np.cumsum(rng.normal(0.001, 0.03, (n_days, n_tickers)), axis=0))
    high = close * (1 + rng.uniform(0, 0.05, close.shape))
    low = close * (1 - rng.uniform(0, 0.05, close.shape))
    openp = low + (high - low) * rng.uniform(0, 1, close.shape)
    vol = rng.integers(200_000, 5_000_000, close.shape).astype(float)
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    idx = days(n_days)
    w = {
        k: pd.DataFrame(v, index=idx, columns=tickers)
        for k, v in {"open": openp, "high": high, "low": low, "close": close, "volume": vol}.items()
    }
    w["close"].iloc[:30, 5] = np.nan  # a late listing
    w["close"].iloc[150:, 6] = np.nan  # a delisting
    w["in_universe"] = pd.DataFrame(
        rng.uniform(0, 1, close.shape) > 0.2, index=idx, columns=tickers
    )
    qqq = pd.Series(300 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n_days))), index=idx)
    return w, qqq


def flatten(out):
    flat = {}
    for name, value in out.items():
        if isinstance(value, pd.DataFrame):
            for col in value.columns:
                flat[f"{name}.{col}"] = value[col]
        else:
            flat[name] = value
    return flat


@pytest.mark.parametrize("t", [40, 99, 150, 198])
def test_no_lookahead(t):
    """Rewriting every bar after day t (prices, volume, universe, QQQ) changes no value on or
    before day t, for every indicator."""
    c = cfg()
    w, qqq = synthetic()
    base = flatten(ind.compute(w, c, qqq))
    rng = np.random.default_rng(99)
    w2 = {k: v.copy() for k, v in w.items()}
    for k in ("open", "high", "low", "close", "volume"):
        w2[k].iloc[t + 1 :] = w2[k].iloc[t + 1 :] * rng.uniform(0.2, 5, w2[k].iloc[t + 1 :].shape)
    w2["in_universe"].iloc[t + 1 :] = ~w2["in_universe"].iloc[t + 1 :]
    q2 = qqq.copy()
    q2.iloc[t + 1 :] = q2.iloc[t + 1 :] * rng.uniform(0.2, 5, len(q2) - t - 1)
    moved = flatten(ind.compute(w2, c, q2))
    assert base.keys() == moved.keys()
    for name in base:
        a, b = base[name].iloc[: t + 1], moved[name].iloc[: t + 1]
        pd.testing.assert_series_equal(a, b, check_names=False, obj=name)
    # the future really did change something
    assert any(not base[n].iloc[t + 1 :].equals(moved[n].iloc[t + 1 :]) for n in base)


def test_wide_from_long_bars():
    long = pd.DataFrame(
        {
            "session_date": days(2) * 2,
            "ticker": ["A", "A", "B", "B"],
            "open": [1, 2, 3, 4],
            "high": [1, 2, 3, 4],
            "low": [1, 2, 3, 4],
            "close": [1, 2, 3, 4],
            "volume": [1, 2, 3, 4],
            "in_universe": [True, False, True, True],
        }
    ).iloc[[0, 2, 3]]  # A has no second bar
    w = ind.wide(long)
    assert w["close"].shape == (2, 2)
    assert np.isnan(w["close"].iloc[1, 0])
    assert w["in_universe"].iloc[1].tolist() == [False, True]
