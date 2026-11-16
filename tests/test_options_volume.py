"""The options-volume collector against a fake client (no network, synthetic data)."""

import datetime as dt

import pandas as pd
import requests

from trading_os import options_volume as ov

T = "ZZZ"
DAY = "2026-03-02"


def ms(date: str) -> int:
    return int(dt.datetime.fromisoformat(date).replace(tzinfo=dt.UTC).timestamp() * 1000)


def contract(n: int, exp: str, kind: str = "call") -> dict:
    return {
        "ticker": f"O:{T}{n}",
        "expiration_date": exp,
        "strike_price": 10.0 + n,
        "contract_type": kind,
    }


class Fake:
    def __init__(self, contracts, forbidden=()):
        self.contracts, self.forbidden = contracts, set(forbidden)
        self.params, self.bar_calls = [], []

    def option_contracts(self, params):
        self.params.append(params)
        return self.contracts, 2

    def daily_bars(self, symbol, start, end):
        self.bar_calls.append((symbol, start, end))
        if symbol in self.forbidden:
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError(response=response)
        return [{"t": ms("2026-02-27"), "v": 7, "c": 1.5, "vw": 1.4, "n": 3}]


def targets(tmp_path, rows):
    path = ov.targets_path(tmp_path)
    path.parent.mkdir(parents=True)
    pd.DataFrame(rows, columns=["ticker", "day", "ref_price"]).to_parquet(path)


def test_nearest_two_expirations():
    cs = [contract(i, f"2026-03-{d}") for i, d in enumerate(["20", "06", "13", "27", "06"])]
    kept = ov.nearest_expirations(cs)
    assert {c["expiration_date"] for c in kept} == {"2026-03-06", "2026-03-13"}
    assert len(kept) == 3


def test_one_list_call_as_of_the_day_without_expired():
    fake = Fake([contract(1, "2026-03-06")])
    rows, calls = ov.list_contracts(fake, T, dt.date(2026, 3, 2), 50.0)
    assert len(fake.params) == 1 and "expired" not in fake.params[0]
    assert fake.params[0]["as_of"] == "2026-03-02"
    assert calls == 2 and len(rows) == 1


def test_params_from_ref_price_and_day():
    p = ov.contract_params(T, dt.date(2026, 3, 2), 50.0)
    assert p["underlying_ticker"] == T
    assert p["as_of"] == "2026-03-02"
    assert p["expiration_date.gt"] == "2026-03-02"
    assert p["expiration_date.lte"] == "2026-05-01"
    assert p["strike_price.gte"] == 45.0
    assert p["strike_price.lte"] == 55.0
    assert p["limit"] == 1000


def test_run_writes_rows_and_bar_window(tmp_path):
    targets(tmp_path, [(T, DAY, 50.0)])
    fake = Fake([contract(1, "2026-03-06", "put")])
    done, calls, remaining = ov.run(tmp_path, fake, deadline=1e12)
    assert (done, calls, remaining) == (1, 3, 0)
    assert fake.bar_calls[0][1:] == (dt.date(2026, 1, 31), dt.date(2026, 3, 2))
    out = pd.read_parquet(ov.out_path(tmp_path, DAY, T))
    assert list(out.columns) == ov.COLUMNS
    assert out.iloc[0]["contract_type"] == "put"
    assert out.iloc[0]["bar_date"] == "2026-02-27"


def test_resume_skips_existing(tmp_path):
    targets(tmp_path, [(T, DAY, 50.0), ("YYY", "2026-03-03", 20.0)])
    ov._write(ov.out_path(tmp_path, DAY, T), [])
    fake = Fake([])
    done, _, remaining = ov.run(tmp_path, fake, deadline=1e12)
    assert done == 1 and remaining == 0
    assert len(fake.params) == 1 and fake.params[0]["underlying_ticker"] == "YYY"


def test_empty_file_for_no_contracts(tmp_path):
    targets(tmp_path, [(T, DAY, 50.0)])
    ov.run(tmp_path, Fake([]), deadline=1e12)
    out = pd.read_parquet(ov.out_path(tmp_path, DAY, T))
    assert out.empty and list(out.columns) == ov.COLUMNS
    assert not list(tmp_path.rglob("*.part"))


def test_403_on_bars_is_zero_rows_and_continues(tmp_path):
    targets(tmp_path, [(T, DAY, 50.0)])
    fake = Fake([contract(1, "2026-03-06"), contract(2, "2026-03-06")], forbidden={f"O:{T}1"})
    ov.run(tmp_path, fake, deadline=1e12)
    out = pd.read_parquet(ov.out_path(tmp_path, DAY, T))
    assert list(out["contract"]) == [f"O:{T}2"]
    assert len(fake.bar_calls) == 2


def test_time_budget_stops_between_targets(tmp_path):
    targets(tmp_path, [(T, DAY, 50.0), (T, "2026-03-03", 50.0), (T, "2026-03-04", 50.0)])
    ticks = iter([0, 100, 100])
    done, _, remaining = ov.run(tmp_path, Fake([]), deadline=50, clock=lambda: next(ticks))
    assert (done, remaining) == (1, 2)


def test_stdout_has_no_ticker(tmp_path, capsys):
    targets(tmp_path, [(T, DAY, 50.0)])
    ov.run(tmp_path, Fake([contract(1, "2026-03-06")]), deadline=1e12)
    out = capsys.readouterr().out
    assert T not in out and "O:" not in out and DAY not in out
    assert "1 targets done this run" in out
