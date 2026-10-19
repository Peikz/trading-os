import datetime as dt

import pytest

from trading_os import massive
from trading_os.history import BAR_COLUMNS

DAY = dt.date(2026, 10, 16)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def test_rate_limiter_spaces_calls_12s_apart_at_5_per_minute():
    fake = FakeClock()
    limiter = massive.RateLimiter(5, clock=fake.clock, sleep=fake.sleep)
    limiter.wait()  # first call: no wait
    fake.now += 2.0  # the request took 2 s
    limiter.wait()
    limiter.wait()
    assert fake.slept == [10.0, 12.0]


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise massive.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, params, headers, timeout):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.response


def client(response):
    session = FakeSession(response)
    limiter = massive.RateLimiter(1000, sleep=lambda s: None)
    return massive.MassiveClient(
        "k3y", "https://api.massive.com/", limiter, session=session
    ), session


def test_grouped_daily_maps_fields_and_keeps_key_out_of_url():
    body = {
        "status": "OK",
        "adjusted": True,
        "resultsCount": 1,
        "results": [
            {"T": "AAA", "o": 10, "h": 12, "l": 9, "c": 11, "v": 1000, "vw": 10.8, "n": 50}
        ],
    }
    c, session = client(FakeResponse(body))
    bars = c.grouped_daily(DAY)
    [call] = session.calls
    assert (
        call["url"] == "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/2026-10-16"
    )
    assert "k3y" not in call["url"] and call["params"] == {"adjusted": "true"}
    assert call["headers"] == {"Authorization": "Bearer k3y"}
    assert list(bars.columns) == BAR_COLUMNS
    row = bars.iloc[0]
    assert (row["ticker"], row["close"], row["volume"], row["trades"]) == ("AAA", 11, 1000.0, 50)
    assert row["session_date"] == DAY and row["source"] == "massive" and bool(row["adjusted"])


def test_no_results_is_an_empty_frame():
    c, _ = client(FakeResponse({"status": "OK", "resultsCount": 0}))
    bars = c.grouped_daily(DAY)
    assert bars.empty and list(bars.columns) == BAR_COLUMNS


def test_bad_status_raises():
    c, _ = client(FakeResponse({"status": "ERROR", "error": "nope"}))
    with pytest.raises(massive.MassiveError):
        c.grouped_daily(DAY)


def test_http_error_raises():
    c, _ = client(FakeResponse({}, status=429))
    with pytest.raises(massive.requests.HTTPError):
        c.grouped_daily(DAY)


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        massive.MassiveClient("", "https://x", massive.RateLimiter(5))
