"""The Research and Live results pages' tables, without any UI (React dashboard, Nov 2026):
moved from `app/streamlit_app.py` so the Streamlit and the React dashboards show the same
research. Each function returns the frames or text a section shows; the study numbers
themselves are computed by the study modules (`strategy_history`, `exits`, `intraday_study`,
`live_tracking`, `stats`, `heat`) and published in the data repo. Facts about past rules, not
advice. Read-only.
"""

from __future__ import annotations

import contextlib
import importlib
import inspect
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import (
    dashboard,
    exits,
    heat,
    intraday_study,
    live_tracking,
    long_history,
    notify,
    outcomes,
    remote_data,
    report,
    stats,
    strategy_history,
)
from trading_os.config import load_config

EP_FLAGS = ["c1_gap", "c2_volume", "c3_growth", "c4_neglect", "c5_stop"]


HISTORY_COLUMNS = [
    "strategy",
    "side",
    "session_date",
    "ticker",
    "entry",
    "stop",
    "stop_adr",
    "close",
    "chg_pct",
    "gap_pct",
    "rvol50",
    "mkt_breadth_state",
    "mkt_qqq_trend",
    "above_ma200",
    "pnl_1d",
    "pnl_5d",
    "pnl_21d",
    "pnl_63d",
    "r_5d",
    "r_21d",
    "r_63d",
    "stop_hit_5d",
    "r_trail_ma10",
    "r_trail_ma20",
    "r_trail_ema9",
    "r_trail_ema21",
    "r_q3_ma10",
    "r_q3_ma20",
    "r_q5_ma10",
    "r_q5_ma20",
    "r_time3d",
    "r_time5d",
    "r_target8_5d",
]
EP_COLUMNS = [
    "is_ep_day",
    "tier",
    "plan_entry",
    "plan_stop",
    "months_sideways",
    "earnings_inferred",
    "eps_growth_yoy",
    "sales_growth_yoy",
    "ret_1d",
    "ret_5d",
    "ret_21d",
    "ret_63d",
]


def feature_points(features) -> pd.DataFrame:
    """A scorecard's features as rows: the feature, the range of values, and the points it
    adds to the predicted net R."""
    rows = []
    for feature, spec in features.items():
        points = spec["points"]
        if "edges" in spec:
            edges = list(spec["edges"])
            labels = [f"< {edges[0]:g}"]
            labels += [f"{a:g} to {b:g}" for a, b in zip(edges, edges[1:], strict=False)]
            labels += [f">= {edges[-1]:g}"]
            pairs = list(zip(labels, points, strict=True))
        else:
            pairs = list(points.items())
        if "na" in spec:
            pairs.append(("unknown", spec["na"]))
        rows += [{"Feature": feature, "Value": v, "Points (R)": f"{p:+.3f}"} for v, p in pairs]
    return pd.DataFrame(rows)


FEATURE_TEXT = {  # the quality conditions' features, in words
    "is_earnings_reaction_day": "the gap is an earnings reaction",
    "sessions_since_earnings": "sessions since the last earnings report",
    "d_neglect_months": "months moving sideways before",
    "mkt_scan_count": "Sunday scan count (stocks up 50 % in a quarter)",
    "revenue_growth_accel": "revenue growth acceleration",
    "eps_yoy_pct": "EPS growth year on year, %",
    "d_from_52w_high": "distance from the 52-week high, %",
    "d_tight5_adr": "5-day range, in ADR",
}


def condition_text(cond) -> str:
    """One quality condition from config, in words: `months moving sideways before 1 to 2`."""
    what = FEATURE_TEXT.get(cond["feature"], cond["feature"])
    if "equals" in cond:
        return what if cond["equals"] is True else f"{what}: {cond['equals']}"
    if "min" in cond and "max" in cond:
        return f"{what}: {cond['min']:g} to {cond['max']:g}"
    for key, word in (
        ("max", "at most"),
        ("min", "at least"),
        ("above", "above"),
        ("below", "under"),
    ):
        if key in cond:
            return f"{what}: {word} {cond[key]:g}"
    return what


