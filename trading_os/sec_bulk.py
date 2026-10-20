"""Point-in-time fundamentals for the 10-year study from SEC EDGAR's free bulk files (Emil,
20 Oct 2026). Study data only: no live scan reads it.

Sources (SEC fair access: a User-Agent with a contact, at most 10 requests a second):

- `submissions.zip`: every filer's filings (form, filing date, acceptance time, 8-K items),
  SIC, name, exchanges, former names.
- `companyfacts.zip`: every XBRL fact with the filing it came from and its `filed` date.
- `company_tickers.json`: SEC's ticker -> CIK list (current names only).
- the data repo's `data/ep_enrich/tickers.parquet`: Massive's ticker list incl. delisted names.

Tables (release `sec-10y` in the data repo):

- `earnings_events`: 8-Ks with item 2.02 since `events_since`, plus 10-Qs/10-Ks that came with
  no 8-K item 2.02 between the period end and the filing (small companies whose report is the
  release). `reaction_session` is the first NYSE session whose 09:30 open is after the
  acceptance; `timing` is pre-market, intraday or after-close.
- `quarterly`: one row per company and fiscal quarter, as first reported: EPS (diluted, else
  basic-and-diluted, else basic), revenue (the first tag of `REVENUE_TAGS` the filing uses),
  net income, and the same three for the year-earlier quarter as stated in the same filing
  (split-adjusted, restated). Q4 is FY minus Q1-Q3 when only the 10-K has it (`derived`).
  `known_at` is the earnings release that announced the quarter (the last 8-K item 2.02
  between the period end and the 10-Q/10-K) when there was one, else the filing itself.
- `shares`: shares outstanding from the cover page (dei:EntityCommonStockSharesOutstanding,
  share classes summed) or, when a filing has none, weighted-average basic shares.
- `companies`: name, SIC, a sector from SIC (`SECTOR_RULES`), exchange, filer category, SPAC
  and fund flags.
- `ticker_cik`: every Massive ticker (and SEC's current ones) with its CIK and the dates it
  applies to; a ticker that moved to another company gets one row per company.

Acceptance times: the submissions JSON writes `acceptanceDateTime` as UTC, but about a third of
the values are UTC plus the Eastern offset again (checked against EDGAR's own filing headers,
`--mode check`, 20 Oct 2026: 147 of 400 filings, every year since 2015, every form, no JSON
field tells them apart). Times outside EDGAR's hours (06:00-22:00 New York) and times after
17:30 that still kept that day's filing date are shifted back by the offset. A pre-market
release shifted this way looks like a mid-morning one, so earnings events in that window
(`ambiguous`) are checked against the filing header, newest first, within `header_minutes` a
run; the checks are cached in the release (`acceptance_checks.parquet`). `time_basis` says
which: header, json, json_shifted. Filings left unchecked keep the later JSON time, which can
only make a quarter known later than it was, never earlier.

`pit_join(rows, tables, ...)` adds the features for (ticker, session_date[, raw_close]) rows
using only what was public before that session's 09:30 open. Logs print counts only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from trading_os.logsafe import status
from trading_os.store import PARQUET_OPTIONS

NEW_YORK = ZoneInfo("America/New_York")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
COMPANYFACTS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
HEADER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index-headers.html"
# EDGAR's own record of the acceptance: Eastern wall-clock time, YYYYMMDDHHMMSS.
ACCEPTANCE_RE = re.compile(r"ACCEPTANCE-DATETIME(?:>|&gt;)\s*(\d{14})")
MEMBER_RE = re.compile(r"CIK(\d{10})(-submissions-\d+)?\.json$")
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

EARNINGS_8K = "8-K"
RELEASE_FORMS = ("10-Q", "10-K", "10-QT", "10-KT")  # a release when no 8-K 2.02 came first
FACT_FORMS = frozenset({*RELEASE_FORMS, *(f"{f}/A" for f in RELEASE_FORMS)})
FUND_FORMS = frozenset(
    {"N-CSR", "N-CSRS", "NPORT-P", "N-Q", "485BPOS", "485APOS", "N-1A", "N-2", "N-CEN", "24F-2NT"}
)
FOREIGN_FORMS = frozenset({"20-F", "40-F"})
EDGAR_OPEN, EDGAR_CLOSE, LATE = 6 * 60, 22 * 60, 17 * 60 + 30  # minutes, New York
OPEN, CLOSE = 9 * 60 + 30, 16 * 60

# (taxonomy, concept, unit) -> (group, preference rank); the lowest rank a filing uses wins.
EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")
REVENUE_TAGS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "RevenuesNetOfInterestExpense",
    "InterestAndDividendIncomeOperating",  # banks without a revenue line
)
NET_INCOME_TAGS = (
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
)
CONCEPTS: dict[tuple[str, str, str], tuple[str, int]] = {
    **{("us-gaap", t, "USD/shares"): ("eps", i) for i, t in enumerate(EPS_TAGS)},
    **{("us-gaap", t, "USD"): ("revenue", i) for i, t in enumerate(REVENUE_TAGS)},
    **{("us-gaap", t, "USD"): ("net_income", i) for i, t in enumerate(NET_INCOME_TAGS)},
    ("dei", "EntityCommonStockSharesOutstanding", "shares"): ("shares_dei", 0),
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", "shares"): ("shares_avg", 0),
}
TAG_NAMES = {(g, r): c for (_, c, _), (g, r) in CONCEPTS.items()}
METRICS = ("eps", "revenue", "net_income")
QUARTER_DAYS, YEAR_DAYS = (70, 120), (330, 380)  # durations that count as a quarter / a year

# SIC -> a GICS-style sector. The first range that holds the code wins, so single codes and
# narrow ranges come before the broad SIC groups they sit in. Unlisted codes (incl. 99xx
# non-operating shells) are "Other".
SECTOR_RULES: tuple[tuple[int, int, str], ...] = (
    (2833, 2836, "Health Care"),  # drugs, biologics
    (2840, 2844, "Consumer Staples"),  # soap, cosmetics
    (3570, 3579, "Information Technology"),  # computers, office machines
    (3630, 3639, "Consumer Discretionary"),  # household appliances
    (3651, 3652, "Consumer Discretionary"),  # household audio and video
    (3660, 3679, "Information Technology"),  # communications equipment, semiconductors
    (3711, 3716, "Consumer Discretionary"),  # motor vehicles and parts
    (3750, 3751, "Consumer Discretionary"),  # motorcycles, bicycles
    (3790, 3799, "Consumer Discretionary"),  # other transportation equipment
    (3812, 3812, "Industrials"),  # search, navigation, guidance (defense)
    (3826, 3826, "Health Care"),  # laboratory analytical instruments
    (3820, 3829, "Information Technology"),  # measuring and control instruments
    (3840, 3851, "Health Care"),  # medical, surgical, dental, ophthalmic
    (3011, 3011, "Consumer Discretionary"),  # tires
    (3411, 3412, "Materials"),  # metal cans
    (2451, 2452, "Consumer Discretionary"),  # mobile homes
    (1220, 1241, "Energy"),  # coal
    (1300, 1399, "Energy"),  # oil and gas extraction and services
    (2900, 2999, "Energy"),  # petroleum refining
    (4610, 4619, "Energy"),  # pipelines
    (4922, 4922, "Energy"),  # natural gas transmission
    (5171, 5172, "Energy"),  # petroleum products wholesale
    (6792, 6792, "Energy"),  # oil royalty traders
    (6795, 6795, "Materials"),  # mineral royalty traders
    (6798, 6798, "Real Estate"),  # REITs
    (4950, 4959, "Industrials"),  # waste management
    (5045, 5045, "Information Technology"),  # computer wholesale
    (5065, 5065, "Information Technology"),  # electronic parts wholesale
    (5047, 5047, "Health Care"),  # medical equipment wholesale
    (5122, 5122, "Health Care"),  # drug wholesale
    (5400, 5499, "Consumer Staples"),  # food stores
    (5912, 5912, "Consumer Staples"),  # drug stores
    (7310, 7319, "Communication Services"),  # advertising
    (7370, 7379, "Information Technology"),  # software, data processing, IT services
    (7800, 7899, "Communication Services"),  # motion pictures
    (8731, 8731, "Health Care"),  # commercial biological research
    (2700, 2749, "Communication Services"),  # newspapers, periodicals, books
    (1520, 1531, "Consumer Discretionary"),  # homebuilders
    (100, 999, "Consumer Staples"),  # agriculture, forestry, fishing
    (1000, 1099, "Materials"),  # metal mining
    (1400, 1499, "Materials"),  # other minerals
    (1500, 1799, "Industrials"),  # construction
    (2000, 2199, "Consumer Staples"),  # food, beverages, tobacco
    (2200, 2399, "Consumer Discretionary"),  # textiles, apparel
    (2400, 2499, "Materials"),  # lumber, wood
    (2500, 2599, "Consumer Discretionary"),  # furniture
    (2600, 2699, "Materials"),  # paper
    (2750, 2799, "Industrials"),  # commercial printing
    (2800, 2899, "Materials"),  # chemicals
    (3000, 3099, "Materials"),  # rubber, plastics
    (3100, 3199, "Consumer Discretionary"),  # leather
    (3200, 3399, "Materials"),  # stone, clay, glass, primary metals
    (3400, 3799, "Industrials"),  # metal products, machinery, electrical, aerospace
    (3800, 3899, "Information Technology"),  # other instruments
    (3900, 3999, "Consumer Discretionary"),  # jewelry, toys, sporting goods
    (4000, 4799, "Industrials"),  # transportation
    (4800, 4899, "Communication Services"),  # telecom, broadcasting, cable
    (4900, 4999, "Utilities"),
    (5000, 5099, "Industrials"),  # wholesale, durable goods
    (5100, 5199, "Consumer Staples"),  # wholesale, nondurable goods
    (5200, 5999, "Consumer Discretionary"),  # retail, restaurants
    (6000, 6499, "Financials"),  # banks, credit, brokers, insurance
    (6500, 6599, "Real Estate"),
    (6700, 6799, "Financials"),  # holding and investment offices, blank checks (6770)
    (7000, 7299, "Consumer Discretionary"),  # hotels, personal services
    (7300, 7399, "Industrials"),  # business services
    (7500, 7599, "Consumer Discretionary"),  # auto services
    (7600, 7699, "Industrials"),  # repair services
    (7900, 7999, "Consumer Discretionary"),  # amusement, recreation, casinos
    (8000, 8099, "Health Care"),  # health services
    (8200, 8299, "Consumer Discretionary"),  # education
    (8100, 8999, "Industrials"),  # legal, engineering, management, other services
)
SPAC_SIC = 6770
FUND_SICS = frozenset({6221, 6722, 6726})  # commodity pools, open-end and closed-end funds
SPAC_NAME = re.compile(
    r"\b(acquisitions?|merger)\s+(corp|corporation|co|company|inc|ltd|limited|holdings|group)\b"
    r"|\bblank check\b",
    re.IGNORECASE,
)
TABLES = ("earnings_events", "quarterly", "shares", "companies", "ticker_cik")
CHECKS_FILE = "acceptance_checks.parquet"


# --------------------------------------------------------------------------- HTTP


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

    def download(self, url: str, path: Path) -> Path:
        response = self._response(url, stream=True)
        if response is None:
            raise FileNotFoundError("SEC bulk file not found")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        with open(tmp, "wb") as fh:
            for chunk in response.iter_content(chunk_size=8 << 20):
                fh.write(chunk)
        tmp.replace(path)
        return path


def sec_tickers(client: BulkClient) -> pd.DataFrame:
    """SEC's current ticker -> CIK list, tickers in the exchanges' dot form (BRK.B)."""
    body = client.json(TICKERS_URL) or {}
    rows = [
        {"ticker": str(v["ticker"]).upper().replace("-", "."), "cik": int(v["cik_str"])}
        for v in body.values()
    ]
    return pd.DataFrame(rows, columns=["ticker", "cik"]).drop_duplicates("ticker")


# --------------------------------------------------------------------------- acceptance times


def filings_frame(page: dict, cik: int) -> pd.DataFrame:
    """One submissions page (the `recent` block or an older `-submissions-NNN` file) as rows."""
    n = len(page.get("accessionNumber") or [])
    columns = {f: page.get(f) or [None] * n for f in FILING_FIELDS}
    return pd.DataFrame(columns).assign(cik=cik)


def header_acceptance(text: str | None) -> dt.datetime | None:
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


def acceptance_times(raw: pd.Series, filed: pd.Series) -> pd.DataFrame:
    """Best UTC acceptance time from the JSON value alone (see the module docstring):
    `accepted` (tz-aware UTC), `time_basis` (json / json_shifted) and `ambiguous` (could be a
    pre-market time shown 4-5 hours late, so worth a header check)."""
    utc = pd.to_datetime(raw, utc=True, format="ISO8601", errors="coerce")
    utc = utc.astype("datetime64[ns, UTC]")
    local = utc.dt.tz_convert(NEW_YORK).dt.tz_localize(None)
    offset = utc.dt.tz_localize(None) - local  # 4 or 5 hours
    minutes = local.dt.hour * 60 + local.dt.minute
    same_day = local.dt.normalize() == pd.to_datetime(filed, errors="coerce").astype(
        "datetime64[ns]"
    )
    shift = (minutes < EDGAR_OPEN) | (minutes >= EDGAR_CLOSE) | ((minutes >= LATE) & same_day)
    shifted = minutes - offset.dt.total_seconds() // 60
    ambiguous = ~shift & (minutes >= OPEN) & (shifted >= EDGAR_OPEN) & (shifted < OPEN)
    return pd.DataFrame(
        {
            "accepted": utc.where(~shift, utc - offset),
            "time_basis": np.where(shift, "json_shifted", "json"),
            "ambiguous": ambiguous.fillna(False).astype(bool),
        },
        index=raw.index,
    )


def apply_checks(filings: pd.DataFrame, checks: pd.DataFrame) -> pd.DataFrame:
    """Header-checked acceptance times replace the JSON estimate."""
    if checks.empty:
        return filings
    known = checks[checks["header_et"].fillna("") != ""].drop_duplicates("accession")
    stamp = pd.to_datetime(known["header_et"], format="%Y%m%d%H%M%S")
    utc = stamp.dt.tz_localize(NEW_YORK, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    by_accession = pd.Series(utc.array, index=known["accession"].array)
    out = filings.copy()
    hit = out["accession"].map(by_accession)
    has = hit.notna()
    out.loc[has, "accepted"] = hit[has].astype("datetime64[ns, UTC]")
    out.loc[has, "time_basis"] = "header"
    out.loc[out["accession"].isin(checks["accession"]), "ambiguous"] = False
    return out


def check_headers(
    client: BulkClient, todo: pd.DataFrame, deadline: float, clock: Callable[[], float]
) -> pd.DataFrame:
    """Fetch EDGAR's filing headers for `todo` (cik, accession) until `deadline`."""
    rows, failed = [], 0
    for row in todo.itertuples():
        if clock() >= deadline:
            break
        folder = row.accession.replace("-", "")
        url = HEADER_URL.format(cik=row.cik, folder=folder, accession=row.accession)
        try:
            header = header_acceptance(client.text(url))
        except requests.RequestException:
            failed += 1
            continue
        rows.append({"accession": row.accession, "header_et": header and f"{header:%Y%m%d%H%M%S}"})
    status(f"SEC bulk: headers checked {len(rows)} of {len(todo)}, {failed} failed")
    return pd.DataFrame(rows, columns=["accession", "header_et"])


