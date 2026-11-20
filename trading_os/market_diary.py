"""Market diary (Emil, 20 Nov 2026): the day's market context saved as data, facts only.

Every weekday after the close, one Parquet file and one short Markdown summary per New York
session go to the data repo (`data/diary/YYYY/D.parquet`, `D.md`), written once and never
rewritten (unless forced). Later studies join them to signals: "do EP signals do worse on CPI
days?", "is A+ weaker when VIX is over 25?". No AI, no opinions: numbers and the headlines'
own titles.

The Parquet is one table, one row per item, told apart by `kind`:
  market     SPY, QQQ, IWM, DIA: close, change, distance to the 10/20/50/200-day SMA (in % and in
             ADR), distance to the 52-week high
  vix        VIX close and change (null when the day's breadth row has none)
  sector     the sector, theme and macro ETFs: change 1d / 5d / 20d and the 1d / 20d rank
  breadth    the day's breadth row, copied (one row per value)
  heat       the Sunday scan count in force, its basis and the heat band
  mover_up / mover_down   top 10 by change among stocks >= $5 and >= $20M traded
  scan       per scan and slot: hits, pushed, grade counts, the pushed tickers
  news_market / news_ticker   headline, publisher, time, url (no bodies)
  calendar   cpi_day, fomc_day, jobs_day, opex_day, quad_witching, half_day, earnings count
  meta       where each part came from and what was missing

Sources are the ones the repo already has: the Massive bars store (or the EOD snapshot's bars
until the next morning's backfill), the sectors file, the breadth file, the candidates. The ETF
history ends the day before at 18:20 in the bar store, so the day's own bar comes from one live
Massive grouped-daily call when that is published, else from the day's sectors file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
from collections.abc import Mapping
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yaml

from trading_os import clock, heat, history, timer
from trading_os.audit import ordinary_ticker
from trading_os.breadth import latest_scan_count
from trading_os.config import Config, load_config
from trading_os.logsafe import run_guarded, status
from trading_os.massive import MassiveClient, MassiveError, RateLimiter
from trading_os.store import PARQUET_OPTIONS

MACRO_CALENDAR = Path(__file__).resolve().parent.parent / "config" / "macro_calendar.yaml"
SMA_WINDOWS = (10, 20, 50, 200)
HISTORY_SESSIONS = 260  # 252 for the 52-week high, a little slack
ADR_DAYS = 20
INDEX_ETFS = ("SPY", "QQQ", "IWM", "DIA")
SECTOR_ETFS = ("XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC")
THEME_ETFS = ("SMH", "XBI", "ARKK", "GLD", "TLT", "USO", "UUP", "IBIT")  # IBIT: the BTC proxy
ALL_ETFS = INDEX_ETFS + SECTOR_ETFS + THEME_ETFS
MOVER_MIN_PRICE = 5.0
MOVER_MIN_DOLLAR_VOLUME = 20e6
MOVERS = 10
MARKET_NEWS = 20
NEWS_PER_TICKER = 3
MAX_NEWS_TICKERS = 15
NEWS_WINDOW_ET = (dt.time(4, 0), dt.time(20, 0))  # pre-market to the end of after hours
GRADES = {"A+": "grade_a_plus", "A": "grade_a", "B": "grade_b", "C": "grade_c"}
BREADTH_SKIP = {"session_date", "run_ts", "slot", "run_kind", "data_source"}

COLUMNS = {
    "session_date": "object",
    "kind": "string",
    "key": "string",
    "rank": "Int64",
    "rank_20d": "Int64",
    "value": "float64",
    "text": "string",
    "scan": "string",
    "slot": "string",
    "close": "float64",
    "chg_pct": "float64",
    "ret_5d_pct": "float64",
    "ret_20d_pct": "float64",
    "adr20_pct": "float64",
    "dist_sma10_pct": "float64",
    "dist_sma20_pct": "float64",
    "dist_sma50_pct": "float64",
    "dist_sma200_pct": "float64",
    "dist_sma10_adr": "float64",
    "dist_sma20_adr": "float64",
    "dist_sma50_adr": "float64",
    "dist_sma200_adr": "float64",
    "dist_high52w_pct": "float64",
    "dollar_volume": "float64",
    "hits": "Int64",
    "pushed": "Int64",
    "grade_a_plus": "Int64",
    "grade_a": "Int64",
    "grade_b": "Int64",
    "grade_c": "Int64",
    "grade_other": "Int64",
    "title": "string",
    "publisher": "string",
    "published_utc": "string",
    "url": "string",
    "tickers": "string",
}


# --------------------------------------------------------------------------- calendar


def load_macro(path: Path = MACRO_CALENDAR) -> dict[str, set[dt.date]]:
    """The CPI, FOMC and jobs-report days of config/macro_calendar.yaml, as sets of dates."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, set[dt.date]] = {}
    for name in ("fomc", "cpi", "nfp"):
        days: set[dt.date] = set()
        for entries in (raw.get(name) or {}).values():
            for d in entries:
                days.add(d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)))
        out[name] = days
    return out


