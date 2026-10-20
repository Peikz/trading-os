"""Raw (unadjusted) daily bars and their factor to the adjusted ones, on canned answers."""

import argparse
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import alpaca

D1, D2, D3 = dt.date(2020, 3, 2), dt.date(2020, 3, 3), dt.date(2020, 3, 4)
# ticker: (adjusted close, real close) on D1, D2, D3. SPLT split 4:1 and REVS reverse-split 1:10,
# both taking effect on D2; PAYS only paid dividends; BIG splits 20:1 after these days.
EXAMPLE = {
    "SPLT": [(25.0, 100.0), (25.5, 25.5), (26.0, 26.0)],
    "REVS": [(5.0, 0.5), (5.5, 5.5), (5.0, 5.0)],
    "PAYS": [(49.0, 50.0), (49.5, 50.0), (50.0, 50.0)],
    "BIG": [(0.25, 5.0), (0.25, 5.0), (0.25, 5.0)],
}
DAYS = (D1, D2, D3)


def adjusted_bars(gone: bool = True) -> pd.DataFrame:
    """The bars-alpaca columns the raw table needs; GONE is a stock-day with no raw bar."""
    rows = [(t, d, c[0]) for t, days in EXAMPLE.items() for d, c in zip(DAYS, days, strict=True)]
    if gone:
        rows.append(("GONE", D1, 2.0))
    return pd.DataFrame(rows, columns=["ticker", "session_date", "close"])


class Canned:
    """Alpaca answering with fixed bars (ticker, date, close) for whichever symbols are asked."""

    feed = "sip"

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def bars(self, symbols, timeframe, start, end, **bar_args):
        self.calls.append((tuple(symbols), bar_args))
        frame = pd.DataFrame(self.rows, columns=["ticker", "day", "close"])
        frame = frame[frame["ticker"].isin(symbols)]
        ts = [pd.Timestamp(f"{d}T05:00:00Z") for d in frame["day"]]  # midnight New York (EST)
        close = frame["close"]
        return frame.drop(columns="day").assign(
            ts=ts, open=close, high=close, low=close, volume=1000.0, trades=3, vwap=close
        )


def example_bars() -> Canned:
    """The example's real prices, plus a stock-day the adjusted bars know nothing about."""
    rows = [(t, d, c[1]) for t, days in EXAMPLE.items() for d, c in zip(DAYS, days, strict=True)]
    return Canned([*rows, ("EXTRA", D1, 3.0)])


def example_table() -> pd.DataFrame:
    raw = alpaca.daily_year_raw(example_bars(), ["SPLT", "REVS", "PAYS", "BIG", "EXTRA"], 2020)
    return alpaca.raw_table(raw, adjusted_bars())


def test_daily_year_raw_asks_for_raw_and_refuses_an_iex_fallback():
    fake = example_bars()
    year = alpaca.daily_year_raw(fake, ["SPLT"], 2020)
    assert fake.calls == [(("SPLT",), {"adjustment": "raw"})]
    assert year["session_date"].tolist() == [D1, D2, D3]
    assert year["close"].tolist() == [100.0, 25.5, 26.0]

    plain = example_bars()
    alpaca.daily_year(plain, ["SPLT"], 2020)  # the adjusted fetch passes nothing extra
    assert plain.calls == [(("SPLT",), {})]

    iex = example_bars()
    iex.feed = "iex"  # IEX closes are not the consolidated ones: no factor from them
    with pytest.raises(RuntimeError):
        alpaca.daily_year_raw(iex, ["SPLT"], 2020)


def test_factor_of_a_forward_split_a_reverse_split_and_dividends():
    table = example_table()
    assert list(table.columns) == [
        "ticker",
        "session_date",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "raw_volume",
        "factor",
    ]
    assert {str(t) for t in table.dtypes.iloc[2:]} == {"float32"}
    assert len(table) == len(adjusted_bars()) and "EXTRA" not in set(table["ticker"])

    def factors(ticker):
        return table.loc[table["ticker"] == ticker, "factor"].tolist()

    assert factors("SPLT") == [4.0, 1.0, 1.0]  # 100 / 25 before the 4:1 split, 1 after it
    assert factors("REVS") == pytest.approx([0.1, 1.0, 1.0])  # 0.5 / 5 before the 1:10 reverse
    assert factors("PAYS") == pytest.approx([50 / 49, 50 / 49.5, 1.0])  # dividends: a few percent
    assert factors("BIG") == [20.0, 20.0, 20.0]
    gone = table[table["ticker"] == "GONE"].iloc[0]
    assert np.isnan(gone["raw_close"]) and np.isnan(gone["factor"])

    # the adjusted price times the factor is the real one, on every stock-day that has both
    both = table.merge(adjusted_bars(), on=["ticker", "session_date"]).dropna()
    assert len(both) == 12
    assert (both["close"] * both["factor"]).tolist() == pytest.approx(both["raw_close"].tolist())
    assert table.loc[table["ticker"] == "REVS", "raw_close"].tolist() == [0.5, 5.5, 5.0]


