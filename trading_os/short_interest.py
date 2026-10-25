"""Days to cover from FINRA's short interest (Emil, 25 Oct 2026). Facts, not advice.

FINRA publishes every listed stock's short interest twice a month (free public API, about 8
business days after each settlement date). Each run asks for the newest settlement date (one
request) and fetches it once (a few pages of 5,000 rows), cached in the data repo under
`data/short_interest/<settlement date>.parquet`.

In the study (data repo docs/research/2026-10-23-new-data.md), A+ and A trades in stocks with
5 or more days to cover lagged the rest; skipping them raised the account's return in 2018-21
and 2022-26 and lowered the drawdown. So an A+/A hit at or over `grading.heavily_shorted_dtc`
becomes C ("heavily shorted"), and every hit there, C included, carries a ⚠️ line.
Auxiliary: a problem leaves the hits as they were and never fails a run.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from trading_os.logsafe import status

DATA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
DATES_URL = "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
FIELDS = ["symbolCode", "settlementDate", "daysToCoverQuantity"]
FOLDER = Path("data") / "short_interest"
PAGE = 5000
MAX_AGE_DAYS = 30  # older than this (a missed release) is not used


def newest_date(http=requests) -> str | None:
    body = http.get(DATES_URL, headers=HEADERS, timeout=60).json()
    dates = [p["partitions"][0] for p in body.get("availablePartitions", []) if p.get("partitions")]
    return max(dates) if dates else None


def fetch(date: str, http=requests) -> pd.DataFrame:
    """Ticker, settlement date and days to cover for every stock on `date`."""
    rows, offset = [], 0
    while True:
        body = {
            "limit": PAGE,
            "offset": offset,
            "fields": FIELDS,
            "compareFilters": [
                {"compareType": "EQUAL", "fieldName": "settlementDate", "fieldValue": date}
            ],
        }
        reply = http.post(DATA_URL, json=body, headers=HEADERS, timeout=120)
        reply.raise_for_status()
        page = reply.json() if reply.text.strip().startswith("[") else []
        rows += page
        if len(page) < PAGE:
            break
        offset += PAGE
    out = pd.DataFrame(rows, columns=FIELDS)
    out["ticker"] = out["symbolCode"].astype(str).str.upper().str.replace("-", ".", regex=False)
    out = out.rename(columns={"daysToCoverQuantity": "dtc", "settlementDate": "si_date"})
    return out[["ticker", "si_date", "dtc"]].drop_duplicates("ticker")


def latest(data_dir: Path, today: dt.date, http=requests) -> pd.DataFrame:
    """The newest report: cached, or fetched once and saved. Empty when too old or missing."""
    folder = Path(data_dir) / FOLDER
    try:
        date = newest_date(http)
        if date and not (folder / f"{date}.parquet").exists():
            table = fetch(date, http)
            if len(table):
                folder.mkdir(parents=True, exist_ok=True)
                table.to_parquet(folder / f"{date}.parquet", index=False)
                status(f"Short interest: {date} saved ({len(table)} stocks)")
    except Exception as exc:  # noqa: BLE001 - the cached report is used
        status(f"Short interest: FINRA not reached ({type(exc).__name__}), cached report used")
    files = sorted(folder.glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=["ticker", "si_date", "dtc"])
    newest = files[-1]
    if (today - dt.date.fromisoformat(newest.stem)).days > MAX_AGE_DAYS:
        return pd.DataFrame(columns=["ticker", "si_date", "dtc"])
    return pd.read_parquet(newest)


def attach(results: dict, table: pd.DataFrame, dtc_max: float) -> dict:
    """`dtc` and `si_date` on every hit; A+/A at or over `dtc_max` become C."""
    if table.empty:
        return results
    lookup = table.set_index("ticker")
    out = {}
    for name, hits in results.items():
        if hits.empty or "ticker" not in hits:
            out[name] = hits
            continue
        h = hits.drop(columns=["dtc", "si_date"], errors="ignore").join(
            lookup[["dtc", "si_date"]], on="ticker"
        )
        if "grade" in h:
            shorted = h["grade"].isin(["A+", "A"]) & (h["dtc"] >= dtc_max)
            if shorted.any():
                h.loc[shorted, "grade_why"] = [
                    f"heavily shorted ({d:.1f} days to cover)" for d in h.loc[shorted, "dtc"]
                ]
                h.loc[shorted, "grade"] = "C"
                h.loc[shorted, "grade_risk_mult"] = 0.0
                h.loc[shorted, "grade_points"] = None
                for col in ("plan_shares", "plan_position_usd", "plan_risk_usd"):
                    if col in h:  # the A size no longer applies
                        h.loc[shorted, col] = float("nan")
        h["si_tag"] = [tag(r, dtc_max) for r in h[["dtc", "si_date"]].to_dict("records")]
        out[name] = h
    return out


def tag(row: dict[str, Any], dtc_max: float) -> str | None:
    """`⚠️ heavily shorted · 6.2 days to cover (09-30)` for any hit at or over `dtc_max`."""
    d = row.get("dtc")
    if d is None or pd.isna(d) or d < dtc_max:
        return None
    when = row.get("si_date")
    known = when is not None and not (isinstance(when, float) and pd.isna(when))
    return f"⚠️ heavily shorted · {d:.1f} days to cover" + (f" ({str(when)[5:]})" if known else "")
