"""Extra research data (insiders, news): parsing only, synthetic data."""

import datetime as dt
import io
import zipfile

from trading_os import research_extra as rx

A = "".join(["S", "R", "F"])


def test_quarters_stop_before_the_running_one():
    q = rx.quarters(2025, dt.date(2026, 10, 23))
    assert q[0] == (2025, 1) and q[-1] == (2026, 3)
    assert rx.quarters(2026, dt.date(2026, 2, 1)) == []


def _zip() -> bytes:
    files = {
        "SUBMISSION.tsv": "ACCESSION_NUMBER\tFILING_DATE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
        f"a1\t05-MAR-2024\t123\t{A.lower()}\n",
        "NONDERIV_TRANS.tsv": "ACCESSION_NUMBER\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\t"
        "TRANS_PRICEPERSHARE\n"
        "a1\t01-MAR-2024\tP\t1000\t10.5\na1\t01-MAR-2024\tA\t500\t0\n",
        "REPORTINGOWNER.tsv": "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNER_RELATIONSHIP\t"
        "RPTOWNER_TITLE\n"
        "a1\t99\tDirector,Officer\tCEO\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_insider_table_keeps_open_market_purchases_and_sales():
    t = rx.insider_table(_zip())
    assert len(t) == 1  # the award (code A) is left out
    row = t.iloc[0]
    assert row["ticker"] == A and row["code"] == "P" and row["value"] == 10_500
    assert row["filing_date"] == dt.date(2024, 3, 5) and row["trans_date"] == dt.date(2024, 3, 1)
    assert row["director"] and row["officer"] and not row["ten_pct"]
    assert row["owner_cik"] == 99


def test_news_rows_keep_headlines_only():
    body = {"news": [{"id": 7, "created_at": "2024-03-05T12:00:00Z", "headline": "x",
                      "source": "benzinga", "symbols": [A], "content": "long text"}]}  # fmt: skip
    rows = rx.news_rows(body, A, dt.date(2024, 3, 5))
    assert rows == [{"ticker": A, "session_date": dt.date(2024, 3, 5), "id": 7,
                     "created_at": "2024-03-05T12:00:00Z", "headline": "x", "source": "benzinga",
                     "symbols": A}]  # fmt: skip


def test_events_8k_keeps_8ks_with_their_items(tmp_path):
    import json

    main = {"filings": {"recent": {"form": ["8-K", "10-Q", "8-K"],
                                   "accessionNumber": ["x1", "x2", "x3"],
                                   "filingDate": ["2024-03-05", "2024-03-06", "2014-01-02"],
                                   "acceptanceDateTime": ["2024-03-05T16:05:00.000Z"] * 3,
                                   "items": ["1.01,9.01", "", "2.02"]}}}  # fmt: skip
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("CIK0000000123.json", json.dumps(main))
    t = rx.events_8k(path)
    want = {"cik": 123, "accession": "x1", "filed": "2024-03-05",
            "accepted": "2024-03-05T16:05:00.000Z", "items": "1.01,9.01"}  # fmt: skip
    assert t.to_dict("records") == [want]


def test_flow_totals_tick_test_retail_and_blocks():
    trades = [
        {"p": 10.00, "s": 100, "x": "Q"},
        {"p": 10.05, "s": 20_000, "x": "Q"},  # uptick: a buy, a block
        {"p": 10.05, "s": 300, "x": "D"},  # same price: still a buy; whole cents, not retail
        {"p": 10.0472, "s": 50, "x": "D"},  # downtick: a sell; 0.72 of a cent: a retail buy
        {"p": 10.0131, "s": 40, "x": "D"},  # downtick: a sell; 0.31 of a cent: a retail sell
    ]
    t = rx.flow_totals(trades)
    assert t["trades"] == 5 and t["volume"] == 20_490
    assert t["buy_vol"] == 20_300 and t["sell_vol"] == 90
    assert t["block_buy"] == 20_000 and t["block_sell"] == 0
    assert t["retail_buy"] == 50 and t["retail_sell"] == 40


def test_open_totals_first_5_15_30_minutes():
    import pandas as pd

    start = pd.Timestamp("2024-03-05T14:30:00Z")
    bars = [
        {"t": f"2024-03-05T14:{30 + m:02d}:00Z", "h": 10 + m, "l": 9 - m * 0.01, "v": 100}
        for m in range(30)
    ]
    t = rx.open_totals(bars, start)
    assert (t["vol_5m"], t["vol_15m"], t["vol_30m"]) == (500, 1500, 3000)
    assert t["orh_5m"] == 14 and t["orh_30m"] == 39


def test_daymins_saves_every_bar_of_each_session(tmp_path):
    import pandas as pd

    from trading_os import research_extra

    class Client:
        def _get(self, url, params):
            assert params["timeframe"] == "1Min" and params["adjustment"] == "all"
            first = {"t": "2026-01-02T14:30:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}
            second = {"t": "2026-01-02T14:31:00Z", "o": 1.5, "h": 2, "l": 1, "c": 2, "v": 7}
            return {"bars": [first, second]}

    asks = pd.DataFrame(
        {"ticker": ["AAA"], "session_date": ["2026-01-02"], "start_utc": ["2026-01-02T14:30:00Z"]}
    )
    asks.to_parquet(tmp_path / "req.parquet")
    assert research_extra.daymins(Client(), tmp_path / "req.parquet", tmp_path / "out") == 0
    got = pd.read_parquet(tmp_path / "out" / "daymins.parquet")
    assert len(got) == 2 and got["c"].tolist() == [1.5, 2]
