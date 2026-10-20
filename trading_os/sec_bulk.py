"""Point-in-time fundamentals for the 10-year study from SEC EDGAR's free bulk files.

Work in progress: this first part holds the HTTP client and the acceptance-time audit.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from trading_os.logsafe import status

NEW_YORK = ZoneInfo("America/New_York")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
HEADER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index-headers.html"
# EDGAR's own record of the acceptance: Eastern wall-clock time, YYYYMMDDHHMMSS.
ACCEPTANCE_RE = re.compile(r"ACCEPTANCE-DATETIME(?:>|&gt;)\s*(\d{14})")
FILING_FIELDS = (
    "accessionNumber",
    "filingDate",
    "reportDate",
    "acceptanceDateTime",
    "act",
    "form",
    "items",
    "size",
    "isXBRL",
    "isInlineXBRL",
    "primaryDocument",
)


class BulkClient:
    """SEC's fair-access rules: a User-Agent with a contact, at most `per_second` requests."""

    def __init__(
        self,
        user_agent: str,
        per_second: float,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if "@" not in user_agent:
            raise ValueError("SEC needs a contact email in the User-Agent")
        self._headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._http = session or requests.Session()
        self._gap, self._sleep, self._clock, self._last = 1 / per_second, sleep, clock, None

    def _response(self, url: str, *, stream: bool = False) -> requests.Response | None:
        """The response for `url`; None for a 404. Waits and retries on 429/5xx."""
        for attempt in range(1, 5):
            if self._last is not None:
                wait = self._gap - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            response = self._http.get(url, headers=self._headers, timeout=120, stream=stream)
            if response.status_code == 404:
                return None
            if (response.status_code == 429 or response.status_code >= 500) and attempt < 4:
                self._sleep(10 * attempt)
                continue
            response.raise_for_status()
            return response
        return None

    def json(self, url: str) -> dict | list | None:
        response = self._response(url)
        return None if response is None else response.json()

    def text(self, url: str) -> str | None:
        response = self._response(url)
        return None if response is None else response.text


def filings_frame(page: dict, cik: int) -> pd.DataFrame:
    """One submissions page (the `recent` block or an older `-submissions-NNN` file) as rows."""
    n = len(page.get("accessionNumber") or [])
    columns = {f: page.get(f) or [None] * n for f in FILING_FIELDS}
    return pd.DataFrame(columns).assign(cik=cik)


def header_acceptance(text: str) -> dt.datetime | None:
    """The acceptance time in a filing's index headers: naive Eastern wall-clock time."""
    found = ACCEPTANCE_RE.search(text or "")
    return dt.datetime.strptime(found.group(1), "%Y%m%d%H%M%S") if found else None


def offset_class(json_value: str, header_et: dt.datetime) -> str:
    """How the submissions JSON's `acceptanceDateTime` relates to the true time.

    utc: it is the UTC time. plus_offset: UTC plus the Eastern offset again (Eastern wall
    time + 2 x offset). et_wall: the Eastern wall time with a "Z". other: none of these.
    """
    raw = dt.datetime.fromisoformat(json_value.replace("Z", "")).replace(tzinfo=None)
    local = header_et.replace(tzinfo=NEW_YORK)
    true_utc = local.astimezone(dt.UTC).replace(tzinfo=None)
    offset = -local.utcoffset().total_seconds() / 3600  # 4 in summer, 5 in winter
    hours = (raw - true_utc).total_seconds() / 3600
    for name, expected in (("utc", 0.0), ("plus_offset", offset), ("et_wall", -offset)):
        if abs(hours - expected) < 0.02:
            return name
    return "other"


def _sample_ciks(ciks: Iterable[int], per_mille: int) -> list[int]:
    """A fixed pseudo-random sample (Knuth's multiplicative hash), the same on every run."""
    return sorted(c for c in set(ciks) if (c * 2654435761) % 1000 < per_mille)


def audit_acceptance(client: BulkClient, per_mille: int = 6, max_headers: int = 400) -> Counter:
    """Compare the submissions JSON's acceptance times with EDGAR's index headers on a sample
    of earnings 8-Ks and periodic reports, one per company, form and year. Counts only."""
    listed = client.json(TICKERS_URL) or {}
    ciks = _sample_ciks((int(v["cik_str"]) for v in listed.values()), per_mille)
    picked = []
    for cik in ciks:
        body = client.json(SUBMISSIONS_URL.format(cik=cik))
        if not body:
            continue
        rows = filings_frame(body["filings"]["recent"], cik)
        rows = rows[rows["filingDate"].fillna("") >= "2015-01-01"]
        earnings = rows["form"].eq("8-K") & rows["items"].fillna("").str.contains("2.02")
        periodic = rows["form"].isin(["10-Q", "10-K"])
        rows = rows[earnings | periodic].assign(
            kind=lambda r: r["form"].where(r["form"] != "8-K", "8-K 2.02"),
            year=lambda r: r["filingDate"].str.slice(0, 4),
        )
        picked.append(rows.drop_duplicates(["kind", "year"]))
    sample = pd.concat(picked, ignore_index=True) if picked else pd.DataFrame()
    if len(sample) > max_headers:
        sample = sample.sample(max_headers, random_state=7)
    counts: Counter = Counter()
    for row in sample.itertuples():
        accession = row.accessionNumber
        folder = accession.replace("-", "")
        text = client.text(HEADER_URL.format(cik=row.cik, folder=folder, accession=accession))
        header = header_acceptance(text)
        if header is None or not row.acceptanceDateTime:
            counts[("all", "no header")] += 1
            continue
        cls = offset_class(row.acceptanceDateTime, header)
        raw = dt.datetime.fromisoformat(row.acceptanceDateTime.replace("Z", "+00:00"))
        et = raw.astimezone(NEW_YORK)
        same_day = et.date().isoformat() == row.filingDate
        late = et.hour * 60 + et.minute >= 17 * 60 + 30
        prefix = int(row.accessionNumber.split("-")[0])
        for feature, value in (
            ("all", "all"),
            ("kind", row.kind),
            ("year", row.year),
            ("xbrl", f"{row.isXBRL}/{row.isInlineXBRL}"),
            ("self_filed", prefix == row.cik),
            ("json_et_hour", f"{et.hour:02d}"),
            ("late_same_day", late and same_day),
            ("header_hour", f"{header.hour:02d}"),
            ("weekday", header.strftime("%a")),
        ):
            counts[(f"{feature}={value}", cls)] += 1
    return counts


def report_audit(counts: Counter) -> None:
    classes = ("utc", "plus_offset", "et_wall", "other")
    groups = sorted({key for key, _ in counts})
    for key in groups:
        cells = ", ".join(f"{c} {counts[(key, c)]}" for c in classes if counts[(key, c)])
        status(f"  {key}: {cells or counts[(key, 'no header')]}")


def main(argv: list[str] | None = None) -> int:
    from trading_os.logsafe import run_guarded

    return run_guarded(lambda: _main(argv), None, "SEC bulk")


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from trading_os.config import load_config

    parser = argparse.ArgumentParser(description="SEC EDGAR bulk fundamentals (10 years)")
    parser.add_argument("--mode", choices=["check"], default="check")
    parser.parse_args(argv)
    conf = load_config().sec
    agent = os.environ.get("SEC_USER_AGENT") or conf["user_agent"]
    if "@" not in agent:
        status("SEC bulk: set SEC_USER_AGENT (a name and contact email; SEC requires one)")
        return 1
    client = BulkClient(agent, conf["requests_per_second"])
    counts = audit_acceptance(client)
    status(f"SEC bulk check: {counts[('all=all', 'utc')]} filings with UTC acceptance times")
    report_audit(counts)
    return 0