def third_friday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(4 - first.weekday()) % 7 + 14)


def calendar_flags(schedule, day: dt.date, macro: Mapping[str, set[dt.date]]) -> dict[str, bool]:
    """Event flags for session `day`. Monthly options expiry is the third Friday, or the session
    before it when that Friday is a holiday; quad witching is that day in March, June, September
    and December; a half day closes before 16:00."""
    expiry = third_friday(day.year, day.month)
    if not clock.is_session(schedule, expiry):
        expiry = clock.previous_session(schedule, expiry)
    opex = day == expiry
    return {
        "cpi_day": day in macro["cpi"],
        "fomc_day": day in macro["fomc"],
        "jobs_day": day in macro["nfp"],
        "opex_day": opex,
        "quad_witching": opex and day.month in (3, 6, 9, 12),
        "half_day": clock.session_close(schedule, day).time() < dt.time(16, 0),
    }


# --------------------------------------------------------------------------- ETF table


def etf_history(data_dir: Path, sessions: list[dt.date], tickers: tuple[str, ...]) -> pd.DataFrame:
    """The ETFs' bars from the Massive bar store for `sessions` (missing files are skipped)."""
    frames = []
    for session in sessions:
        path = history.bars_path(data_dir, "massive", session)
        if path.exists():
            frames.append(
                pd.read_parquet(
                    path,
                    columns=["session_date", "ticker", "high", "low", "close"],
                    filters=[("ticker", "in", list(tickers))],
                )
            )
    if not frames:
        return pd.DataFrame(columns=["session_date", "ticker", "high", "low", "close"])
    out = pd.concat(frames, ignore_index=True)
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out


def sectors_row(data_dir: Path, day: dt.date) -> pd.DataFrame:
    path = Path(data_dir) / "data" / "sectors" / str(day.year) / f"{day.isoformat()}_eod.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["ticker", "close"])
    return pd.read_parquet(path, columns=["ticker", "close"])


def _wide(frame: pd.DataFrame, field: str, sessions: list[dt.date]) -> pd.DataFrame:
    wide = frame.pivot_table(index="session_date", columns="ticker", values=field, aggfunc="last")
    return wide.reindex(sessions)


