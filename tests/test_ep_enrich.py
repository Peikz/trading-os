"""The resumable Massive fetch for the EP study, against a fake client (no network)."""

import datetime as dt

import pandas as pd
import pytest
import requests

from trading_os import ep_enrich
from trading_os.massive import MassiveClient

DAYS = [dt.date(2026, 10, d) for d in (13, 14, 15, 16)]
A, B, C = ("".join(["A", "A", "X"]), "".join(["B", "B", "X"]), "".join(["C", "C", "X"]))


def write_study(tmp_path):
    study = pd.DataFrame(
        {
            "session_date": [DAYS[1], DAYS[2], DAYS[2], DAYS[3]],
            "ticker": [A, B, C, A],
            "is_ep_day": [True, True, False, True],  # C is EP9M only: not fetched
            "tier": ["log", "alert", "alert", "alert"],
        }
    )
    folder = tmp_path / "data" / "ep_history"
    folder.mkdir(parents=True)
    study.to_parquet(folder / "ep_history_2026-10-16.parquet")


class Fake:
    def __init__(self):
        self.calls = []

    def tickers(self, *, active):
        self.calls.append(("tickers", active))
        return [{"ticker": A, "type": "CS", "active": active}]

    def minute_bars(self, ticker, start, end):
        self.calls.append(("minutes", ticker, start, end))
        ts = pd.Timestamp(f"{start} 13:30", tz="UTC")
        return pd.DataFrame({"ticker": [ticker], "ts": [ts], "open": [1.0], "close": [1.1]})

    def short_interest(self, ticker):
        self.calls.append(("short", ticker))
        return [{"settlement_date": "2026-09-30", "short_interest": 1000, "days_to_cover": 2.5}]

    def ticker_details(self, ticker, day):
        self.calls.append(("details", ticker, day))
        if ticker == A and day == DAYS[2]:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        return {"market_cap": 5e8, "share_class_shares_outstanding": 2e7, "type": "CS"}

    def news_between(self, ticker, start, end):
        self.calls.append(("news", ticker, start, end))
        return [{"title": "Beats", "publisher": "PR", "published_utc": end, "url": ""}]


def test_minute_bars_are_left_to_alpaca_by_default(tmp_path):
    write_study(tmp_path)
    fake = Fake()
    ep_enrich.run(tmp_path, fake, DAYS, max_calls=100, deadline=1e18)
    assert not [c for c in fake.calls if c[0] == "minutes"]


def test_fetches_in_priority_order_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(ep_enrich, "FETCH_MINUTES", True)
    write_study(tmp_path)
    fake = Fake()
    done = ep_enrich.run(tmp_path, fake, DAYS, max_calls=100, deadline=1e18)
    kinds = [c[0] for c in fake.calls]
    assert kinds[:2] == ["tickers", "tickers"]
    # Alert tier first, newest first: A on 16 Oct, then B on 15 Oct; the log-tier A last.
    minutes = [c[1:] for c in fake.calls if c[0] == "minutes"]
    assert minutes[0] == (A, DAYS[2], DAYS[3]) and minutes[1] == (B, DAYS[1], DAYS[3])
    assert minutes[2] == (A, DAYS[0], DAYS[2])
    assert all(c[1] != C for c in fake.calls if len(c) > 1)  # EP9M-only events are skipped
    assert done["minutes"] == 3 and done["short_interest"] == 2 and done["news"] == 3
    assert ep_enrich.minutes_path(tmp_path, DAYS[3], A).exists()
    shorts = pd.concat(
        pd.read_parquet(f) for f in (tmp_path / "data/ep_enrich/short_interest").glob("*.parquet")
    )
    assert set(shorts["ticker"]) == {A, B} and shorts["days_to_cover"].iloc[0] == 2.5
    # The 404 on A's details is recorded, so a second run asks for nothing again.
    again = Fake()
    ep_enrich.run(tmp_path, again, DAYS, max_calls=100, deadline=1e18)
    assert again.calls == []


def test_news_window_is_prior_close_to_ep_close():
    start, end = ep_enrich._news_window(DAYS[3], DAYS[2])
    assert (start, end) == ("2026-10-15T20:00:00Z", "2026-10-16T20:00:00Z")  # 16:00 EDT


def test_budget_and_deadline_stop_the_run(tmp_path):
    write_study(tmp_path)
    fake = Fake()
    ep_enrich.run(tmp_path, fake, DAYS, max_calls=3, deadline=1e18)
    assert len(fake.calls) <= 4  # the ticker list (2 calls, counted as 2) and one more
    late = Fake()
    ep_enrich.run(tmp_path, late, DAYS, max_calls=100, deadline=0)
    assert late.calls == []


def test_deadline_takes_the_earlier_stop():
    now = dt.datetime(2026, 10, 19, 22, 40, tzinfo=dt.UTC).timestamp()
    end = ep_enrich.deadline(now, 345, "04:20")
    assert dt.datetime.fromtimestamp(end, dt.UTC) == dt.datetime(2026, 10, 20, 4, 20, tzinfo=dt.UTC)
    assert ep_enrich.deadline(now, 10, "04:20") == pytest.approx(now + 600)


def test_client_waits_once_on_a_rate_limit():
    class Response:
        def __init__(self, code):
            self.status_code, self.ok = code, code == 200

        def raise_for_status(self):
            if not self.ok:
                raise requests.HTTPError(response=self)

        def json(self):
            return {"results": [{"t": 1_760_000_000_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 5}]}

    class Http:
        def __init__(self):
            self.codes = [429, 200]

        def get(self, url, params, headers, timeout):
            return Response(self.codes.pop(0))

    class NoWait:
        def wait(self):
            pass

    slept = []
    client = MassiveClient("k", "https://x", NoWait(), session=Http(), sleep=slept.append)
    bars = client.minute_bars(A, DAYS[0], DAYS[1])
    assert slept == [60] and len(bars) == 1 and bars["ts"].iloc[0].year == 2025