def quality_rules(grading) -> pd.DataFrame:
    """The quality grades as config has them: per setup, its points, the grade per count, and
    the plan (when to buy, stop, exit)."""
    rows = []
    for rule in (grading.get("quality") or {}).values():
        parts = list(rule["parts"])
        points = "; ".join(
            f"{i}. {condition_text(grading['conditions'][part])}" for i, part in enumerate(parts, 1)
        )
        bands, top = [], len(parts)
        for floor, grade in rule["grades"]:
            span = f"{floor}" if floor == top else f"{floor}-{top}"
            bands.append(f"{span} = {grade}")
            top = floor - 1
        if parts:
            bands.append(f"0-{top} = C" if top > 0 else "0 = C")
        else:  # a setup graded as a whole (EP9M AVWAP)
            bands = [f"every hit = {rule['grades'][0][1]}"]
        buys = "; ".join(
            f"{report.SCAN_LABELS.get(scan, scan)}: {notify.ENTRY_TEXT.get(entry, entry)}"
            for scan, entry in rule["entries"].items()
        )
        rows.append(
            {
                "Setup": " / ".join(report.SCAN_LABELS.get(s, s) for s in rule["live_scans"]),
                "Points (one each)": points,
                "Grade by points": " · ".join(bands),
                "When to buy": buys,
                "Stop": (
                    f"{rule['stop_adr']:g} ADR under the entry (at least 1 %)"
                    if "stop_adr" in rule
                    else "under the signal day's low (at most 2 ADR)"
                    if rule.get("stop") == "signal_low"
                    else "the scan's order stop"
                ),
                "Exit": (
                    f"at the close {rule['hold_sessions']} sessions after the entry"
                    if "hold_sessions" in rule
                    else notify.EXIT_TEXT.get(rule.get("exit"), str(rule.get("exit")))
                ),
            }
        )
    return pd.DataFrame(rows)


# (label, rules from: a live scan's name or a study module, its config, its heat-table key)
STRATEGY_RULES = [
    ("EP 10:30 (the EP gap at the open)", "scan:ep_am", None, "ep_a_1030"),
    ("EP-AH (earnings gap after hours)", "scan:ep_ah", None, "ep_a_ah"),
    ("EP-Day (the gap at the close)", "scan:ep_day", None, "ep_next_day"),
    ("EP-PM (pre-market gappers)", "scan:ep_pm", None, None),
    ("EP9M (Stockbee: 9 million shares)", "scan:ep9m", None, None),
    ("EP9M pace (EP9M during the session)", "scan:ep9m_pace", None, "ep9m_a"),
    ("EP9M AVWAP re-entry (grade B)", "module:avwap_live", None, None),
    ("Momentum Burst up (Stockbee)", "scan:mb_up", None, "mb_up"),
    ("Momentum Burst down (Stockbee)", "scan:mb_down", None, "mb_down"),
    ("Parabolic long (Qullamaggie)", "scan:parabolic_long", None, "parabolic_long"),
    ("Parabolic short (Qullamaggie)", "scan:parabolic_short", None, "parabolic_short"),
    ("Breakouts B1-B5 (BO-Watch, trigger)", "module:breakouts", "breakout", "breakout"),
    ("MA-surf (Qullamaggie)", "module:qm_setups", "qm_surf", "qm_surf"),
    ("VCP (Minervini)", "module:minervini", "minervini", "vcp"),
    ("Trend Template (Minervini)", "module:minervini", "minervini", None),
    ("Luk AVWAP flush (Martin Luk)", "module:luk", "luk", "luk_flush_a"),
    ("Luk pullback (Martin Luk)", "module:luk", "luk", "luk_pullback"),
    ("Luk inside day (Martin Luk)", "module:luk", "luk", "luk_inside_day"),
    ("High tight flag (O'Neil, Minervini)", "module:patterns", "htf", None),
    ("Pocket pivot (Morales and Kacher)", "module:patterns", "pocket_pivot", None),
]


def release(data_dir: Path, tag: str, pattern: str = "*") -> Path:
    """A data-repo release's cache folder with `pattern` fetched (offline: what is cached)."""
    with contextlib.suppress(Exception):
        remote_data.fetch(remote_data.repo_of(Path(data_dir)), tag, pattern)
    return remote_data.CACHE / tag


def funds(data_dir: Path) -> frozenset:
    """ETFs, ETNs and funds (Massive's ticker types): left out of the study views."""
    from trading_os.regime_study import non_stocks

    return frozenset(non_stocks(Path(data_dir)))


# --- History


