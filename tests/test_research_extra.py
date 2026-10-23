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
        "REPORTINGOWNER.tsv": "ACCESSION_NUMBER\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\n"
        "a1\tDirector,Officer\tCEO\n",
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


def test_news_rows_keep_headlines_only():
    body = {"news": [{"id": 7, "created_at": "2024-03-05T12:00:00Z", "headline": "x",
                      "source": "benzinga", "symbols": [A], "content": "long text"}]}  # fmt: skip
    rows = rx.news_rows(body, A, dt.date(2024, 3, 5))
    assert rows == [{"ticker": A, "session_date": dt.date(2024, 3, 5), "id": 7,
                     "created_at": "2024-03-05T12:00:00Z", "headline": "x", "source": "benzinga",
                     "symbols": A}]  # fmt: skip
