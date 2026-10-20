"""Alpaca market data (free account): daily and minute bars for all US stocks back to 2016.

For research history beyond Massive's free 2 years (Emil, 19 Oct 2026). Keys come from the
ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY secrets and travel in headers only. The free plan
allows about 200 requests a minute; a request can ask for many symbols at once. The SIP feed
(all exchanges) is allowed for anything older than 15 minutes; IEX is the fallback.

`check` answers the open question before anything is built on it: does Alpaca have bars for
stocks that have since been delisted (the EP study needs them).

The daily bars are split- and dividend-adjusted, so a price floor or a per-share cost read from
them is wrong for any stock that later split. `raw_history` adds the real prices (Emil,
20 Oct 2026): what every stock-day of the adjusted history actually traded at, and the factor
between the two.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from trading_os.logsafe import status

DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
# Probe symbols for the check: listed for decades, and a few delisted since 2023.
LISTED = "AAPL"
DELISTED = ("SIVB", "FRC", "BBBY", "SPWR")
BAR_FIELDS = ["ticker", "ts", "open", "high", "low", "close", "volume", "trades", "vwap"]
# Real ticker shapes only: Alpaca's inactive list also holds CUSIP-style placeholders.
SYMBOL_SHAPE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def _empty_bars() -> pd.DataFrame:
    frame = pd.DataFrame(columns=BAR_FIELDS)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


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
        self._shared = session  # tests pass a fake; otherwise one requests session per thread
        self._local = threading.local()
        self._lock = threading.Lock()  # the request spacing holds across threads
        self._gap, self._sleep, self._clock, self._last = 60 / per_minute, sleep, clock, None
        self.feed = "sip"

    @property
    def _http(self):
        if self._shared is not None:
            return self._shared
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _get(self, url: str, params: dict) -> dict | list:
        for attempt in (1, 2, 3):
            with self._lock:
                if self._last is not None:
                    wait = self._gap - (self._clock() - self._last)
                    if wait > 0:
                        self._sleep(wait)
                self._last = self._clock()
            response = self._http.get(url, params=params, headers=self._headers, timeout=60)
            if response.status_code == 429 and attempt < 3:
                self._sleep(30)
                continue
            if not response.ok:
                # Never the URL: it carries the symbols, and job logs are public.
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            return response.json()
        raise requests.HTTPError("rate limited three times")

    def bars(
        self,
        symbols: Iterable[str],
        timeframe: str,
        start: dt.datetime,
        end: dt.datetime,
        max_pages: int = 1000,
        adjustment: str = "all",
    ) -> pd.DataFrame:
        """Bars for several symbols (all pages): ticker, ts (UTC), open, high, low, close,
        volume, trades, vwap. Split- and dividend-adjusted unless `adjustment` asks for another
        of Alpaca's values: "raw" (as traded that day), "split" or "dividend"."""
        symbols = list(symbols)
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 10_000,
            "adjustment": adjustment,
            "feed": self.feed,
        }
        rows = []
        for _ in range(max_pages):
            try:
                body = self._get(DATA_URL, params)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                if code in (403, 422) and self.feed == "sip":
                    # The plan refused SIP (also happens when the window reaches the last 15
                    # minutes). IEX has a sliver of the volume: say so, never silently.
                    status("Alpaca: SIP refused, falling back to IEX (partial volume)")
                    self.feed = params["feed"] = "iex"
                    continue
                if code == 400 and len(symbols) > 1 and "page_token" not in params:
                    # One unknown symbol rejects the batch: split it to find the rest.
                    half = len(symbols) // 2
                    return pd.concat(
                        [
                            self.bars(symbols[:half], timeframe, start, end, max_pages, adjustment),
                            self.bars(symbols[half:], timeframe, start, end, max_pages, adjustment),
                        ],
                        ignore_index=True,
                    )
                if code == 400:
                    return _empty_bars()
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
        frame = pd.DataFrame(rows, columns=BAR_FIELDS)
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

    from trading_os.logsafe import run_guarded

    parser = argparse.ArgumentParser(description="Alpaca market data")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--ep-minutes", action="store_true", help="minute bars around EPs")
    parser.add_argument("--data-dir", type=Path, help="checkout of trading-os-data")
    parser.add_argument("--out", type=Path, help="folder for the monthly minute files")
    parser.add_argument("--daily-years", help="FIRST-LAST, e.g. 2016-2024: daily bars per year")
    parser.add_argument("--raw-years", help="FIRST-LAST, e.g. 2016-2026: unadjusted bars per year")
    parser.add_argument("--raw-check", action="store_true", help="counts over the raw year files")
    parser.add_argument("--bars", type=Path, help="folder with the bars-alpaca year files")
    parser.add_argument("--raw-dir", type=Path, help="folder with the raw_YYYY.parquet files")
    args = parser.parse_args(argv)
    if args.raw_check:  # reads files only: no keys, no requests
        return run_guarded(lambda: _raw_check_run(args), None, "Alpaca")
    key, secret = (
        os.environ.get("ALPACA_API_KEY_ID", ""),
        os.environ.get("ALPACA_API_SECRET_KEY", ""),
    )
    if not key or not secret:
        status("Alpaca: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set")
        return 1
    client = AlpacaClient(key, secret)
    return run_guarded(lambda: _run(args, client), None, "Alpaca")


