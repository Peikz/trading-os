"""SEC bulk fundamentals: parsing and point-in-time joins on tiny hand-made fixtures."""

import datetime as dt
import json
import zipfile

import exchange_calendars as xcals
import pandas as pd
import pytest

from trading_os import sec_bulk
from trading_os.config import load_config

D = dt.date


def test_header_acceptance_reads_the_eastern_wall_time():
    text = "<SEC-HEADER>&lt;ACCEPTANCE-DATETIME&gt;20250731163039\nACCESSION NUMBER: x"
    assert sec_bulk.header_acceptance(text) == dt.datetime(2025, 7, 31, 16, 30, 39)
    assert sec_bulk.header_acceptance("<ACCEPTANCE-DATETIME>20250102070001") == dt.datetime(
        2025, 1, 2, 7, 0, 1
    )
    assert sec_bulk.header_acceptance("nothing here") is None


def test_offset_class_names_the_three_conventions():
    header = dt.datetime(2025, 7, 31, 16, 30, 39)  # EDT, UTC-4
    assert sec_bulk.offset_class("2025-07-31T20:30:39.000Z", header) == "utc"
    assert sec_bulk.offset_class("2025-08-01T00:30:39.000Z", header) == "plus_offset"
    assert sec_bulk.offset_class("2025-07-31T16:30:39.000Z", header) == "et_wall"
    winter = dt.datetime(2025, 2, 3, 7, 0, 0)  # EST, UTC-5
    assert sec_bulk.offset_class("2025-02-03T12:00:00.000Z", winter) == "utc"
    assert sec_bulk.offset_class("2025-02-03T17:00:00.000Z", winter) == "plus_offset"
    assert sec_bulk.offset_class("2025-02-03T09:00:00.000Z", winter) == "other"


def test_acceptance_times_shift_impossible_and_late_same_day_values():
    raw = pd.Series(
        [
            "2025-07-31T20:30:39.000Z",  # 16:30 ET: kept
            "2025-08-01T00:16:24.000Z",  # 20:16 ET, same filing day: really 16:16
            "2025-07-31T15:00:00.000Z",  # 11:00 ET: could be 07:00 shown late
            "2025-07-31T02:10:00.000Z",  # 22:10 ET: EDGAR was closed, so 18:10
            "2025-07-31T22:00:00.000Z",  # 18:00 ET, filed the next day: genuinely late
            "2025-01-15T12:30:00.000Z",  # 07:30 EST: pre-market, nothing to check
            "2021-05-05T07:30:00.000Z",  # 03:30 ET on the filing day: 07:30 ET written as UTC
        ]
    )
    filed = pd.Series(
        [
            "2025-07-31",
            "2025-07-31",
            "2025-07-31",
            "2025-07-30",
            "2025-08-01",
            "2025-01-15",
            "2021-05-05",
        ]
    )
    got = sec_bulk.acceptance_times(raw, filed)
    utc = [t.strftime("%Y-%m-%d %H:%M") for t in got["accepted"]]
    assert utc == [
        "2025-07-31 20:30",
        "2025-07-31 20:16",
        "2025-07-31 15:00",
        "2025-07-30 22:10",
        "2025-07-31 22:00",
        "2025-01-15 12:30",
        "2021-05-05 11:30",
    ]
    assert list(got["time_basis"]) == [
        "json",
        "json_shifted",
        "json",
        "json_shifted",
        "json",
        "json",
        "json_shifted",
    ]
    assert list(got["ambiguous"]) == [False, False, True, False, False, False, False]


def test_apply_checks_takes_the_header_time():
    filings = pd.DataFrame({"accession": ["a", "b"], "accepted_raw": ["", ""]})
    filings = filings.join(
        sec_bulk.acceptance_times(
            pd.Series(["2025-07-31T15:00:00Z", "2025-07-31T15:00:00Z"]),
            pd.Series(["2025-07-31", "2025-07-31"]),
        )
    )
    checks = pd.DataFrame({"accession": ["a"], "header_et": ["20250731070000"]})
    got = sec_bulk.apply_checks(filings, checks)
    assert got.loc[0, "accepted"] == pd.Timestamp("2025-07-31 11:00", tz="UTC")
    assert list(got["time_basis"]) == ["header", "json"]
    assert list(got["ambiguous"]) == [False, True]


