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

FEATURE_SESSIONS = 260  # the 52-week high before the signal (quality counts)
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
    """The close the features come from: the run's own session after the close (EOD, after
    hours), else the one before."""
    if slot in ("eod", "ah"):
        return session
    return clock.previous_session(cfg.schedule, session)


def entry_price(rec: Mapping[str, Any], scan: str) -> float | None:
    """The live price a hit would be bought at: after hours the post-market price (from the
    post-market change when TradingView has no price), else the last price."""
    if scan == "ep_ah":
        price = rec.get("ah_price")
        if price is None or pd.isna(price):
            close, change = rec.get("close"), rec.get("ah_change_pct")
            if close is None or change is None or pd.isna(close) or pd.isna(change):
                return None
            price = close * (1 + change / 100)
        return float(price)
    price = rec.get("close")
    return None if price is None or pd.isna(price) else float(price)


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


# Short names of the quality points for the push and the report (Emil, 22 Oct 2026).
POINT_NAMES = {
    "earnings": "earnings",
    "earnings_recent": "earnings ≤10d",
    "sideways_1_2m": "1-2 mo base",
    "market_cool_lt45": "market not hot",
    "revenue_accel": "revenue accel.",
    "eps_yoy_pos": "EPS up y/y",
    "near_52w_high": "near 52w high",
    "tight_5d": "tight 5d",
}


def point_text(g: grader.Grade) -> str | None:
    """`✅ earnings · ✅ EPS up y/y · ❌ market not hot`: which quality points held (count
    grades only)."""
    if not g.note or "quality points" not in g.note:
        return None
    marks = [f"{'✅' if pts else '❌'} {POINT_NAMES.get(name, name)}" for name, _, pts in g.reasons]
    return " · ".join(marks)


def _why(g: grader.Grade, top: int = 3) -> str:
    parts = [f"{name} {pts:+.2f}" for name, _, pts in g.reasons[:top] if pts]
    return ", ".join(parts)


def rule_for(scan: str, grading: Mapping[str, Any]) -> tuple[str | None, Mapping | None]:
    """(strategy, its rule): a quality count when those are on, else the scorecard."""
    name = grader.quality_for(scan, grading)
    if name is not None:
        return name, grading["quality"][name]
    name = grader.strategy_for(scan, grading)
    return name, None if name is None else grading["strategies"][name]


def earnings_facts(rec: Mapping[str, Any], schedule, asof: dt.date | None) -> dict:
    """`is_earnings_reaction_day` (earnings on the signal session or the evening before, the
    live EP flag) and `sessions_since_earnings` (from TradingView's last report date)."""
    out = {"is_earnings_reaction_day": bool(rec.get("earnings_flag", False))}
    last = rec.get("earnings_date_last")
    if asof is not None and last is not None and not pd.isna(last):
        day = pd.Timestamp(last)
        if day.tzinfo is not None:
            day = day.tz_convert("America/New_York")
        day = day.date()
        if day <= asof:
            cal = clock._calendar(schedule.calendar)
            out["sessions_since_earnings"] = float(
                len(cal.sessions_in_range(pd.Timestamp(day), pd.Timestamp(asof))) - 1
            )
    return out


def grade_hits(
    hits: pd.DataFrame,
    scan: str,
    cfg,
    market: Mapping[str, Any],
    stocks: pd.DataFrame,
    extra: pd.DataFrame | None = None,
    asof: dt.date | None = None,
    slot: str | None = None,
) -> pd.DataFrame:
    """`hits` plus the grade columns and, for graded hits, the study plan's entry and stop. A
    quality rule's `entries` may name a plan per check (`<scan>@<slot>`), e.g. EP9M names first
    found at the 12:00 check take the 12:00 plan."""
    grading = cfg.grading
    name, rule = rule_for(scan, grading)
    rows = []
    for rec in hits.to_dict("records"):
        if name is None:
            g = grader.grade(scan, {}, grading)
            rows.append({"grade": g.grade, "grade_why": g.note})
            continue
        feats = dict(market)
        feats.update(earnings_facts(rec, cfg.schedule, asof))
        ticker = rec["ticker"]
        if ticker in stocks.index:
            feats.update(stocks.loc[ticker].to_dict())
        if extra is not None and ticker in extra.index:
            feats.update(extra.loc[ticker].dropna().to_dict())
        if "base_days" in rec:
            feats["sig_base_days"] = rec.get("base_days")
        entry = entry_price(rec, scan)
        adr_usd = rec.get("adr20_usd")
        adr_pct = rec.get("adr20_pct")
        stop = stop_for(entry, adr_usd, rule["stop_adr"], cfg.intraday_study["min_stop_pct"])
        g = grader.grade(
            scan,
            feats,
            grading,
            price=entry,
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
                "grade_why": g.note or _why(g),
                "grade_points": point_text(g),
                "grade_entry_rule": rule.get("entries", {}).get(
                    f"{scan}@{slot}", g.plan.get("entry", rule.get("entry"))
                ),
                "grade_hold_sessions": rule["hold_sessions"],
                "grade_risk_mult": g.risk_mult,
                "grade_stop": stop,
                "grade_entry": entry,
                "grade_basis": "quality" if "parts" in rule else "scorecard",
            }
        )
    frame = pd.DataFrame(rows, index=hits.index)
    return hits.drop(columns=[c for c in frame.columns if c in hits]).join(frame)