def _run(args, client: AlpacaClient) -> int:
    if args.check:
        return 0 if check(client) else 1
    if args.ep_minutes:
        files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
        sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
        ep_minutes(args.data_dir, client, args.out, sessions)
        return 0
    if args.daily_years:
        first, last = (int(y) for y in args.daily_years.split("-"))
        daily_history(client, args.out, first, last)
        return 0
    if args.raw_years:
        first, last = (int(y) for y in args.raw_years.split("-"))
        raw_history(client, args.bars, args.raw_dir, first, last)
        return 0
    status("Alpaca: pass --check, --ep-minutes, --daily-years, --raw-years or --raw-check")
    return 1


def _raw_check_run(args) -> int:
    raw_check(args.bars, args.raw_dir)
    return 0


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


YEAR_BATCH = 200  # symbols per daily-bar request


def stock_symbols(client: AlpacaClient) -> list[str]:
    """Every US equity Alpaca knows, listed or delisted, on an exchange (no OTC)."""
    assets = client.assets("active") + client.assets("inactive")
    return sorted(
        {
            a["symbol"]
            for a in assets
            if a.get("exchange") not in ("OTC", None) and SYMBOL_SHAPE.match(a.get("symbol") or "")
        }
    )


def daily_year(client: AlpacaClient, symbols: list[str], year: int, **bar_args) -> pd.DataFrame:
    """Daily bars for one calendar year in the history bars shape (source alpaca). `bar_args`
    go on to `client.bars` (`daily_year_raw` passes adjustment="raw")."""
    from trading_os.metrics import NEW_YORK

    start = dt.datetime(year, 1, 1, tzinfo=dt.UTC)
    # Never ask for "now": the free plan refuses SIP for the last 15 minutes, and the IEX
    # fallback has ~2 % of the volume (it broke the first 2026 file, 20 Oct 2026).
    yesterday = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = min(dt.datetime(year, 12, 31, 23, 59, tzinfo=dt.UTC), yesterday)
    frames = []
    for k in range(0, len(symbols), YEAR_BATCH):
        bars = client.bars(symbols[k : k + YEAR_BATCH], "1Day", start, end, **bar_args)
        if len(bars):
            frames.append(bars)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["session_date"] = out["ts"].dt.tz_convert(NEW_YORK).dt.date
    out["source"] = "alpaca"
    out["feed"] = getattr(client, "feed", "sip")
    columns = ["session_date", "ticker", "open", "high", "low", "close", "volume", "vwap", "trades"]
    return (
        out[[*columns, "source", "feed"]]
        .sort_values(["ticker", "session_date"])
        .reset_index(drop=True)
    )


def daily_history(client: AlpacaClient, out_dir, first_year: int, last_year: int) -> list[int]:
    """`YYYY.parquet` per year into `out_dir`; years already there are skipped."""
    from pathlib import Path

    from trading_os.store import PARQUET_OPTIONS

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [y for y in range(first_year, last_year + 1) if not (out_dir / f"{y}.parquet").exists()]
    if not todo:
        return []
    symbols = stock_symbols(client)
    status(f"Alpaca daily: {len(symbols)} symbols, years {todo}")
    written = []
    for year in todo:
        bars = daily_year(client, symbols, year)
        path = out_dir / f"{year}.parquet"
        tmp = path.with_name(path.name + ".tmp")
        bars.to_parquet(tmp, **PARQUET_OPTIONS)
        tmp.replace(path)
        written.append(year)
        status(f"Alpaca daily: {year}: {bars['ticker'].nunique() if len(bars) else 0} stocks")
    return written


