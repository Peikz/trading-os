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
