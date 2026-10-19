"""Entries and exits on minute bars for every strategy (Emil, 19 Oct 2026). Facts, not advice.

The question is which entry and which exit worked best, so an entry may only use what was
known at that moment. Picking EPs with the day's close and then "buying" them at 09:31 is
look-ahead: it skips every gap that faded. So the study runs in two steps.

1. `candidates` picks the stock-days to fetch minute bars for: per group a generous superset
   from daily bars, so everything the rule could have picked at entry time is in it.
2. The entry engine applies each strategy's rule at the entry time, on the minute bars.

| group    | stock-days fetched (superset)                      | rule at entry time             |
|----------|----------------------------------------------------|--------------------------------|
| gap      | opening gap >= 3 %                                 | after-hours / pre-market move, |
|          |                                                    | opening gap >= 10 %            |
| ep9m     | day high >= +4 % and day volume >= 1.5M            | +4 % and on pace for 9M        |
| pivot    | day high >= the pivot of the base the day before   | the minute it crosses          |
| next_day | the session after an end-of-day hit (EP-Day, EP9M, | known at the prior close       |
|          | MB up/down, parabolic long/short, BO trigger)      |                                |

Every group starts from the alert tier's prior-day facts: prior close >= $1 and 20-day average
volume >= 500K (both known before the open). 1-minute bars for the same-day groups, 5-minute
for next_day. One residual: a stock up 10 % pre-market that opens less than 3 % up is not
fetched; `residual` counts how many opened 3-5 % up, which bounds it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os import breakouts
from trading_os import history_metrics as hm
from trading_os.audit import ordinary_ticker
from trading_os.metrics import NEW_YORK

NEXT_DAY_STRATEGIES = (
    "ep_day",
    "ep9m",
    "mb_up",
    "mb_down",
    "parabolic_long",
    "parabolic_short",
    "breakout_trigger",
)


def daily(bars: pd.DataFrame, sessions: list) -> tuple[dict, pd.Index]:
    return hm.grids(bars[bars["ticker"].map(ordinary_ticker)], sessions)


def prior_facts(g: dict, floors: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Prior close, prior 20-day average volume and ADR $ (all known before the open), and
    whether the stock passes the alert tier's price and volume floors on them."""
    c, v, h, lo = g["close"], g["volume"], g["high"], g["low"]
    with np.errstate(divide="ignore", invalid="ignore"):
        prev_close = hm.shift(c, 1)
        avg20 = hm.shift(hm.rolling_mean(v, hm.AVG_DAYS), 1)
        adr_pct = hm.shift(hm.rolling_mean((h / lo - 1) * 100, hm.ADR_DAYS), 1)
        ok = (prev_close >= floors["price_min"]) & (avg20 >= floors["avg_volume_20d_min"])
    return {
        "prev_close": prev_close,
        "avg20": avg20,
        "adr_usd": adr_pct * prev_close / 100,
        "ok": ok,
    }


def _rows(t, j, sessions, tickers, facts: dict, group: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "group": group,
            "session_date": [sessions[i] for i in t],
            "ticker": np.asarray(tickers)[j],
            "prev_close": facts["prev_close"][t, j],
            "avg_volume_20d": facts["avg20"][t, j],
            "adr_usd": facts["adr_usd"][t, j],
        }
    )


