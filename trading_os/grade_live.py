"""Study grades on live scan hits (Emil, 20 Oct 2026; SPEC §11.17). Facts, not advice.

For every hit of a scan the grading rules cover (config `grading.strategies.*.live_scans`),
the features the study used, taken the same way:

- `d_*`: the stock's daily facts at the last close before the entry day: the previous
  session's close for the intraday checks (entries that day), the signal session's own
  close at the EOD run (entries the next day). From the stored daily bars.
- `mkt_*`: that session's market row (Market Light, QQQ trend, breadth state, the Sunday
  scan count; SPY over its 200-day MA, QQQ over its 50-day MA).
- the setup's own (`sig_base_days` = the AVWAP flush's base) and revenue growth acceleration
  from TradingView's quarterly history when a scorecard uses it.

Then `grader.grade` gives the grade, and the study plan becomes the hit's plan: entry at the
live price, stop 1 ADR under it (at least the 1 % floor), the account's risk x the grade's
multiple. Every other hit is C ("no edge after costs"). The per-grade history (trades, win
rate, R, years) comes from the private data repo. Auxiliary: a failure leaves the hits
ungraded and never stops a run.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import clock, grader, history
from trading_os import history_metrics as hm

FEATURE_SESSIONS = 80  # the scorecards' longest window is about 60 sessions
INDEX_SESSIONS = 210  # SPY's 200-day MA
GRADE_COLUMNS = [
    "grade",
    "grade_strategy",
    "grade_score",
    "grade_cost_r",
    "grade_why",
    "grade_entry_rule",
    "grade_hold_sessions",
    "grade_risk_mult",
]
STAT_KEYS = ("trades", "win_pct", "mean_r", "median_r", "years_pos", "years", "days_median")


def asof_session(cfg, session: dt.date, slot: str) -> dt.date:
    """The close the features come from: the run's own session at EOD, else the one before."""
    return session if slot == "eod" else clock.previous_session(cfg.schedule, session)