def etf_metrics(
    hist: pd.DataFrame,
    today: pd.DataFrame,
    sessions: list[dt.date],
    tickers: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[str, str]]:
    """One row per ETF with a close on the last session: change, 5/20-day returns, ADR, distance
    to the SMAs and the 52-week high. `today`: the last session's own bars (ticker, close and
    optionally high/low) that replace or fill the stored history's last row. Returns the table
    (index: ticker) and where each last close came from."""
    last = sessions[-1]
    hist = hist[hist["session_date"].isin(sessions)]
    hist = hist[~((hist["session_date"] == last) & hist["ticker"].isin(today["ticker"]))]
    extra = today.copy()
    extra["session_date"] = last
    for field in ("high", "low"):
        if field not in extra:
            extra[field] = np.nan
    frame = pd.concat([hist, extra[["session_date", "ticker", "high", "low", "close"]]])
    frame = frame[frame["ticker"].isin(tickers)]
    close, high, low = (_wide(frame, f, sessions) for f in ("close", "high", "low"))
    close = close.dropna(axis=1, subset=[last]) if last in close.index else close.iloc[:0]
    high, low = high.reindex(columns=close.columns), low.reindex(columns=close.columns)
    rows = {}
    for t in close.columns:
        c = close[t]
        px = c.iloc[-1]
        rng = ((high[t] / low[t] - 1) * 100).iloc[-ADR_DAYS:]
        adr = float(rng.mean()) if rng.notna().sum() >= ADR_DAYS // 2 else np.nan
        row = {
            "close": float(px),
            "chg_pct": _ret(px, c.iloc[-2]) if len(c) > 1 else np.nan,
            "ret_5d_pct": _ret(px, c.iloc[-6]) if len(c) > 5 else np.nan,
            "ret_20d_pct": _ret(px, c.iloc[-21]) if len(c) > 20 else np.nan,
            "adr20_pct": adr,
        }
        for w in SMA_WINDOWS:
            sma = c.iloc[-w:].mean() if len(c) >= w and c.iloc[-w:].notna().all() else np.nan
            pct = _ret(px, sma)
            row[f"dist_sma{w}_pct"] = pct
            row[f"dist_sma{w}_adr"] = pct / adr if adr and not math.isnan(adr) else np.nan
        top = pd.concat([high[t], c], axis=1).max(axis=1).iloc[-252:]
        row["dist_high52w_pct"] = _ret(px, top.max()) if top.notna().any() else np.nan
        rows[t] = row
    source = {t: "bars" if t in set(today["ticker"]) else "stored" for t in rows}
    return pd.DataFrame.from_dict(rows, orient="index"), source


def _ret(now: float, before: float) -> float:
    if before is None or pd.isna(before) or before == 0 or pd.isna(now):
        return np.nan
    return float((now / before - 1) * 100)


# --------------------------------------------------------------------------- bars, movers


def day_bars(
    data_dir: Path, day: dt.date, client: MassiveClient | None
) -> tuple[pd.DataFrame, str]:
    """The day's bars and their source: the stored Massive file, else one live grouped-daily
    call (kept in memory only), else the EOD snapshot's bars; an empty frame and `none`."""
    if history.have_bars(data_dir, "massive", day):
        return history.load_bars(data_dir, [day]), "massive"
    if client is not None:
        try:
            live = client.grouped_daily(day)
        except (requests.RequestException, MassiveError):
            live = pd.DataFrame()
        if not live.empty:
            return live, "massive-live"
    snap = history.load_bars(data_dir, [day])
    return snap, ("tradingview-snapshot" if not snap.empty else "none")