def candidates(
    bars: pd.DataFrame, sessions: list, cfg, next_day_hits: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Every stock-day to fetch, with the facts known before it."""
    conf = cfg.intraday_study
    g, tickers = daily(bars, sessions)
    facts = prior_facts(g, cfg.universe["alert"])
    with np.errstate(divide="ignore", invalid="ignore"):
        gap = (g["open"] / facts["prev_close"] - 1) * 100
        up = (g["high"] / facts["prev_close"] - 1) * 100
        gap_mask = facts["ok"] & (gap >= conf["gap_superset_pct"])
        ep9m_mask = (
            facts["ok"]
            & (up >= cfg.scans["ep9m"]["chg_min_pct"])
            & (g["volume"] >= conf["ep9m_volume_superset"])
        )
    frames = [
        _rows(*np.nonzero(gap_mask), sessions, tickers, facts, "gap").assign(gap_pct=gap[gap_mask]),
        _rows(*np.nonzero(ep9m_mask), sessions, tickers, facts, "ep9m"),
        pivot_candidates(g, tickers, sessions, cfg.breakout, facts),
    ]
    if next_day_hits is not None and len(next_day_hits):
        frames.append(next_day_candidates(next_day_hits, sessions, tickers, facts))
    out = pd.concat([f for f in frames if len(f)], ignore_index=True)
    return out.sort_values(["group", "session_date", "ticker"]).reset_index(drop=True)


def pivot_candidates(g, tickers, sessions, params, facts) -> pd.DataFrame:
    """Days whose high reached the pivot of the base that ended the session before.

    The pivot is the highest high of the base window, so a numpy pre-filter (high >= the
    prior `base_max_days` high) finds the few stock-days worth the full base analysis."""
    high, low, close, volume = (g[f] for f in ("high", "low", "close", "volume"))
    window = params["base_max_days"]
    with np.errstate(invalid="ignore"):
        prior_high = hm.shift(hm.rolling_extreme(high, window, "max"), 1)
        reach = facts["ok"] & (high >= prior_high)
    ind = breakouts.indicators(high, low, close, volume)
    rows = []
    for j in np.unique(np.nonzero(reach)[1]):
        col = {k: v[:, j] for k, v in ind.items()}
        args = (high[:, j], low[:, j], close[:, j], volume[:, j], col, params)
        for t in np.nonzero(reach[:, j])[0]:
            base = breakouts.analyze_base(int(t) - 1, *args)
            if base is None or not high[t, j] >= base.pivot:
                continue
            rows.append(
                {
                    "group": "pivot",
                    "session_date": sessions[t],
                    "ticker": tickers[j],
                    "prev_close": facts["prev_close"][t, j],
                    "avg_volume_20d": facts["avg20"][t, j],
                    "adr_usd": facts["adr_usd"][t, j],
                    "pivot": base.pivot,
                    "order_stop": base.order_stop,
                    "base_adr_usd": base.adr_usd,
                    "b1": base.b1,
                    "b2": base.b2,
                    "b3": base.b3,
                    "b4": base.b4,
                }
            )
    return pd.DataFrame(rows)


def next_day_candidates(hits: pd.DataFrame, sessions, tickers, facts) -> pd.DataFrame:
    """The session after each end-of-day hit; the signal day's bar is known by then."""
    index = {d: i for i, d in enumerate(sessions)}
    col = {t: j for j, t in enumerate(tickers)}
    rows = []
    for rec in hits.to_dict("records"):
        t, j = index.get(rec["session_date"]), col.get(rec["ticker"])
        if t is None or j is None or t + 1 >= len(sessions):
            continue
        rows.append(
            {
                "group": "next_day",
                "session_date": sessions[t + 1],
                "ticker": rec["ticker"],
                "prev_close": facts["prev_close"][t + 1, j],
                "avg_volume_20d": facts["avg20"][t + 1, j],
                "adr_usd": facts["adr_usd"][t + 1, j],
                "strategy": rec["strategy"],
                "signal_date": rec["session_date"],
                "signal_high": rec.get("high"),
                "signal_low": rec.get("low"),
            }
        )
    return pd.DataFrame(rows)


def next_day_hits(data_dir) -> pd.DataFrame:
    """Alert-tier end-of-day hits from the strategy history and the EP history."""
    from trading_os import strategy_history
    from trading_os.ep_enrich import latest_study

    hits = strategy_history.load(data_dir)
    keep = ["strategy", "session_date", "ticker", "high", "low"]
    frames = []
    if len(hits):
        hits = hits[hits["strategy"].isin(NEXT_DAY_STRATEGIES)]
        frames.append(hits[[c for c in keep if c in hits]])
    study = latest_study(data_dir)
    if len(study):
        ep = study[study["is_ep_day"] & (study["tier"] == "alert")]
        frames.append(ep[["session_date", "ticker"]].assign(strategy="ep_day"))
    if not frames:
        return pd.DataFrame(columns=keep)
    out = pd.concat(frames, ignore_index=True)
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out


def fetch_windows(cands: pd.DataFrame, sessions: list) -> pd.DataFrame:
    """Up to three requests per entry day, each stock-day fetched once:

    - `evening`: 1-minute bars from the prior 16:00 ET (after-hours entries), gap stocks;
    - `day`: 1-minute bars from 04:00 ET, the other same-day stocks;
    - `day5`: 5-minute bars from 04:00 ET, next-day stocks not already in the two above
      (a 1-minute day resamples to 5 minutes)."""
    index = {d: i for i, d in enumerate(sessions)}
    rows = []
    for day, part in cands.groupby("session_date"):
        i = index[day]
        groups = part.groupby("group")["ticker"].agg(set).to_dict()
        evening = groups.get("gap", set())
        same_day = (groups.get("ep9m", set()) | groups.get("pivot", set())) - evening
        later = groups.get("next_day", set()) - evening - same_day
        prior = sessions[i - 1] if i else day
        for kind, symbols, start, timeframe in (
            ("evening", evening, pd.Timestamp(f"{prior} 16:00", tz=NEW_YORK), "1Min"),
            ("day", same_day, pd.Timestamp(f"{day} 04:00", tz=NEW_YORK), "1Min"),
            ("day5", later, pd.Timestamp(f"{day} 04:00", tz=NEW_YORK), "5Min"),
        ):
            if not symbols:
                continue
            end = pd.Timestamp(f"{day} 16:00", tz=NEW_YORK)
            rows.append(
                {
                    "kind": kind,
                    "timeframe": timeframe,
                    "session_date": day,
                    "month": f"{day:%Y-%m}",
                    "tickers": sorted(symbols),
                    "start": start.tz_convert("UTC").to_pydatetime(),
                    "end": end.tz_convert("UTC").to_pydatetime(),
                }
            )
    return pd.DataFrame(rows)


BATCH = {"1Min": 50, "5Min": 200}  # symbols per request
ASKED = ".asked.parquet"  # suffix of the per-file list of stock-days asked for
BAR_COLUMNS = ["ticker", "ts", "open", "high", "low", "close", "volume", "vwap"]


def asked(out_dir) -> set[tuple]:
    """(session_date, ticker, kind) already asked for, from every `*.asked.parquet`."""
    from pathlib import Path

    files = sorted(Path(out_dir).glob(f"*{ASKED}"))
    if not files:
        return set()
    seen = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    seen["session_date"] = pd.to_datetime(seen["session_date"]).dt.date
    return set(seen[["session_date", "ticker", "kind"]].itertuples(index=False, name=None))


def _compact(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars[BAR_COLUMNS].copy()
    for c in ("open", "high", "low", "close", "vwap"):
        out[c] = out[c].astype("float32")
    out["volume"] = out["volume"].astype("int64")
    return out


def fetch(client, windows: pd.DataFrame, out_dir, deadline: float | None = None) -> dict:
    """Bars for the stock-days in `windows` not asked for before, newest month first.

    Each run adds `YYYY-MM_<run>.parquet` (the bars) and `YYYY-MM_<run>.asked.parquet` (the
    stock-days asked for, so one with no bars is not asked again) per month it touched.
    Stops between months once `deadline` (time.time()) has passed. Counts only in the log."""
    import time
    from pathlib import Path

    from trading_os.logsafe import status
    from trading_os.store import PARQUET_OPTIONS

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    have = asked(out_dir)
    run = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    written: dict[str, int] = {}
    for month, part in sorted(windows.groupby("month"), reverse=True):
        if deadline is not None and time.time() > deadline:
            status("Intraday minutes: stopped at the deadline, the next run resumes")
            break
        frames, done = [], []
        for row in part.itertuples(index=False):
            todo = [t for t in row.tickers if (row.session_date, t, row.kind) not in have]
            size = BATCH[row.timeframe]
            for k in range(0, len(todo), size):
                bars = client.bars(todo[k : k + size], row.timeframe, row.start, row.end)
                if len(bars):
                    frames.append(
                        _compact(bars).assign(session_date=row.session_date, kind=row.kind)
                    )
            done += [(row.session_date, t, row.kind) for t in todo]
        if not done:
            continue
        stem, n = f"{month}_{run}", 1
        while (out_dir / f"{stem}{ASKED}").exists():  # two runs in one second (tests)
            stem, n = f"{month}_{run}{n:02d}", n + 1
        month_bars = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=[*BAR_COLUMNS, "session_date", "kind"])
        )
        for name, frame in (
            (f"{stem}.parquet", month_bars),
            (f"{stem}{ASKED}", pd.DataFrame(done, columns=["session_date", "ticker", "kind"])),
        ):
            tmp = out_dir / (name + ".tmp")
            frame.to_parquet(tmp, **PARQUET_OPTIONS)
            tmp.replace(out_dir / name)
        written[month] = len(done)
        status(f"Intraday minutes: {month}: {len(done)} stock-days, {len(month_bars)} bars")
    status(f"Intraday minutes: {len(written)} months, {sum(written.values())} stock-days added")
    return written