def history_frame(
    data_dir: Path,
    period: str = "2y",
    hist: pd.DataFrame | None = None,
    ep: pd.DataFrame | None = None,
    skip: Iterable[str] | None = None,
) -> pd.DataFrame:
    """The strategy history plus the EP study's alert-tier EP-Days as strategy `ep_day`, in
    one shape: the EP study's returns become `pnl_*`, its planned entry and stop `entry` and
    `stop`; its criteria and fundamentals columns come along for the EP filters. `10y`: the
    yearly files of the history-10y release (only the columns the page uses). ETFs and funds
    (`skip`, default `funds`) are left out."""
    skip = funds(data_dir) if skip is None else frozenset(skip)
    if period == "10y":
        long_dir = remote_data.CACHE / "history-10y"
        hist = long_history.load(long_dir, "strategy", HISTORY_COLUMNS)
        ep = long_history.load(long_dir, "ep", [*HISTORY_COLUMNS, *EP_COLUMNS, *EP_FLAGS])
    else:
        hist = strategy_history.load(data_dir) if hist is None else hist
        if ep is None:
            built = sorted((Path(data_dir) / "data" / "ep_history").glob("ep_history_*.parquet"))
            ep = pd.read_parquet(built[-1]) if built else pd.DataFrame()
    if hist.empty:  # nothing downloaded (offline, or the release not reachable)
        return hist
    if ep.empty:
        hist = hist[~hist["ticker"].isin(skip)]
        return hist.assign(year=pd.to_datetime(hist["session_date"]).dt.year)
    ep = ep[ep["is_ep_day"] & (ep["tier"] == "alert")].copy()
    ep["session_date"] = pd.to_datetime(ep["session_date"]).dt.date
    outcome = re.compile(r"^ret_\d+d$")  # outcomes only; ret_22 etc. are features
    ep = ep.rename(columns={c: "pnl_" + c[4:] for c in ep.columns if outcome.match(c)})
    ep = ep.assign(strategy="ep_day", side="long", entry=ep["plan_entry"], stop=ep["plan_stop"])
    ep["criteria_met"] = ep[EP_FLAGS].fillna(False).astype(bool).sum(axis=1)
    extra = ("gap_pct", "rvol50", "months_sideways", "earnings_inferred", "criteria_met")
    extra += ("eps_growth_yoy", "sales_growth_yoy", *EP_FLAGS)
    missing = [c for c in extra if c not in hist]
    if missing:  # one block of columns, so the frame isn't fragmented
        hist = pd.concat([hist, pd.DataFrame(None, index=hist.index, columns=missing)], axis=1)
    out = pd.concat([hist, ep[[c for c in ep.columns if c in hist]]], ignore_index=True)
    out = out[~out["ticker"].isin(skip)].copy()  # stocks only; one block
    return out.assign(year=pd.to_datetime(out["session_date"]).dt.year)


def filter_history(hist: pd.DataFrame, picked, years, states, ep_args) -> pd.DataFrame:
    """The History rows for one set of filters: strategies, years, the breadth state, and for
    EP-Day (gap min, RVOL min, months sideways min, earnings any/yes/no/unknown, criteria that
    must pass). Adds the price (and EP gap / RVOL) buckets the splits use."""
    keep = hist["strategy"].isin(picked) & hist["year"].isin(years)
    if states:
        keep &= hist["mkt_breadth_state"].isin(states)
    if ep_args is not None:
        gap_min, rvol_min, months_min, earnings, must = ep_args
        ep = hist["strategy"] == "ep_day"
        ok = (hist["gap_pct"] >= gap_min) & (hist["rvol50"] >= rvol_min)
        ok &= hist["months_sideways"].fillna(0) >= months_min
        known = hist["earnings_inferred"]
        if earnings == "yes":
            ok &= known.eq(True)
        elif earnings == "no":
            ok &= known.eq(False)
        elif earnings == "unknown":
            ok &= known.isna()
        for flag in must:
            ok &= hist[flag].fillna(False).astype(bool)
        keep &= ~ep | ok
    view = hist[keep].copy()
    view["price_bucket"] = pd.cut(
        view["close"], [0, 5, 10, 50, 1e9], labels=["<5", "5-10", "10-50", "50+"]
    )
    if ep_args is not None:
        view["gap_bucket"] = pd.cut(
            view["gap_pct"], [0, 15, 25, 50, 1e9], labels=["<15", "15-25", "25-50", "50+"]
        )
        view["rvol_bucket"] = pd.cut(
            view["rvol50"], [0, 5, 10, 20, 1e9], labels=["<5", "5-10", "10-20", "20+"]
        )
    return view


