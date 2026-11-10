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
multiple. A setup on its own plan (`stop: order`, MA-surf since 23 Oct 2026) keeps the scan's
buy-stop at the pivot and its order stop, and trails the 20-day MA instead of a holding
period. Every other hit is C ("no edge after costs"). The per-grade history (trades, win
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

from trading_os import clock, grader, history, press, sizing
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


def signal_low_stop(entry, low, adr_usd, max_adr: float = 2.0) -> float:
    """Under the signal day's low, at most `max_adr` ADR below the entry (the EP9M AVWAP plan);
    NaN without the inputs."""
    vals = [entry, low, adr_usd]
    if any(v is None or pd.isna(v) for v in vals) or not entry > low:
        return float("nan")
    return float(max(low, entry - max_adr * adr_usd))


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


def under_weekly_ma(bars: pd.DataFrame, entry_session: dt.date, weeks: int = 40) -> pd.Series:
    """1.0 when the stock's last completed weekly close before the entry week is under the
    `weeks`-week average of weekly closes, else 0.0; missing with fewer weeks (Emil, 9 Nov
    2026: the Luk flush 40-week study, weeks that ended before the entry day's week)."""
    if bars.empty:
        return pd.Series(dtype=float, name=f"d_under_w{weeks}")
    monday = pd.Timestamp(entry_session) - pd.Timedelta(days=entry_session.weekday())
    out = {}
    for ticker, g in bars.groupby("ticker"):
        close = g.set_index(pd.to_datetime(g["session_date"]))["close"].sort_index()
        wk = close.resample("W-FRI").last().dropna()
        wk = wk[wk.index < monday]
        if len(wk) < weeks:
            continue
        out[ticker] = 1.0 if wk.iloc[-1] < wk.iloc[-weeks:].mean() else 0.0
    return pd.Series(out, dtype=float, name=f"d_under_w{weeks}")


def earlier_signal(bars: pd.DataFrame, session: dt.date, cfg, days: int = 90) -> pd.Series:
    """1.0 when the stock had an EP-Day or an EP9M day (the EP history rules, from its daily
    bars) in the `days` calendar days before `session`, else 0.0 (Emil, 10 Nov 2026: the
    earlier-signal grades). Bars before `session` only."""
    name = "d_earlier_ep"
    if bars.empty:
        return pd.Series(dtype=float, name=name)
    ep, ep9 = cfg.scans["ep_day"], cfg.scans["ep9m"]
    start = pd.Timestamp(session) - pd.Timedelta(days=days)
    out = {}
    for ticker, g in bars.groupby("ticker"):
        g = g.assign(day=pd.to_datetime(g["session_date"])).sort_values("day")
        g = g[g["day"] < pd.Timestamp(session)]
        c, v = g["close"].astype(float), g["volume"].astype(float)
        pc = c.shift(1)
        rvol = v / v.shift(1).rolling(hm.RVOL_DAYS).mean()
        is_ep = (
            ((g["open"] / pc - 1) * 100 >= ep["gap_min_pct"])
            & (rvol >= ep["rvol_min"])
            & (v >= ep["volume_min"])
            & (c >= ep["price_min"])
        )
        is_ep9m = (v >= ep9["volume_min"]) & ((c / pc - 1) * 100 >= ep9["chg_min_pct"])
        hit = (is_ep | is_ep9m) & (g["day"] >= start)
        out[ticker] = 1.0 if hit.any() else 0.0
    return pd.Series(out, dtype=float, name=name)


def w10_earlier_grade(rule10: Mapping[str, Any], under10, earlier) -> tuple[str, str] | None:
    """(grade, why) from the 10-week MA and the earlier signal; None without the 10-week MA."""
    if under10 not in (0.0, 1.0):
        return None
    side = "under" if under10 == 1.0 else "over"
    key = f"{side}_earlier" if earlier == 1.0 else side
    grade = rule10["grades"][key]
    n, win, r = rule10["study"][key]
    word = "an" if earlier == 1.0 else "no"
    why = (
        f"{side} its 10-week MA, {word} EP/EP9M in the {rule10['days']} days before: {grade}"
        f"{' (no push)' if grade == 'C' else ''}; study {n} trades, {win}% won, {r:+.2f}R a trade"
    )
    return grade, why


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
    "spy_over_ma200": "SPY > 200-day",
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
        adr_pct = rec.get("adr20_pct")
        if rule.get("stop") == "order":  # its own plan: buy-stop at the pivot, its order stop
            entry, stop, basis = sizing.plan(rec, scan, cfg.sizing)
        elif rule.get("stop") == "signal_low":  # EP9M AVWAP: under the signal day's low
            entry = entry_price(rec, scan)
            stop = signal_low_stop(entry, rec.get("low"), rec.get("adr20_usd"))
            basis = "under the signal day's low (at most 2 ADR)"
        else:
            entry = entry_price(rec, scan)
            min_stop = cfg.intraday_study["min_stop_pct"]
            stop = stop_for(entry, rec.get("adr20_usd"), rule["stop_adr"], min_stop)
            basis = "1 ADR (study plan)"
        g = grader.grade(
            scan,
            feats,
            grading,
            price=entry,
            stop=stop if not pd.isna(stop) else None,
            dvol20=rec.get("avg_dollar_volume_20d"),
            adr_pct=adr_pct,
        )
        entry_rule = rule.get("entries", {}).get(
            f"{scan}@{slot}", g.plan.get("entry", rule.get("entry"))
        )
        label, risk_mult, why = g.grade, g.risk_mult, g.note or _why(g)
        pace = rule.get("pace_b")  # EP9M A+ under a 20M pace at 10:15 -> B (Emil, 6 Nov 2026)
        proj = rec.get("proj_volume")
        slow = pace and not pd.isna(proj) and float(proj) < float(pace["below"])
        if slow and label == "A+" and entry_rule == pace["entry"]:
            label, risk_mult = "B", float(grading["risk_mult"].get("B", 0.0))
            why = f"{why}; on pace for {float(proj) / 1e6:.0f}M, under {pace['below'] / 1e6:.0f}M"
        up = rule.get(
            "under_w40"
        )  # Luk flush A under its 40-week MA -> A+ at x2 (Emil, 9 Nov 2026)
        if up and label == up["grade"] and feats.get("d_under_w40") == 1.0:
            label, risk_mult = up["label"], float(risk_mult) * float(up["mult"])
            size = f"x{float(up['mult']):g} the {up['grade']} size"
            why = f"{why}; under its 40-week MA: {up['label']}, {size}"
        rule10 = rule.get("w10_earlier")  # EP / EP9M A+ (Emil, 10 Nov 2026): same size, C no push
        if rule10 and label == "A+" and entry_rule == rule10["entry"]:
            found = w10_earlier_grade(rule10, feats.get("d_under_w10"), feats.get("d_earlier_ep"))
            if found:
                label, more = found
                why = f"{why}; {more}"
                if label not in ("A+++", "A++", "A+"):
                    risk_mult = float(grading["risk_mult"].get(label, 0.0))
        rows.append(
            {
                "grade": label,
                "grade_strategy": name,
                "grade_score": g.score,
                "grade_cost_r": g.cost_r,
                "grade_why": why,
                "grade_points": point_text(g),
                "grade_entry_rule": entry_rule,
                "grade_hold_sessions": rule.get("hold_sessions")
                or (21 if rule.get("exit") == "hold_21" else None),
                "grade_exit": rule.get("exit", "hold"),
                "grade_risk_mult": risk_mult,
                "grade_stop": stop,
                "grade_entry": entry,
                "grade_stop_basis": basis,
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
    """The study plan as the hit's plan: entry at the live price (MA-surf: the pivot), the
    study stop, shares for the account's risk x the grade's multiple (C: none)."""
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
        basis = rec.get("grade_stop_basis")
        out.at[idx, "plan_stop_basis"] = basis if isinstance(basis, str) else "1 ADR (study plan)"
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


def weekly_ma_weeks(scan: str, grading: Mapping[str, Any]) -> set[int]:
    """The weekly MAs the scan's quality rule reads: 40 (size-up), 10 (the note)."""
    _, rule = rule_for(scan, grading)
    if not rule:
        return set()
    return ({40} if rule.get("under_w40") else set()) | ({10} if rule.get("w10_earlier") else set())


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
        weeks = set().union(*(weekly_ma_weeks(n, cfg.grading) for n in graded))
        nxt = clock.sessions_after(cfg.schedule, asof, 1, asof + dt.timedelta(days=10))
        entry_day = nxt[0] if slot in ("eod", "ah") and nxt else session
        for w in sorted(weeks):
            col = under_weekly_ma(bars, entry_day, weeks=w)
            stocks = stocks.join(col, how="outer") if len(stocks) else col.to_frame()
        days = [r["w10_earlier"]["days"] for n in graded if (r := rule_for(n, cfg.grading)[1])
                and r.get("w10_earlier")]  # fmt: skip
        if days:
            col = earlier_signal(bars, entry_day, cfg, days=max(days))
            stocks = stocks.join(col, how="outer") if len(stocks) else col.to_frame()
    stats = load_stats(data_dir, cfg)
    press_state = press.load(data_dir, session)
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
        graded_hits = press.apply(graded_hits, press_state, cfg.grading["press"])
        out[name] = resize(graded_hits, account, usd_rate)
    return out