def market_features(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """`mkt_*` from a breadth row (None: all missing, scored as such)."""
    if not row:
        return {}

    def above(name: str, window: int):
        close, ma = row.get(f"{name}_close"), row.get(f"{name}_sma{window}")
        if close is None or ma is None or pd.isna(close) or pd.isna(ma):
            return None
        return 1.0 if close > ma else 0.0

    return {
        "mkt_light": row.get("light"),
        "mkt_qqq_trend": row.get("qqq_trend"),
        "mkt_breadth_state": row.get("breadth_state"),
        "mkt_scan_count": row.get("scan_count"),
        "mkt_mkt_ratio_10d": row.get("ratio_10d"),
        "mkt_spy_above_ma200": above("spy", 200),
        "mkt_qqq_above_ma50": above("qqq", 50),
    }


def stock_features(bars: pd.DataFrame, asof: dt.date, sessions: list) -> pd.DataFrame:
    """`d_*` per ticker at `asof` from daily bars (sessions up to and including `asof`)."""
    from trading_os.grading_study import daily_features

    if bars.empty:
        return pd.DataFrame()
    g, tickers = hm.grids(bars, sessions)
    if asof not in sessions:
        return pd.DataFrame(index=pd.Index([], name="ticker"))
    row = sessions.index(asof)
    feats = daily_features(g)
    table = pd.DataFrame({f"d_{k}": v[row] for k, v in feats.items()}, index=tickers)
    table.index.name = "ticker"
    return table


def load_stats(data_dir: Path, cfg) -> dict:
    path = Path(data_dir) / cfg.grading["stats_file"]
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("strategies", {})


def stop_for(entry: float, adr_usd: float, stop_adr: float, floor_pct: float) -> float:
    """Study stop: `stop_adr` x ADR under the entry, at least `floor_pct` % away."""
    if any(x is None or pd.isna(x) for x in (entry, adr_usd)) or not entry > 0:
        return math.nan
    return entry - max(stop_adr * adr_usd, floor_pct / 100 * entry)


def _why(g: grader.Grade, top: int = 3) -> str:
    parts = [f"{name} {pts:+.2f}" for name, _, pts in g.reasons[:top] if pts]
    return ", ".join(parts)


def grade_hits(
    hits: pd.DataFrame,
    scan: str,
    cfg,
    market: Mapping[str, Any],
    stocks: pd.DataFrame,
    extra: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """`hits` plus the grade columns and, for graded hits, the study plan's entry and stop."""
    grading = cfg.grading
    name = grader.strategy_for(scan, grading)
    rows = []
    for rec in hits.to_dict("records"):
        if name is None:
            g = grader.grade(scan, {}, grading)
            rows.append({"grade": g.grade, "grade_why": g.note})
            continue
        rule = grading["strategies"][name]
        feats = dict(market)
        ticker = rec["ticker"]
        if ticker in stocks.index:
            feats.update(stocks.loc[ticker].to_dict())
        if extra is not None and ticker in extra.index:
            feats.update(extra.loc[ticker].dropna().to_dict())
        if "base_days" in rec:
            feats["sig_base_days"] = rec.get("base_days")
        entry = rec.get("close")
        adr_usd = rec.get("adr20_usd")
        adr_pct = rec.get("adr20_pct")
        stop = stop_for(entry, adr_usd, rule["stop_adr"], cfg.intraday_study["min_stop_pct"])
        g = grader.grade(
            scan,
            feats,
            grading,
            price=entry if entry and not pd.isna(entry) else None,
            stop=stop if not pd.isna(stop) else None,
            dvol20=rec.get("avg_dollar_volume_20d"),
            adr_pct=adr_pct,
        )
        rows.append(
            {
                "grade": g.grade,
                "grade_strategy": name,
                "grade_score": g.score,
                "grade_cost_r": g.cost_r,
                "grade_why": _why(g),
                "grade_entry_rule": rule["entry"],
                "grade_hold_sessions": rule["hold_sessions"],
                "grade_risk_mult": g.risk_mult,
                "grade_stop": stop,
            }
        )
    frame = pd.DataFrame(rows, index=hits.index)
    return hits.drop(columns=[c for c in frame.columns if c in hits]).join(frame)


def with_stats(hits: pd.DataFrame, stats: Mapping[str, Any]) -> pd.DataFrame:
    """The history behind each graded hit's grade (`grade_stat_*`)."""
    if hits.empty or "grade_strategy" not in hits:
        return hits
    out = hits.copy()
    for key in STAT_KEYS:
        out[f"grade_stat_{key}"] = [
            stats.get(s, {}).get("grades", {}).get(g, {}).get(key) if isinstance(s, str) else None
            for s, g in zip(out["grade_strategy"], out["grade"], strict=True)
        ]
    return out


def resize(hits: pd.DataFrame, account, usd_rate: float) -> pd.DataFrame:
    """The study plan as the hit's plan: entry at the live price, the study stop, shares
    for the account's risk x the grade's multiple (C: none)."""
    from trading_os import sizing

    if account is None or hits.empty or "grade_stop" not in hits:
        return hits
    out = hits.copy()
    risk_usd, account_usd = account.risk_usd(usd_rate), account.size_usd(usd_rate)
    for idx, rec in out.iterrows():
        mult = rec.get("grade_risk_mult")
        if rec.get("grade_strategy") is None or pd.isna(mult) or not mult > 0:
            continue
        sized = sizing.size(
            rec.get("close"),
            rec.get("grade_stop"),
            risk_usd * mult,
            account_usd,
            account.max_position_pct,
        )
        if sized is None:
            continue
        for key, value in sized.items():
            out.at[idx, key] = value
        out.at[idx, "plan_stop_basis"] = "1 ADR (study plan)"
    return out


def growth_accel(symbols: list[str], fetch_details) -> pd.DataFrame:
    """Revenue growth acceleration (percentage points vs the quarter before), by tv_ticker,
    from TradingView's quarterly history (the same arithmetic as the SEC study feature)."""
    from trading_os import context

    if not symbols:
        return pd.DataFrame()
    details = fetch_details(symbols, list(context.DETAIL_FIELDS))
    details = context.growth_columns(details.rename(columns=context.DETAIL_FIELDS))
    out = pd.DataFrame(index=details.index)
    out["revenue_growth_accel"] = details["ctx_rev_growth_q"] - details["ctx_rev_growth_q_prev"]
    return out


def add_grades(
    results: Mapping[str, pd.DataFrame],
    data_dir: Path,
    cfg,
    session: dt.date,
    slot: str,
    market_row: Mapping[str, Any] | None = None,
    account=None,
    usd_rate: float = 1.0,
    fetch_details=None,
    today: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Grades (and the study plan's size) on every hit; `market_row`: this run's breadth row
    at EOD, else the latest EOD row before `session` is read; `today`: the session's own
    bars at EOD (not stored yet)."""
    from trading_os import breadth

    if not cfg.grading["enabled"]:
        return dict(results)
    asof = asof_session(cfg, session, slot)
    if market_row is None:
        market_row = breadth.latest_eod_row(data_dir, asof + dt.timedelta(days=1))
    market = market_features(market_row)
    graded = {
        n
        for n, hits in results.items()
        if len(hits) and grader.strategy_for(n, cfg.grading) is not None
    }
    tickers = sorted({t for n in graded for t in results[n]["ticker"]})
    stocks = pd.DataFrame()
    if tickers:
        sessions = list(clock.sessions_back(cfg.schedule, asof, FEATURE_SESSIONS))
        bars = history.load_bars(data_dir, sessions)
        if today is not None and len(today):
            bars = pd.concat([bars[bars["session_date"] != asof], today], ignore_index=True)
        bars = bars[bars["ticker"].isin(tickers)]
        stocks = stock_features(bars, asof, sessions)
    stats = load_stats(data_dir, cfg)
    out = {}
    for name, hits in results.items():
        if hits.empty:
            out[name] = hits
            continue
        extra = None
        strategy = grader.strategy_for(name, cfg.grading)
        uses_growth = (
            strategy is not None
            and "revenue_growth_accel" in (cfg.grading["strategies"][strategy]["features"])
        )
        if uses_growth and fetch_details is not None and "tv_ticker" in hits:
            try:
                accel = growth_accel(sorted(hits["tv_ticker"].dropna().unique()), fetch_details)
                extra = hits.set_index("ticker")[["tv_ticker"]].join(accel, on="tv_ticker")
                extra = extra.drop(columns=["tv_ticker"])
            except Exception:  # noqa: BLE001 - the feature then scores as missing
                extra = None
        graded_hits = grade_hits(hits, name, cfg, market, stocks, extra)
        graded_hits = with_stats(graded_hits, stats)
        out[name] = resize(graded_hits, account, usd_rate)
    return out
