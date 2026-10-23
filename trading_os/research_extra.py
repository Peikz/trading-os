"""New data for the research (Emil, 23 Oct 2026: "get more data"), fetched by the manual
`research-extra.yml` job into the data repo's "research-extra" release (not git):

- `insiders`: SEC's quarterly insider transaction data sets (Forms 3/4/5, free bulk files):
  open-market purchases (code P) and sales (S) with the filing date, the issuer's ticker and
  the owner's role. Filing date = the day the market could know.
- `events8k`: every 8-K since 2015 with its item codes (1.01 a material agreement, 2.02
  results, 5.02 a management change, 8.01 other events...) and acceptance time, from SEC's
  bulk submissions.zip.
- `news`: Alpaca's news headlines (Benzinga) for a list of (ticker, window end) requests, the
  study's EP / EP9M trades, each for the 4 days up to its entry. Headlines only, no article text.

Research only, never part of a scan. This repo is public: the job prints counts and status only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import zipfile
from pathlib import Path

import pandas as pd

from trading_os.logsafe import status

INSIDER_URL = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
    "{year}q{quarter}_form345.zip"
)
NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
INSIDER_COLUMNS = [
    "ticker", "cik", "filing_date", "trans_date", "code", "shares", "price", "value",
    "director", "officer", "ten_pct", "title", "owner_cik",
]  # fmt: skip
ACC = "ACCESSION_NUMBER"
NEWS_COLUMNS = ["ticker", "session_date", "id", "created_at", "headline", "source", "symbols"]


def quarters(first: int, today: dt.date) -> list[tuple[int, int]]:
    """Every completed quarter from `first` Q1 to the one before `today`'s."""
    last = (today.year, (today.month - 1) // 3)  # quarter 0 = last year's Q4
    if last[1] == 0:
        last = (today.year - 1, 4)
    return [(y, q) for y in range(first, last[0] + 1) for q in range(1, 5) if (y, q) <= last]


def _read(z: zipfile.ZipFile, name: str, columns: list[str]) -> pd.DataFrame:
    member = next(m for m in z.namelist() if m.upper().endswith(name))
    with z.open(member) as fh:
        return pd.read_csv(fh, sep="\t", usecols=columns, dtype=str, quoting=3, on_bad_lines="skip")


def _day(text: pd.Series) -> pd.Series:
    return pd.to_datetime(text, format="%d-%b-%Y", errors="coerce").dt.date


def insider_table(blob: bytes) -> pd.DataFrame:
    """Open-market purchases and sales from one quarter's Form 345 zip."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        sub = _read(z, "SUBMISSION.TSV", [ACC, "FILING_DATE", "ISSUERCIK", "ISSUERTRADINGSYMBOL"])
        trans = _read(
            z,
            "NONDERIV_TRANS.TSV",
            [ACC, "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE"],
        )
        owner = _read(
            z, "REPORTINGOWNER.TSV", [ACC, "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]
        )
    trans = trans[trans["TRANS_CODE"].isin(["P", "S"])]
    rel = owner.groupby(ACC).agg(
        relationship=("RPTOWNER_RELATIONSHIP", lambda s: ",".join(s.dropna())),
        title=("RPTOWNER_TITLE", lambda s: ",".join(s.dropna())),
        owner_cik=("RPTOWNERCIK", "first"),
    )
    t = trans.merge(sub, on=ACC).join(rel, on=ACC)
    shares = pd.to_numeric(t["TRANS_SHARES"], errors="coerce")
    price = pd.to_numeric(t["TRANS_PRICEPERSHARE"], errors="coerce")
    relationship = t["relationship"].fillna("").str.lower()
    out = pd.DataFrame(
        {
            "ticker": t["ISSUERTRADINGSYMBOL"].str.upper().str.strip(),
            "cik": pd.to_numeric(t["ISSUERCIK"], errors="coerce"),
            "filing_date": _day(t["FILING_DATE"]),
            "trans_date": _day(t["TRANS_DATE"]),
            "code": t["TRANS_CODE"],
            "shares": shares,
            "price": price,
            "value": shares * price,
            "director": relationship.str.contains("director"),
            "officer": relationship.str.contains("officer"),
            "ten_pct": relationship.str.contains("tenpercent|10"),
            "title": t["title"].fillna(""),
            "owner_cik": pd.to_numeric(t["owner_cik"], errors="coerce"),
        }
    )
    return out.dropna(subset=["ticker", "filing_date"])[INSIDER_COLUMNS]


def insiders(client, out: Path, first_year: int, today: dt.date) -> int:
    frames = []
    for year, quarter in quarters(first_year, today):
        response = client._response(INSIDER_URL.format(year=year, quarter=quarter))
        if response is None:
            status(f"Insiders {year}Q{quarter}: not published")
            continue
        frames.append(insider_table(response.content))
        status(f"Insiders {year}Q{quarter}: {len(frames[-1])} purchases and sales")
    empty = pd.DataFrame(columns=INSIDER_COLUMNS)
    table = pd.concat(frames, ignore_index=True) if frames else empty
    out.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out / "insiders.parquet", index=False)
    status(f"Insiders: {len(table)} rows, {len(frames)} quarters")
    return 0 if frames else 1


def news_rows(body: dict, ticker: str, session_date) -> list[dict]:
    return [
        {
            "ticker": ticker,
            "session_date": session_date,
            "id": item.get("id"),
            "created_at": item.get("created_at"),
            "headline": item.get("headline"),
            "source": item.get("source"),
            "symbols": ",".join(item.get("symbols") or []),
        }
        for item in body.get("news") or []
    ]


def news(client, requests_file: Path, out: Path, days: int = 4) -> int:
    """Headlines for each request: the `days` before its `until_utc` (the entry)."""
    asks = pd.read_parquet(requests_file)
    rows, failed = [], 0
    for k, ask in enumerate(asks.itertuples(index=False), 1):
        until = pd.Timestamp(ask.until_utc)
        params = {
            "symbols": ask.ticker,
            "start": (until - pd.Timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 50,
            "sort": "desc",
            "include_content": "false",
        }
        try:
            rows += news_rows(client._get(NEWS_URL, params), ask.ticker, ask.session_date)
        except Exception:  # noqa: BLE001 - counted; the message could carry a symbol
            failed += 1
        if k % 2000 == 0:
            status(f"News: {k} of {len(asks)} requests, {len(rows)} headlines, {failed} failed")
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=NEWS_COLUMNS).to_parquet(out / "news.parquet", index=False)
    status(f"News: {len(asks)} requests, {len(rows)} headlines, {failed} failed")
    return 0 if failed < len(asks) else 1


def events_8k(zip_path: Path, since: str = "2015-01-01") -> pd.DataFrame:
    """cik, accession, filed, accepted, items for every 8-K filed since `since`."""
    import json

    from trading_os.sec_bulk import _member_cik

    cols: dict[str, list] = {k: [] for k in ("cik", "accession", "filed", "accepted", "items")}
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            parsed = _member_cik(member.filename)
            if parsed is None:
                continue
            cik, is_main = parsed
            body = json.loads(zf.read(member))
            page = (body.get("filings") or {}).get("recent") or {} if is_main else body
            forms = page.get("form") or []
            n = len(forms)
            keys = ("accessionNumber", "filingDate", "acceptanceDateTime", "items")
            get = {k: page.get(k) or [None] * n for k in keys}
            for i, form in enumerate(forms):
                if form != "8-K" or (get["filingDate"][i] or "") < since:
                    continue
                cols["cik"].append(cik)
                cols["accession"].append(get["accessionNumber"][i])
                cols["filed"].append(get["filingDate"][i])
                cols["accepted"].append(get["acceptanceDateTime"][i])
                cols["items"].append(get["items"][i] or "")
    return pd.DataFrame(cols)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extra research data (insiders, news)")
    parser.add_argument("--mode", choices=["insiders", "events8k", "news"], required=True)
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--requests", type=Path, help="news: the (ticker, until_utc) list")
    parser.add_argument("--first-year", type=int, default=2015)
    args = parser.parse_args(argv)
    if args.mode == "insiders":
        from trading_os.sec_bulk import BulkClient

        agent = os.environ.get("SEC_USER_AGENT", "")
        if "@" not in agent:
            status("Insiders: SEC_USER_AGENT not set")
            return 1
        return insiders(BulkClient(agent, 5), args.out, args.first_year, dt.date.today())
    if args.mode == "events8k":
        from trading_os.sec_bulk import SUBMISSIONS_ZIP_URL, BulkClient

        agent = os.environ.get("SEC_USER_AGENT", "")
        if "@" not in agent:
            status("8-K events: SEC_USER_AGENT not set")
            return 1
        path = BulkClient(agent, 5).download(SUBMISSIONS_ZIP_URL, Path("work") / "submissions.zip")
        table = events_8k(path)
        args.out.mkdir(parents=True, exist_ok=True)
        table.to_parquet(args.out / "events_8k.parquet", index=False)
        status(f"8-K events: {len(table)} filings")
        return 0 if len(table) else 1
    from trading_os.alpaca import AlpacaClient

    key = os.environ.get("ALPACA_API_KEY_ID", "")
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "")
    if not key or not secret:
        status("News: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set")
        return 1
    return news(AlpacaClient(key, secret, per_minute=150), args.requests, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
