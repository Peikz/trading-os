"""Strategy history (Emil, 19 Oct 2026): every scan's hits over the Massive bars, and what
happened after. The live scan functions run unchanged on metrics rebuilt for each session,
so the study tests exactly the rules that send the pushes.

Strategies, the side they're measured on, and their stop (facts, not trade advice):

| strategy           | side  | entry                      | stop                                   |
|--------------------|-------|----------------------------|----------------------------------------|
| ep9m               | long  | signal close               | day low within the EP ADR bounds       |
| mb_up              | long  | signal close               | day low (min distance 0.25 ADR)        |
| mb_down            | short | signal close               | day high (min distance 0.25 ADR)       |
| parabolic_short    | short | signal close               | day high (min distance 0.25 ADR)       |
| parabolic_long     | long  | signal close               | day low (min distance 0.25 ADR)        |
| breakout_trigger   | long  | signal close (B5)          | order stop (§6.4)                      |
| breakout_watch     | long  | pivot, when crossed within 10 sessions | order stop                 |
| qm_gainers (Fri)   | long  | Friday close               | none: returns only                     |
| tight_bases (Fri)  | long  | Friday close               | none: returns only                     |

EP-Day has its own, richer study (`ep_history`). Alert tier only (§4), except the market cap
floor, which has no history: parabolic short's large-cap rule uses today's market cap where
known (else the small-cap rule). Outcomes after 1, 3, 5, 21, 63, 126 and 252 sessions, plus a
trailing exit at the first close through the 10-day / 20-day MA.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os import audit, enrich, ep_history, exits, sizing
from trading_os import history_metrics as hm
from trading_os.scans import REGISTRY

HORIZONS = (1, 3, 5, 21, 63, 126, 252)
TRAILS = (10, 20)
CHUNK = 1000  # tickers per metrics pass (memory)
WATCH_TRIGGER_DAYS = 10
SIDES = {
    "ep9m": 1,
    "mb_up": 1,
    "mb_down": -1,
    "parabolic_short": -1,
    "parabolic_long": 1,
    "breakout_trigger": 1,
    "breakout_watch": 1,
    "qm_gainers": 1,
    "tight_bases": 1,
}
DAILY = ("ep9m", "mb_up", "mb_down", "parabolic_short", "parabolic_long")
WEEKLY = ("qm_gainers", "tight_bases")


def _first(mask: np.ndarray) -> int | None:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if len(idx) else None


def outcomes(
    o, h, lo, c, mas: Mapping[int, np.ndarray], t: int, entry: float, stop: float | None, side: int
) -> dict[str, Any]:
    """Horizons and trailing exits for one hit, long (side 1) or short (side -1).

    `pnl` is the side's profit in percent; R uses `stop` (a hit fills at the stop, or at the
    open on a gap through it); no stop = returns only. A missing bar leaves it unknown.
    """
    row: dict[str, Any] = {}
    n = len(c)
    risk = (entry - stop) * side if stop is not None and not np.isnan(stop) else np.nan
    has_stop = risk > 0
    for horizon in HORIZONS:
        end = t + horizon
        seg = slice(t + 1, end + 1)
        keys = [f"{k}_{horizon}d" for k in ("pnl", "best", "worst", "r", "stop_hit")]
        if end >= n or np.isnan(c[end]) or np.isnan(lo[seg]).any():
            row.update(dict.fromkeys(keys, np.nan))
            continue
        favourable = h[seg].max() if side > 0 else lo[seg].min()
        adverse = lo[seg].min() if side > 0 else h[seg].max()
        hit = None
        if has_stop:
            hit = _first(lo[seg] <= stop) if side > 0 else _first(h[seg] >= stop)
        if has_stop:
            if hit is not None:
                d = t + 1 + hit
                gap = o[d] if not np.isnan(o[d]) else stop
                exit_price = min(gap, stop) if side > 0 else max(gap, stop)
            else:
                exit_price = c[end]
            r = (exit_price - entry) * side / risk
        else:
            r = np.nan
        row.update(
            {
                f"pnl_{horizon}d": (c[end] / entry - 1) * 100 * side,
                f"best_{horizon}d": (favourable / entry - 1) * 100 * side,
                f"worst_{horizon}d": (adverse / entry - 1) * 100 * side,
                f"r_{horizon}d": r,
                f"stop_hit_{horizon}d": (hit is not None) if has_stop else np.nan,
            }
        )
    last = min(n - 1, t + max(HORIZONS))
    seg = slice(t + 1, last + 1)
    for window in TRAILS:
        empty = {f"r_trail_ma{window}": np.nan, f"pnl_trail_ma{window}": np.nan}
        empty[f"days_trail_ma{window}"] = np.nan
        if last == t:
            row |= empty
            continue
        missing = np.isnan(lo[seg])
        stopped = np.zeros(last - t, dtype=bool)
        if has_stop:
            stopped = lo[seg] <= stop if side > 0 else h[seg] >= stop
        with np.errstate(invalid="ignore"):
            through = c[seg] < mas[window][seg] if side > 0 else c[seg] > mas[window][seg]
        first = _first(missing | stopped | through)
        if first is not None and missing[first]:
            row |= empty
            continue
        d = t + 1 + first if first is not None else last
        if first is not None and stopped[first]:
            gap = o[d] if not np.isnan(o[d]) else stop
            exit_price = min(gap, stop) if side > 0 else max(gap, stop)
        else:
            exit_price = c[d]
        row |= {
            f"pnl_trail_ma{window}": (exit_price / entry - 1) * 100 * side,
            f"r_trail_ma{window}": (exit_price - entry) * side / risk if has_stop else np.nan,
            f"days_trail_ma{window}": float(d - t),
        }
    return row


def _stop(row: Mapping[str, Any], strategy: str, rules) -> float | None:
    adr = row.get("adr20_usd", np.nan)
    floor = rules["min_stop_adr"] * adr if adr == adr else 0.0
    if strategy == "ep9m":
        return sizing.plan(row, "ep_day", rules)[1]
    if strategy in ("mb_up", "parabolic_long"):
        return min(row["low"], row["close"] - floor)
    if strategy in ("mb_down", "parabolic_short"):
        return max(row["high"], row["close"] + floor)
    if strategy in ("breakout_trigger", "breakout_watch"):
        return row.get("order_stop")
    return None


def _alert(frame: pd.DataFrame, cfg) -> pd.Series:
    t = cfg.universe["alert"]
    return (
        (frame["close"] >= t["price_min"])
        & (frame["avg_volume_20d"] >= t["avg_volume_20d_min"])
        & (frame["dollar_volume"] >= t["signal_dollar_volume_min"])
    )


def _frame(g: dict, tickers: pd.Index, sessions: list, cfg, caps: Mapping[str, float]):
    """Every (ticker, session) with the columns the live scans read (hist_* included)."""
    metrics = hm.compute_from_grids(g, tickers, sessions, windows=enrich.scan_windows(cfg))
    for column in enrich.HIST_COLUMNS:
        metrics[f"hist_{column}"] = metrics[column]
    h = g["high"]
    with np.errstate(invalid="ignore"):
        windows = np.lib.stride_tricks.sliding_window_view(
            np.vstack([np.full((251, h.shape[1]), np.nan), h]), 252, axis=0
        )
        counts = (~np.isnan(windows)).sum(axis=-1)
        high = np.where(
            counts >= 126, np.nanmax(np.where(np.isnan(windows), -np.inf, windows), axis=-1), np.nan
        )
    pos = {s: i for i, s in enumerate(sessions)}
    col = {t: j for j, t in enumerate(tickers)}
    rows = metrics["session_date"].map(pos).to_numpy()
    cols = metrics["ticker"].map(col).to_numpy()
    metrics["high_52w"] = high[rows, cols]
    metrics["pct_from_52w_high"] = (metrics["close"] / metrics["high_52w"] - 1) * 100
    for w in hm.MA_WINDOWS:
        metrics[f"above_ma{w}"] = metrics["close"] > metrics[f"ma{w}"]
    metrics["market_cap"] = metrics["ticker"].map(caps).fillna(0.0)
    metrics["tier"] = np.where(_alert(metrics, cfg), "alert", "log")
    return metrics


def _fridays(sessions: list) -> set:
    """The last session of each week."""
    out, by_week = set(), {}
    for s in sessions:
        by_week[s.isocalendar()[:2]] = s
    out.update(by_week.values())
    return out


FEATURES = [
    "close",
    "open",
    "high",
    "low",
    "volume",
    "chg_pct",
    "gap_pct",
    "rvol50",
    "dollar_volume",
    "close_loc",
    "adr20_pct",
    "adr20_usd",
    "ret_22",
    "ret_63",
    "ret_126",
    "pct_from_52w_high",
    "above_ma50",
    "above_ma200",
    "dist_ma10_adr",
    "gain_max_pct",
    "drop_max_pct",
    "consec_up",
    "consec_down",
]


def find(bars: pd.DataFrame, sessions: list, cfg, caps: Mapping[str, float]) -> pd.DataFrame:
    """All alert-tier hits of every strategy with features, the market and outcomes."""
    stocks = bars[bars["ticker"].map(audit.ordinary_ticker)]
    g, tickers = hm.grids(stocks, sessions)
    market = ep_history.market_context(g, tickers, cfg).to_dict("records")
    col = {t: j for j, t in enumerate(tickers)}
    pos = {s: i for i, s in enumerate(sessions)}
    fridays = _fridays(sessions)
    hits, weekly_rows = [], []
    for start in range(0, len(tickers), CHUNK):
        part = tickers[start : start + CHUNK]
        sub = {k: v[:, start : start + CHUNK] for k, v in g.items()}
        frame = _frame(sub, part, sessions, cfg, caps)
        alert = frame[frame["tier"] == "alert"]
        for name in DAILY:
            found = REGISTRY[name](alert, cfg.scans[name])
            hits.append(found.assign(strategy=name))
        weekly_rows.append(frame[frame["session_date"].isin(fridays)])
    weekly = pd.concat(weekly_rows, ignore_index=True)
    floors = cfg.universe["logged"]
    for _, cross in weekly.groupby("session_date"):
        logged = cross[
            (cross["close"] >= floors["price_min"])
            & (cross["avg_dollar_volume_20d"] >= floors["avg_dollar_volume_20d_min"])
        ]
        qm = REGISTRY["qm_gainers"](logged, cfg.scans["qm_gainers"])
        hits.append(qm[qm["tier"] == "alert"].assign(strategy="qm_gainers"))
    tight = REGISTRY["tight_bases"](weekly[weekly["tier"] == "alert"], cfg.scans["tight_bases"])
    hits.append(tight.assign(strategy="tight_bases"))
    lookback = cfg.breakout["base_max_days"] + cfg.breakout["prior_move_max_days"] + 60
    if len(sessions) > lookback:
        bo = audit.replay(stocks, sessions, len(sessions) - lookback, cfg)
        if not bo.empty:
            bo["strategy"] = bo["kind"].map(
                {"watch": "breakout_watch", "trigger": "breakout_trigger"}
            )
            hits.append(bo)
    found = pd.concat([h for h in hits if len(h)], ignore_index=True)
    return measure(found, g, col, pos, market, cfg)


def measure(found: pd.DataFrame, g, col, pos, market, cfg) -> pd.DataFrame:
    """Entry, stop and outcomes for each hit (one ticker's arrays at a time)."""
    o, h, lo, c = (g[f] for f in ("open", "high", "low", "close"))
    rows: list[dict[str, Any]] = []
    for ticker, group in found.groupby("ticker"):
        j = col.get(ticker)
        if j is None:
            continue
        oc, hc, lc, cc = o[:, j], h[:, j], lo[:, j], c[:, j]
        mas = {w: hm.rolling_mean(cc[:, None], w)[:, 0] for w in TRAILS}
        with np.errstate(divide="ignore", invalid="ignore"):
            adr_pct = hm.rolling_mean(((hc / lc - 1) * 100)[:, None], hm.ADR_DAYS)[:, 0]
        for rec in group.to_dict("records"):
            t = pos.get(rec["session_date"])
            if t is None:
                continue
            strategy, side = rec["strategy"], SIDES[rec["strategy"]]
            day = {
                "close": cc[t],
                "low": lc[t],
                "high": hc[t],
                "adr20_usd": adr_pct[t] * cc[t] / 100,
            }
            entry_t, entry = t, cc[t]
            if strategy == "breakout_watch":
                later = hc[t + 1 : t + 1 + WATCH_TRIGGER_DAYS] >= rec["pivot"]
                first = _first(later)
                rec["triggered_within_days"] = None if first is None else first + 1
                if first is None:
                    rows.append(_row(rec, day, None, None, market[t]))
                    continue
                entry_t = t + 1 + first
                entry = (
                    max(oc[entry_t], rec["pivot"]) if oc[entry_t] == oc[entry_t] else rec["pivot"]
                )
            stop = _stop({**rec, **day}, strategy, cfg.sizing)
            result = outcomes(oc, hc, lc, cc, mas, entry_t, entry, stop, side)
            result |= exits.managed(oc, hc, lc, cc, mas, entry_t, entry, stop, side, cfg.exits)
            rows.append(_row(rec, day, entry, stop, market[t]) | result)
    return (
        pd.DataFrame(rows)
        .sort_values(["strategy", "session_date", "ticker"])
        .reset_index(drop=True)
    )


def _row(rec, day, entry, stop, market) -> dict[str, Any]:
    keep = {k: rec.get(k) for k in FEATURES if k in rec}
    extra = {
        k: rec.get(k)
        for k in (
            "pivot",
            "order_stop",
            "risk_adr",
            "base_len",
            "b1",
            "b2",
            "b3",
            "b4",
            "b5",
            "qm_lists",
            "tightness_adr",
            "triggered_within_days",
        )
        if k in rec
    }
    adr = day["adr20_usd"]
    risk = (
        abs(entry - stop) / adr
        if entry is not None and stop is not None and stop == stop and adr and adr == adr
        else np.nan
    )
    return {
        "strategy": rec["strategy"],
        "side": "long" if SIDES[rec["strategy"]] > 0 else "short",
        "session_date": rec["session_date"],
        "ticker": rec["ticker"],
        "entry": entry,
        "stop": stop,
        "stop_adr": risk,
        **keep,
        **extra,
        **market,
    }


def summary(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Per strategy (and group): count, win rate and median P&L per horizon, mean R (capped
    at 20 so one runner can't carry a group), stop-out within a week, trailing-exit R."""
    keys = ["strategy", *(by or [])]
    rows = []
    for key, part in df.groupby(keys, dropna=False, observed=True):
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(keys, key, strict=True)) | {"events": len(part)}
        for horizon in (1, 5, 21, 63):
            pnl = part[f"pnl_{horizon}d"].dropna()
            row[f"win_{horizon}d%"] = (pnl > 0).mean() * 100 if len(pnl) else np.nan
            row[f"med_{horizon}d%"] = pnl.median() if len(pnl) else np.nan
        for horizon in (5, 21, 63):
            r = part[f"r_{horizon}d"].dropna()
            row[f"R_{horizon}d"] = r.clip(upper=20).mean() if len(r) else np.nan
        hit = part["stop_hit_5d"].dropna()
        row["stopped_5d%"] = hit.astype(float).mean() * 100 if len(hit) else np.nan
        trail = part["r_trail_ma20"].dropna()
        row["R_trail_ma20"] = trail.clip(upper=20).mean() if len(trail) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def write(df: pd.DataFrame, folder) -> list:
    """One file per strategy (floats as float32), so none is too big for git."""
    from pathlib import Path

    from trading_os.store import PARQUET_OPTIONS

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, part in df.groupby("strategy"):
        slim = part.dropna(axis=1, how="all").copy()
        for column in slim.select_dtypes("float64").columns:
            slim[column] = slim[column].astype("float32")
        path = folder / f"{name}.parquet"
        slim.to_parquet(path, **PARQUET_OPTIONS)
        paths.append(path)
    return paths


def load(data_dir) -> pd.DataFrame:
    """The newest build, all strategies."""
    from pathlib import Path

    builds = sorted(
        p for p in (Path(data_dir) / "data" / "strategy_history").glob("*") if p.is_dir()
    )
    if not builds:
        return pd.DataFrame()
    frames = [pd.read_parquet(f) for f in sorted(builds[-1].glob("*.parquet"))]
    out = pd.concat(frames, ignore_index=True)
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import datetime as dt
    from pathlib import Path

    from trading_os import history
    from trading_os.config import load_config
    from trading_os.logsafe import status

    parser = argparse.ArgumentParser(description="Strategy history over the Massive bars")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--rebuild", action="store_true", help="replace this date's build")
    args = parser.parse_args(argv)
    cfg = load_config()
    files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
    sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
    if len(sessions) < 200:
        status("Strategy history: not enough bars yet")
        return 1
    folder = args.data_dir / "data" / "strategy_history" / sessions[-1].isoformat()
    if folder.exists() and not args.rebuild:
        status(f"Strategy history: {folder.name} already built (--rebuild replaces it)")
        return 0
    root = args.data_dir / "data"
    snaps = [*root.glob("universe/*/*.parquet"), *root.glob("manual/*/universe.parquet")]
    caps: dict[str, float] = {}
    if snaps:
        snap = pd.read_parquet(max(snaps, key=lambda f: f.stat().st_mtime))
        caps = dict(zip(snap["ticker"], snap["market_cap"], strict=True))
    df = find(history.load_bars(args.data_dir, sessions), sessions, cfg, caps)
    write(df, folder)
    counts = df["strategy"].value_counts().to_dict()
    status(f"Strategy history: {len(df)} hits over {len(sessions)} sessions {counts}, saved")
    return 0