def load_minutes(out_dir, month: str | None = None) -> pd.DataFrame:
    """Every bar file in `out_dir` (one month with `month`), deduplicated."""
    from pathlib import Path

    pattern = f"{month}_*.parquet" if month else "*.parquet"
    files = [f for f in sorted(Path(out_dir).glob(pattern)) if not f.name.endswith(ASKED)]
    if not files:
        return pd.DataFrame(columns=[*BAR_COLUMNS, "session_date", "kind"])
    bars = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    return bars.drop_duplicates(["ticker", "ts", "kind"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    from trading_os.logsafe import run_guarded

    return run_guarded(lambda: _main(argv), None, "Intraday study")


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import datetime as dt
    import os
    import time
    from pathlib import Path

    from trading_os import history
    from trading_os.alpaca import AlpacaClient
    from trading_os.config import load_config
    from trading_os.logsafe import status

    parser = argparse.ArgumentParser(description="Minute-bar entry and exit study")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--fetch", type=Path, help="folder of the minute files to add to")
    parser.add_argument("--minutes", type=int, default=0, help="stop fetching after N minutes")
    args = parser.parse_args(argv)
    cfg = load_config()
    files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
    sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
    bars = history.load_bars(args.data_dir, sessions)
    cands = candidates(bars, sessions, cfg, next_day_hits(args.data_dir))
    status(f"Intraday study: {cands.groupby('group').size().to_dict()} candidate stock-days")
    if args.fetch:
        key = os.environ.get("ALPACA_API_KEY_ID", "")
        secret = os.environ.get("ALPACA_API_SECRET_KEY", "")
        if not key or not secret:
            status("Intraday study: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set")
            return 1
        deadline = time.time() + args.minutes * 60 if args.minutes else None
        fetch(AlpacaClient(key, secret), fetch_windows(cands, sessions), args.fetch, deadline)
    return 0
