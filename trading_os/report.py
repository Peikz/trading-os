"""Daily Markdown report per run, written to the private data repo (reports/YYYY/<stem>.md).

GitHub renders Markdown and relative images in a private repo, so each run can be read on
a phone in the GitHub app: market lines, every scan's hits as a table, and the before-shot
charts of pushed candidates inline. A report is written once and never rewritten.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import clock, context, notify
from trading_os.notify import SCAN_LABELS, SLOT_LABELS
from trading_os.store import RunContext

# (header, column, format) per scan. Formats: python format spec, or money / shares / flag /
# text / int. Columns missing from a run are left blank.
_MOVE = [("Chg %", "chg_pct", "+.1f"), ("Volume", "volume", "shares")]
COLUMNS: dict[str, list[tuple[str, str, str]]] = {
    "ep_day": [
        ("Gap %", "gap_pct", "+.1f"),
        ("Chg %", "chg_pct", "+.1f"),
        ("RVOL", "rvol50", ".1f"),
        ("$ vol", "dollar_volume", "money"),
        ("Mcap", "market_cap", "money"),
        ("Earnings", "earnings_flag", "flag"),
    ],
    "ep9m": [
        *_MOVE,
        ("RVOL", "rvol50", ".1f"),
        ("$ vol", "dollar_volume", "money"),
        (">MA50", "above_ma50", "flag"),
        (">MA200", "above_ma200", "flag"),
    ],
    "ep_ah": [
        ("AH %", "ah_change_pct", "+.1f"),
        ("AH vol", "ah_volume", "shares"),
        ("Mcap", "market_cap", "money"),
        ("Earnings", "earnings_flag", "flag"),
    ],
    "ep_am": [
        ("Gap %", "gap_pct", "+.1f"),
        ("Chg %", "chg_pct", "+.1f"),
        ("RVOL at time", "rvol_at_time_tv", ".1f"),
        ("$ vol", "dollar_volume", "money"),
        ("Mcap", "market_cap", "money"),
        ("Earnings", "earnings_flag", "flag"),
    ],
    "ep9m_pace": [
        *_MOVE,
        ("Pace", "proj_volume", "shares"),
        ("RVOL at time", "rvol_at_time_tv", ".1f"),
        ("$ vol", "dollar_volume", "money"),
    ],
    "ep_pm": [
        ("PM %", "pm_change_pct", "+.1f"),
        ("PM vol", "pm_volume", "shares"),
        ("PM $ vol", "pm_dollar_volume", "money"),
        ("Mcap", "market_cap", "money"),
        ("Earnings", "earnings_flag", "flag"),
    ],
    "ep9m_early": [("PM gap %", "pm_gap_used", "+.1f"), ("PM vol", "pm_volume", "shares")],
    "watchlist_gappers": [("PM gap %", "pm_gap_used", "+.1f"), ("PM vol", "pm_volume", "shares")],
    "mb_up": [*_MOVE, ("Prior vol", "prev_volume", "shares"), ("Close loc", "close_loc", ".2f")],
    "mb_down": [*_MOVE, ("Prior vol", "prev_volume", "shares"), ("Close loc", "close_loc", ".2f")],
    "parabolic_short": [
        ("Gain <=10d %", "hist_gain_max_pct", "+.0f"),
        ("Up days", "hist_consec_up", "int"),
        ("MA10 dist (ADR)", "hist_dist_ma10_adr", ".1f"),
    ],
    "parabolic_long": [
        ("Drop <=10d %", "hist_drop_max_pct", ".0f"),
        ("Down days", "hist_consec_down", "int"),
        ("MA10 dist (ADR)", "hist_dist_ma10_adr", ".1f"),
    ],
    "breakout_watch": [
        ("Pivot", "pivot", ".2f"),
        ("Stop", "order_stop", ".2f"),
        ("Risk ADR", "risk_adr", ".2f"),
        ("Base d", "base_len", "int"),
        ("Contractions %", "contraction_depths", "text"),
        ("B1-B5", "b_flags", "text"),
    ],
    "qm_gainers": [
        ("Lists", "qm_lists", "text"),
        ("1M %", "ret_22", "+.0f"),
        ("3M %", "ret_63", "+.0f"),
        ("6M %", "ret_126", "+.0f"),
        ("ADR %", "adr20_pct", ".1f"),
        ("$ vol", "avg_dollar_volume_20d", "money"),
        ("CATS", "cats", ".1f"),
    ],
    "growth_bucket_1": [
        ("Rev % q", "rev_growth_q", "+.0f"),
        ("Rev % q-1", "rev_growth_q_prev", "+.0f"),
        ("TTM rev", "revenue_ttm", "money"),
        ("Quarters", "growth_quarters_checked", "int"),
    ],
    "growth_bucket_2": [
        ("EPS % q", "eps_growth_q", "+.0f"),
        ("EPS % q-1", "eps_growth_q_prev", "+.0f"),
        ("Rev % q", "rev_growth_q", "+.0f"),
        ("Rev % q-1", "rev_growth_q_prev", "+.0f"),
    ],
    "tight_bases": [
        ("From 52w high %", "pct_from_52w_high", "+.1f"),
        ("Range / ADR", "tightness_adr", ".2f"),
        ("ADR %", "hist_adr20_pct", ".1f"),
        ("CATS", "cats", ".1f"),
    ],
}
_PLAN = [
    ("Buy", "plan_entry", ".2f"),
    ("Stop", "plan_stop", ".2f"),
    ("Shares", "plan_shares", "int"),
    ("Risk $", "plan_risk_usd", ".0f"),
]
for _scan in ("ep_day", "ep9m", "ep9m_pace", "ep_pm", "ep9m_early", "watchlist_gappers"):
    COLUMNS[_scan] = [*COLUMNS[_scan], *_PLAN]
COLUMNS["breakout_watch"] = [*COLUMNS["breakout_watch"], *_PLAN[2:]]
COLUMNS["breakout_trigger"] = [("Chg %", "chg_pct", "+.1f"), *COLUMNS["breakout_watch"]]
COLUMNS["pivot_watch"] = [
    ("Chg %", "chg_pct", "+.1f"),
    ("Price", "close", ".2f"),
    ("Pivot", "pivot", ".2f"),
    ("vs pivot %", "pivot_dist_pct", "+.1f"),
    ("Stop", "order_stop", ".2f"),
    ("RVOL at time", "rvol_at_time_tv", ".1f"),
    ("Levels from", "pivot_from_session", "text"),
    *_PLAN,
]


def cell(value: Any, fmt: str) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    if fmt == "money":
        return f"${value / 1e9:.1f}B" if value >= 1e9 else f"${value / 1e6:.0f}M"
    if fmt == "shares":
        return f"{value / 1e6:.1f}M"
    if fmt == "flag":
        return "yes" if bool(value) else ""
    if fmt == "int":
        return str(int(value))
    if fmt == "text":
        return str(value)
    return format(value, fmt)


def _b_flags(row: Mapping[str, Any]) -> str:
    return "".join(str(i) if bool(row.get(f"b{i}")) else "-" for i in range(1, 6))


def scan_table(scan: str, hits: pd.DataFrame, max_rows: int) -> list[str]:
    columns = [("Rank", "rank", "int"), ("Ticker", "ticker", "text"), ("Tier", "tier", "text")]
    if "grade" in hits:  # the study grade and why (Emil, 22 Oct 2026)
        columns += [("Grade", "grade", "text"), ("Why", "grade_why", "text")]
        if "grade_points" in hits and hits["grade_points"].notna().any():
            columns.append(("Points", "grade_points", "text"))
    if "heat_tag" in hits:
        columns.append(("Heat", "heat_tag", "text"))
    if "si_tag" in hits and hits["si_tag"].notna().any():  # Emil, 25 Oct 2026
        columns.append(("Short", "si_tag", "text"))
    if "ibd_tag" in hits and hits["ibd_tag"].notna().any():  # tracked, not a rule (`ibd`)
        columns.append(("IBD", "ibd_tag", "text"))
    columns += COLUMNS.get(scan, [])
    lines = [
        "| " + " | ".join(h for h, _, _ in columns) + " |",
        "|" + "---|" * len(columns),
    ]
    hits = notify.best_first(hits)
    shown = hits if max_rows <= 0 else hits.head(max_rows)
    for row in shown.to_dict("records"):
        if scan.startswith("breakout_"):
            row["b_flags"] = _b_flags(row)
        lines.append("| " + " | ".join(cell(row.get(c), f) for _, c, f in columns) + " |")
    if 0 < max_rows < len(hits):
        lines.append(f"\n_{len(hits) - max_rows} more in the candidates file._")
    return lines


def _md_text(text: str) -> str:
    return text.replace("[", r"\[").replace("]", r"\]")


def fact_lines(scan: str, hits: pd.DataFrame) -> list[str]:
    """One bullet per pushed name with the facts behind it, the headline linked below."""
    if scan not in (*context.EP_SCANS, *context.BREAKOUT_SCANS):
        return []
    if "ctx_done" not in hits:
        return []
    hits = hits[hits["ctx_done"].fillna(False).astype(bool)]  # only names with facts
    lines = []
    for row in hits.to_dict("records"):
        if not context.has_context(row):
            continue
        parts, found = context.parts(row, scan), context.headline(row, max_chars=200)
        if not parts and found is None:
            continue
        lines.append(f"- **{row['ticker']}**" + (f" · {' · '.join(parts)}" if parts else ""))
        if found is not None:
            title, where = found
            url = row.get("ctx_news_url")
            text = f"[{_md_text(title)}]({url})" if isinstance(url, str) and url else title
            lines.append(f"  - {text}" + (f" ({where})" if where else ""))
    return lines


# Jump links on GitHub, so a long report needs no scrolling (Emil, 25 Oct 2026). GitHub keeps
# `name` anchors (as user-content-…) and still scrolls to `#name`.
TOP_ANCHOR = '<a name="top"></a>'
BACK_TO_TOP = "[↑ Top](#top)"


def _anchor(scan: str) -> str:
    return f'<a name="scan-{scan}"></a>'


def jump_list(results: Mapping[str, pd.DataFrame], names: list[str], market: bool) -> list[str]:
    """`Jump to: Market · EP-Day (3) · …`, in the order the scans appear."""
    links = ["[Market](#market)"] if market else []
    links += [f"[{SCAN_LABELS.get(n, n)} ({len(results[n])})](#scan-{n})" for n in names]
    return [f"Jump to: {' · '.join(links)}"] if links else []


def build(
    ctx: RunContext,
    results: Mapping[str, pd.DataFrame],
    selected: Mapping[str, pd.DataFrame],
    header_lines: list[str],
    charts: Mapping[tuple[str, str], Path],
    report_path: Path,
    max_rows: int,
) -> str:
    title = f"# Trading OS · {SLOT_LABELS[ctx.slot]} {ctx.session.isoformat()}"
    kind = f"{ctx.run_kind}{', forced' if ctx.forced else ''}"
    when = clock.both_times(ctx.run_ts).replace("NY", "New York").replace("CPH", "Copenhagen")
    run_line = f"_Run {ctx.run_ts:%Y-%m-%d %H:%M} UTC ({when}) · {kind}_"
    lines = [TOP_ANCHOR, title, "", run_line, ""]
    pushed = [n for n in results if n in selected]
    logged = [n for n in results if n not in selected]
    lines += [*jump_list(results, pushed + logged, bool(header_lines)), ""]
    if header_lines:
        lines += ["## Market", "", *[f"- {line}" for line in header_lines], ""]
    for heading, names in (("Pushed scans", pushed), ("Saved only", logged)):
        if not names:
            continue
        lines += [f"## {heading}", ""]
        for name in names:
            hits = results[name]
            label = SCAN_LABELS.get(name, name)
            alert = int((hits["tier"] == "alert").sum()) if len(hits) and "tier" in hits else 0
            lines += [_anchor(name), f"### {label} — {len(hits)} hits ({alert} alert)", ""]
            if hits.empty:
                lines += ["_No hits._", "", BACK_TO_TOP, ""]
                continue
            lines += [*scan_table(name, hits, max_rows), ""]
            facts = fact_lines(name, selected.get(name, hits.iloc[:0]))
            if facts:
                lines += ["Facts (not a grade):", "", *facts, ""]
            for row in selected.get(name, pd.DataFrame(columns=["ticker"])).to_dict("records"):
                chart = charts.get((name, row["ticker"]))
                if chart is not None:
                    link = Path(os.path.relpath(chart, report_path.parent)).as_posix()
                    lines += [f"![{row['ticker']} {label}]({link})", ""]
            lines += [BACK_TO_TOP, ""]
    return "\n".join(lines).rstrip() + "\n"


def write(path: Path, text: str) -> Path | None:
    """Write once; an existing report is never replaced."""
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.rename(path)
    return path
