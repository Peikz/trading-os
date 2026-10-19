"""Minute-bar study: candidate stock-days and the incremental fetch (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd

from trading_os import intraday_study as s
from trading_os.config import load_config

CFG = load_config()
A, B, C = ("".join(["A", "A", "Q"]), "".join(["B", "B", "Q"]), "".join(["C", "C", "Q"]))


def sessions(n, start=dt.date(2025, 1, 2)):
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    return days


def flat_bars(days, ticker, price=10.0, volume=1_000_000):
    return pd.DataFrame(
        {
            "session_date": days,
            "ticker": ticker,
            "open": price,
            "high": price * 1.02,
            "low": price * 0.98,
            "close": price,
            "volume": float(volume),
        }
    )


def test_prior_facts_use_nothing_from_the_day_itself():
    days = sessions(30)
    bars = flat_bars(days, A)
    g, _ = s.daily(bars, days)
    g = {k: v.copy() for k, v in g.items()}
    before = s.prior_facts(g, CFG.universe["alert"])
    g["close"][-1, 0], g["volume"][-1, 0] = 99.0, 9e9
    after = s.prior_facts(g, CFG.universe["alert"])
    for key in ("prev_close", "avg20", "adr_usd", "ok"):
        assert before[key][-1, 0] == after[key][-1, 0]


def test_gap_group_keeps_liquid_gaps_from_the_superset_up():
    days = sessions(30)
    bars = pd.concat(
        [flat_bars(days, A), flat_bars(days, B), flat_bars(days, C, price=0.5)], ignore_index=True
    )
    last = bars["session_date"] == days[-1]
    bars.loc[last & (bars["ticker"] == A), ["open", "high"]] = [10.4, 10.6]  # +4 %
    bars.loc[last & (bars["ticker"] == B), ["open", "high"]] = [10.2, 10.3]  # +2 %
    bars.loc[last & (bars["ticker"] == C), ["open", "high"]] = [0.6, 0.6]  # +20 %, under $1
    cands = s.candidates(bars, days, CFG)
    gap = cands[cands["group"] == "gap"]
    assert gap["ticker"].tolist() == [A] and gap["session_date"].tolist() == [days[-1]]
    assert round(float(gap["gap_pct"].iloc[0]), 1) == 4.0 and gap["prev_close"].iloc[0] == 10.0


def test_pivot_group_finds_the_day_that_reaches_the_prior_base_high():
    days = sessions(140)
    rise = np.linspace(10, 20, 80)
    base = 19 + np.tile([0.0, -0.6, -1.0, -0.5, -0.2], 12)[:59]
    close = np.concatenate([rise, base, [20.5]])
    bars = pd.DataFrame(
        {
            "session_date": days,
            "ticker": A,
            "open": close,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1_000_000.0,
        }
    )
    bars.loc[79, "high"] = 20.4  # the base's top: the pivot
    bars.loc[139, "high"] = 20.9
    cands = s.candidates(bars, days, CFG)
    pivot = cands[cands["group"] == "pivot"]
    assert days[-1] in set(pivot["session_date"])
    hit = pivot[pivot["session_date"] == days[-1]].iloc[0]
    assert hit["pivot"] <= 20.9 and "b1" in pivot


def test_next_day_rows_are_the_session_after_the_signal():
    days = sessions(30)
    hits = pd.DataFrame(
        {
            "strategy": ["mb_up"],
            "session_date": [days[-2]],
            "ticker": [A],
            "high": [11.0],
            "low": [9.5],
        }
    )
    cands = s.candidates(flat_bars(days, A), days, CFG, hits)
    nxt = cands[cands["group"] == "next_day"].iloc[0]
    assert nxt["session_date"] == days[-1] and nxt["signal_date"] == days[-2]
    assert nxt["strategy"] == "mb_up" and nxt["signal_high"] == 11.0


def test_fetch_windows_ask_each_stock_day_once_with_the_right_bars():
    days = sessions(3)
    cands = pd.DataFrame(
        {
            "group": ["gap", "ep9m", "ep9m", "next_day", "next_day"],
            "session_date": [days[2]] * 5,
            "ticker": [A, A, B, B, C],
        }
    )
    w = s.fetch_windows(cands, days).set_index("kind")
    assert w.loc["evening", "tickers"] == [A] and w.loc["day", "tickers"] == [B]
    assert w.loc["day5", "tickers"] == [C] and w.loc["day5", "timeframe"] == "5Min"
    # 16:00 New York on the prior session (EST in January) = 21:00 UTC.
    assert w.loc["evening", "start"] == dt.datetime(2025, 1, 3, 21, tzinfo=dt.UTC)
    assert w.loc["day", "start"] == dt.datetime(2025, 1, 6, 9, tzinfo=dt.UTC)


class Fake:
    def __init__(self):
        self.calls = []

    def bars(self, symbols, timeframe, start, end):
        self.calls.append((tuple(symbols), timeframe))
        got = [t for t in symbols if t != C]  # C has no bars at all
        return pd.DataFrame(
            {
                "ticker": got,
                "ts": [pd.Timestamp(start)] * len(got),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 10,
                "trades": 1,
                "vwap": 1.0,
            }
        )


def test_fetch_is_incremental_and_remembers_stock_days_without_bars(tmp_path):
    days = sessions(3)
    first = pd.DataFrame(
        {"group": ["ep9m", "ep9m"], "session_date": [days[2]] * 2, "ticker": [A, C]}
    )
    fake = Fake()
    assert s.fetch(fake, s.fetch_windows(first, days), tmp_path) == {"2025-01": 2}
    assert fake.calls == [((A, C), "1Min")]
    bars = s.load_minutes(tmp_path)
    assert bars["ticker"].tolist() == [A] and bars["kind"].tolist() == ["day"]
    more = pd.concat(
        [first, pd.DataFrame({"group": ["ep9m"], "session_date": [days[2]], "ticker": [B]})]
    )
    again = Fake()
    s.fetch(again, s.fetch_windows(more, days), tmp_path)
    assert again.calls == [((B,), "1Min")]  # A and C were asked for already
    assert sorted(s.load_minutes(tmp_path)["ticker"]) == [A, B]
    assert str(s.load_minutes(tmp_path)["close"].dtype) == "float32"


def test_fetch_stops_at_the_deadline(tmp_path):
    days = sessions(3)
    cands = pd.DataFrame({"group": ["ep9m"], "session_date": [days[2]], "ticker": [A]})
    fake = Fake()
    assert s.fetch(fake, s.fetch_windows(cands, days), tmp_path, deadline=0) == {}
    assert fake.calls == []
