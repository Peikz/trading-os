"""Job openings log (Emil, 25 Oct 2026): how many jobs each listed company advertises, once a
day, so that in 6-12 months hiring growth can be tested as an EP variable. No free source
keeps this history, so we build our own from today on. Facts only; nothing reads it yet.

- Boards: the public job-board-aggregator lists (github.com/Feashliaa/job-board-aggregator,
  the same lists career-ops' scan-ats-full.mjs uses) for Greenhouse, Lever, Ashby and Workday,
  matched to SEC-listed companies by exact normalized name (no fuzzy matching: a wrong match
  would be worse than none). Saved once as data/jobs/boards.parquet.
- Daily: the open-job count per board, one request each, sequential with a pause (polite to
  every host). Saved as data/jobs/YYYY/YYYY-MM-DD.parquet (append-only, never overwritten).
- Public logs: counts only.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

import pandas as pd
import requests

DATASET = "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/{ats}_companies.json"
ATS = ("greenhouse", "lever", "ashby", "workday")
SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "companies", "holdings",
    "holding", "group", "ltd", "limited", "plc", "the", "sa", "nv", "ag", "se", "lp", "llc",
    "de", "del", "new", "class", "a", "com",
}  # fmt: skip
PAUSE_S = 0.5
TIMEOUT_S = 20
HEADERS = {"User-Agent": "trading-os job-openings log (private research)"}


def normalize(name: str) -> str:
    """`AMERICAN VANGUARD CORP` -> `americanvanguard`; a slug `american-vanguard` -> the same."""
    words = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower().replace("&", " and ")).split()
    return "".join(w for w in words if w not in SUFFIXES)


def slug_key(ats: str, entry: str) -> str:
    slug = entry.split("|")[0] if ats == "workday" else entry
    return re.sub(r"[^a-z0-9]+", "", slug.lower())


def build_boards(companies: pd.DataFrame, lists: dict[str, list[str]]) -> pd.DataFrame:
    """Listed companies (`cik`, `name`, `ticker`) matched to boards: one row per company and
    board. A key shared by two companies is dropped (ambiguous)."""
    names = companies.assign(key=companies["name"].map(normalize))
    names = names[names["key"].str.len() >= 4]
    names = names[~names["key"].duplicated(keep=False)]
    rows = []
    for ats, entries in lists.items():
        boards = pd.DataFrame({"entry": entries})
        boards["key"] = boards["entry"].map(lambda e, a=ats: slug_key(a, e))
        boards = boards[~boards["key"].duplicated(keep=False)]
        rows.append(names.merge(boards, on="key").assign(ats=ats))
    if not rows:
        return pd.DataFrame(columns=["ticker", "cik", "name", "ats", "entry"])
    out = pd.concat(rows, ignore_index=True)
    return out[["ticker", "cik", "name", "ats", "entry"]].sort_values(["ticker", "ats"])


def count(ats: str, entry: str, http=requests) -> int | None:
    """Open jobs on one board; None when the board doesn't answer."""
    try:
        if ats == "greenhouse":
            r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{entry}/jobs",
                         headers=HEADERS, timeout=TIMEOUT_S)  # fmt: skip
            return len(r.json()["jobs"]) if r.ok else None
        if ats == "lever":
            r = http.get(f"https://api.lever.co/v0/postings/{entry}?mode=json",
                         headers=HEADERS, timeout=TIMEOUT_S)  # fmt: skip
            return len(r.json()) if r.ok else None
        if ats == "ashby":
            r = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{entry}",
                         headers=HEADERS, timeout=TIMEOUT_S)  # fmt: skip
            return len(r.json()["jobs"]) if r.ok else None
        if ats == "workday":
            tenant, instance, site = entry.split("|")
            url = f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            body = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
            r = http.post(url, json=body, headers=HEADERS, timeout=TIMEOUT_S)
            return int(r.json()["total"]) if r.ok else None
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None
    return None


def snapshot(boards: pd.DataFrame, today: dt.date, http=requests, pause_s=PAUSE_S) -> pd.DataFrame:
    """Today's counts for every board (sequential, a pause between requests)."""
    rows = []
    for rec in boards.to_dict("records"):
        n = count(rec["ats"], rec["entry"], http)
        rows.append({"session_date": today, "ticker": rec["ticker"], "cik": rec["cik"],
                     "ats": rec["ats"], "entry": rec["entry"], "open_jobs": n})  # fmt: skip
        time.sleep(pause_s)
    out = pd.DataFrame(rows)
    out["fetched_ts"] = pd.Timestamp.now(tz="UTC")
    return out


def snapshot_path(data_dir: Path, today: dt.date) -> Path:
    return Path(data_dir) / "data" / "jobs" / str(today.year) / f"{today.isoformat()}.parquet"
