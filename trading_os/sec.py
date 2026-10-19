"""SEC EDGAR for the EP study (Emil, 19 Oct 2026): exact earnings dates and quarterly EPS and
revenue as filed, including companies delisted since. Free; SEC asks for a contact in the
User-Agent (the SEC_USER_AGENT secret, kept out of this public repo) and at most 10 requests
a second.

- Earnings releases: 8-K filings with item 2.02 ("Results of Operations"), with the minute they
  were accepted, so an EP can be tagged earnings before the open, after the prior close, or
  during the session.
- Quarterly numbers: the XBRL "frames" API returns one calendar quarter of one concept for every
  company in a single request, so two years of EPS and revenue take a few dozen requests.

US filers only (10-Q/10-K); foreign issuers filing 20-F/6-K are not covered and keep the
TradingView estimate. Writes to `data/ep_enrich/sec/` in the data repo.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import requests

from trading_os.logsafe import status
from trading_os.store import PARQUET_OPTIONS

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json"
EPS = ("EarningsPerShareDiluted", "USD-per-shares")
REVENUE = (
    ("Revenues", "USD"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
    ("SalesRevenueNet", "USD"),
)


class SecClient:
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

    def get(self, url: str) -> dict | list | None:
        """JSON for `url`; None for a 404 (no such filer or frame). Waits on 429/503 once."""
        for attempt in (1, 2):
            if self._last is not None:
                wait = self._gap - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            response = self._http.get(url, headers=self._headers, timeout=60)
            if response.status_code == 404:
                return None
            if response.status_code in (429, 503) and attempt == 1:
                self._sleep(10)
                continue
            response.raise_for_status()
            return response.json()
        return None

    def company_tickers(self) -> pd.DataFrame:
        body = self.get(TICKERS_URL) or {}
        rows = [{"ticker": v["ticker"], "cik": int(v["cik_str"])} for v in body.values()]
        return pd.DataFrame(rows, columns=["ticker", "cik"])

    def earnings_releases(self, cik: int, since: dt.date) -> list[dict]:
        """8-K item 2.02 filings since `since`: filing date and acceptance time (UTC)."""
        body = self.get(SUBMISSIONS_URL.format(cik=cik))
        if not body:
            return []
        pages = [body["filings"]["recent"]]
        for extra in body["filings"].get("files", []):
            if dt.date.fromisoformat(extra["filingTo"]) >= since:
                page = self.get(SUBMISSIONS_PAGE_URL.format(name=extra["name"]))
                if page:
                    pages.append(page)
        out = []
        for page in pages:
            for form, items, filed, accepted in zip(
                page["form"],
                page["items"],
                page["filingDate"],
                page["acceptanceDateTime"],
                strict=True,
            ):
                release = form.startswith("8-K") and "2.02" in (items or "").split(",")
                if release and dt.date.fromisoformat(filed) >= since:
                    out.append({"cik": cik, "filed": filed, "accepted": accepted})
        return out

    def frame(self, concept: str, unit: str, period: str) -> pd.DataFrame:
        """One concept for one calendar period (CY2025Q2, or CY2025 for a year), all filers."""
        body = self.get(FRAMES_URL.format(concept=concept, unit=unit, period=period)) or {}
        rows = body.get("data") or []
        frame = pd.DataFrame(rows, columns=["cik", "end", "val", "accn"])
        return frame.assign(concept=concept, period=period)


def quarters(since: dt.date, until: dt.date) -> list[str]:
    """Calendar quarters from a year before `since` (for YoY) up to `until`."""
    out, year, q = [], since.year - 1, 1
    while (year, q) <= (until.year, (until.month - 1) // 3 + 1):
        out.append(f"CY{year}Q{q}")
        year, q = (year + 1, 1) if q == 4 else (year, q + 1)
    return out


def quarterly(frames: pd.DataFrame) -> pd.DataFrame:
    """cik x quarter with eps and revenue. Q4 comes from the year minus Q1-Q3 when the
    company only filed the annual number (most 10-Ks); revenue takes the first tag a
    company uses."""
    out = []
    for kind, concepts in (("eps", [EPS[0]]), ("revenue", [c for c, _ in REVENUE])):
        part = frames[frames["concept"].isin(concepts)].copy()
        part["rank"] = part["concept"].map({c: i for i, c in enumerate(concepts)})
        part = part.sort_values("rank").drop_duplicates(["cik", "period"])
        quarter = part[part["period"].str.contains("Q")].copy()
        annual = part[~part["period"].str.contains("Q")]
        rows = quarter[["cik", "period", "end", "val"]].assign(derived=False)
        for row in annual.itertuples():
            year = row.period[2:]
            known = quarter[
                (quarter["cik"] == row.cik) & quarter["period"].str.startswith(f"CY{year}Q")
            ]
            if len(known) == 3 and f"CY{year}Q4" not in set(known["period"]):
                rows = pd.concat(
                    [
                        rows,
                        pd.DataFrame(
                            [
                                {
                                    "cik": row.cik,
                                    "period": f"CY{year}Q4",
                                    "end": row.end,
                                    "val": row.val - known["val"].sum(),
                                    "derived": True,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
        out.append(rows.rename(columns={"val": kind, "derived": f"{kind}_derived"}))
    eps, revenue = out
    return eps.merge(revenue, on=["cik", "period"], how="outer", suffixes=("", "_rev"))


def check(client: SecClient) -> bool:
    """One small request each to the three endpoints; logs status only."""
    ok = True
    for label, call in (
        ("company list", lambda: client.company_tickers()),
        ("filings", lambda: client.earnings_releases(320193, dt.date(2025, 1, 1))),
        ("frames", lambda: client.frame(*EPS, "CY2025Q2")),
    ):
        try:
            result = call()
            status(f"SEC check: {label}: OK, {len(result)} rows")
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            status(f"SEC check: {label}: HTTP {code}")
            ok = False
    return ok


def fetch(data_dir: Path, client: SecClient, ciks: list[int], since: dt.date, until: dt.date):
    """Earnings releases for `ciks` (resumable) and the quarterly frames, into the data repo."""
    folder = Path(data_dir) / "data" / "ep_enrich" / "sec"
    folder.mkdir(parents=True, exist_ok=True)
    releases_path = folder / "earnings_releases.parquet"
    done = set()
    old = pd.DataFrame(columns=["cik", "filed", "accepted"])
    if releases_path.exists():
        old = pd.read_parquet(releases_path)
        done = set(old["cik"])
    marker = folder / "ciks_done.parquet"
    if marker.exists():
        done |= set(pd.read_parquet(marker)["cik"])
    rows, finished = [], []
    for cik in [c for c in ciks if c not in done]:
        rows += client.earnings_releases(cik, since)
        finished.append(cik)
    pd.concat([old, pd.DataFrame(rows, columns=old.columns)], ignore_index=True).to_parquet(
        releases_path, **PARQUET_OPTIONS
    )
    pd.DataFrame({"cik": sorted(done | set(finished))}).to_parquet(marker, **PARQUET_OPTIONS)
    frames = [
        client.frame(concept, unit, period)
        for period in quarters(since, until) + [f"CY{y}" for y in range(since.year - 1, until.year)]
        for concept, unit in (EPS, *REVENUE)
    ]
    table = quarterly(pd.concat(frames, ignore_index=True))
    table.to_parquet(folder / "quarterly.parquet", **PARQUET_OPTIONS)
    status(
        f"SEC: releases for {len(finished)} new filers ({len(rows)} 8-K 2.02), "
        f"{len(table)} quarters"
    )


def cik_map(data_dir: Path, client: SecClient) -> dict[str, int]:
    """ticker -> CIK: Massive's list (covers delisted names) where fetched, else SEC's own."""
    out = dict(client.company_tickers().itertuples(index=False, name=None))
    massive = Path(data_dir) / "data" / "ep_enrich" / "tickers.parquet"
    if massive.exists():
        listed = pd.read_parquet(massive)
        if "cik" in listed:
            known = listed.dropna(subset=["cik"])
            for ticker, cik in zip(known["ticker"], known["cik"], strict=True):
                out.setdefault(str(ticker), int(cik))
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    from trading_os.config import load_config
    from trading_os.ep_enrich import events, latest_study

    parser = argparse.ArgumentParser(description="SEC EDGAR extras for the EP history study")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="three test requests, status only")
    args = parser.parse_args(argv)
    import os

    conf = load_config().sec
    agent = os.environ.get("SEC_USER_AGENT") or conf["user_agent"]
    if "@" not in agent:
        status("SEC: set SEC_USER_AGENT (a name and contact email; SEC requires one)")
        return 1
    client = SecClient(agent, conf["requests_per_second"])
    if args.check:
        return 0 if check(client) else 1
    study = latest_study(args.data_dir)
    if study.empty:
        status("SEC: no EP history built yet")
        return 1
    ep = events(study)
    mapping = cik_map(args.data_dir, client)
    ciks = sorted({mapping[t] for t in ep["ticker"] if t in mapping})
    used = {t: mapping[t] for t in ep["ticker"].unique() if t in mapping}
    folder = args.data_dir / "data" / "ep_enrich" / "sec"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ticker": list(used), "cik": list(used.values())}).to_parquet(
        folder / "cik_map.parquet", **PARQUET_OPTIONS
    )
    status(f"SEC: {len(ciks)} filers for {ep['ticker'].nunique()} EP tickers")
    since, until = min(ep["session_date"]), max(ep["session_date"])
    fetch(args.data_dir, client, ciks, since, until)
    return 0