HISTORY_SPLITS = ["none", "year", "mkt_breadth_state", "mkt_qqq_trend", "price_bucket",
                  "above_ma200"]  # fmt: skip
EP_SPLITS = ["earnings_inferred", "criteria_met", "gap_bucket", "rvol_bucket", "c4_neglect"]
EVENT_COLUMNS = ["session_date", "ticker", "side", "entry", "stop", "stop_adr", "chg_pct"]
EP_EVENT_COLUMNS = ["gap_pct", "rvol50", "months_sideways", "eps_growth_yoy", "sales_growth_yoy",
                    "earnings_inferred", "criteria_met"]  # fmt: skip
OUTCOME_COLUMNS = ["pnl_5d", "pnl_21d", "pnl_63d", "r_21d", "r_trail_ma20", "mkt_breadth_state"]
HISTORY_CAPTION = (
    "Every alert-tier hit of each scan over the Massive bars (EP-Day from the EP study, with its "
    "criteria), the market that day and what happened after. P&L is in the strategy's "
    "direction (shorts profit when it falls). Entries at the signal close (EP-Day: the gap-day "
    "close, stop at the day low within the live ADR bounds); other stops as in "
    "`strategy_history.py`. Gross: no costs, ETFs and funds left out on load. Facts, not advice."
)
SUMMARY_CAPTION = (
    "win/med = share up and median % move after 1, 5, 21 and 63 sessions; R = mean R with the "
    "stop (capped at 20); trails = out at the first close under the 10/20-day MA or EMA 9/21."
)


def history_tables(view: pd.DataFrame, exit_rules, group: str):
    """(summary, exits compared) for one filtered view and split."""
    by = None if group == "none" else [group]
    table = strategy_history.summary(view, by)
    compared = exits.compare(view[view["entry"].notna()], exit_rules, ["strategy", *(by or [])])
    compared = compared.assign(
        group=compared["group"].map(
            lambda g: " · ".join(map(str, g)) if isinstance(g, tuple) else str(g)
        )
    )
    return table, compared


def history_events(view: pd.DataFrame, one: str) -> pd.DataFrame:
    """One strategy's events, newest first, with the columns the events table shows."""
    events = view[view["strategy"] == one].sort_values("session_date", ascending=False)
    columns = [*EVENT_COLUMNS, *(EP_EVENT_COLUMNS if one == "ep_day" else []), *OUTCOME_COLUMNS]
    return events[[c for c in columns if c in events]]


def event_window(bars: pd.DataFrame, day, before: int = 120, after: int = 63) -> pd.DataFrame:
    """The bars around an event: `before` sessions up to it and `after` after it."""
    if bars.empty:
        return bars
    head = bars[bars["session_date"] <= day].tail(before)
    tail = bars[bars["session_date"] > day].head(after)
    return pd.concat([head, tail])


GRADED_CAPTION = (
    "The same events, tested the way the grading study tests them: stocks only (no ETFs or "
    "funds), real price at least $1, Saxo's commission and slippage (borrow for shorts), entry "
    "at the signal close (a buy-stop at the pivot for BO-Watch, VCP and the inside day), the "
    "exit with the best net R, and grades from scorecards fitted on earlier years only "
    "(2019-2026 out of sample). QM gainers, tight bases and the Trend Template have no stop of "
    "their own: 1 ADR under the Friday close, judged on the lows. Entries tested on minute bars "
    "(the open, the 10:15 and 12:00 checks, opening ranges, next-day breaks) are under "
    "Research, Grades."
)
GRADED_RENAME = {"best_exit": "best exit", "gross_r": "gross R", "mean_r": "net R",
                 "median_r": "median R", "win_pct": "win %", "years_pos": "years +",
                 "days": "days held"}  # fmt: skip


