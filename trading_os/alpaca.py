"""Alpaca market data (free account): daily and minute bars for all US stocks back to 2016.

For research history beyond Massive's free 2 years (Emil, 19 Oct 2026). Keys come from the
ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY secrets and travel in headers only. The free plan
allows about 200 requests a minute; a request can ask for many symbols at once. The SIP feed
(all exchanges) is allowed for anything older than 15 minutes; IEX is the fallback.

`check` answers the open question before anything is built on it: does Alpaca have bars for
stocks that have since been delisted (the EP study needs them)?
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import pandas as pd
import requests

from trading_os.logsafe import status

DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
# Probe symbols for the check: listed for decades, and a few delisted since 2023.
LISTED = "AAPL"
DELISTED = ("SIVB", "FRC", "BBBY", "SPWR")


class AlpacaClient:
    def __init__(
        self,
        key_id: str,
        secret: str,
        per_minute: float = 180,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not key_id or not secret:
            raise ValueError("Alpaca keys are empty")
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}
        self._http = session or requests.Session()
        self._gap, self._sleep, self._clock, self._last = 60 / per_minute, sleep, clock, None
        self.feed = "sip"

    def _get(self, url: str, params: dict) -> dict | list:
        for attempt in (1, 2, 3):
            if self._last is not None:
                wait = self._gap - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            response = self._http.get(url, params=params, headers=self._headers, timeout=60)
            if response.status_code == 429 and attempt < 3:
                self._sleep(30)
                continue
            response.raise_for_status()
            return response.json()
        raise requests.HTTPError("rate limited three times")

    def bars(
        self,
        symbols: Iterable[str],
        timeframe: str,
        start: dt.datetime,
        end: dt.datetime,
        max_pages: int = 1000,
    ) -> pd.DataFrame:
        """Bars for several symbols (all pages): ticker, ts (UTC), open, high, low, close,
        volume, trades, vwap. Split- and dividend-adjusted."""
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 10_000,
            "adjustment": "all",
            "feed": self.feed,
        }
        rows = []
        for _ in range(max_pages):
            try:
                body = self._get(DATA_URL, params)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                if code in (403, 422) and self.feed == "sip":
                    self.feed = params["feed"] = "iex"  # the plan doesn't allow SIP
                    continue
                raise
            for symbol, items in (body.get("bars") or {}).items():
                for b in items:
                    rows.append(
                        {
                            "ticker": symbol,
                            "ts": b["t"],
                            "open": b["o"],
                            "high": b["h"],
                            "low": b["l"],
                            "close": b["c"],
                            "volume": b["v"],
                            "trades": b.get("n"),
                            "vwap": b.get("vw"),
                        }
                    )
            token = body.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        frame = pd.DataFrame(
            rows,
            columns=["ticker", "ts", "open", "high", "low", "close", "volume", "trades", "vwap"],
        )
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        return frame

    def assets(self, status_filter: str) -> list[dict]:
        """US equity assets, 'active' or 'inactive' (delisted, renamed, merged)."""
        body = self._get(ASSETS_URL, {"status": status_filter, "asset_class": "us_equity"})
        return body if isinstance(body, list) else []


def check(client: AlpacaClient) -> bool:
    """Access, history depth, minute bars and delisted coverage; counts only in the log."""
    ok = True
    day = dt.datetime(2016, 1, 4, tzinfo=dt.UTC)
    probes = {
        "active stocks": lambda: client.assets("active"),
        "inactive (delisted etc.)": lambda: client.assets("inactive"),
        "daily bars Jan 2016": lambda: client.bars(
            [LISTED], "1Day", day, day + dt.timedelta(days=5)
        ),
        "minute bars one day 2018": lambda: client.bars(
            [LISTED],
            "1Min",
            dt.datetime(2018, 3, 1, 8, tzinfo=dt.UTC),
            dt.datetime(2018, 3, 2, 2, tzinfo=dt.UTC),
        ),
        "delisted names, daily 2022": lambda: client.bars(
            DELISTED,
            "1Day",
            dt.datetime(2022, 1, 3, tzinfo=dt.UTC),
            dt.datetime(2022, 2, 1, tzinfo=dt.UTC),
        ),
    }
    for label, call in probes.items():
        try:
            result = call()
            extra = ""
            if isinstance(result, pd.DataFrame) and "ticker" in result:
                extra = f", {result['ticker'].nunique()} of the symbols"
            status(f"Alpaca check: {label}: OK, {len(result)} rows{extra} (feed {client.feed})")
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            status(f"Alpaca check: {label}: HTTP {code}")
            ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Alpaca market data")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--ep-minutes", action="store_true", help="minute bars around EPs")
    parser.add_argument("--data-dir", type=Path, help="checkout of trading-os-data")
    parser.add_argument("--out", type=Path, help="folder for the monthly minute files")
    args = parser.parse_args(argv)
    key, secret = (
        os.environ.get("ALPACA_API_KEY_ID", ""),
        os.environ.get("ALPACA_API_SECRET_KEY", ""),
    )
    if not key or not secret:
        status("Alpaca: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set")
        return 1
    client = AlpacaClient(key, secret)
    if args.check:
        return 0 if check(client) else 1
    if args.ep_minutes:
        files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
        sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
        ep_minutes(args.data_dir, client, args.out, sessions)
        return 0
    status("Alpaca: pass --check or --ep-minutes")
    return 1


BATCH = 50  # symbols per request


def ep_minutes(data_dir, client: AlpacaClient, out_dir, sessions: list[dt.date]) -> dict[str, int]:
    """1-minute bars (pre/post-market included) around every EP-Day event, from the session
    before to the session after, written as one file per month (`YYYY-MM.parquet`) in
    `out_dir`. EPs on the same day share requests. Months already written are skipped."""
    from pathlib import Path

    from trading_os.ep_enrich import events, latest_study
    from trading_os.metrics import NEW_YORK
    from trading_os.store import PARQUET_OPTIONS

    study = latest_study(data_dir)
    if study.empty:
        return {}
    ep = events(study)
    index = {d: i for i, d in enumerate(sessions)}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done: dict[str, int] = {}
    ep["month"] = ep["session_date"].map(lambda d: f"{d:%Y-%m}")
    for month, part in sorted(ep.groupby("month"), reverse=True):
        path = out_dir / f"{month}.parquet"
        if path.exists():
            continue
        frames = []
        for day, same_day in part.groupby("session_date"):
            i = index.get(day)
            if i is None or i == 0:
                continue
            prev, nxt = sessions[i - 1], sessions[min(i + 1, len(sessions) - 1)]
            start = pd.Timestamp(f"{prev} 15:30", tz=NEW_YORK).tz_convert("UTC").to_pydatetime()
            end = pd.Timestamp(f"{nxt} 16:00", tz=NEW_YORK).tz_convert("UTC").to_pydatetime()
            tickers = sorted(set(same_day["ticker"]))
            for k in range(0, len(tickers), BATCH):
                bars = client.bars(tickers[k : k + BATCH], "1Min", start, end)
                if len(bars):
                    frames.append(bars.assign(event_date=day))
        month_bars = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        tmp = path.with_name(path.name + ".tmp")
        month_bars.to_parquet(tmp, **PARQUET_OPTIONS)
        tmp.replace(path)
        done[month] = int(month_bars["ticker"].nunique()) if len(month_bars) else 0
    status(f"Alpaca minutes: {len(done)} months written, {sum(done.values())} stock-months")
    return done