def test_reaction_sessions_and_timing():
    stamps = pd.Series(
        pd.to_datetime(
            [
                "2025-07-31 07:00",  # Thursday pre-market
                "2025-07-31 11:00",  # during the session
                "2025-07-31 16:30",  # after the close
                "2025-08-01 16:05",  # Friday after the close -> Monday
                "2025-04-18 07:00",  # Good Friday (NYSE closed) -> Monday
                "2025-11-28 14:00",  # after the 13:00 early close -> Monday
            ]
        ).tz_localize("America/New_York")
    ).dt.tz_convert("UTC")
    got = sec_bulk.reaction_sessions(stamps, "XNYS")
    assert list(got["reaction_session"]) == [
        D(2025, 7, 31),
        D(2025, 8, 1),
        D(2025, 8, 1),
        D(2025, 8, 4),
        D(2025, 4, 21),
        D(2025, 12, 1),
    ]
    assert list(got["timing"]) == [
        "pre-market",
        "intraday",
        "after-close",
        "after-close",
        "after-close",
        "after-close",
    ]


def _page(rows):
    keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "items"]
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


def test_read_submissions_keeps_earnings_8ks_and_reports_with_company_fields(tmp_path):
    recent = _page(
        [
            (
                "0001-25-1",
                "2025-05-07",
                "2025-05-07",
                "2025-05-07T20:05:00.000Z",
                "8-K",
                "2.02,9.01",
            ),
            ("0001-25-2", "2025-05-01", "2025-05-01", "2025-05-01T20:00:00.000Z", "8-K", "5.07"),
            ("0001-25-3", "2025-05-08", "2025-03-31", "2025-05-08T20:00:00.000Z", "10-Q", ""),
            ("0001-25-4", "2025-05-09", "", "2025-05-09T20:00:00.000Z", "4", ""),
        ]
    )
    main = {
        "cik": "42",
        "name": "Example Corp",
        "sic": "7372",
        "sicDescription": "Services-Prepackaged Software",
        "entityType": "operating",
        "category": "Non-accelerated filer<br>Smaller reporting company",
        "exchanges": ["Nasdaq"],
        "tickers": ["EXM"],
        "fiscalYearEnd": "1231",
        "formerNames": [
            {"name": "Example Acquisition Corp", "from": "2019-01-01T00:00:00", "to": "2021-03-04"}
        ],
        "filings": {"recent": recent, "files": [{"name": "CIK0000000042-submissions-001.json"}]},
    }
    older = _page(
        [
            ("0001-14-1", "2014-02-20", "2013-12-31", "2014-02-20T21:00:00.000Z", "10-K", ""),
            ("0001-12-1", "2012-02-20", "2011-12-31", "2012-02-20T21:00:00.000Z", "10-K", ""),
        ]
    )
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("CIK0000000042.json", json.dumps(main))
        zf.writestr("CIK0000000042-submissions-001.json", json.dumps(older))
        zf.writestr("CIK0000000099.json", json.dumps({**main, "cik": "99"}))
    filings, raw = sec_bulk.read_submissions(path, {42}, "2013-01-01", "2015-01-01")
    assert list(filings["accession"]) == ["0001-25-1", "0001-25-3", "0001-14-1"]
    assert set(filings["cik"]) == {42}
    companies = sec_bulk.companies_table(raw)
    row = companies.iloc[0]
    assert (row["cik"], row["sic"], row["sector"], row["exchange"]) == (
        42,
        7372,
        "Information Technology",
        "Nasdaq",
    )
    assert row["filer_category"] == "Non-accelerated filer; Smaller reporting company"
    assert not row["is_spac"] and row["spac_until"] == D(2021, 3, 4)
    assert not row["is_fund"] and row["last_filed"] == D(2025, 5, 9)


def _filings(rows):
    """(cik, accession, form, filed, report, accepted_raw) -> filings with best times."""
    columns = ["cik", "accession", "form", "filed", "report", "accepted_raw"]
    frame = pd.DataFrame(rows, columns=columns)
    return frame.join(sec_bulk.acceptance_times(frame["accepted_raw"], frame["filed"]))


def test_earnings_events_count_a_report_only_without_a_release():
    filings = _filings(
        [
            (1, "r1", "8-K", "2025-05-07", "2025-05-07", "2025-05-07T20:05:00Z"),
            (1, "q1", "10-Q", "2025-05-08", "2025-03-31", "2025-05-08T20:00:00Z"),
            (2, "r0", "8-K", "2025-03-10", "2025-03-10", "2025-03-10T20:05:00Z"),
            (2, "q2", "10-Q", "2025-05-12", "2025-03-31", "2025-05-12T11:00:00Z"),
            (2, "q0", "10-K", "2014-03-01", "2013-12-31", "2014-03-01T11:00:00Z"),
        ]
    )
    events = sec_bulk.earnings_events(filings, "2015-01-01", "XNYS")
    assert list(events["accession"]) == ["r1", "r0", "q2"]
    by = events.set_index("accession")
    assert by.loc["q2", "form"] == "10-Q" and by.loc["q2", "timing"] == "pre-market"
    assert by.loc["q2", "reaction_session"] == D(2025, 5, 12)
    assert by.loc["r1", "reaction_session"] == D(2025, 5, 8)