def history_graded(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every History strategy net of costs and graded walk-forward (the grading-10y release):
    (one row per strategy, out-of-sample grades per strategy). Empty when not reachable."""
    folder = release(data_dir, "grading-10y", "history_grades_*.parquet")
    files = [folder / f"history_grades_{n}.parquet" for n in ("summary", "by_grade")]
    if not all(f.exists() for f in files):
        return pd.DataFrame(), pd.DataFrame()
    return pd.read_parquet(files[0]), pd.read_parquet(files[1])


# --- Strategy rules, How it was tested, Grades, Study notes


def strategy_rules(cfg, data_dir: Path, label: str) -> dict[str, Any]:
    """One strategy's definition: its rules text (a live scan's function, or the study module
    that sets it up), its config numbers, and its study result per market heat."""
    from trading_os.scans import REGISTRY

    _, source, conf_key, heat_key = next(r for r in STRATEGY_RULES if r[0] == label)
    kind, name = source.split(":")
    if kind == "scan":
        scan = cfg.scans[name]
        status = "on" if scan.enabled else "off"
        heading = (
            f"Live scan `{name}` · {status} · runs at {', '.join(scan.slots)} · "
            f"{'pushed' if scan.action == 'push' else 'saved only'}"
        )
        doc = inspect.getdoc(REGISTRY[name]) or ""
        settings = dict(scan.params)
    else:
        live = {
            "qm_setups": "ma_surf",
            "breakouts": "breakout_watch / breakout_trigger",
            "luk": "luk_flush and luk_pullback (not the inside day)",
            "minervini": "vcp and minervini_tt (the Trend Template list)",
            "avwap_live": "ep9m_avwap (graded B: half the A+ size)",
        }.get(name)
        heading = "Live scan " + live if live else "Tested in the study only, no live scan"
        doc = inspect.getdoc(importlib.import_module(f"trading_os.{name}")) or ""
        if conf_key:
            settings = dict(getattr(cfg, conf_key, {}) or {})
        else:  # a live module without a config block of its own: its grade rule
            settings = (
                dict(cfg.grading["quality"].get("ep9m_avwap", {})) if name == "avwap_live" else {}
            )
    rows = [
        {"setting": k, "value": str(list(v) if isinstance(v, tuple) else v)}
        for k, v in settings.items()
    ]
    heat_rows = []
    found = heat.load(data_dir)
    if heat_key and found:
        setup = next((s["label"] for s in found["setups"] if s["key"] == heat_key), None)
        for _, band in found["bands"]:
            t = heat.table(found, band)
            mine = t[t["setup"] == setup]
            if len(mine):
                r = mine.iloc[0]
                heat_rows.append({
                    "heat": f"{band} ({found['band_labels'][band]})",
                    "R 2016-21": r["r_2016-21"], "trades 16-21": r["trades_2016-21"],
                    "R 2022-26": r["r_2022-26"], "trades 22-26": r["trades_2022-26"],
                    "verdict": r["verdict"], "plan": r["plan"],
                })  # fmt: skip
    return {
        "heading": heading,
        "rules": doc.replace("\n- ", "\n\n- "),
        "settings": rows,
        "heat": heat_rows,
        "heat_note": None
        if heat_key
        else (
            "No per-heat result for this one: it was tested as a condition or a variant (see "
            "How it was tested and the research report in the data repo)."
        ),
    }


def how_tested(cfg, data_dir: Path) -> dict[str, Any]:
    """The grade rules in config in words, the size per grade, and the write-up."""
    rules = quality_rules(cfg.grading)
    setups = []
    for row in rules.to_dict("records"):
        points = row["Points (one each)"]
        setups.append({
            "setup": row["Setup"], "grades": row["Grade by points"],
            "points": points.split("; ") if points else [],
            "buy": row["When to buy"], "stop": row["Stop"], "exit": row["Exit"],
        })  # fmt: skip
    live = bool(cfg.grading.get("quality_enabled"))
    caption = (
        ("Live: the pushes grade with these points. " if live else "Not live yet ")
        + (
            ""
            if live
            else "(config `grading.quality_enabled` is off; the pushes still use the "
            "scorecards under Grades). "
        )
        + "Size per grade: "
        + ", ".join(
            f"{g} not traded" if m == 0 else f"{g} {m:g}x your risk per trade"
            for g, m in cfg.grading["risk_mult"].items()
        )
        + ". Read straight from config, so it stays right when the rules change."
    )
    write_up = Path(data_dir) / "docs" / "research" / "how-we-test.md"
    return {
        "setups": setups,
        "caption": caption,
        "write_up": write_up.read_text(encoding="utf-8") if write_up.is_file() else None,
    }


def study_notes(data_dir: Path) -> list[Path]:
    """The research write-ups (docs/research/*.md): dated studies newest first, then others."""
    return sorted(
        (Path(data_dir) / "docs" / "research").glob("*.md"),
        key=lambda p: (p.stem[:1].isdigit(), p.stem),
        reverse=True,
    )


PUSH_TEXT = {"full": "full block", "line": "one line", "count": "saved and counted only"}


def study_grades(cfg, data_dir: Path) -> dict[str, Any]:
    """The grading rules per strategy (entry, stop, exit, bands, base, points per feature),
    the size and push per grade, the history behind each grade, the costs, the report."""
    rules = cfg.grading
    path = Path(data_dir) / rules["stats_file"]
    found = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    sizes = [
        {"Grade": g, "Size (x your risk per trade)": m,
         "Push": PUSH_TEXT.get(rules["push"][g], rules["push"][g])}
        for g, m in rules["risk_mult"].items()
    ]  # fmt: skip
    strategies = []
    for name, rule in rules["strategies"].items():
        history = found.get("strategies", {}).get(name, {}).get("grades", {})
        strategies.append(
            {
                "title": " / ".join(report.SCAN_LABELS.get(s, s) for s in rule["live_scans"]),
                "entry": notify.ENTRY_TEXT.get(rule["entry"], rule["entry"]),
                "stop": f"{rule['stop_adr']:g} ADR under the entry",
                "exit": f"at the close {rule['hold_sessions']} sessions after the entry",
                "bands": " · ".join(f"{grade} from {cut:+.2f}R" for cut, grade in rule["bands"]),
                "base": f"{rule['base']:+.3f}R",
                "history": [
                    {
                        "Grade": g,
                        "Trades": h.get("trades"),
                        "Win %": h.get("win_pct"),
                        "Mean R": h.get("mean_r"),
                        "Median R": h.get("median_r"),
                        "Years +": f"{h.get('years_pos')}/{h.get('years')}",
                        "Worst year R": h.get("worst_year_r"),
                        "Days held (median)": h.get("days_median"),
                    }
                    for g, h in history.items()
                ],  # fmt: skip
                "features": feature_points(rule["features"]).to_dict("records"),
            }
        )
    costs = rules["costs"]
    slips = ", ".join(f"${lo / 1e6:g}M+: {pct:g} %" for lo, pct in costs["slip_by_dvol"])
    research = Path(data_dir) / str(found.get("source", ""))
    return {
        "period": found.get("period"),
        "source": found.get("source"),
        "sizes": sizes,
        "ungraded": rules["ungraded"],
        "strategies": strategies,
        "costs": [
            f"Commission {costs['commission_pct']:g} % per order",
            f"Slippage by the day's dollar volume: {slips}; x{costs['open_mult']:g} at the "
            f"open, x{costs['offhours_mult']:g} outside regular hours",
            f"A filled stop slips {costs['stop_slip_adr']:g} ADR",
        ],
        "report": research.read_text(encoding="utf-8")
        if found and found.get("source") and research.is_file()
        else None,
    }


# --- Entries & exits (the minute study) and Market regime

ENTRIES_CAPTION = (
    "Every strategy bought (or shorted) at different times on minute bars, each entry picked "
    "only with what was known at that minute, then run with every exit. R is per unit of the "
    "starting risk (capped at 20 per trade in the means). Stops: lod = the low so far (high "
    "for shorts), adr = 1 ADR, order = the setup's own stop, signal = the signal day's "
    "low/high. Facts, not advice."
)
DEFAULT_EXITS = ("hold_1d", "hold_5d", "hold_21d", "trail_ema9", "q3_ma20")
TRADE_COLUMNS = ["session_date", "ticker", "entry", "stop_rule", "side", "price", "stop",
                 "risk_adr", "r_0d", "r_hold_5d", "r_hold_21d", "r_trail_ema9", "pnl_hold_5d",
                 "pnl_hold_21d"]  # fmt: skip


def exits_of(table: pd.DataFrame) -> list[str]:
    return [c[2:] for c in table.columns if c.startswith("R_")]


def entries_10y(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """The 10-year minute study: (summary, by year), or None when not published."""
    ten = release(data_dir, "intraday-10y", "intraday_summary_10y*.parquet")
    files = [ten / "intraday_summary_10y.parquet", ten / "intraday_summary_10y_by_year.parquet"]
    if not all(f.exists() for f in files):
        return None
    return pd.read_parquet(files[0]), pd.read_parquet(files[1])


def by_year_table(by_year: pd.DataFrame, strategy: str, exit_name: str) -> pd.DataFrame:
    """Mean R per year for one exit, per entry and stop (groups of 20+ trades)."""
    part = by_year[(by_year["strategy"] == strategy) & (by_year["trades"] >= 20)]
    table = part.pivot_table(index=["entry", "stop_rule"], columns="year", values=f"R_{exit_name}")
    table.columns = [str(c) for c in table.columns]
    return table.reset_index()


def entries_2y_splits(data_dir: Path) -> list[str]:
    """The 2-year minute study's splits ("none" first); [] when not published."""
    two = release(data_dir, "intraday-2y", "summary_*.parquet")
    if not (two / "summary_none.parquet").exists():
        return []
    names = [p.name.removeprefix("summary_").removesuffix(".parquet")
             for p in sorted(two.glob("summary_*.parquet"))]  # fmt: skip
    return ["none", *[n for n in names if n != "none"]]


def entries_2y(data_dir: Path, group: str) -> pd.DataFrame:
    path = remote_data.CACHE / "intraday-2y" / f"summary_{group}.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def entries_table(table: pd.DataFrame, group: str, shown: list[str], min_trades: int):
    """Every entry and stop with the picked exits' win rate and R (groups of `min_trades`+)."""
    columns = ["strategy", "entry", "stop_rule", *([] if group == "none" else [group])]
    columns += ["trades", "stopped_same_day%"]
    for e in shown:
        columns += [f"win_{e}%", f"R_{e}"]
    table = table[table["trades"] >= min_trades]
    return table[[c for c in columns if c in table]]


def strategy_trades(data_dir: Path, strategy: str, limit: int = 2000) -> pd.DataFrame:
    """One strategy's minute-study trades (2 years), newest first."""
    path = release(data_dir, "intraday-2y", f"{strategy}.parquet") / f"{strategy}.parquet"
    if not path.exists():
        return pd.DataFrame()
    rows = pd.read_parquet(path)
    rows = rows[[c for c in TRADE_COLUMNS if c in rows]]
    return rows.sort_values("session_date", ascending=False).head(limit)


REGIME_FILES = ["regime_daily", "regime_minute", "regime_minute_by_year", "regime_daily_study",
                "regime_daily_study_by_year"]  # fmt: skip
REGIME_CAPTION = (
    "Would skipping trades in a bad market have helped? Each trade gets the regime known "
    "before it was entered (the prior close; for entries at a signal's close, that close) and "
    "each filter keeps or skips it. Market Light = your rules (QQQ trend, breadth, the Sunday "
    "scan count) rebuilt from 10 years of daily bars; ETFs and funds left out. Mean R capped "
    "at 20 per trade. Facts, not advice."
)


def regime(data_dir: Path) -> Path | None:
    """The regime-10y release folder, or None when it isn't published."""
    folder = release(data_dir, "regime-10y", "*.parquet")
    return folder if all((folder / f"{n}.parquet").exists() for n in REGIME_FILES) else None


def light_mix(folder: Path) -> pd.DataFrame:
    """Market Light per year, % of sessions."""
    daily = pd.read_parquet(folder / "regime_daily.parquet")
    daily["year"] = pd.to_datetime(daily["session_date"]).dt.year
    mix = pd.crosstab(daily["year"], daily["light"].fillna("n/a"), normalize="index") * 100
    mix.columns = [str(c) for c in mix.columns]
    return mix.round(0).reset_index()


def regime_view(folder: Path, source: str, strategy: str | None, exit_name: str | None,
                entry: str | None = None, stop: str | None = None) -> dict[str, Any]:  # fmt: skip
    """Each filter's effect for one strategy (and, minute study, entry and stop): all years,
    and mean R year by year, with the choices for the pickers."""
    name = "regime_minute" if source == "minute" else "regime_daily_study"
    table = pd.read_parquet(folder / f"{name}.parquet")
    by_year = pd.read_parquet(folder / f"{name}_by_year.parquet")
    exit_names = exits_of(table)
    strategies = sorted(table["strategy"].unique())
    strategy = strategy if strategy in strategies else strategies[0]
    exit_name = exit_name if exit_name in exit_names else exit_names[0]
    part = table[table["strategy"] == strategy]
    year_part = by_year[by_year["strategy"] == strategy]
    entries, stops = [], []
    if source == "minute":
        entries = sorted(part["entry"].unique())
        entry = entry if entry in entries else entries[0]
        stops = sorted(part.loc[part["entry"] == entry, "stop_rule"].unique())
        stop = stop if stop in stops else stops[0]
        part = part[(part["entry"] == entry) & (part["stop_rule"] == stop)]
        year_part = year_part[(year_part["entry"] == entry) & (year_part["stop_rule"] == stop)]
    base = part.loc[part["filter"] == "all", "trades"]
    view = part[["filter", "trades", f"R_{exit_name}", f"win_{exit_name}%"]].copy()
    if len(base):
        view.insert(2, "kept_%", view["trades"] / base.iloc[0] * 100)
    pivot = year_part.pivot_table(index="year", columns="filter", values=f"R_{exit_name}")
    pivot.columns = [str(c) for c in pivot.columns]
    return {
        "strategies": strategies, "strategy": strategy, "exits": exit_names, "exit": exit_name,
        "entries": entries, "entry": entry, "stops": stops, "stop": stop,
        "filters": view.sort_values(f"R_{exit_name}", ascending=False).round(2),
        "by_year": pivot.round(2).reset_index(),
    }  # fmt: skip


# --- Live results


LIVE_CAPTION = (
    "Each live A+ / A / B signal played out by its study plan: bought at the plan's price, out "
    "at the stop (checked from the next session) or at the close after the plan's sessions, "
    "net of the study's cost. MA-surf is a buy-stop at the pivot the next session (no trade "
    "when it doesn't fill), out at the stop or the first close under the 20-day MA. 'Below "
    "the study' needs {n}+ closed trades and both the mean R "
    "and the win rate clearly under the study's; until then it says 'too few trades yet'."
)


def live_grades(data_dir: Path, bars_of) -> dict[str, Any] | None:
    """Live A+ / A / B signals by their study plan, next to the study; your trades against
    the plan of the signal they came from. None when there are no live graded signals.
    `bars_of(ticker)`: its daily bars."""
    cands = outcomes.load_candidates(data_dir)
    graded = cands[cands["grade"].isin(live_tracking.LIVE_GRADES)] if "grade" in cands else cands
    monthly = sorted((Path(data_dir) / "docs" / "live-tracking").glob("*.md"))
    newest = monthly[-1].stem if monthly else None
    if graded.empty:
        return {"compare": None, "gaps": None, "signals": None, "monthly": newest}
    tickers = sorted(set(graded["ticker"]))
    bars = pd.concat([bars_of(t).assign(ticker=t) for t in tickers], ignore_index=True)
    exit_rules = live_tracking.exit_rules(load_config().grading)
    results = live_tracking.plan_results(graded, bars, exit_rules)
    trades = dashboard.latest_journal(data_dir)
    if "r_multiple" in trades:
        trades = trades.dropna(subset=["r_multiple"])
    gaps = live_tracking.execution(results, trades, sorted(bars["session_date"].unique()))
    return {
        "compare": live_tracking.compare(results).round(2),
        "gaps": gaps.round(2),
        "signals": results.round(2),
        "monthly": newest,
    }


def outcome_stats(data_dir: Path, minimum: int) -> tuple[pd.DataFrame, int]:
    """Outcome statistics of the live signals per scan, and how many outcomes there are."""
    found = stats.load_outcomes(data_dir)
    return stats.summarize(outcomes.load_candidates(data_dir), found, minimum), len(found)


def graded_signals(data_dir: Path) -> pd.DataFrame:
    """The signals you graded, with what happened 5/10/20/60 sessions after."""
    notes = dashboard.notes_state(data_dir)
    graded = notes[notes["kind"] == "signal"]
    if graded.empty:
        return graded
    cands = outcomes.load_candidates(data_dir)
    found = stats.load_outcomes(data_dir)
    keep = ["signal_id", "session_date", "scan", "ticker", "tier"]
    view = graded.merge(
        cands[[c for c in keep if c in cands]].drop_duplicates("signal_id"),
        left_on="ref_id",
        right_on="signal_id",
        how="left",
    )
    if not found.empty:
        wide = found.pivot_table(index="signal_id", columns="horizon", values="close_ret_pct")
        wide.columns = [f"ret_{h}d" for h in wide.columns]
        view = view.merge(wide, left_on="ref_id", right_index=True, how="left")
    return view.drop(columns=[c for c in ("kind", "signal_id") if c in view])


def best(table: pd.DataFrame, min_trades: int) -> pd.DataFrame:
    """The best entry, stop and exit per strategy (`intraday_study.best`)."""
    return intraday_study.best(table, min_trades)
