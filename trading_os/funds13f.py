"""Fund holdings on the card (Emil, 5 Nov 2026: "put in card"; data repo
docs/research/2026-11-05-funds-and-rotation.md): what the funds held in each stock at the end
of the last quarter, from SEC's Form 13F data sets.

- `fund_holders`: managers holding the stock, counting only those who filed on time.
- `fund_breadth`: (new holders - holders who left) / holders the quarter before, among managers
  who filed in both quarters (Chen, Hong & Stein 2002).
- `fund_own`: 13F shares / shares outstanding (market cap / close of the run).

Known the day after the 45-day filing deadline, so 1.5-4.5 months old. A quarterly job
(`funds13f.yml`) writes `data/funds/fund_holdings.parquet`. CUSIPs are mapped to tickers through
OpenFIGI's public mapping API, which gets the CUSIPs only, and the answers are cached in
`data/funds/figi_cache.parquet`.

Facts, not grades. In the study (2016-26, live A+/A), trades in stocks the funds owned more than
80 % of made +0.27 / +0.36R against +0.81 / +0.58R for the rest. Halving their risk cost nothing
in the account, but the gain was inside the noise. Funds piling in (breadth +10 % or more) was
better per trade, but sizing it up did no better than random extra risk.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

from trading_os.logsafe import status

TABLE = Path("data") / "funds" / "fund_holdings.parquet"
CACHE = Path("data") / "funds" / "figi_cache.parquet"
FIGI_URL = "https://api.openfigi.com/v3/mapping"
COLUMNS = ["ticker", "cusip", "period", "available", "n_holders", "shares", "breadth"]
MIN_HOLDERS = 3  # CUSIPs worth mapping
MIN_PREV = 5  # holders the quarter before, for a breadth
NOT_SHARES = r"\b(?:NOTE|NOTES|PUT|CALL|WT|WTS|WARRANT|PFD|PREF|DEB|BOND|RIGHT|RTS|UNIT)\b"
HIGH_OWN, PILING_IN = 0.80, 0.10  # the study's lines for the card
MAX_OWN = 1.5  # 13F shares over 150 % of the shares outstanding: left out
OWN_NOTE = "A+/A in stocks the funds owned over 80 % did worse in the study"
FILES = 3  # the newest 13F zips: two quarters and one before them


def _file_end(url: str) -> dt.date:
    """The last filing day a 13F zip covers, from its name (2023q4 or 01dec2025-28feb2026)."""
    name = url.rsplit("/", 1)[-1]
    m = re.match(r"(\d{4})q([1-4])_", name)
    if m:
        year, quarter = int(m.group(1)), int(m.group(2))
        return (pd.Timestamp(year, 3 * quarter, 1) + pd.offsets.MonthEnd(0)).date()
    m = re.match(r"\d{2}[a-z]{3}\d{4}-(\d{2}[a-z]{3}\d{4})_", name)
    return dt.datetime.strptime(m.group(1), "%d%b%Y").date() if m else dt.date.min


def newest(links: list[str], n: int = FILES) -> list[str]:
    return sorted(links, key=_file_end)[-n:]


def figi(cusips: list[str], cache: pd.DataFrame, http=None, pause: float = 2.45) -> pd.DataFrame:
    """`cache` plus OpenFIGI's ticker for every CUSIP not in it (US listing first; '' = none).
    Public API without a key: 10 CUSIPs a request, 25 requests a minute."""
    http = http or requests.Session()
    todo = [c for c in cusips if c not in set(cache["cusip"])]
    rows = []
    for k in range(0, len(todo), 10):
        batch = todo[k : k + 10]
        for attempt in range(5):
            r = http.post(
                FIGI_URL, json=[{"idType": "ID_CUSIP", "idValue": c} for c in batch], timeout=60
            )
            if r.status_code != 429:
                break
            time.sleep(15 * (attempt + 1))
        r.raise_for_status()
        for c, answer in zip(batch, r.json(), strict=True):
            data = answer.get("data", [])
            us = [d for d in data if d.get("exchCode") == "US"] or data[:1]
            ticker = (us[0].get("ticker") or "") if us else ""
            rows.append({"cusip": c, "ticker": ticker.replace("/", ".")})
        if pause:
            time.sleep(pause)
    return pd.concat([cache, pd.DataFrame(rows, columns=["cusip", "ticker"])], ignore_index=True)


def by_ticker(holdings: pd.DataFrame, cache: pd.DataFrame) -> pd.DataFrame:
    """Per ticker and quarter (the CUSIP with the most holders): holders, shares and breadth
    against the quarter before."""
    tick = cache[cache["ticker"] != ""].drop_duplicates("cusip").set_index("cusip")["ticker"]
    h = holdings[holdings["cusip"].isin(tick.index)].assign(ticker=lambda d: d["cusip"].map(tick))
    h = h.sort_values("n_holders").drop_duplicates(["ticker", "period"], keep="last")
    h = h.sort_values(["ticker", "period"])
    prev = h.groupby("ticker")["n_holders"].shift(1)
    gap = (
        pd.to_datetime(h["period"]) - pd.to_datetime(h.groupby("ticker")["period"].shift(1))
    ).dt.days
    prev = prev.where(gap.between(80, 100) & (prev >= MIN_PREV))
    h["breadth"] = (h["n_new"] - h["n_exit"]) / prev
    return h[COLUMNS].reset_index(drop=True)


def build(client, data_dir: Path, work: Path, http=None, pause: float = 2.45) -> pd.DataFrame:
    """Fetch the newest 13F zips, map their CUSIPs and save the newest quarter per ticker."""
    from trading_os import research_extra as rx

    page = client._response(rx.HOLDINGS_INDEX)
    links = newest(rx.holdings_links(page.text)) if page is not None else []
    if not links:
        raise RuntimeError("13F: no data set links")
    since = _file_end(links[0]) - dt.timedelta(days=200)
    names = []
    for k, url in enumerate(links):
        response = client._response(url)
        if response is None:
            continue
        pos, seen = rx.holder_rows(response.content, since)
        del response
        for period, part in pos.groupby("period"):
            part.to_parquet(work / f"{period:%Y-%m-%d}_{k:03d}.parquet", index=False)
        names.append(seen)
        status(f"13F: file {k + 1} of {len(links)}, {len(pos)} positions")
    holdings = rx.holdings_table(work, pd.concat(names, ignore_index=True))
    shares_like = ~holdings["title"].fillna("").str.upper().str.contains(NOT_SHARES)
    wanted = holdings[shares_like & (holdings["n_holders"] >= MIN_HOLDERS)]
    cache_path = Path(data_dir) / CACHE
    cache = (
        pd.read_parquet(cache_path)
        if cache_path.exists()
        else pd.DataFrame(columns=["cusip", "ticker"])
    )
    cache = figi(sorted(set(wanted["cusip"])), cache, http, pause)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache.to_parquet(cache_path, index=False)
    table = by_ticker(wanted, cache)
    last = table["period"].max()
    table = table[table["period"] == last].reset_index(drop=True)
    table.to_parquet(Path(data_dir) / TABLE, index=False)
    with_breadth = int(table["breadth"].notna().sum())
    status(f"13F: {len(table)} tickers for the quarter, {with_breadth} with a breadth")
    return table


def attach(df: pd.DataFrame, data_dir: Path, session: dt.date) -> pd.DataFrame:
    """`df` plus `fund_holders`, `fund_breadth`, `fund_own` and `fund_period` from the saved
    quarter, if it was complete before `session`. Without the table, `df` as it was."""
    path = Path(data_dir) / TABLE
    if not path.exists():
        return df
    t = pd.read_parquet(path)
    t = (
        t[pd.to_datetime(t["available"]).dt.date < session]
        .drop_duplicates("ticker")
        .set_index("ticker")
    )
    tick = df["ticker"].astype(str)
    out = df.assign(
        fund_holders=tick.map(t["n_holders"]).astype(float).to_numpy(),
        fund_breadth=tick.map(t["breadth"]).astype(float).to_numpy(),
        fund_period=tick.map(t["period"].astype(str)).to_numpy(),
    )
    if "market_cap" in df and "close" in df:
        outstanding = pd.to_numeric(df["market_cap"], errors="coerce") / pd.to_numeric(
            df["close"], errors="coerce"
        )
        own = tick.map(t["shares"]).astype(float) / outstanding.where(outstanding > 0)
        out["fund_own"] = own.where(own <= MAX_OWN).to_numpy()  # above: a CUSIP or class mix-up
    return out


def _quarter(period) -> str:
    p = pd.Timestamp(period)
    return f"Q{p.quarter} {p.year}"


def card_tag(row) -> str | None:
    """The card's line when the funds own over 80 % or piled in (+10 % net new holders)."""
    own, breadth, period = row.get("fund_own"), row.get("fund_breadth"), row.get("fund_period")
    if not isinstance(period, str) or not period:
        return None
    when = f"13F, {_quarter(period)}"
    if own is not None and not pd.isna(own) and own > HIGH_OWN:
        return f"🏦 Funds own {own:.0%} ({when}). {OWN_NOTE}"
    if breadth is not None and not pd.isna(breadth) and breadth >= PILING_IN:
        return f"🏦 Funds piling in: {breadth:+.0%} net new holders ({when})"
    return None


def main(argv: list[str] | None = None) -> int:
    from trading_os.sec_bulk import BulkClient

    parser = argparse.ArgumentParser(description="13F fund holdings for the card")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    agent = os.environ.get("SEC_USER_AGENT", "")
    if "@" not in agent:
        status("13F: SEC_USER_AGENT not set")
        return 1
    work = Path("work") / "13f"
    work.mkdir(parents=True, exist_ok=True)
    build(BulkClient(agent, 5), args.data_dir, work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
