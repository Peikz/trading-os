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
| vcp      | day high >= the pivot of a VCP (Minervini) ended   | the minute it crosses          |
|          | the day before, on a Trend Template stock          |                                |
| luk      | a leader whose low reached yesterday's EMA 9/21 or | the touch, then the turn green |
|          | AVWAP zone (Martin Luk, `luk.py`)                  |                                |
| next_day | the session after an end-of-day hit (EP-Day, EP9M, | known at the prior close       |
|          | MB up/down, parabolic long/short, BO trigger,     |                                |
|          | Luk setups)                                        |                                |

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

from trading_os import breakouts, luk, minervini
from trading_os import history_metrics as hm
from trading_os.audit import ordinary_ticker
from trading_os.metrics import NEW_YORK

SAME_DAY = ("ep9m", "pivot", "vcp", "luk")  # 1-minute bars of the session
NEXT_DAY_STRATEGIES = (
    "ep_day",
    "ep9m",
    "mb_up",
    "mb_down",
    "parabolic_long",
    "parabolic_short",
    "breakout_trigger",
    *luk.STRATEGIES,
    "vcp_breakout",
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
    g, tickers = daily(bars, sessions)
    return from_grids(g, tickers, sessions, cfg, next_day_hits)


def from_grids(g, tickers, sessions, cfg, next_day_hits=None) -> pd.DataFrame:
    conf = cfg.intraday_study
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
        luk_candidates(g, tickers, sessions, cfg.luk, facts),
        vcp_candidates(g, tickers, sessions, cfg.minervini, facts),
    ]
    if next_day_hits is not None and len(next_day_hits):
        frames.append(next_day_candidates(next_day_hits, sessions, tickers, facts, g))
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


def luk_candidates(g, tickers, sessions, conf, facts) -> pd.DataFrame:
    """Days a leader (EMA 9 > EMA 21, both yesterday) traded down to within `touch_adr` ADR of
    the highest of yesterday's EMA 9, EMA 21 and AVWAP: every day a Luk pullback or AVWAP
    flush could have been bought during the session."""
    ind = luk.indicators(g, conf)
    keys = ("leader", "lead", "mid_rising", "ema_fast", "ema_mid", "avwap", "base_days")
    y = {k: hm.shift(ind[k].astype(float), 1) for k in keys}
    zone = np.fmax(np.fmax(y["ema_fast"], y["ema_mid"]), y["avwap"])
    with np.errstate(invalid="ignore"):
        mask = (
            facts["ok"]
            & (y["leader"] == 1)
            & (y["ema_fast"] > y["ema_mid"])
            & (g["low"] <= zone + conf["touch_adr"] * facts["adr_usd"])
        )
    t, j = np.nonzero(mask)
    out = _rows(t, j, sessions, tickers, facts, "luk")
    for k in ("ema_fast", "ema_mid", "avwap", "base_days"):
        out[k] = y[k][t, j]
    out["lead"], out["mid_rising"] = y["lead"][t, j] == 1, y["mid_rising"][t, j] == 1
    return out


def vcp_candidates(g, tickers, sessions, conf, facts) -> pd.DataFrame:
    """VCP trigger days (Minervini): the day's high reached the pivot of a VCP that ended
    the session before, on a Trend Template stock."""
    found = minervini.find(g, tickers, sessions, conf, minervini.rs_rating(g["close"]))
    found = found[found["strategy"] == "vcp_breakout"]
    if found.empty:
        return pd.DataFrame()
    index = {d: i for i, d in enumerate(sessions)}
    col = {t: j for j, t in enumerate(tickers)}
    t = found["session_date"].map(index).to_numpy()
    j = found["ticker"].map(col).to_numpy()
    keep = facts["ok"][t, j]
    out = _rows(t[keep], j[keep], sessions, tickers, facts, "vcp")
    for c in ("pivot", "last_low", "contractions", "last_depth_pct", "rs_rating"):
        out[c] = found[c].to_numpy()[keep]
    out["setup"] = "vcp_breakout"
    return out


def next_day_candidates(hits: pd.DataFrame, sessions, tickers, facts, g) -> pd.DataFrame:
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
                "signal_high": g["high"][t, j],
                "signal_low": g["low"][t, j],
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
        same_day = set().union(*(groups.get(k, set()) for k in SAME_DAY)) - evening
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


KIND_ORDER = {"evening": 0, "day": 1, "day5": 2}  # a wider fetch wins for the same stock-day