def _fact(start, end, val, accn, fy, fp, form, filed):
    return {
        "start": start,
        "end": end,
        "val": val,
        "accn": accn,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": filed,
    }


def _companyfacts(tmp_path):
    """FY ends in September. Q1-Q3 from 10-Qs, the year from the 10-K: Q4 is derived."""
    q1, q2, q3, fy = ("a1", 2025, "Q1"), ("a2", 2025, "Q2"), ("a3", 2025, "Q3"), ("a4", 2025, "FY")
    filed = {"a1": "2025-02-05", "a2": "2025-05-06", "a3": "2025-08-05", "a4": "2025-11-20"}

    def f(start, end, val, filing, form="10-Q"):
        accn, year, fp = filing
        return _fact(start, end, val, accn, year, fp, form, filed[accn])

    revenues = [
        f("2024-10-01", "2024-12-31", 110, q1),
        f("2023-10-01", "2023-12-31", 100, q1),
        f("2025-01-01", "2025-03-31", 120, q2),
        f("2024-01-01", "2024-03-31", 100, q2),
        f("2024-10-01", "2025-03-31", 230, q2),  # six months: neither a quarter nor a year
        f("2025-04-01", "2025-06-30", 130, q3),
        f("2024-04-01", "2024-06-30", 100, q3),
        f("2024-10-01", "2025-09-30", 500, fy, "10-K"),
        f("2023-10-01", "2024-09-30", 400, fy, "10-K"),
    ]
    sales = [f("2024-10-01", "2024-12-31", 999, q1)]  # a lower-ranked tag in the same filing
    eps = [
        f("2024-10-01", "2024-12-31", 1.1, q1),
        f("2023-10-01", "2023-12-31", 1.0, q1),
        f("2025-01-01", "2025-03-31", 1.2, q2),
        f("2025-04-01", "2025-06-30", 1.3, q3),
        f("2024-10-01", "2025-09-30", 5.0, fy, "10-K"),
    ]
    dei = [
        _fact(None, "2025-01-31", 900, "a1", 2025, "Q1", "10-Q", "2025-02-05"),
        _fact(None, "2025-01-31", 100, "a1", 2025, "Q1", "10-Q", "2025-02-05"),
    ]
    avg = [_fact("2025-01-01", "2025-03-31", 1010, "a2", 2025, "Q2", "10-Q", "2025-05-06")]
    body = {
        "cik": 7,
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": revenues}},
                "SalesRevenueNet": {"units": {"USD": sales}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
                "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": avg}},
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": dei}}},
        },
    }
    path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("CIK0000000007.json", json.dumps(body))
    return path


def test_quarterly_labels_fiscal_quarters_derives_q4_and_dates_it_by_the_release(tmp_path):
    facts = sec_bulk.read_facts(_companyfacts(tmp_path), {7}, "2013-01-01")
    filings = _filings(
        [
            (7, "e1", "8-K", "2025-02-04", "2025-02-04", "2025-02-04T21:05:00Z"),
            (7, "a1", "10-Q", "2025-02-05", "2024-12-31", "2025-02-05T21:00:00Z"),
            (7, "a2", "10-Q", "2025-05-06", "2025-03-31", "2025-05-06T21:00:00Z"),
            (7, "a3", "10-Q", "2025-08-05", "2025-06-30", "2025-08-05T21:00:00Z"),
            (7, "e4", "8-K", "2025-11-13", "2025-11-13", "2025-11-13T12:00:00Z"),
            (7, "a4", "10-K", "2025-11-20", "2025-09-30", "2025-11-20T21:00:00Z"),
        ]
    )
    events = sec_bulk.earnings_events(filings, "2015-01-01", "XNYS")
    q = sec_bulk.quarterly_table(facts, filings, events)
    q = q.set_index(["fiscal_year", "fiscal_quarter"])
    assert q.loc[(2025, 1), "period_end"] == D(2024, 12, 31)
    assert q.loc[(2025, 1), "revenue"] == 110 and q.loc[(2025, 1), "revenue_prior"] == 100
    assert q.loc[(2025, 1), "revenue_tag"] == "Revenues"  # outranks SalesRevenueNet
    assert q.loc[(2025, 1), "known_at"] == pd.Timestamp("2025-02-04 21:05", tz="UTC")
    assert q.loc[(2025, 2), "known_at"] == pd.Timestamp("2025-05-06 21:00", tz="UTC")  # no 8-K
    q4 = q.loc[(2025, 4)]
    assert q4["derived"] and q4["form"] == "10-K" and q4["period_end"] == D(2025, 9, 30)
    assert q4["revenue"] == 140 and q4["revenue_prior"] == 100  # 500-360, 400-300
    assert q4["eps"] == pytest.approx(1.4)  # 5.0 - 3.6
    assert q4["known_at"] == pd.Timestamp("2025-11-13 12:00", tz="UTC")
    assert not q.loc[(2025, 3), "derived"]
    # The prior-year Q1 is in the 10-Q as a comparative only, so it is a quarter of its own.
    assert q.loc[(2024, 1), "revenue"] == 100


