import datetime as dt

import pandas as pd

from trading_os import board_data

D = dt.date


def _bars(last):
    return pd.DataFrame(
        {
            "session_date": [D(2026, 11, 9), last],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [10.0, 20.0],
        }
    )


def _fetch(calls):
    def f(tickers):
        calls.append(list(tickers))
        return {
            t: {"open": 3.0, "high": 4.0, "low": 2.5, "close": 3.5, "volume": 99.0} for t in tickers
        }

    return f


def test_adds_todays_candle_during_a_session():
    calls = []
    out = board_data.with_today(
        _bars(D(2026, 11, 10)), "ZZZ", session=D(2026, 11, 11), fetch=_fetch(calls)
    )
    assert len(out) == 3
    last = out.iloc[-1]
    assert last["session_date"] == D(2026, 11, 11) and last["close"] == 3.5 and last["high"] == 4.0
    assert calls == [["ZZZ"]]


def test_leaves_bars_alone_outside_a_session_or_when_the_file_has_today():
    calls = []
    b = _bars(D(2026, 11, 10))
    assert board_data.with_today(b, "ZZZ", session=None, fetch=_fetch(calls)).equals(
        b
    )  # no session
    b2 = _bars(D(2026, 11, 11))
    assert len(board_data.with_today(b2, "ZZZ", session=D(2026, 11, 11), fetch=_fetch(calls))) == 2
    assert calls == []


def test_today_bars_caches_per_stock_and_survives_errors():
    calls = []
    board_data.today_bars(["AAA", "BBB"], now=0.0, fetch=_fetch(calls))
    board_data.today_bars(["AAA", "CCC"], now=30.0, fetch=_fetch(calls))  # AAA still fresh
    assert calls == [["AAA", "BBB"], ["CCC"]]

    def boom(tickers):
        raise OSError("offline")

    got = board_data.today_bars(["AAA", "DDD"], now=200.0, fetch=boom)
    assert got == {}  # stale entries refreshed to nothing, no exception
