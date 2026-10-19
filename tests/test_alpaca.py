"""Alpaca client against canned responses (no network)."""

import datetime as dt

import pytest
import requests

from trading_os.alpaca import AlpacaClient


class Response:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._body


class Http:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params, headers, timeout):
        self.calls.append(dict(params))
        return self.responses.pop(0)


def bar(t, c):
    return {"t": t, "o": c, "h": c, "l": c, "c": c, "v": 100, "n": 3, "vw": c}


DAY = dt.datetime(2016, 1, 4, tzinfo=dt.UTC)


def client(responses):
    http = Http(responses)
    return AlpacaClient("id", "secret", 1e9, session=http, sleep=lambda s: None), http


def test_needs_keys():
    with pytest.raises(ValueError):
        AlpacaClient("", "x")


def test_bars_follow_page_tokens_across_symbols():
    pages = [
        Response(200, {"bars": {"A": [bar("2016-01-04T05:00:00Z", 1.0)]}, "next_page_token": "p2"}),
        Response(200, {"bars": {"B": [bar("2016-01-04T05:00:00Z", 2.0)]}, "next_page_token": None}),
    ]
    c, http = client(pages)
    frame = c.bars(["A", "B"], "1Day", DAY, DAY + dt.timedelta(days=1))
    assert frame["ticker"].tolist() == ["A", "B"] and frame["close"].tolist() == [1.0, 2.0]
    assert http.calls[1]["page_token"] == "p2" and http.calls[0]["symbols"] == "A,B"
    assert str(frame["ts"].dt.tz) == "UTC"


def test_rate_limit_waits_and_sip_falls_back_to_iex():
    c, http = client([Response(429), Response(403), Response(200, {"bars": {}})])
    frame = c.bars(["A"], "1Min", DAY, DAY)
    assert frame.empty and c.feed == "iex" and http.calls[-1]["feed"] == "iex"


def test_ep_minutes_writes_one_file_per_month_and_skips_done_months(tmp_path):
    import pandas as pd

    from trading_os import alpaca

    days = [dt.date(2026, 9, 29), dt.date(2026, 9, 30), dt.date(2026, 10, 1), dt.date(2026, 10, 2)]
    study = pd.DataFrame(
        {
            "session_date": [days[1], days[2], days[2]],
            "ticker": ["AAA", "BBB", "CCC"],
            "is_ep_day": [True, True, True],
            "tier": ["alert", "alert", "log"],
        }
    )
    folder = tmp_path / "data" / "ep_history"
    folder.mkdir(parents=True)
    study.to_parquet(folder / "ep_history_2026-10-02.parquet")

    class Fake:
        calls = []

        def bars(self, symbols, timeframe, start, end):
            self.calls.append((tuple(symbols), timeframe))
            ts = pd.Timestamp(start)
            return pd.DataFrame({"ticker": list(symbols), "ts": [ts] * len(symbols), "close": 1.0})

    fake = Fake()
    out = tmp_path / "minutes"
    done = alpaca.ep_minutes(tmp_path, fake, out, days)
    assert done == {"2026-10": 2, "2026-09": 1}
    assert ("BBB", "CCC") in [c[0] for c in fake.calls]  # same-day EPs share a request
    month = pd.read_parquet(out / "2026-10.parquet")
    assert set(month["ticker"]) == {"BBB", "CCC"} and set(month["event_date"]) == {days[2]}
    again = Fake()
    again.calls = []
    assert alpaca.ep_minutes(tmp_path, again, out, days) == {} and again.calls == []