def movers(today: pd.DataFrame, before: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top up and down movers (price and dollar volume floors) vs the previous session's close."""
    if today.empty or before.empty:
        empty = pd.DataFrame(columns=["ticker", "close", "chg_pct", "dollar_volume"])
        return empty, empty
    prev = before.set_index("ticker")["close"]
    df = today[["ticker", "close", "volume"]].copy()
    df["ticker"] = df["ticker"].astype(str)
    df = df[df["ticker"].map(ordinary_ticker)]
    df["prev"] = df["ticker"].map(prev)
    df["dollar_volume"] = df["close"] * df["volume"]
    df = df[
        (df["close"] >= MOVER_MIN_PRICE)
        & (df["dollar_volume"] >= MOVER_MIN_DOLLAR_VOLUME)
        & (df["prev"] > 0)
    ]
    df["chg_pct"] = (df["close"] / df["prev"] - 1) * 100
    cols = ["ticker", "close", "chg_pct", "dollar_volume"]
    up = df.sort_values("chg_pct", ascending=False).head(MOVERS)[cols]
    down = df.sort_values("chg_pct").head(MOVERS)[cols]
    return up.reset_index(drop=True), down.reset_index(drop=True)


# --------------------------------------------------------------------------- our scans


def load_day_candidates(data_dir: Path, day: dt.date) -> pd.DataFrame:
    """The session's canonical scan runs (manual test runs live elsewhere), one row a signal."""
    files = sorted(
        (Path(data_dir) / "data" / "candidates" / str(day.year)).glob(
            f"{day.isoformat()}_*.parquet"
        )
    )
    if not files:
        return pd.DataFrame()
    out = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return out.drop_duplicates("signal_id") if "signal_id" in out else out


def scan_rows(cands: pd.DataFrame) -> list[dict]:
    rows = []
    if cands.empty:
        return rows
    for (scan, slot), grp in cands.groupby(["scan", "slot"], sort=True):
        pushed = grp[grp["pushed"].fillna(False).astype(bool)]
        grades = grp["grade"].astype(str) if "grade" in grp else pd.Series(dtype=str)
        row = {
            "kind": "scan",
            "key": f"{scan}/{slot}",
            "scan": scan,
            "slot": slot,
            "hits": len(grp),
            "pushed": len(pushed),
            "tickers": ",".join(sorted(pushed["ticker"].astype(str))),
        }
        known = 0
        for grade, col in GRADES.items():
            row[col] = int((grades == grade).sum())
            known += row[col]
        row["grade_other"] = int(len(grades) - known) if len(grades) else 0
        rows.append(row)
    return rows


def pushed_tickers(cands: pd.DataFrame) -> list[str]:
    """Distinct pushed tickers, graded names (not C) first, then by rank."""
    if cands.empty:
        return []
    p = cands[cands["pushed"].fillna(False).astype(bool)].copy()
    if p.empty:
        return []
    grade = p["grade"].astype(str) if "grade" in p else pd.Series("C", index=p.index)
    p["_c"] = (grade == "C").astype(int)
    p["_r"] = p["rank"].fillna(9999) if "rank" in p else 9999
    return list(dict.fromkeys(p.sort_values(["_c", "_r"])["ticker"].astype(str)))


def earnings_pushed(cands: pd.DataFrame) -> int | None:
    """Pushed tickers with earnings within one session (None when the data has no such column)."""
    if cands.empty or "earnings_in_sessions" not in cands:
        return None
    p = cands[cands["pushed"].fillna(False).astype(bool)]
    near = p[p["earnings_in_sessions"].fillna(99) <= 1]
    return int(near["ticker"].nunique())


# --------------------------------------------------------------------------- news


def news_window_utc(day: dt.date) -> tuple[str, str]:
    zone = ZoneInfo("America/New_York")
    start, end = (dt.datetime.combine(day, t, tzinfo=zone) for t in NEWS_WINDOW_ET)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(dt.UTC).strftime(fmt), end.astimezone(dt.UTC).strftime(fmt)


def fetch_news(client: MassiveClient | None, day: dt.date, tickers: list[str]) -> dict:
    """Market headlines and up to 3 per pushed ticker (at most 15 tickers). The client's rate
    limiter spaces the calls; the first failure (e.g. not on the plan) stops the lookups."""
    out = {"status": "no_key", "market": [], "by_ticker": {}, "looked_up": 0, "skipped": 0}
    if client is None:
        out["skipped"] = len(tickers)
        return out
    start, end = news_window_utc(day)
    try:
        out["market"] = client.news_window(start, end, None, MARKET_NEWS)
        for ticker in tickers[:MAX_NEWS_TICKERS]:
            out["by_ticker"][ticker] = client.news_window(start, end, ticker, NEWS_PER_TICKER)
            out["looked_up"] += 1
    except (requests.RequestException, MassiveError) as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        out["status"] = f"error {code or type(exc).__name__}"
    else:
        out["status"] = "ok"
    out["skipped"] = len(tickers) - out["looked_up"]
    return out


# --------------------------------------------------------------------------- the diary


def breadth_row(data_dir: Path, day: dt.date) -> dict | None:
    path = Path(data_dir) / "data" / "breadth" / str(day.year) / f"{day.isoformat()}_eod.parquet"
    return pd.read_parquet(path).iloc[0].to_dict() if path.exists() else None


def _known(x) -> bool:
    return x is not None and not pd.isna(x)


def build_diary(
    data_dir: Path,
    cfg: Config,
    day: dt.date,
    *,
    macro: Mapping[str, set[dt.date]],
    client: MassiveClient | None,
    news: bool = True,
    backfilled: bool = False,
) -> pd.DataFrame:
    rows: list[dict] = []
    meta: dict[str, object] = {}

    # Bars: the day's, the previous session's, and the ETFs' history.
    today, source = day_bars(data_dir, day, client)
    prev_day = clock.previous_session(cfg.schedule, day)
    before = history.load_bars(data_dir, [prev_day])
    meta["bars_source"] = source
    sessions = clock.sessions_back(cfg.schedule, day, HISTORY_SESSIONS)
    hist = etf_history(data_dir, sessions[:-1], ALL_ETFS)
    todays_etf = today[today["ticker"].isin(ALL_ETFS)][["ticker", "high", "low", "close"]]
    if source in ("massive", "massive-live"):
        etf_source = source
    else:
        fallback = sectors_row(data_dir, day)
        todays_etf = fallback[fallback["ticker"].isin(ALL_ETFS)][["ticker", "close"]]
        etf_source = "sectors-file" if len(todays_etf) else "none"
    meta["etf_source"] = etf_source
    table, _ = etf_metrics(hist, todays_etf, sessions, ALL_ETFS)
    meta["etf_missing"] = len(ALL_ETFS) - len(table)

    for t in INDEX_ETFS:
        if t in table.index:
            rows.append({"kind": "market", "key": t, **table.loc[t].to_dict()})
    secs = table.loc[[t for t in ALL_ETFS if t in table.index and t not in INDEX_ETFS]]
    r1 = secs["chg_pct"].rank(ascending=False, method="min")
    r20 = secs["ret_20d_pct"].rank(ascending=False, method="min")
    for t, rec in secs.iterrows():
        rows.append(
            {
                "kind": "sector",
                "key": t,
                "rank": r1[t] if _known(r1[t]) else None,
                "rank_20d": r20[t] if _known(r20[t]) else None,
                **rec.to_dict(),
            }
        )

    # Breadth, heat, VIX: the day's own breadth row, copied.
    brow = breadth_row(data_dir, day)
    meta["breadth"] = "ok" if brow else "missing"
    vix_close = vix_chg = None
    if brow:
        for key, val in brow.items():
            if key in BREADTH_SKIP:
                continue
            if isinstance(val, str):
                rows.append({"kind": "breadth", "key": key, "text": val})
            elif _known(val):
                rows.append({"kind": "breadth", "key": key, "value": float(val)})
        vix_close = brow.get("vix_close")
        vix_chg = brow.get("vix_chg_pct")
    vix_ok = _known(vix_close)
    meta["vix"] = "ok" if vix_ok else "null"
    rows.append(
        {
            "kind": "vix",
            "key": "VIX",
            "close": float(vix_close) if vix_ok else None,
            "chg_pct": float(vix_chg) if vix_ok and _known(vix_chg) else None,
        }
    )
    count, count_day = latest_scan_count(data_dir, day)
    stats = heat.load(data_dir)
    band = heat.band(count, stats["bands"]) if stats and count is not None else None
    rows.append(
        {
            "kind": "heat",
            "key": "scan_count",
            "value": float(count) if count is not None else None,
            "text": f"sunday {count_day}" if count_day else None,
        }
    )
    rows.append({"kind": "heat", "key": "heat_band", "text": band})
    if brow and isinstance(brow.get("light"), str):
        rows.append({"kind": "heat", "key": "market_light", "text": brow["light"]})

    # Movers.
    up, down = movers(today, before)
    for kind, frame in (("mover_up", up), ("mover_down", down)):
        for rank, rec in enumerate(frame.to_dict("records"), 1):
            rows.append({"kind": kind, "key": rec.pop("ticker"), "rank": rank, **rec})

    # Our scans.
    cands = load_day_candidates(data_dir, day)
    rows += scan_rows(cands)
    meta["candidate_runs"] = 0 if cands.empty else int(cands["slot"].nunique())

    # News.
    pushed = pushed_tickers(cands)
    result = fetch_news(client if news else None, day, pushed)
    if not news:
        result["status"] = "disabled"
    meta.update(
        news=result["status"],
        news_backfilled=backfilled,
        news_tickers_looked_up=result["looked_up"],
        news_tickers_skipped=result["skipped"],
    )
    for item in result["market"]:
        rows.append({"kind": "news_market", **_news(item)})
    for ticker, items in result["by_ticker"].items():
        for item in items:
            rows.append({"kind": "news_ticker", "key": ticker, **_news(item)})

    # Calendar.
    flags = calendar_flags(cfg.schedule, day, macro)
    for name, on in flags.items():
        rows.append({"kind": "calendar", "key": name, "value": float(on)})
    n_earn = earnings_pushed(cands)
    rows.append(
        {
            "kind": "calendar",
            "key": "pushed_earnings_within_1_session",
            "value": float(n_earn) if n_earn is not None else None,
        }
    )

    for key, val in meta.items():
        if isinstance(val, bool | int | float):
            rows.append({"kind": "meta", "key": key, "value": float(val)})
        else:
            rows.append({"kind": "meta", "key": key, "text": str(val)})
    return to_frame(day, rows)


def _news(item: Mapping) -> dict:
    return {
        "title": item.get("title"),
        "publisher": item.get("publisher"),
        "published_utc": item.get("published_utc"),
        "url": item.get("url"),
        "tickers": ",".join(item.get("tickers") or []) or None,
    }


def to_frame(day: dt.date, rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    frame["session_date"] = day
    for col, dtype in COLUMNS.items():
        if col == "session_date":
            continue
        if dtype == "Int64":
            frame[col] = pd.to_numeric(frame[col]).astype("Int64")
        elif dtype == "float64":
            frame[col] = pd.to_numeric(frame[col]).astype("float64")
        else:
            frame[col] = frame[col].astype("string")
    return frame


# --------------------------------------------------------------------------- Markdown


def _f(x, spec: str = ".2f", suffix: str = "") -> str:
    return "n/a" if not _known(x) else f"{x:{spec}}{suffix}"


def render_md(day: dt.date, df: pd.DataFrame) -> str:
    """A short readable summary of the same facts: numbers only."""
    lines = [f"# Market diary {day.isoformat()}", ""]
    meta = {r.key: r for r in df[df["kind"] == "meta"].itertuples()}

    def txt(key):
        return getattr(meta.get(key), "text", None) if key in meta else None

    cal = df[df["kind"] == "calendar"]
    on = [
        r.key
        for r in cal.itertuples()
        if r.value == 1 and r.key != "pushed_earnings_within_1_session"
    ]
    lines.append("Calendar flags: " + (", ".join(on) if on else "none") + ".")
    earn = cal[cal["key"] == "pushed_earnings_within_1_session"]["value"]
    if len(earn) and _known(earn.iloc[0]):
        lines.append(f"Pushed tickers with earnings within 1 session: {int(earn.iloc[0])}.")
    lines.append("")

    lines += [
        "## Market",
        "",
        "| | close | 1d % | 20d % | vs SMA10 % | SMA20 % | SMA50 % | SMA200 % | 52w high % |",
    ]
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in df[df["kind"] == "market"].itertuples():
        lines.append(
            f"| {r.key} | {_f(r.close)} | {_f(r.chg_pct, '+.2f')} | {_f(r.ret_20d_pct, '+.2f')} "
            f"| {_f(r.dist_sma10_pct, '+.2f')} | {_f(r.dist_sma20_pct, '+.2f')} "
            f"| {_f(r.dist_sma50_pct, '+.2f')} | {_f(r.dist_sma200_pct, '+.2f')} "
            f"| {_f(r.dist_high52w_pct, '+.2f')} |"
        )
    vix = df[df["kind"] == "vix"].iloc[0]
    if _known(vix["close"]):
        lines += ["", f"VIX {_f(vix['close'], '.2f')}, change {_f(vix['chg_pct'], '+.2f', '%')}."]
    else:
        lines += ["", "VIX: not available for this day (null in the data)."]

    lines += [
        "",
        "## Sectors and themes",
        "",
        "| ETF | rank 1d | 1d % | 5d % | 20d % | rank 20d |",
        "|---|---|---|---|---|---|",
    ]
    for r in df[df["kind"] == "sector"].sort_values("rank").itertuples():
        lines.append(
            f"| {r.key} | {_f(r.rank, '.0f')} | {_f(r.chg_pct, '+.2f')} "
            f"| {_f(r.ret_5d_pct, '+.2f')} "
            f"| {_f(r.ret_20d_pct, '+.2f')} | {_f(r.rank_20d, '.0f')} |"
        )

    lines += ["", "## Breadth and heat", ""]
    b = {r.key: r for r in df[df["kind"] == "breadth"].itertuples()}
    if b:
        for key in (
            "up4",
            "down4",
            "mb_up",
            "mb_down",
            "ratio_5d",
            "ratio_10d",
            "up25q",
            "down25q",
            "pct_above_ma20",
            "pct_above_ma50",
        ):
            if key in b and _known(b[key].value):
                lines.append(f"- {key}: {_f(b[key].value, 'g')}")
    else:
        lines.append("- breadth row: not available")
    for r in df[df["kind"] == "heat"].itertuples():
        shown = _f(r.value, "g") if _known(r.value) else (r.text if _known(r.text) else "n/a")
        basis = f" ({r.text})" if _known(r.value) and _known(r.text) else ""
        lines.append(f"- {r.key}: {shown}{basis}")

    for kind, title in (("mover_up", "Top movers up"), ("mover_down", "Top movers down")):
        lines += ["", f"## {title} (price >= $5, >= $20M traded)", ""]
        sub = df[df["kind"] == kind]
        if sub.empty:
            lines.append("none (no bars)")
        for r in sub.itertuples():
            lines.append(
                f"{r.rank}. {r.key} {_f(r.chg_pct, '+.1f', '%')} at {_f(r.close)} "
                f"(${r.dollar_volume / 1e6:,.0f}M)"
            )

    lines += ["", "## Our scans", ""]
    sc = df[df["kind"] == "scan"]
    if sc.empty:
        lines.append("No scan runs saved for this session.")
    for r in sc.itertuples():
        lines.append(
            f"- {r.key}: {r.hits} hits, {r.pushed} pushed; grades A+ {r.grade_a_plus}, "
            f"A {r.grade_a}, "
            f"B {r.grade_b}, C {r.grade_c}, other {r.grade_other}"
        )

    lines += ["", "## News", ""]
    lines.append(
        f"Status: {txt('news')}; per-ticker lookups {int(meta['news_tickers_looked_up'].value)}, "
        f"skipped {int(meta['news_tickers_skipped'].value)}; "
        f"backfilled {bool(meta['news_backfilled'].value)}."
    )
    for kind, label in (("news_market", "Market"), ("news_ticker", "Pushed tickers")):
        sub = df[df["kind"] == kind]
        if len(sub):
            lines += ["", f"{label}:"]
            for r in sub.itertuples():
                tag = f"[{r.key}] " if kind == "news_ticker" else ""
                lines.append(f"- {r.published_utc} {tag}{r.title} ({r.publisher})")

    lines += ["", "## Sources", ""]
    for key in ("bars_source", "etf_source", "vix", "breadth", "news"):
        lines.append(f"- {key}: {txt(key)}")
    lines.append(f"- ETFs without data: {int(meta['etf_missing'].value)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- files, entry


def diary_paths(data_dir: Path, day: dt.date) -> tuple[Path, Path]:
    base = Path(data_dir) / "data" / "diary" / str(day.year)
    return base / f"{day.isoformat()}.parquet", base / f"{day.isoformat()}.md"


def write_diary(data_dir: Path, day: dt.date, df: pd.DataFrame, md: str, force: bool) -> bool:
    """Write the day once. False (nothing written) when it exists and `force` is off."""
    parquet, md_path = diary_paths(data_dir, day)
    if parquet.exists() and not force:
        return False
    parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp = parquet.with_name(parquet.name + ".tmp")
    df.to_parquet(tmp, **PARQUET_OPTIONS)
    tmp.replace(parquet)
    md_path.write_text(md, encoding="utf-8", newline="\n")
    return True


def _client(cfg: Config) -> MassiveClient | None:
    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        return None
    return MassiveClient(
        key, cfg.history["massive_base_url"], RateLimiter(cfg.history["calls_per_minute"])
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market diary: the day's context as data")
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    parser.add_argument("--date", type=dt.date.fromisoformat, help="a past session (YYYY-MM-DD)")
    parser.add_argument("--from", dest="start", type=dt.date.fromisoformat, help="backfill start")
    parser.add_argument("--to", dest="end", type=dt.date.fromisoformat, help="backfill end")
    parser.add_argument("--force", action="store_true", help="skip the guards, rewrite the day")
    parser.add_argument("--no-news", action="store_true", help="leave the news lookups out")
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")
    if bool(args.start) != bool(args.end):
        parser.error("--from and --to go together")
    if not args.force and timer.skip("diary", "Market diary"):
        return 0
    return run_guarded(lambda: _run(args), Path(args.data_dir) / "logs", "Market diary")


def _run(args: argparse.Namespace) -> int:
    cfg = load_config()
    now = dt.datetime.now(dt.UTC)
    today = clock.ny_time(cfg.schedule, now).date()
    if args.start:
        days = clock.sessions_between(cfg.schedule, args.start, args.end)
    elif args.date:
        days = [args.date]
    else:
        days = [clock.session_date(cfg.schedule, "eod", now)]
        if not args.force and days[0] != today:
            status(
                "Market diary: today's session hasn't closed or isn't a trading day, nothing to do"
            )
            return 0
    macro = load_macro()
    client = _client(cfg)
    written = skipped = 0
    for day in days:
        if not args.force and not _closed(cfg, day, now):
            status("Market diary: a session in the range has not closed, skipped")
            skipped += 1
            continue
        if diary_paths(args.data_dir, day)[0].exists() and not args.force:
            skipped += 1
            continue
        # Past days: news is looked up the same way, but flagged as built afterwards.
        df = build_diary(
            args.data_dir,
            cfg,
            day,
            macro=macro,
            client=client,
            news=not args.no_news,
            backfilled=day < today,
        )
        write_diary(args.data_dir, day, df, render_md(day, df), args.force)
        written += 1
        meta = df[df["kind"] == "meta"].set_index("key")
        status(
            f"Market diary: {len(df)} rows written, news {meta.loc['news', 'text']}, "
            f"vix {meta.loc['vix', 'text']}, bars {meta.loc['bars_source', 'text']}"
        )
    if not written:
        status(f"Market diary: nothing new to write ({skipped} already done or not closed)")
    else:
        status(f"Market diary: {written} day(s) written, {skipped} skipped")
    return 0


def _closed(cfg: Config, day: dt.date, now: dt.datetime) -> bool:
    return clock.is_session(cfg.schedule, day) and clock.session_close(cfg.schedule, day) <= now