# Real prices (Emil, 20 Oct 2026). The bars-alpaca files are split- and dividend-adjusted, so a
# price floor or a per-share cost read from them is wrong for any stock that later split.
# raw_<year>.parquet holds what each stock-day really traded at, plus the factor between the two.
BAR_KEY = ["ticker", "session_date"]
RAW_FIELDS = {
    "open": "raw_open",
    "high": "raw_high",
    "low": "raw_low",
    "close": "raw_close",
    "volume": "raw_volume",
}
RAW_COLUMNS = [*BAR_KEY, *RAW_FIELDS.values(), "factor"]
# Checks only, no scan reads them: a split or reverse split moves the factor by more than 1.5x
# up or under 0.67x in a day; dividends move it by a few percent.
SPLIT_UP, SPLIT_DOWN = 1.5, 0.67
MAX_NO_RAW_SHARE = 0.01  # (proposed) more stock-days than this without a raw bar: no file


def daily_year_raw(client: AlpacaClient, symbols: list[str], year: int) -> pd.DataFrame:
    """`daily_year` unadjusted (adjustment=raw): prices and volume as they traded that day."""
    bars = daily_year(client, symbols, year, adjustment="raw")
    if len(bars) and (bars["feed"] != "sip").any():
        # IEX closes differ from the consolidated ones: a factor built on them would be noise.
        status("Alpaca raw: SIP refused, the raw bars would not match the adjusted ones")
        raise RuntimeError("SIP feed refused")
    return bars


def raw_table(raw: pd.DataFrame, adjusted: pd.DataFrame) -> pd.DataFrame:
    """Unadjusted OHLCV for every stock-day of `adjusted` (one bars-alpaca year: ticker,
    session_date, close) as float32, and factor = raw close / adjusted close, so the adjusted
    price times the factor is the real one. A stock-day Alpaca sent no raw bar for stays NaN."""
    adjusted = adjusted.drop_duplicates(BAR_KEY, keep="last")[[*BAR_KEY, "close"]]
    raw = raw.drop_duplicates(BAR_KEY, keep="last")[[*BAR_KEY, *RAW_FIELDS]]
    table = adjusted.merge(raw.rename(columns=RAW_FIELDS), on=BAR_KEY, how="left", validate="1:1")
    factor = table["raw_close"] / table.pop("close")
    table["factor"] = factor.where(np.isfinite(factor))
    table[RAW_COLUMNS[2:]] = table[RAW_COLUMNS[2:]].astype("float32")
    return table[RAW_COLUMNS].sort_values(BAR_KEY).reset_index(drop=True)