def test_shares_sum_classes_and_fall_back_to_weighted_average(tmp_path):
    facts = sec_bulk.read_facts(_companyfacts(tmp_path), {7}, "2013-01-01")
    filings = _filings(
        [
            (7, "a1", "10-Q", "2025-02-05", "2024-12-31", "2025-02-05T21:00:00Z"),
            (7, "a2", "10-Q", "2025-05-06", "2025-03-31", "2025-05-06T21:00:00Z"),
        ]
    )
    shares = sec_bulk.shares_table(facts, filings)
    assert list(shares["shares"]) == [1000, 1010]
    assert list(shares["source"]) == ["dei", "weighted_basic"]
    assert list(shares["classes"]) == [2, 1]
    assert list(shares["as_of"]) == [D(2025, 1, 31), D(2025, 3, 31)]


def test_ticker_map_splits_a_reused_ticker_by_date():
    massive = pd.DataFrame(
        {
            "ticker": ["OLD", "ABC", "XYZ"],
            "cik": ["0000000010", "0000000030", None],
            "active": [False, True, False],
            "delisted_utc": ["2019-06-03T04:00:00Z", None, "2018-01-02T05:00:00Z"],
            "type": ["CS", "CS", "CS"],
            "name": ["Old Co", "Abc Inc", "Xyz"],
        }
    )
    current = pd.DataFrame({"ticker": ["OLD", "ABC", "NEW"], "cik": [20, 30, 40]})
    companies = pd.DataFrame({"cik": [10, 20, 30, 40], "last_filed": [None] * 4})
    got = sec_bulk.ticker_map(massive, current, companies).set_index(["ticker", "cik"])
    assert got.loc[("OLD", 10), "valid_to"] == D(2019, 6, 3)
    assert got.loc[("OLD", 20), "valid_from"] == D(2019, 6, 4)
    assert got.loc[("OLD", 20), "reused"] and not got.loc[("ABC", 30), "reused"]
    assert got.loc[("ABC", 30), "source"] == "massive+sec"
    assert got.loc[("NEW", 40), "source"] == "sec"
    assert got.reset_index().set_index("ticker").loc["XYZ", "cik"] is pd.NA


def _tables():
    utc = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
    ticker_cik = pd.DataFrame(
        {
            "ticker": ["OLD", "OLD", "ABC"],
            "cik": pd.array([10, 20, 30], dtype="Int64"),
            "valid_from": [None, D(2019, 6, 4), None],
            "valid_to": [D(2019, 6, 3), None, None],
        }
    )
    events = pd.DataFrame(
        {
            "cik": [30, 30],
            "reaction_session": [D(2025, 5, 8), D(2025, 8, 7)],
            "timing": ["pre-market", "after-close"],
        }
    )
    quarterly = pd.DataFrame(
        {
            "cik": [30, 30, 30],
            "fiscal_year": [2024, 2025, 2025],
            "fiscal_quarter": [4, 1, 2],
            "period_end": [D(2024, 12, 31), D(2025, 3, 31), D(2025, 6, 30)],
            "accepted": [utc("2025-02-12 21:00"), utc("2025-05-20 21:00"), utc("2025-08-12 21:00")],
            # Q1 was announced before the open on 8 May, Q2 after the close on 6 Aug.
            "known_at": [utc("2025-02-10 21:00"), utc("2025-05-08 11:00"), utc("2025-08-06 20:05")],
            "eps": [1.2, 1.5, 2.0],
            "eps_prior": [1.0, 1.0, 1.0],
            "revenue": [120.0, 150.0, 200.0],
            "revenue_prior": [100.0, 100.0, 100.0],
        }
    )
    shares = pd.DataFrame(
        {
            "cik": [30, 30],
            "accepted": [utc("2025-05-08 21:00"), utc("2025-08-06 22:00")],
            "as_of": [D(2025, 5, 1), D(2025, 8, 1)],
            "shares": [1000.0, 2000.0],
            "source": ["dei", "dei"],
        }
    )
    companies = pd.DataFrame(
        {
            "cik": [10, 20, 30],
            "sic": pd.array([6770, 2834, 7372], dtype="Int64"),
            "sector": ["Financials", "Health Care", "Information Technology"],
            "is_spac": [True, False, False],
            "spac_until": [None, D(2020, 1, 15), None],
        }
    )
    return sec_bulk.Tables(ticker_cik, events, quarterly, shares, companies)