@cache
def _calendar_arrays(name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sessions (midnight), opens and closes (UTC) as datetime64[ns] arrays."""
    import exchange_calendars as xcals

    cal = xcals.get_calendar(name, start="2005-01-01")
    days = cal.sessions if cal.sessions.tz is None else cal.sessions.tz_localize(None)
    sessions = days.to_numpy("datetime64[ns]")
    opens = cal.opens.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]")
    closes = cal.closes.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]")
    return sessions, opens, closes


def reaction_sessions(accepted: pd.Series, calendar: str) -> pd.DataFrame:
    """`reaction_session`: the first session whose open is after `accepted` (UTC); `timing`:
    intraday (between a session's open and close), pre-market (earlier the same New York
    day), else after-close (evenings, weekends, holidays)."""
    sessions, opens, closes = _calendar_arrays(calendar)
    at = accepted.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]")
    known = ~np.isnat(at)
    k = np.searchsorted(opens, at, side="right")
    valid = known & (k < len(opens))
    k = np.minimum(k, len(opens) - 1)
    during = valid & (k > 0) & (at < closes[np.maximum(k - 1, 0)])
    local_day = accepted.dt.tz_convert(NEW_YORK).dt.tz_localize(None).dt.normalize()
    same_day = local_day.to_numpy("datetime64[ns]") == sessions[k]
    timing = np.select([during, same_day], ["intraday", "pre-market"], "after-close")
    session = pd.Series(sessions[k], index=accepted.index).dt.date
    return pd.DataFrame(
        {
            "reaction_session": session.where(valid, None),
            "timing": pd.Series(timing, index=accepted.index).where(valid, None),
        }
    )


# --------------------------------------------------------------------------- submissions


def _member_cik(name: str) -> tuple[int, bool] | None:
    found = MEMBER_RE.search(name)
    return (int(found.group(1)), found.group(2) is None) if found else None


def read_submissions(
    path: Path, ciks: set[int] | None, facts_since: str, events_since: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(filings, companies) from submissions.zip for `ciks` (all filers when None).

    filings: the 8-Ks with item 2.02 and the 10-Q/10-K family filed since `facts_since`.
    companies: one row per filer with the fields `companies_table` needs and per-filer flags.
    """
    cols: dict[str, list] = {k: [] for k in ("cik", "accession", "form", "filed", "report")}
    cols["accepted_raw"] = []
    info: dict[int, dict] = {}
    flags: dict[int, dict] = {}
    with zipfile.ZipFile(path) as zf:
        for member in zf.infolist():
            parsed = _member_cik(member.filename)
            if parsed is None or (ciks is not None and parsed[0] not in ciks):
                continue
            cik, is_main = parsed
            body = json.loads(zf.read(member))
            page = body
            if is_main:
                info[cik] = _company_fields(body, cik)
                page = (body.get("filings") or {}).get("recent") or {}
            flag = flags.setdefault(
                cik, {"fund_forms": False, "us_reports": False, "foreign": False, "last": ""}
            )
            _page_rows(page, cik, facts_since, events_since, cols, flag)
    filings = pd.DataFrame(cols)
    filings["cik"] = filings["cik"].astype("int64")
    companies = pd.DataFrame(
        [{**info.get(c, {"cik": c}), **f} for c, f in flags.items()] or None,
        columns=[*_COMPANY_COLUMNS, "fund_forms", "us_reports", "foreign", "last"],
    )
    return filings, companies


_COMPANY_COLUMNS = (
    "cik",
    "name",
    "sic",
    "sic_description",
    "entity_type",
    "category",
    "exchanges",
    "sec_tickers",
    "fiscal_year_end",
    "former_spac_until",
)


def _company_fields(body: dict, cik: int) -> dict:
    spac_until = None
    for former in body.get("formerNames") or []:
        if SPAC_NAME.search(former.get("name") or "") and former.get("to"):
            spac_until = max(spac_until or "", former["to"][:10])
    sic = str(body.get("sic") or "").strip()
    return {
        "cik": cik,
        "name": body.get("name"),
        "sic": int(sic) if sic.isdigit() else None,
        "sic_description": body.get("sicDescription") or None,
        "entity_type": body.get("entityType") or None,
        "category": body.get("category") or None,
        "exchanges": "/".join(dict.fromkeys(e for e in body.get("exchanges") or [] if e)) or None,
        "sec_tickers": ",".join(t for t in body.get("tickers") or [] if t) or None,
        "fiscal_year_end": body.get("fiscalYearEnd") or None,
        "former_spac_until": spac_until,
    }


def _page_rows(
    page: dict, cik: int, facts_since: str, events_since: str, cols: dict, flag: dict
) -> None:
    forms = page.get("form") or []
    n = len(forms)
    accession = page.get("accessionNumber") or [None] * n
    filed = page.get("filingDate") or [""] * n
    report = page.get("reportDate") or [""] * n
    accepted = page.get("acceptanceDateTime") or [""] * n
    items = page.get("items") or [""] * n
    for i, form in enumerate(forms):
        day = filed[i] or ""
        if day > flag["last"]:
            flag["last"] = day
        if form in FUND_FORMS:
            flag["fund_forms"] = True
        if day >= events_since:
            if form in ("10-K", "10-Q"):
                flag["us_reports"] = True
            elif form in FOREIGN_FORMS:
                flag["foreign"] = True
        if day < facts_since:
            continue
        if form == EARNINGS_8K:
            if "2.02" not in (items[i] or "").split(","):
                continue
        elif form not in FACT_FORMS:
            continue
        cols["cik"].append(cik)
        cols["accession"].append(accession[i])
        cols["form"].append(form)
        cols["filed"].append(day)
        cols["report"].append(report[i] or None)
        cols["accepted_raw"].append(accepted[i] or None)


def sector(sic: int | None) -> str:
    if sic is not None and not pd.isna(sic):
        for low, high, name in SECTOR_RULES:
            if low <= sic <= high:
                return name
    return "Other"


def companies_table(raw: pd.DataFrame) -> pd.DataFrame:
    """companies.parquet: one row per CIK with the sector, SPAC and fund flags."""
    out = raw.copy()
    out["sic"] = out["sic"].astype("Int64")
    out["sector"] = [sector(s) for s in out["sic"].astype("float64")]
    out["is_spac"] = out["sic"].eq(SPAC_SIC).fillna(False).astype(bool)
    # A former SPAC (renamed at its merger) was a blank check until that name ended.
    out["spac_until"] = pd.to_datetime(out["former_spac_until"], errors="coerce").dt.date
    out.loc[out["is_spac"], "spac_until"] = None
    flag = {k: out[k].fillna(False).astype(bool) for k in ("fund_forms", "us_reports", "foreign")}
    out["is_fund"] = (
        out["sic"].isin(FUND_SICS).astype(bool)
        | out["entity_type"].eq("investment").fillna(False).astype(bool)
        | (flag["fund_forms"] & ~flag["us_reports"])
    )
    out["is_foreign"] = flag["foreign"] & ~flag["us_reports"]
    out["filer_category"] = out["category"].str.replace("<br>", "; ", regex=False)
    out["last_filed"] = pd.to_datetime(
        out["last"].where(out["last"] != ""), errors="coerce"
    ).dt.date
    columns = [
        "cik",
        "name",
        "sic",
        "sic_description",
        "sector",
        "exchanges",
        "filer_category",
        "entity_type",
        "is_spac",
        "spac_until",
        "is_fund",
        "is_foreign",
        "fiscal_year_end",
        "sec_tickers",
        "last_filed",
    ]
    return out[columns].rename(columns={"exchanges": "exchange"}).reset_index(drop=True)


# --------------------------------------------------------------------------- events


def _release_before(left: pd.DataFrame, releases: pd.DataFrame) -> pd.DataFrame:
    """For each left row (cik, at, period_end): the last release (cik, accepted, accession)
    accepted at or before `at` and after the period end."""
    lhs = left.assign(_at=left["at"].astype("datetime64[ns, UTC]")).sort_values("_at")
    rhs = releases[["cik", "accepted", "accession"]].dropna(subset=["accepted"])
    rhs = rhs.rename(columns={"accepted": "_rel", "accession": "release_accession"})
    rhs = rhs.assign(_rel=rhs["_rel"].astype("datetime64[ns, UTC]")).sort_values("_rel")
    merged = pd.merge_asof(
        lhs, rhs, left_on="_at", right_on="_rel", by="cik", direction="backward"
    ).set_index(lhs.index)
    end = pd.to_datetime(merged["period_end"], errors="coerce") + pd.Timedelta(days=1)
    after_end = merged["_rel"] >= end.dt.tz_localize("UTC")
    merged.loc[~after_end.fillna(False), ["_rel", "release_accession"]] = None
    return merged.rename(columns={"_rel": "release_accepted"}).drop(columns="_at").loc[left.index]


def earnings_events(filings: pd.DataFrame, since: str, calendar: str) -> pd.DataFrame:
    """earnings_events.parquet from the filings (with best acceptance times)."""
    recent = filings[(filings["filed"] >= since) & filings["accepted"].notna()]
    eight = recent[recent["form"] == EARNINGS_8K]
    reports = recent[recent["form"].isin(RELEASE_FORMS)]
    matched = _release_before(
        reports.assign(at=reports["accepted"], period_end=reports["report"]), eight
    )
    alone = reports[matched["release_accepted"].isna()]
    events = pd.concat([eight, alone]).sort_values(["cik", "accepted"])
    timing = reaction_sessions(events["accepted"], calendar)
    out = pd.DataFrame(
        {
            "cik": events["cik"].astype("int64"),
            "accession": events["accession"],
            "form": events["form"],
            "filed": pd.to_datetime(events["filed"]).dt.date,
            "accepted": events["accepted"],
            "accepted_json": events["accepted_raw"],
            "time_basis": events["time_basis"],
            "reaction_session": timing["reaction_session"],
            "timing": timing["timing"],
        }
    )
    return out.dropna(subset=["reaction_session"]).reset_index(drop=True)


def header_todo(
    filings: pd.DataFrame, since: str, ciks: set[int], checked: Iterable[str]
) -> pd.DataFrame:
    """Earnings events whose JSON time might hide a pre-market release, newest first."""
    done = set(checked)
    recent = filings[(filings["filed"] >= since) & filings["ambiguous"]]
    eight = recent["form"] == EARNINGS_8K
    reports = recent[recent["form"].isin(RELEASE_FORMS)]
    todo = pd.concat([recent[eight], reports])
    todo = todo[todo["cik"].isin(ciks) & ~todo["accession"].isin(done)]
    return todo.sort_values("accepted", ascending=False)[["cik", "accession"]]


# --------------------------------------------------------------------------- companyfacts


def read_facts(path: Path, ciks: set[int] | None, since: str) -> pd.DataFrame:
    """The `CONCEPTS` facts from 10-Q/10-K-family filings with an end date since `since`."""
    cols: dict[str, list] = {
        k: [] for k in ("cik", "group", "rank", "start", "end", "val", "accn", "fy", "fp", "form")
    }
    cols["filed"] = []
    with zipfile.ZipFile(path) as zf:
        for member in zf.infolist():
            parsed = _member_cik(member.filename)
            if parsed is None or not parsed[1] or (ciks is not None and parsed[0] not in ciks):
                continue
            cik = parsed[0]
            facts = json.loads(zf.read(member)).get("facts") or {}
            for (taxonomy, concept, unit), (group, rank) in CONCEPTS.items():
                entries = (
                    ((facts.get(taxonomy) or {}).get(concept) or {}).get("units", {}).get(unit)
                )
                for f in entries or ():
                    if f.get("form") not in FACT_FORMS or (f.get("end") or "") < since:
                        continue
                    cols["cik"].append(cik)
                    cols["group"].append(group)
                    cols["rank"].append(rank)
                    cols["start"].append(f.get("start"))
                    cols["end"].append(f["end"])
                    cols["val"].append(f.get("val"))
                    cols["accn"].append(f.get("accn"))
                    cols["fy"].append(f.get("fy"))
                    cols["fp"].append(f.get("fp"))
                    cols["form"].append(f["form"])
                    cols["filed"].append(f.get("filed"))
    out = pd.DataFrame(cols)
    for column in ("start", "end", "filed"):
        out[column] = pd.to_datetime(out[column], format="%Y-%m-%d", errors="coerce").astype(
            "datetime64[ns]"
        )
    out["val"] = pd.to_numeric(out["val"], errors="coerce")
    out["fy"] = pd.to_numeric(out["fy"], errors="coerce")
    out["cik"] = out["cik"].astype("int64")
    out["rank"] = out["rank"].astype("int64")
    return out.dropna(subset=["val", "end", "accn"])


def _filing_times(filings: pd.DataFrame, facts: pd.DataFrame) -> pd.Series:
    """accn -> UTC acceptance; the day after `filed` (UTC midnight, after the close) when the
    filing is missing from the submissions."""
    known = filings.drop_duplicates("accession").set_index("accession")["accepted"]
    at = facts["accn"].map(known).astype("datetime64[ns, UTC]")
    fallback = (facts["filed"] + pd.Timedelta(days=1)).dt.tz_localize("UTC")
    return at.fillna(fallback)


def _fiscal_index(d: pd.DataFrame) -> pd.Series:
    """fiscal_year * 4 + quarter of each fact, from its filing's fy/fp, stepped back by the
    quarters between the fact's end and the filing's own period end."""
    quarter = d["fp"].map({"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 4})
    current = d.groupby("accn")["end"].transform("max")
    back = ((current - d["end"]).dt.days / 91.31).round()
    return d["fy"] * 4 + quarter - back


def quarterly_table(
    facts: pd.DataFrame, filings: pd.DataFrame, events: pd.DataFrame
) -> pd.DataFrame:
    """quarterly.parquet (see the module docstring)."""
    d = facts[facts["group"].isin(METRICS) & facts["start"].notna()].copy()
    days = (d["end"] - d["start"]).dt.days
    d["kind"] = np.select(
        [days.between(*QUARTER_DAYS), days.between(*YEAR_DAYS)], ["Q", "FY"], "other"
    )
    d = d[d["kind"] != "other"]
    d["idx"] = _fiscal_index(d)
    d = d.dropna(subset=["idx"])
    d["idx"] = d["idx"].astype("int64")
    d = d[(d["kind"] == "Q") | (d["idx"] % 4 == 0)]  # a year ends a fiscal Q4
    d["accepted"] = _filing_times(filings, d)
    keys = ["accn", "group", "kind", "idx"]
    values = d.drop_duplicates([*keys, "rank"])
    chosen = values.sort_values("rank").drop_duplicates(keys)
    prior = values[[*keys, "rank", "val"]].assign(idx=values["idx"] + 4)
    chosen = chosen.merge(prior.rename(columns={"val": "prior"}), on=[*keys, "rank"], how="left")
    first = chosen.sort_values(["filed", "accepted"]).drop_duplicates(
        ["cik", "group", "kind", "idx"]
    )
    first = first.assign(derived=False)
    quarters = first[first["kind"] == "Q"]
    years = first[first["kind"] == "FY"]
    q_vals = quarters.set_index(["cik", "group", "idx"])[["val", "prior"]]
    parts = []
    for back in (1, 2, 3):
        key = pd.MultiIndex.from_arrays([years["cik"], years["group"], years["idx"] - back])
        parts.append(q_vals.reindex(key).to_numpy())
    stacked = np.stack(parts)  # back x rows x (val, prior)
    have = years.set_index(["cik", "group", "idx"]).index.isin(q_vals.index)
    q4 = years.assign(
        val=years["val"].to_numpy() - stacked[:, :, 0].sum(axis=0),
        prior=years["prior"].to_numpy() - stacked[:, :, 1].sum(axis=0),
        derived=True,
        kind="Q",
    )[~have & ~np.isnan(stacked[:, :, 0]).any(axis=0)]
    allq = pd.concat([quarters, q4], ignore_index=True)
    allq["tag"] = [TAG_NAMES[(g, r)] for g, r in zip(allq["group"], allq["rank"], strict=True)]
    return _quarter_rows(allq, events)


def _quarter_rows(allq: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """One row per (cik, fiscal quarter); the latest filing among the metrics is the row's."""
    keys = ["cik", "idx"]
    wide = allq.groupby([*keys, "group"])[["val", "prior"]].first().unstack("group")
    out = pd.DataFrame(index=wide.index)
    for metric in METRICS:
        for part, suffix in (("val", ""), ("prior", "_prior")):
            column = (part, metric)
            out[f"{metric}{suffix}"] = wide.get(column, np.nan)
    tags = allq.groupby([*keys, "group"])["tag"].first().unstack("group")
    for metric, name in (("eps", "eps_tag"), ("revenue", "revenue_tag")):
        out[name] = tags.get(metric, None)
    latest = allq.sort_values("accepted").drop_duplicates(keys, keep="last").set_index(keys)
    order = {"revenue": 0, "eps": 1, "net_income": 2}
    ends = allq.assign(o=allq["group"].map(order)).sort_values("o").drop_duplicates(keys)
    out["period_end"] = ends.set_index(keys)["end"].reindex(out.index).dt.date
    out["form"] = latest["form"].reindex(out.index)
    out["accession"] = latest["accn"].reindex(out.index)
    out["filed"] = latest["filed"].reindex(out.index).dt.date
    out["accepted"] = latest["accepted"].reindex(out.index)
    out["derived"] = allq.groupby(keys)["derived"].any().reindex(out.index)
    out = out.reset_index()
    out["fiscal_year"] = (out["idx"] - 1) // 4
    out["fiscal_quarter"] = (out["idx"] - 1) % 4 + 1
    releases = events[events["form"] == EARNINGS_8K]
    matched = _release_before(out.assign(at=out["accepted"]), releases)
    out["release_accepted"] = matched["release_accepted"].astype("datetime64[ns, UTC]")
    out["known_at"] = out["release_accepted"].fillna(out["accepted"])
    columns = [
        "cik",
        "fiscal_year",
        "fiscal_quarter",
        "period_end",
        "form",
        "accession",
        "filed",
        "accepted",
        "release_accepted",
        "known_at",
        "derived",
        "eps",
        "eps_prior",
        "eps_tag",
        "revenue",
        "revenue_prior",
        "revenue_tag",
        "net_income",
        "net_income_prior",
    ]
    return out[columns].sort_values(["cik", "fiscal_year", "fiscal_quarter"]).reset_index(drop=True)


def shares_table(facts: pd.DataFrame, filings: pd.DataFrame) -> pd.DataFrame:
    """shares.parquet: cover-page shares (classes summed), else weighted-average basic."""
    dei = facts[facts["group"] == "shares_dei"]
    cover = (
        dei.groupby(["cik", "accn", "end"])
        .agg(shares=("val", "sum"), classes=("val", "size"), form=("form", "first"))
        .reset_index()
        .assign(source="dei")
    )
    cover = cover.join(dei.groupby("accn")["filed"].first(), on="accn")
    avg = facts[(facts["group"] == "shares_avg") & facts["start"].notna()].copy()
    days = (avg["end"] - avg["start"]).dt.days
    avg = avg[days.between(QUARTER_DAYS[0], YEAR_DAYS[1])].assign(days=days)
    avg = avg[avg["end"] == avg.groupby("accn")["end"].transform("max")]
    avg = avg[~avg["accn"].isin(cover["accn"])].sort_values("days").drop_duplicates("accn")
    avg = avg.rename(columns={"val": "shares"}).assign(classes=1, source="weighted_basic")
    keep = ["cik", "accn", "end", "shares", "classes", "form", "filed", "source"]
    out = pd.concat([cover[keep], avg[keep]], ignore_index=True)
    out["accepted"] = _filing_times(filings, out)
    out = out.sort_values("accepted").drop_duplicates(["cik", "end", "shares"])
    out = out.rename(columns={"accn": "accession", "end": "as_of"})
    out["as_of"] = out["as_of"].dt.date
    out["filed"] = out["filed"].dt.date
    columns = ["cik", "as_of", "filed", "accepted", "form", "accession", "shares", "source"]
    return out[[*columns, "classes"]].sort_values(["cik", "accepted"]).reset_index(drop=True)


# --------------------------------------------------------------------------- tickers


def ticker_map(massive: pd.DataFrame, current: pd.DataFrame, companies: pd.DataFrame):
    """ticker_cik.parquet: every ticker with the CIK it stood for and from/to dates.

    Massive's row says which company a ticker belonged to and when it was delisted; SEC's
    current list says who holds it today. When they differ, the ticker moved: the earlier
    holder ends at its delisting (or its last filing) and the current one starts the next day.
    A delisted ticker ends at its delisting date, so a later unknown holder gets no CIK.
    """
    last = companies.set_index("cik")["last_filed"].to_dict()
    sec = dict(zip(current["ticker"], current["cik"].astype(int), strict=True))
    m = massive.copy()
    m["cik"] = pd.to_numeric(m.get("cik"), errors="coerce")
    m["delisted"] = pd.to_datetime(m.get("delisted_utc"), errors="coerce", utc=True).dt.date
    fields = ["type", "active", "delisted", "name"]
    meta = m.drop_duplicates("ticker").set_index("ticker")[[*fields, "cik"]].to_dict("index")
    empty = dict.fromkeys(fields)
    rows = []
    for ticker in sorted(set(m["ticker"]) | set(sec)):
        row = meta.get(ticker)
        info = {k: row[k] for k in fields} if row else empty
        cands: dict[int, dict] = {}
        if row and not pd.isna(row["cik"]):
            active = bool(row["active"])
            end = None if active or pd.isna(row["delisted"]) else row["delisted"]
            cands[int(row["cik"])] = {"end": end, "current": active, "source": "massive"}
        if ticker in sec:
            if sec[ticker] in cands:
                cands[sec[ticker]].update(current=True, end=None, source="massive+sec")
            else:
                cands[sec[ticker]] = {"end": None, "current": True, "source": "sec"}
        base = {"ticker": ticker, **info}
        if not cands:
            rows.append({**base, "cik": None, "valid_from": None, "valid_to": None, "source": None})
            continue
        if len(cands) == 1:
            cik, c = next(iter(cands.items()))
            rows.append(
                {
                    **base,
                    "cik": cik,
                    "valid_from": None,
                    "valid_to": c["end"],
                    "source": c["source"],
                }
            )
            continue
        holder = next((k for k, c in cands.items() if "sec" in c["source"]), None)
        earlier = []
        for cik, c in cands.items():
            if cik == holder:
                continue
            end = c["end"] if c["end"] is not None else last.get(cik)
            if end is not None and not pd.isna(end):
                earlier.append((end, cik, c["source"]))
        start = None
        for end, cik, source in sorted(earlier):
            rows.append(
                {**base, "cik": cik, "valid_from": start, "valid_to": end, "source": source}
            )
            start = end + dt.timedelta(days=1)
        if holder is not None:
            rows.append(
                {
                    **base,
                    "cik": holder,
                    "valid_from": start,
                    "valid_to": None,
                    "source": cands[holder]["source"],
                }
            )
    out = pd.DataFrame(rows)
    out["cik"] = out["cik"].astype("Int64")
    out["reused"] = out.duplicated("ticker", keep=False)
    columns = ["ticker", "cik", "valid_from", "valid_to", "source", "reused", "type", "active"]
    return out[[*columns, "delisted", "name"]]


# --------------------------------------------------------------------------- point in time


@dataclass(frozen=True)
class Tables:
    ticker_cik: pd.DataFrame
    earnings_events: pd.DataFrame
    quarterly: pd.DataFrame
    shares: pd.DataFrame
    companies: pd.DataFrame


def load_tables(folder: Path) -> Tables:
    return Tables(**{name: pd.read_parquet(Path(folder) / f"{name}.parquet") for name in TABLES})


FEATURES = (
    "cik",
    "sessions_since_earnings",
    "is_earnings_reaction_day",
    "earnings_timing",
    "sessions_to_next_earnings_est",
    "last_quarter_end",
    "eps_yoy_pct",
    "eps_yoy_prev_pct",
    "eps_growth_accel",
    "revenue_yoy_pct",
    "revenue_yoy_prev_pct",
    "revenue_growth_accel",
    "shares_outstanding",
    "shares_as_of",
    "shares_source",
    "market_cap_sec",
    "sector",
    "sic",
    "is_spac",
)


def _naive_utc(values: pd.Series) -> np.ndarray:
    return pd.to_datetime(values, utc=True).dt.tz_localize(None).to_numpy("datetime64[ns]")


def _growth(current: pd.Series, prior: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (current - prior) / prior.abs() * 100
    return out.where(prior.ne(0) & prior.notna() & current.notna())


def _quarter_state(quarterly: pd.DataFrame, known: str) -> pd.DataFrame:
    """Per company and moment a quarter became known: the latest quarter's YoY growth and
    the growth of the quarter before it (both as known then)."""
    q = quarterly.copy()
    q["idx"] = q["fiscal_year"].astype("int64") * 4 + q["fiscal_quarter"].astype("int64")
    q["at"] = _naive_utc(q["known_at"] if known == "release" else q["accepted"])
    year_ago = q.set_index(["cik", "idx"])[["eps", "revenue", "at"]]
    key = pd.MultiIndex.from_arrays([q["cik"], q["idx"] - 4])
    old = year_ago.reindex(key)
    for metric in ("eps", "revenue"):
        fallback = pd.Series(old[metric].to_numpy(), index=q.index)
        prior = q[f"{metric}_prior"].fillna(fallback)
        q[f"{metric}_yoy_pct"] = _growth(q[metric], prior)
    before = q.set_index(["cik", "idx"])[["eps_yoy_pct", "revenue_yoy_pct", "at"]]
    prev = before.reindex(pd.MultiIndex.from_arrays([q["cik"], q["idx"] - 1]))
    known_then = prev["at"].to_numpy() <= q["at"].to_numpy()
    for metric in ("eps", "revenue"):
        q[f"{metric}_yoy_prev_pct"] = np.where(known_then, prev[f"{metric}_yoy_pct"], np.nan)
    q = q.sort_values(["cik", "at", "idx"])
    q = q[q["idx"] >= q.groupby("cik")["idx"].cummax()]  # a late older quarter changes nothing
    keep = ["cik", "at", "period_end", "eps_yoy_pct", "eps_yoy_prev_pct"]
    return q[[*keep, "revenue_yoy_pct", "revenue_yoy_prev_pct"]]


def _asof(left: pd.DataFrame, right: pd.DataFrame, right_on: str, exact: bool) -> pd.DataFrame:
    """For each left row (cik, key): the last right row of the same cik at or before key
    (strictly before when `exact` is False). Returns right's columns aligned to left."""
    lhs = left.sort_values("key")
    rhs = right.dropna(subset=[right_on]).sort_values(right_on)
    merged = pd.merge_asof(
        lhs,
        rhs,
        left_on="key",
        right_on=right_on,
        by="cik",
        direction="backward",
        allow_exact_matches=exact,
    )
    merged.index = lhs.index
    return merged.loc[left.index]


def pit_join(
    rows: pd.DataFrame,
    tables: Tables,
    *,
    quarter_sessions: int,
    calendar: str = "XNYS",
    known: str = "release",
) -> pd.DataFrame:
    """`rows` (ticker, session_date[, raw_close]) plus `FEATURES`, from what was public before
    that session's 09:30 open: filings accepted before the open, events whose reaction session
    is this one or earlier. A quarter counts as known from its earnings release (`known=
    "release"`, the 8-K that announced the numbers) or only from the 10-Q/10-K (`"filing"`).

    sessions_to_next_earnings_est is the last reaction session plus `quarter_sessions`,
    counted from today (negative when overdue); it never looks at a later filing. Growth is
    YoY in % against the year-earlier quarter as the same filing states it; acceleration is
    the change in percentage points from the quarter before. market_cap_sec = shares x
    raw_close when `raw_close` is given. is_spac also covers a former SPAC up to its merger.
    """
    if known not in ("release", "filing"):
        raise ValueError("known must be 'release' or 'filing'")
    sessions, opens, _ = _calendar_arrays(calendar)
    day = pd.to_datetime(rows["session_date"]).to_numpy("datetime64[ns]")
    pos = np.minimum(np.searchsorted(sessions, day), len(sessions) - 1)
    is_session = sessions[pos] == day
    work = pd.DataFrame(
        {
            "ticker": rows["ticker"].astype(str).to_numpy(),
            "day": day,
            "sidx": np.where(is_session, pos, -1),
            "key": np.where(is_session, opens[pos], np.datetime64("NaT", "ns")),
        }
    )
    tc = tables.ticker_cik.dropna(subset=["cik"])
    m = work[["ticker", "day"]].reset_index().merge(tc[["ticker", "cik", "valid_from", "valid_to"]])
    start = pd.to_datetime(m["valid_from"]).to_numpy("datetime64[ns]")
    end = pd.to_datetime(m["valid_to"]).to_numpy("datetime64[ns]")
    inside = (np.isnat(start) | (m["day"].to_numpy() >= start)) & (
        np.isnat(end) | (m["day"].to_numpy() <= end)
    )
    m = m[inside].assign(_start=start[inside]).sort_values(["index", "_start"], na_position="first")
    cik = m.drop_duplicates("index", keep="last").set_index("index")["cik"]
    work["cik"] = cik.reindex(work.index).astype("Int64")
    out = pd.DataFrame(index=work.index, columns=list(FEATURES), dtype="object")
    out["cik"] = work["cik"]
    base = work[work["cik"].notna() & (work["sidx"] >= 0)].copy()
    base["cik"] = base["cik"].astype("int64")

    ev = tables.earnings_events[["cik", "reaction_session", "timing"]].copy()
    ev["ev_day"] = pd.to_datetime(ev["reaction_session"]).to_numpy("datetime64[ns]")
    ev["ev_sidx"] = np.searchsorted(sessions, ev["ev_day"].to_numpy())
    ev["cik"] = ev["cik"].astype("int64")
    last = _asof(
        base.assign(key=base["day"]), ev[["cik", "ev_day", "ev_sidx", "timing"]], "ev_day", True
    )
    since = base["sidx"] - last["ev_sidx"]
    out.loc[base.index, "sessions_since_earnings"] = since
    out.loc[base.index, "is_earnings_reaction_day"] = since.eq(0).where(since.notna())
    out.loc[base.index, "earnings_timing"] = last["timing"]
    out.loc[base.index, "sessions_to_next_earnings_est"] = (
        last["ev_sidx"] + quarter_sessions - base["sidx"]
    )

    state = _quarter_state(tables.quarterly, known).assign(cik=lambda s: s["cik"].astype("int64"))
    got = _asof(base, state, "at", False)
    out.loc[base.index, "last_quarter_end"] = got["period_end"]
    for metric in ("eps", "revenue"):
        now, then = got[f"{metric}_yoy_pct"], got[f"{metric}_yoy_prev_pct"]
        out.loc[base.index, f"{metric}_yoy_pct"] = now
        out.loc[base.index, f"{metric}_yoy_prev_pct"] = then
        out.loc[base.index, f"{metric}_growth_accel"] = now - then

    sh = tables.shares[["cik", "accepted", "as_of", "shares", "source"]].copy()
    sh["at"] = _naive_utc(sh["accepted"])
    sh["cik"] = sh["cik"].astype("int64")
    got = _asof(base, sh[["cik", "at", "as_of", "shares", "source"]], "at", False)
    out.loc[base.index, "shares_outstanding"] = got["shares"]
    out.loc[base.index, "shares_as_of"] = got["as_of"]
    out.loc[base.index, "shares_source"] = got["source"]

    co = tables.companies.set_index("cik")
    info = co.reindex(base["cik"].to_numpy())
    spac_until = pd.to_datetime(info["spac_until"]).to_numpy("datetime64[ns]")
    was_spac = ~np.isnat(spac_until) & (base["day"].to_numpy() <= spac_until)
    out.loc[base.index, "sector"] = info["sector"].to_numpy()
    out.loc[base.index, "sic"] = info["sic"].to_numpy()
    out.loc[base.index, "is_spac"] = info["is_spac"].fillna(False).to_numpy(bool) | was_spac

    result = rows.copy()
    for name, dtype in _FEATURE_DTYPES.items():
        values = out[name]
        if dtype in ("Int64", "float64"):
            values = pd.to_numeric(values, errors="coerce").astype(dtype)
        elif dtype:
            values = values.astype(dtype)
        result[name] = values.array
    if "raw_close" in rows:
        result["market_cap_sec"] = result["shares_outstanding"] * rows["raw_close"].astype(float)
    return result


_FEATURE_DTYPES = {
    "cik": "Int64",
    "sessions_since_earnings": "Int64",
    "is_earnings_reaction_day": "boolean",
    "earnings_timing": None,
    "sessions_to_next_earnings_est": "Int64",
    "last_quarter_end": None,
    "eps_yoy_pct": "float64",
    "eps_yoy_prev_pct": "float64",
    "eps_growth_accel": "float64",
    "revenue_yoy_pct": "float64",
    "revenue_yoy_prev_pct": "float64",
    "revenue_growth_accel": "float64",
    "shares_outstanding": "float64",
    "shares_as_of": None,
    "shares_source": None,
    "market_cap_sec": "float64",
    "sector": None,
    "sic": "Int64",
    "is_spac": "boolean",
}


# --------------------------------------------------------------------------- build and check


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
            counts[("all=no header", "count")] += 1
            continue
        cls = offset_class(row.acceptanceDateTime, header)
        fixed = acceptance_times(pd.Series([row.acceptanceDateTime]), pd.Series([row.filingDate]))
        true_utc = header.replace(tzinfo=NEW_YORK).astimezone(dt.UTC)
        rule_ok = fixed["accepted"].iloc[0].to_pydatetime() == true_utc
        for feature, value in (
            ("all", "all"),
            ("kind", row.kind),
            ("year", row.year),
            ("rule_correct", rule_ok),
            ("rule_ambiguous", bool(fixed["ambiguous"].iloc[0])),
            ("header_hour", f"{header.hour:02d}"),
        ):
            counts[(f"{feature}={value}", cls)] += 1
    return counts


def report_audit(counts: Counter) -> None:
    classes = ("utc", "plus_offset", "et_wall", "other", "count")
    for key in sorted({key for key, _ in counts}):
        cells = ", ".join(f"{c} {counts[(key, c)]}" for c in classes if counts[(key, c)])
        status(f"  {key}: {cells}")


def coverage(bars_dir: Path, tables: Tables, data_dir: Path | None, quarter_sessions: int):
    """Counts only: stock tickers and stock rows of the 10-year bars with a CIK, with an
    earnings event, with growth and with shares."""
    from trading_os.regime_study import non_stocks

    funds = non_stocks(data_dir) if data_dir else set()
    total: Counter = Counter()
    tickers: dict[str, set] = {k: set() for k in ("all", "cik", "events", "growth", "shares")}
    for path in sorted(Path(bars_dir).glob("20*.parquet")):
        bars = pd.read_parquet(path, columns=["ticker", "session_date"])
        bars = bars[~bars["ticker"].isin(funds)].reset_index(drop=True)
        got = pit_join(bars, tables, quarter_sessions=quarter_sessions)
        flags = {
            "all": pd.Series(True, index=got.index),
            "cik": got["cik"].notna(),
            "events": got["sessions_since_earnings"].notna(),
            "growth": got["revenue_yoy_pct"].notna() | got["eps_yoy_pct"].notna(),
            "shares": got["shares_outstanding"].notna(),
        }
        for name, flag in flags.items():
            total[f"rows_{name}"] += int(flag.sum())
            tickers[name] |= set(got.loc[flag.to_numpy(bool), "ticker"])
        status(
            f"SEC bulk coverage {path.stem}: {len(got)} stock rows, "
            + ", ".join(f"{k} {int(v.sum())}" for k, v in flags.items() if k != "all")
        )
    return {**total, **{f"tickers_{k}": len(v) for k, v in tickers.items()}}


def build(
    client: BulkClient,
    conf: Mapping,
    calendar: str,
    data_dir: Path,
    bars_dir: Path | None,
    work: Path,
    out: Path,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    start = clock()
    deadline = start + 60 * float(conf["header_minutes"])
    facts_since, events_since = str(conf["facts_since"]), str(conf["events_since"])
    out.mkdir(parents=True, exist_ok=True)
    massive = pd.read_parquet(Path(data_dir) / "data" / "ep_enrich" / "tickers.parquet")
    current = sec_tickers(client)
    ciks = set(pd.to_numeric(massive["cik"], errors="coerce").dropna().astype(int))
    ciks |= set(current["cik"])
    status(f"SEC bulk: {len(ciks)} filers from {len(massive)} + {len(current)} tickers")
    sub_zip = work / "submissions.zip"
    if not sub_zip.exists():
        client.download(SUBMISSIONS_ZIP_URL, sub_zip)
    status(f"SEC bulk: submissions.zip {sub_zip.stat().st_size >> 20} MB")
    filings, raw = read_submissions(sub_zip, ciks, facts_since, events_since)
    companies = companies_table(raw)
    status(f"SEC bulk: {len(filings)} filings, {len(companies)} companies")
    tickers = ticker_map(massive, current, companies)
    filings = filings.join(acceptance_times(filings["accepted_raw"], filings["filed"]))
    checks = pd.DataFrame(columns=["accession", "header_et"])
    if (work / CHECKS_FILE).exists():
        checks = pd.read_parquet(work / CHECKS_FILE)
    from trading_os.regime_study import FUND_TYPES

    stock_ciks = set(tickers.loc[~tickers["type"].isin(FUND_TYPES), "cik"].dropna().astype(int))
    todo = header_todo(filings, events_since, stock_ciks, checks["accession"])
    status(f"SEC bulk: {len(todo)} earnings filings to check against their headers")
    fresh = check_headers(client, todo, deadline, clock)
    checks = pd.concat([checks, fresh], ignore_index=True).drop_duplicates("accession")
    checks.to_parquet(out / CHECKS_FILE, **PARQUET_OPTIONS)
    filings = apply_checks(filings, checks)
    events = earnings_events(filings, events_since, calendar)
    basis = {k: int(v) for k, v in events["time_basis"].value_counts().items()}
    left = int(header_todo(filings, events_since, stock_ciks, checks["accession"]).shape[0])
    status(f"SEC bulk: {len(events)} earnings events, time basis {basis}, {left} unchecked")
    facts_zip = work / "companyfacts.zip"
    if not facts_zip.exists():
        client.download(COMPANYFACTS_ZIP_URL, facts_zip)
    status(f"SEC bulk: companyfacts.zip {facts_zip.stat().st_size >> 20} MB")
    facts = read_facts(facts_zip, ciks, facts_since)
    status(f"SEC bulk: {len(facts)} facts")
    quarterly = quarterly_table(facts, filings, events)
    shares = shares_table(facts, filings)
    del facts
    built = {
        "earnings_events": events,
        "quarterly": quarterly,
        "shares": shares,
        "companies": companies,
        "ticker_cik": tickers,
    }
    for name, frame in built.items():
        frame.to_parquet(out / f"{name}.parquet", **PARQUET_OPTIONS)
        status(f"SEC bulk: {name}: {len(frame)} rows")
    summary = {
        "events": len(events),
        "events_by_basis": basis,
        "events_unchecked": left,
        "quarters": len(quarterly),
        "quarters_derived": int(quarterly["derived"].sum()),
        "quarters_known_at_release": int(quarterly["release_accepted"].notna().sum()),
        "shares_rows": len(shares),
        "companies": len(companies),
        "tickers": int(tickers["ticker"].nunique()),
        "tickers_with_cik": int(tickers.dropna(subset=["cik"])["ticker"].nunique()),
        "tickers_reused": int(tickers.loc[tickers["reused"], "ticker"].nunique()),
    }
    if bars_dir is not None and Path(bars_dir).exists():
        summary["coverage"] = coverage(
            bars_dir, Tables(**built), data_dir, int(conf["quarter_sessions"])
        )
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    status(f"SEC bulk: summary {json.dumps(summary, default=str)}")
    return summary


def main(argv: list[str] | None = None) -> int:
    from trading_os.logsafe import run_guarded

    return run_guarded(lambda: _main(argv), None, "SEC bulk")


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from trading_os.config import load_config

    parser = argparse.ArgumentParser(description="SEC EDGAR bulk fundamentals (10 years)")
    parser.add_argument("--mode", choices=["check", "build"], default="check")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--bars", type=Path, help="folder with the 10-year YYYY.parquet bars")
    parser.add_argument("--work", type=Path, default=Path("work"))
    parser.add_argument("--out", type=Path, default=Path("out"))
    args = parser.parse_args(argv)
    config = load_config()
    conf = config.sec_bulk
    agent = os.environ.get("SEC_USER_AGENT") or config.sec["user_agent"]
    if "@" not in agent:
        status("SEC bulk: set SEC_USER_AGENT (a name and contact email; SEC requires one)")
        return 1
    client = BulkClient(agent, conf["requests_per_second"])
    if args.mode == "check":
        counts = audit_acceptance(client)
        status(
            f"SEC bulk check: {sum(v for (k, _), v in counts.items() if k == 'all=all')} filings"
        )
        report_audit(counts)
        return 0
    if args.data_dir is None:
        status("SEC bulk: --data-dir is required for a build")
        return 1
    args.work.mkdir(parents=True, exist_ok=True)
    build(client, conf, config.schedule.calendar, args.data_dir, args.bars, args.work, args.out)
    return 0