def raw_history(
    client: AlpacaClient, bars_dir, out_dir, first_year: int, last_year: int
) -> list[int]:
    """`raw_YYYY.parquet` per year into `out_dir`: the real prices of every stock-day in
    `bars_dir/YYYY.parquet` (the bars-alpaca files). Years go one after another, so the client's
    request spacing holds on the shared key; years already in `out_dir` are skipped."""
    from trading_os.store import PARQUET_OPTIONS

    bars_dir, out_dir = Path(bars_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    years = range(first_year, last_year + 1)
    todo = [y for y in years if not (out_dir / f"raw_{y}.parquet").exists()]
    status(f"Alpaca raw: years {todo}")
    written = []
    for year in todo:
        source = bars_dir / f"{year}.parquet"
        if not source.exists():
            status(f"Alpaca raw: {year}: no bars-alpaca file to match")
            raise FileNotFoundError(source)
        adjusted = pd.read_parquet(source, columns=[*BAR_KEY, "close"])
        raw = daily_year_raw(client, sorted(adjusted["ticker"].unique()), year)
        if raw.empty:
            status(f"Alpaca raw: {year}: no raw bars came back")
            raise RuntimeError("no raw bars")
        table = raw_table(raw, adjusted)
        missing = int(table["raw_close"].isna().sum())
        stocks = table["ticker"].nunique()
        status(
            f"Alpaca raw: {year}: {len(table)} stock-days, {stocks} stocks, {missing} no raw bar"
        )
        if missing > MAX_NO_RAW_SHARE * len(table):
            raise RuntimeError("too many stock-days without a raw bar")
        path = out_dir / f"raw_{year}.parquet"
        tmp = path.with_name(path.name + ".tmp")
        table.to_parquet(tmp, **PARQUET_OPTIONS)
        tmp.replace(path)
        written.append(year)
    return written


def factor_jumps(table: pd.DataFrame, previous: pd.Series | None = None) -> pd.Series:
    """True on the rows where a stock's factor moved by more than SPLIT_UP or under SPLIT_DOWN
    since its previous row: the day a split or reverse split took effect. `table` is sorted by
    ticker, then date; each stock's first row is compared with `previous` (its last factor the
    year before) when that is given."""
    before = table.groupby("ticker", sort=False)["factor"].shift(1)
    if previous is not None:
        first = ~table["ticker"].duplicated()
        before = before.where(~first, table["ticker"].map(previous))
    ratio = table["factor"] / before
    return (ratio > SPLIT_UP) | (ratio < SPLIT_DOWN)


def raw_counts(
    adjusted: pd.DataFrame, table: pd.DataFrame, floor: float, previous: pd.Series | None = None
) -> dict[str, int]:
    """Counts for one raw year against its bars-alpaca twin (`adjusted`: ticker, session_date,
    close): size, days without a raw bar, days only one of the two files has, stocks whose factor
    jumped (a split), and the stock-days a price floor reads differently on adjusted prices."""
    adjusted = adjusted.drop_duplicates(BAR_KEY, keep="last")[[*BAR_KEY, "close"]]
    joined = adjusted.merge(table[[*BAR_KEY, "raw_close"]], on=BAR_KEY, how="outer", indicator=True)
    both = joined[joined["_merge"] == "both"]
    real, adj = both["raw_close"], both["close"]
    jumps = factor_jumps(table, previous)
    return {
        "stock_days": len(table),
        "stocks": int(table["ticker"].nunique()),
        "no_raw_bar": int(table["raw_close"].isna().sum()),
        "only_in_bars": int((joined["_merge"] == "left_only").sum()),
        "only_in_raw": int((joined["_merge"] == "right_only").sum()),
        "jump_stocks": int(table.loc[jumps, "ticker"].nunique()),
        "jump_days": int(jumps.sum()),
        "real_below_floor": int(((real < floor) & (adj >= floor)).sum()),
        "real_above_floor": int(((real >= floor) & (adj < floor)).sum()),
    }


def raw_check(bars_dir, raw_dir, floor: float | None = None) -> list[dict[str, int]]:
    """Counts for every `raw_YYYY.parquet` in `raw_dir` against `bars_dir/YYYY.parquet`, one log
    line per year (counts only: never a ticker or a price). `floor` defaults to the alert tier's
    price_min. A split on a year's first day shows up against the year before, when its file is
    there too."""
    if floor is None:
        from trading_os.config import load_config

        floor = float(load_config().universe["alert"]["price_min"])
    bars_dir, raw_dir = Path(bars_dir), Path(raw_dir)
    years = sorted(int(p.stem.removeprefix("raw_")) for p in raw_dir.glob("raw_*.parquet"))
    results: list[dict[str, int]] = []
    carry, last = None, None
    for year in years:
        table = pd.read_parquet(
            raw_dir / f"raw_{year}.parquet", columns=[*BAR_KEY, "raw_close", "factor"]
        )
        previous = carry if last == year - 1 else None
        carry, last = table.groupby("ticker")["factor"].last(), year
        source = bars_dir / f"{year}.parquet"
        if not source.exists():
            status(f"Alpaca raw check {year}: no bars-alpaca file to match")
            continue
        adjusted = pd.read_parquet(source, columns=[*BAR_KEY, "close"])
        c = raw_counts(adjusted, table, floor, previous)
        results.append({"year": year, **c})
        status(
            f"Alpaca raw check {year}: {c['stock_days']} stock-days, {c['stocks']} stocks; "
            f"no raw bar {c['no_raw_bar']}, only in bars {c['only_in_bars']}, "
            f"only in raw {c['only_in_raw']}; factor jumps (>{SPLIT_UP}x or <{SPLIT_DOWN}x) "
            f"{c['jump_stocks']} stocks on {c['jump_days']} days; real close < ${floor:.2f} but "
            f"adjusted >= ${floor:.2f}: {c['real_below_floor']} stock-days (real >= and "
            f"adjusted <: {c['real_above_floor']})"
        )
    if not results:
        status("Alpaca raw check: no raw year files matched to bars")
    return results