def test_pit_join_uses_only_what_was_public_before_the_open():
    rows = pd.DataFrame(
        {
            "ticker": ["ABC", "ABC", "ABC", "OLD", "OLD", "OLD", "ZZZ"],
            "session_date": [
                D(2025, 5, 8),
                D(2025, 8, 6),
                D(2025, 8, 7),
                D(2019, 5, 1),
                D(2019, 7, 1),
                D(2020, 3, 2),
                D(2025, 8, 6),
            ],
            "raw_close": [5.0, 10.0, 12.0, 10.0, 10.0, 20.0, 1.0],
        },
        index=[10, 11, 12, 13, 14, 15, 16],
    )
    got = sec_bulk.pit_join(rows, _tables(), quarter_sessions=63)
    assert list(got.index) == list(rows.index)
    cal = xcals.get_calendar("XNYS", start="2025-01-01")
    gap = len(cal.sessions_in_range("2025-05-08", "2025-08-06")) - 1
    abc = got.loc[[10, 11, 12]]
    # The pre-market release counts on its own day; the after-close one only the next day.
    assert list(abc["sessions_since_earnings"]) == [0, gap, 0]
    assert list(abc["is_earnings_reaction_day"]) == [True, False, True]
    assert list(abc["earnings_timing"]) == ["pre-market", "pre-market", "after-close"]
    assert list(abc["sessions_to_next_earnings_est"]) == [63, 63 - gap, 63]
    assert list(abc["eps_yoy_pct"]) == pytest.approx([50, 50, 100])
    assert list(abc["eps_yoy_prev_pct"]) == pytest.approx([20, 20, 50])
    assert list(abc["eps_growth_accel"]) == pytest.approx([30, 30, 50])
    assert list(abc["revenue_yoy_pct"]) == pytest.approx([50, 50, 100])
    assert abc.loc[12, "last_quarter_end"] == D(2025, 6, 30)
    # Shares filed after the 6 Aug open are used from 7 Aug; none were known on 8 May.
    assert pd.isna(abc.loc[10, "shares_outstanding"])
    assert list(abc["shares_outstanding"].iloc[1:]) == [1000, 2000]
    assert list(abc["market_cap_sec"].iloc[1:]) == [10_000, 24_000]
    assert abc.loc[11, "sector"] == "Information Technology" and abc.loc[11, "sic"] == 7372
    # A reused ticker: the old company until its delisting, the new one after.
    assert list(got.loc[[13, 14, 15], "cik"]) == [10, 20, 20]
    assert list(got.loc[[13, 14, 15], "is_spac"]) == [True, True, False]
    assert got.loc[16, "cik"] is pd.NA and pd.isna(got.loc[16, "sessions_since_earnings"])


def test_pit_join_filing_basis_waits_for_the_10q():
    rows = pd.DataFrame({"ticker": ["ABC", "ABC"], "session_date": [D(2025, 5, 8), D(2025, 5, 21)]})
    got = sec_bulk.pit_join(rows, _tables(), quarter_sessions=63, known="filing")
    assert list(got["eps_yoy_pct"]) == pytest.approx([20, 50])
    assert "market_cap_sec" in got and got["market_cap_sec"].isna().all()


def test_sector_from_sic():
    assert sec_bulk.sector(2834) == "Health Care"
    assert sec_bulk.sector(3674) == "Information Technology"
    assert sec_bulk.sector(1311) == "Energy"
    assert sec_bulk.sector(6770) == "Financials"
    assert sec_bulk.sector(6798) == "Real Estate"
    assert sec_bulk.sector(4911) == "Utilities"
    assert sec_bulk.sector(5812) == "Consumer Discretionary"
    assert sec_bulk.sector(9995) == "Other" and sec_bulk.sector(None) == "Other"


def test_config_has_the_sec_bulk_section():
    conf = load_config().sec_bulk
    assert conf["quarter_sessions"] == 63 and str(conf["events_since"]) == "2015-01-01"