def test_split_days_are_the_factor_jumps_and_the_year_boundary_counts():
    table = example_table()
    jumps = alpaca.factor_jumps(table)
    # 4:1 is a 0.25x step, 1:10 a 10x step; dividends and the later split don't show
    flagged = set(zip(table.loc[jumps, "ticker"], table.loc[jumps, "session_date"], strict=True))
    assert flagged == {("SPLT", D2), ("REVS", D2)}

    one = pd.DataFrame({"ticker": ["AAA"], "session_date": [D1], "factor": np.float32([1.0])})
    assert not alpaca.factor_jumps(one).any()
    # its factor was 4 on the last day of the year before: the split took effect today
    assert alpaca.factor_jumps(one, pd.Series({"AAA": np.float32(4.0)})).all()
    assert not alpaca.factor_jumps(one, pd.Series({"ZZZ": np.float32(4.0)})).any()


def test_counts_for_a_year_against_its_adjusted_twin():
    table, adjusted = example_table(), adjusted_bars()
    assert alpaca.raw_counts(adjusted, table, 1.0) == {
        "stock_days": 13,
        "stocks": 5,
        "no_raw_bar": 1,  # GONE
        "only_in_bars": 0,
        "only_in_raw": 0,
        "jump_stocks": 2,  # SPLT and REVS
        "jump_days": 2,
        "real_below_floor": 1,  # REVS on D1: $0.50 really, $5.00 adjusted
        "real_above_floor": 3,  # BIG: $5 really, $0.25 adjusted
    }
    short = alpaca.raw_counts(adjusted, table.iloc[1:], 1.0)  # a stock-day the raw file lacks
    assert short["only_in_bars"] == 1 and short["only_in_raw"] == 0
    extra = pd.concat([table, table.iloc[:1].assign(ticker="NEW")], ignore_index=True)
    assert alpaca.raw_counts(adjusted, extra, 1.0)["only_in_raw"] == 1


def test_raw_history_writes_a_file_per_year_and_skips_years_already_there(tmp_path):
    bars, raw = tmp_path / "bars", tmp_path / "raw"
    bars.mkdir()
    raw.mkdir()
    adjusted_bars(gone=False).to_parquet(bars / "2020.parquet")
    (raw / "raw_2021.parquet").touch()  # uploaded earlier
    fake = example_bars()
    assert alpaca.raw_history(fake, bars, raw, 2020, 2021) == [2020]
    # the symbols come from the adjusted file, so every stock-day in it is asked for
    assert fake.calls == [(("BIG", "PAYS", "REVS", "SPLT"), {"adjustment": "raw"})]
    written = pd.read_parquet(raw / "raw_2020.parquet")
    assert len(written) == 12 and written["factor"].dtype == "float32"
    assert written["session_date"].tolist()[:3] == [D1, D2, D3]  # sorted; dates, not timestamps
    assert not list(raw.glob("*.tmp"))

    args = argparse.Namespace(
        check=False,
        ep_minutes=False,
        daily_years=None,
        raw_years="2020-2021",
        bars=bars,
        raw_dir=raw,
    )
    again = example_bars()
    assert alpaca._run(args, again) == 0 and again.calls == []  # nothing left to fetch
    with pytest.raises(FileNotFoundError):  # a year with no adjusted file to match
        alpaca.raw_history(again, bars, raw, 2019, 2019)


def test_raw_history_writes_nothing_when_too_many_days_have_no_raw_bar(tmp_path):
    bars, raw = tmp_path / "bars", tmp_path / "raw"
    bars.mkdir()
    adjusted_bars().to_parquet(bars / "2020.parquet")  # GONE: 1 of 13 stock-days has no raw bar
    with pytest.raises(RuntimeError):
        alpaca.raw_history(example_bars(), bars, raw, 2020, 2020)
    assert not list(raw.glob("raw_*.parquet"))

    class Nothing(Canned):
        def bars(self, symbols, timeframe, start, end, **bar_args):
            return pd.DataFrame()

    with pytest.raises(RuntimeError):  # an empty answer is a failed fetch, not a table of NaN
        alpaca.raw_history(Nothing([]), bars, raw, 2020, 2020)


def test_raw_check_needs_no_keys_logs_counts_only_and_finds_a_split_on_new_years_day(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    bars, raw = tmp_path / "bars", tmp_path / "raw"
    bars.mkdir()
    raw.mkdir()
    # SPLT splits 4:1 on the first session of 2021: its factor is 4 on the last day of 2020, 1 after
    years = {2020: (dt.date(2020, 12, 31), 10.0, 40.0), 2021: (dt.date(2021, 1, 4), 10.5, 10.5)}
    for year, (day, adjusted_close, real_close) in years.items():
        adjusted = pd.DataFrame(
            {
                "ticker": ["SPLT", "QUIET"],
                "session_date": [day, day],
                "close": [adjusted_close, 20.0],
            }
        )
        adjusted.to_parquet(bars / f"{year}.parquet")
        canned = Canned([("SPLT", day, real_close), ("QUIET", day, 20.0)])
        alpaca.raw_history(canned, bars, raw, year, year)
    capsys.readouterr()

    assert alpaca.main(["--raw-check", "--bars", str(bars), "--raw-dir", str(raw)]) == 0
    out = capsys.readouterr().out
    assert "SPLT" not in out and "QUIET" not in out  # counts, never a ticker
    assert "2020" in out and "2021" in out and "$1.00" in out  # the floor is the config's $1.00
    results = alpaca.raw_check(bars, raw, 1.0)
    assert [(r["year"], r["jump_stocks"]) for r in results] == [(2020, 0), (2021, 1)]
    (raw / "raw_2020.parquet").unlink()  # without the year before there is nothing to compare
    assert [r["jump_stocks"] for r in alpaca.raw_check(bars, raw, 1.0)] == [0]