def _stat(stats: Mapping[str, Any], strategy, grade, entry, basis, key: str):
    """One history figure: a quality count's from its entry (`quality.<entry>.<grade>`), a
    scorecard's from `grades.<grade>`."""
    if not isinstance(strategy, str):
        return None
    block = stats.get(strategy, {})
    if basis == "quality":
        return block.get("quality", {}).get(entry, {}).get(grade, {}).get(key)
    return block.get("grades", {}).get(grade, {}).get(key)


def with_stats(hits: pd.DataFrame, stats: Mapping[str, Any]) -> pd.DataFrame:
    """The history behind each graded hit's grade (`grade_stat_*`)."""
    if hits.empty or "grade_strategy" not in hits:
        return hits
    out = hits.copy()
    none = pd.Series(None, index=out.index, dtype=object)
    entries = out.get("grade_entry_rule", none)
    bases = out.get("grade_basis", none)
    for key in STAT_KEYS:
        out[f"grade_stat_{key}"] = [
            _stat(stats, s, g, e, b, key)
            for s, g, e, b in zip(out["grade_strategy"], out["grade"], entries, bases, strict=True)
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
        entry = rec.get("grade_entry")
        sized = sizing.size(
            rec.get("close") if entry is None or pd.isna(entry) else entry,
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
    """Revenue growth acceleration (percentage points vs the quarter before) and EPS growth
    YoY of the latest quarter, by tv_ticker, from TradingView's quarterly history (the same
    arithmetic as the SEC study features)."""
    from trading_os import context

    if not symbols:
        return pd.DataFrame()
    details = fetch_details(symbols, list(context.DETAIL_FIELDS))
    details = context.growth_columns(details.rename(columns=context.DETAIL_FIELDS))
    out = pd.DataFrame(index=details.index)
    out["revenue_growth_accel"] = details["ctx_rev_growth_q"] - details["ctx_rev_growth_q_prev"]
    out["eps_yoy_pct"] = details["ctx_eps_growth_q"]
    return out


GROWTH_FEATURES = ("revenue_growth_accel", "eps_yoy_pct")


def uses_growth(scan: str, grading: Mapping[str, Any]) -> bool:
    """Whether the scan's grade reads TradingView's quarterly growth (one extra request)."""
    name, rule = rule_for(scan, grading)
    if rule is None:
        return False
    if "parts" in rule:
        feats = {grading["conditions"][p]["feature"] for p in rule["parts"]}
    else:
        feats = set(rule["features"])
    return bool(feats & set(GROWTH_FEATURES))


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
        n for n, hits in results.items() if len(hits) and rule_for(n, cfg.grading)[0] is not None
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
        if uses_growth(name, cfg.grading) and fetch_details is not None and "tv_ticker" in hits:
            try:
                accel = growth_accel(sorted(hits["tv_ticker"].dropna().unique()), fetch_details)
                extra = hits.set_index("ticker")[["tv_ticker"]].join(accel, on="tv_ticker")
                extra = extra.drop(columns=["tv_ticker"])
            except Exception:  # noqa: BLE001 - the feature then scores as missing
                extra = None
        graded_hits = grade_hits(hits, name, cfg, market, stocks, extra, asof, slot)
        graded_hits = with_stats(graded_hits, stats)
        out[name] = resize(graded_hits, account, usd_rate)
    return out