def stock_days(month_bars: pd.DataFrame) -> dict[tuple, Any]:
    """(session_date, ticker) -> `intraday_entries.Bars`, minutes relative to that session's
    midnight in New York (the evening before is negative)."""
    from trading_os.intraday_entries import Bars

    if month_bars.empty:
        return {}
    df = month_bars.assign(prio=month_bars["kind"].map(KIND_ORDER))
    df = df[df["prio"] == df.groupby(["session_date", "ticker"])["prio"].transform("min")]
    ny = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(NEW_YORK)
    before = (pd.to_datetime(df["session_date"]) - pd.to_datetime(ny.dt.date)).dt.days
    minute = (ny.dt.hour * 60 + ny.dt.minute) - 1440 * before
    df = df.assign(minute=minute.to_numpy()).sort_values(["session_date", "ticker", "minute"])
    cols = {c: df[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close", "volume")}
    vwap = df["vwap"].to_numpy(dtype=float)
    vwap = np.where(np.isnan(vwap), cols["close"], vwap)
    m = df["minute"].to_numpy()
    out = {}
    for key, rows in df.groupby(["session_date", "ticker"], sort=False).indices.items():
        sl = slice(int(rows[0]), int(rows[-1]) + 1)  # sorted, so each stock-day is contiguous
        out[key] = Bars(
            m[sl],
            cols["open"][sl],
            cols["high"][sl],
            cols["low"][sl],
            cols["close"][sl],
            cols["volume"][sl],
            vwap[sl],
        )
    return out


def params(cfg) -> dict[str, Any]:
    """Every threshold the entry rules read, from the live scans' own config."""
    return {
        "gap_min_pct": cfg.scans["ep_day"]["gap_min_pct"],
        "ah_change_min_pct": cfg.scans["ep_ah"]["ah_change_min_pct"],
        "ah_volume_min": cfg.scans["ep_ah"]["ah_volume_min"],
        "pm_change_min_pct": cfg.scans["ep_pm"]["pm_change_min_pct"],
        "pm_volume_min": cfg.scans["ep_pm"]["pm_volume_min"],
        "ep9m_chg_min_pct": cfg.scans["ep9m_pace"]["chg_min_pct"],
        "ep9m_volume_min": cfg.scans["ep9m_pace"]["volume_min"],
        "pace_fraction": dict(cfg.intraday_study["pace_fraction"]),
        "touch_adr": cfg.luk["touch_adr"],
        "flush_adr": cfg.luk["flush_adr"],
        "base_min_days": cfg.luk["base_min_days"],
        "min_stop_adr": cfg.sizing["min_stop_adr"],
        "wide_stop_adr": cfg.intraday_study["wide_stop_adr"],
        "vcp_stop_max_pct": cfg.minervini["stop_max_pct"],
    }


def trail_lines(g: dict) -> dict[str, np.ndarray]:
    close = g["close"]
    return {
        "ma10": hm.rolling_mean(close, 10),
        "ma20": hm.rolling_mean(close, 20),
        "ema9": hm.ema(close, 9),
        "ema21": hm.ema(close, 21),
    }


KEEP = ("group", "session_date", "ticker", "prev_close", "adr_usd", "signal_date", "rs_rating")


def study_month(month_bars, cands, g, lines, sessions, tickers, cfg) -> pd.DataFrame:
    """Every entry x stop rule for one month's candidates, with every exit."""
    from trading_os import intraday_entries as ie
    from trading_os import intraday_exits

    lookup = stock_days(month_bars)
    p = params(cfg)
    rows = []
    for rec in cands.to_dict("records"):
        b = lookup.get((rec["session_date"], rec["ticker"]))
        if b is None or not rec.get("adr_usd", 0) > 0:
            continue
        b = ie.for_group(b, rec["group"])
        for entry in ie.RULES[rec["group"]](b, rec, p):
            stopped, price = ie.entry_day_exit(b, entry)
            keep = {k: rec.get(k) for k in KEEP}
            rows.append(keep | entry | {"stopped0": stopped, "exit0": price})
    if not rows:
        return pd.DataFrame()
    trades = pd.DataFrame(rows)
    index = {d: i for i, d in enumerate(sessions)}
    col = {t: j for j, t in enumerate(tickers)}
    t = trades["session_date"].map(index)
    j = trades["ticker"].map(col)
    trades = trades[t.notna() & j.notna()].reset_index(drop=True)
    t, j = t.dropna().astype(int).to_numpy(), j.dropna().astype(int).to_numpy()
    results = intraday_exits.run(
        g,
        lines,
        t,
        j,
        trades["price"].to_numpy(dtype=float),
        trades["stop"].to_numpy(dtype=float),
        trades["side"].to_numpy(dtype=int),
        (trades["stopped0"].to_numpy(dtype=bool), trades["exit0"].to_numpy(dtype=float)),
        cfg.exits,
    )
    trades = trades.assign(**results)
    trades["risk_adr"] = (trades["price"] - trades["stop"]).abs() / trades["adr_usd"]
    return trades.drop(columns=["start", "exit0", "stopped0"])


def exit_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("r_")]


def summary(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Per strategy, entry and stop rule (and `by`): trades, then for every exit the win rate
    and mean R (capped at 20 so one runner can't carry a group)."""
    keys = ["strategy", "entry", "stop_rule", *(by or [])]
    rows = []
    for key, part in df.groupby(keys, dropna=False, observed=True):
        row = dict(zip(keys, key if isinstance(key, tuple) else (key,), strict=True))
        row["trades"] = len(part)
        row["stopped_same_day%"] = part["stopped_0d"].astype(float).mean() * 100
        for column in exit_columns(part):
            r = part[column].dropna()
            name = column[2:]
            row[f"win_{name}%"] = (r > 0).mean() * 100 if len(r) else np.nan
            row[f"R_{name}"] = r.clip(upper=20).mean() if len(r) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def best(table: pd.DataFrame, min_trades: int = 50, top: int = 3) -> pd.DataFrame:
    """Per strategy: the `top` entry x stop x exit combinations by mean R (at least
    `min_trades` trades), with their win rate."""
    rows = []
    for _, part in table[table["trades"] >= min_trades].groupby("strategy"):
        found = []
        for rec in part.to_dict("records"):
            for column in (c for c in rec if c.startswith("R_")):
                if rec[column] == rec[column]:
                    name = column[2:]
                    found.append(
                        {
                            "strategy": rec["strategy"],
                            "entry": rec["entry"],
                            "stop_rule": rec["stop_rule"],
                            "exit": name,
                            "trades": rec["trades"],
                            "mean_R": rec[column],
                            "win%": rec.get(f"win_{name}%"),
                        }
                    )
        rows += sorted(found, key=lambda r: -r["mean_R"])[:top]
    return pd.DataFrame(rows)


def write_results(df: pd.DataFrame, folder) -> None:
    """One file per strategy (floats as float32)."""
    from pathlib import Path

    from trading_os.store import PARQUET_OPTIONS

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, part in df.groupby("strategy"):
        slim = part.copy()
        for column in slim.select_dtypes("float64").columns:
            slim[column] = slim[column].astype("float32")
        slim.to_parquet(folder / f"{name}.parquet", **PARQUET_OPTIONS)


def load_results(data_dir) -> pd.DataFrame:
    """The newest build, every strategy."""
    from pathlib import Path

    root = Path(data_dir) / "data" / "intraday_study"
    builds = sorted(p for p in root.glob("*") if p.is_dir())
    if not builds:
        return pd.DataFrame()
    out = pd.concat([pd.read_parquet(f) for f in sorted(builds[-1].glob("*.parquet"))])
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out.reset_index(drop=True)


def run_study(g, tickers, sessions, cands, minutes_dir, cfg) -> pd.DataFrame:
    """Month by month over the minute files in `minutes_dir`."""
    from pathlib import Path

    lines = trail_lines(g)
    files = Path(minutes_dir).glob("*.parquet")
    months = sorted({f.name[:7] for f in files if not f.name.endswith(ASKED)})
    month_of = cands["session_date"].map(lambda d: f"{d:%Y-%m}")
    frames = []
    for month in months:
        part = cands[month_of == month]
        if part.empty:
            continue
        bars = load_minutes(minutes_dir, month)
        found = study_month(bars, part, g, lines, sessions, tickers, cfg)
        if len(found):
            frames.append(found)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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
    parser.add_argument("--run", type=Path, help="folder of downloaded minute files: run it")
    args = parser.parse_args(argv)
    cfg = load_config()
    files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
    sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
    g, tickers = daily(history.load_bars(args.data_dir, sessions), sessions)
    cands = from_grids(g, tickers, sessions, cfg, next_day_hits(args.data_dir))
    status(f"Intraday study: {cands.groupby('group').size().to_dict()} candidate stock-days")
    if args.fetch:
        key = os.environ.get("ALPACA_API_KEY_ID", "")
        secret = os.environ.get("ALPACA_API_SECRET_KEY", "")
        if not key or not secret:
            status("Intraday study: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set")
            return 1
        deadline = time.time() + args.minutes * 60 if args.minutes else None
        fetch(AlpacaClient(key, secret), fetch_windows(cands, sessions), args.fetch, deadline)
    if args.run:
        trades = run_study(g, tickers, sessions, cands, args.run, cfg)
        folder = args.data_dir / "data" / "intraday_study" / sessions[-1].isoformat()
        write_results(trades, folder)
        counts = trades.groupby("strategy").size().to_dict() if len(trades) else {}
        status(f"Intraday study: {len(trades)} trades {counts}, saved")
    return 0
