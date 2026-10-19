"""SEC EDGAR parsing against canned responses (no network)."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import sec


class Http:
    def __init__(self, bodies):
        self.bodies, self.urls = bodies, []

    def get(self, url, headers, timeout):
        self.urls.append(url)
        code, body = self.bodies[url]

        class Response:
            status_code = code

            def raise_for_status(self):
                if code >= 400:
                    raise sec.requests.HTTPError(response=self)

            def json(self):
                return body

        return Response()


def client(bodies):
    return sec.SecClient("Name name@example.org", 1000, session=Http(bodies), sleep=lambda s: None)


def test_needs_a_contact():
    with pytest.raises(ValueError):
        sec.SecClient("no contact", 5)


def test_earnings_releases_are_8k_item_202_since_a_date():
    recent = {
        "form": ["8-K", "10-Q", "8-K", "8-K"],
        "items": ["2.02,9.01", "", "5.07", "2.02"],
        "filingDate": ["2026-07-30", "2026-08-01", "2026-06-01", "2024-01-30"],
        "acceptanceDateTime": ["2026-07-30T16:05:12.000Z", "x", "y", "z"],
    }
    url = sec.SUBMISSIONS_URL.format(cik=42)
    got = client({url: (200, {"filings": {"recent": recent, "files": []}})}).earnings_releases(
        42, dt.date(2025, 1, 1)
    )
    assert got == [{"cik": 42, "filed": "2026-07-30", "accepted": "2026-07-30T16:05:12.000Z"}]
    missing = client({sec.SUBMISSIONS_URL.format(cik=7): (404, None)})
    assert missing.earnings_releases(7, dt.date(2025, 1, 1)) == []


def test_quarters_start_a_year_early_for_yoy():
    assert sec.quarters(dt.date(2025, 3, 1), dt.date(2025, 5, 1)) == [
        "CY2024Q1",
        "CY2024Q2",
        "CY2024Q3",
        "CY2024Q4",
        "CY2025Q1",
        "CY2025Q2",
    ]


def test_quarterly_derives_q4_from_the_year_and_prefers_the_first_revenue_tag():
    rows = [
        {"cik": 1, "end": f"2025-0{m}-30", "val": v, "accn": "a", "concept": c, "period": p}
        for c, p, m, v in [
            ("EarningsPerShareDiluted", "CY2025Q1", 3, 1.0),
            ("EarningsPerShareDiluted", "CY2025Q2", 6, 1.0),
            ("EarningsPerShareDiluted", "CY2025Q3", 9, 1.0),
            ("EarningsPerShareDiluted", "CY2025", 9, 4.5),
            ("Revenues", "CY2025Q1", 3, 100.0),
            ("SalesRevenueNet", "CY2025Q1", 3, 999.0),
        ]
    ]
    table = sec.quarterly(pd.DataFrame(rows)).set_index("period")
    assert (
        table.loc["CY2025Q4", "eps"] == pytest.approx(1.5) and table.loc["CY2025Q4", "eps_derived"]
    )
    assert table.loc["CY2025Q1", "revenue"] == 100.0  # Revenues outranks SalesRevenueNet
