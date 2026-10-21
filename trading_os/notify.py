"""ntfy.sh notifications (SPEC §8): one message per job, never one per ticker.

The topic is a secret. Messages go straight to ntfy and are never printed to logs.

Laid out for a phone: the title carries the counts, the market lines come first, then one
section per scan with a short block per stock (the alert, entry and size, then the facts
wrapped to the screen). A stock already shown above gets one line. Scans without alerts share
one line at the end. Tapping the notification opens the run's full report.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from trading_os import context
from trading_os.breadth import LIGHT_ICONS
from trading_os.config import Config
from trading_os.store import RunContext

SLOT_LABELS = {
    "pm": "Pre-market",
    "am": "Intraday 10:15",
    "mid": "Intraday 12:00",
    "close": "Close 15:45",
    "eod": "EOD",
    "ah": "After hours 16:50",
    "weekly": "Weekly",
}
SCAN_LABELS = {
    "ep_pm": "EP-PM",
    "ep9m_early": "EP9M early",
    "watchlist_gappers": "Watchlist gappers",
    "ep_day": "EP-Day",
    "ep_close": "EP close",
    "ep_am": "EP 10:30",
    "ep_ah": "EP-AH",
    "ep9m": "EP9M",
    "ep9m_pace": "EP9M pace",
    "pivot_watch": "BO pivot",
    "mb_up": "MB up",
    "mb_down": "MB down",
    "parabolic_short": "Parabolic short",
    "parabolic_long": "Parabolic long",
    "breakout_watch": "BO-Watch",
    "breakout_trigger": "Breakout",
    "qm_gainers": "QM gainers",
    "growth_bucket_1": "Growth 1",
    "growth_bucket_2": "Growth 2",
    "tight_bases": "Tight bases",
    "luk_flush": "Luk flush",
    "ma_surf": "MA-surf",
}
# An icon per section, so the eye finds the setup type (no meaning beyond the type).
SECTION_ICONS = {
    "ep_day": "⚡",
    "ep_close": "⚡",
    "ep_am": "⚡",
    "ep_ah": "🌙",
    "luk_flush": "🌊",
    "ma_surf": "🏄",
    "parabolic_long": "🪂",
    "parabolic_short": "🎢",
    "ep9m": "📊",
    "ep9m_pace": "⏱️",
    "ep_pm": "🌅",
    "ep9m_early": "🌅",
    "watchlist_gappers": "👀",
    "pivot_watch": "🎯",
    "breakout_trigger": "🚀",
    "breakout_watch": "🎯",
    "qm_gainers": "🏆",
    "growth_bucket_1": "📈",
    "growth_bucket_2": "📈",
}
# What the B-flag squares stand for, in order (SPEC §6.4); 🟩 passed, 🟥 failed.
FLAG_LEGENDS = {
    "breakout_trigger": "B: move · base · trend · tight · trigger",
    "breakout_watch": "B: move · base · trend · tight",
}
# Short names for the notification title.
TITLE_LABELS = {
    "ep_day": "EP",
    "breakout_trigger": "BO",
    "breakout_watch": "Watch",
    "watchlist_gappers": "Gappers",
    "pivot_watch": "Pivot",
    "qm_gainers": "QM",
}

# The percent shown on each line: the move that triggered the scan.
PCT_COLUMNS = {
    "ep_pm": "pm_change_pct",
    "ep9m_early": "pm_gap_used",
    "watchlist_gappers": "pm_gap_used",
    "ep_day": "gap_pct",
    "ep_close": "gap_pct",
    "ep_am": "gap_pct",
    "ep_ah": "ah_change_pct",
    "ep9m": "chg_pct",
}

# Study grades (SPEC §11.17): when to enter, per the grading study's plan (entry rule).
ENTRY_TEXT = {
    "close": "buy 15:45-15:58 NY (21:45 CPH)",
    "t_1200": "buy after the 12:00 check (18:00 CPH)",
    "next_1030": "buy next session ~10:30 NY (16:30 CPH)",
    "pm_0915": "buy pre-market ~09:15 NY (15:15 CPH)",
    "ah_1800": "buy after hours ~18:00 NY (00:00 CPH)",
    "t_1015": "buy after the 10:15 check (16:15 CPH)",
    "t_1030": "buy ~10:30 NY (16:30 CPH)",
    "ah_1645": "buy after hours now, before 17:00 NY (23:00 CPH, Saxo's cutoff)",
}
GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}
# The plan of a scan pushed without a grade (`push_ungraded`): the study's entry and exit.
UNGRADED_PLANS = {
    "ma_surf": [
        "C (no grade) · from 10:00 NY (16:00 CPH)",
        "over the pivot: buy · under it: buy-stop at the pivot",
        "out on a close under the 20-day MA",
    ],
    "breakout_watch": ["C (no grade) · buy-stop at the pivot"],
    "parabolic_long": [
        "C (no grade) · study plan: buy at the open",
        "stop 1 ADR under · out at the close after 21 sessions",
    ],
    "parabolic_short": [
        "C (no grade) · study plan: short ~10:30 NY (16:30 CPH)",
        "stop over the signal day's high · cover on a close over the 20-day MA",
    ],
}


def premarket_line(row: Mapping[str, Any]) -> str | None:
    """`PM 15.80 +3.1% · +3.3% vs pivot`, and a warning when it is up more than 1 ADR
    pre-market (the study's MA-surf plan doesn't buy a stock already up more than its ADR)."""
    if row.get("carried_from") != "eod":
        return None
    price, change = row.get("pm_price"), row.get("pm_change_pct")
    if price is None or pd.isna(price):
        return "PM: no trade yet"
    text = f"PM {price:.2f}" + ("" if change is None or pd.isna(change) else f" {change:+.1f}%")
    pivot = row.get("pivot")
    if pivot is not None and not pd.isna(pivot) and pivot > 0:
        text += f" · {(price / pivot - 1) * 100:+.1f}% vs pivot"
    close, adr = row.get("close"), row.get("adr20_usd")
    known = close is not None and adr is not None and not pd.isna(adr) and adr > 0
    if known and price - close > adr:
        text += " · ⚠️ up > 1 ADR"
    return text


WIDTH = 40  # characters per line that fit a phone notification without wrapping
INDENT = "   "
NTFY_LIMIT = 3900  # ntfy turns longer messages into attachments (4096 bytes)


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    click: str | None = None  # opened when the notification is tapped


@dataclass(frozen=True)
class Line:
    role: str  # head | gap | section | hit | plan | fact | news | note
    text: str


def pushes_now(scan, slot: str | None) -> bool:
    """A scan pushes in its own run, or in the run its `push_slot` names (BO-Watch, MA-surf
    and the parabolics: found at the close, pushed the next morning pre-market)."""
    if scan.action != "push":
        return False
    later = scan.params.get("push_slot")
    return slot is None or later is None or later == slot


def select_for_push(
    results: Mapping[str, pd.DataFrame], cfg: Config, slot: str | None = None
) -> dict[str, pd.DataFrame]:
    """Hits that go into the message: push scans only, push tier only, top N by rank."""
    limit = cfg.notify["max_tickers_per_scan"]
    selected = {}
    for name, hits in results.items():
        scan = cfg.scans[name]
        if not pushes_now(scan, slot):
            continue
        eligible = hits
        if "push_tier" in scan.params:
            eligible = hits[hits["tier"] == scan["push_tier"]]
        if graded(cfg, eligible):
            # Study grades (SPEC §11.17): A+/A get a full block, B one line, C is saved and
            # counted in the closing line.
            mode = push_modes(cfg, eligible, scan)
            order = eligible.assign(_g=eligible["grade"].map(GRADE_RANK).fillna(9))
            keys = [k for k in ("_g", "grade_score", "rank") if k in order]
            order = order.sort_values(keys, ascending=[k != "grade_score" for k in keys])
            full = order[mode.loc[order.index] == "full"].head(limit)
            line = order[mode.loc[order.index] == "line"].head(limit)
            selected[name] = pd.concat(
                [full.assign(push_partial=False), line.assign(push_partial=True)]
            ).drop(columns="_g")
            continue
        if "push_if_all" in scan.params:
            # A breakout trigger with B1-B4 gets a full block; the top B5-only ones get one
            # line each below (`push_partial`), so trigger days stay visible without the noise.
            full = _all_pass(eligible, scan["push_if_all"])
            top = eligible[full].sort_values("rank").head(limit).assign(push_partial=False)
            rest = eligible[~full].sort_values("rank").head(scan.params.get("partial_top_n", 0))
            selected[name] = pd.concat([top, rest.assign(push_partial=True)])
            continue
        selected[name] = eligible.sort_values("rank").head(limit)
    return selected


def graded(cfg: Config, hits: pd.DataFrame) -> bool:
    return bool(cfg.grading["enabled"]) and "grade" in hits


def push_modes(cfg: Config, hits: pd.DataFrame, scan=None) -> pd.Series:
    """full / line / count per hit, from its grade (config `grading.push`). A scan with
    `push_ungraded` (Emil's MA-surf) shows its C hits in full as well."""
    modes = cfg.grading["push"]
    out = hits["grade"].fillna("C").map(lambda g: modes.get(g, "count"))
    if scan is not None and scan.params.get("push_ungraded"):
        out = out.replace("count", "full")
    return out


def grade_lines(row: Mapping[str, Any]) -> list[str]:
    """`🅰 Study A · +0.52R`, the plan's timing and exit, and the history behind the grade."""
    grade = row.get("grade")
    if grade is None or pd.isna(grade) or grade == "C":
        return []
    score = row.get("grade_score")
    why = str(row.get("grade_why") or "")
    if "quality points" in why:  # a quality count: show the points, not R
        head = f"🅰 Study {grade} · {why}"
    else:
        tail = "" if score is None or pd.isna(score) else f" · {score:+.2f}R"
        head = f"🅰 Study {grade}" + tail
    out = [head]
    when = ENTRY_TEXT.get(str(row.get("grade_entry_rule")), "")
    hold = row.get("grade_hold_sessions")
    median = row.get("grade_stat_days_median")
    exit_text = ""
    if hold is not None and not pd.isna(hold):
        exit_text = f"out at the close after {int(hold)} sessions"
        if median is not None and not pd.isna(median):
            exit_text += f" (median {median:.0f})"
    out += wrap([p for p in (when, exit_text) if p], WIDTH - len(INDENT))
    trades = row.get("grade_stat_trades")
    if trades is not None and not pd.isna(trades):
        years = row.get("grade_stat_years")
        tail = ""
        if years is not None and not pd.isna(years) and years:
            tail = f" · {int(row['grade_stat_years_pos'])}/{int(years)} yrs +"
        out.append(
            f"📚 {int(trades):,} trades · {row['grade_stat_win_pct']:.0f}% win · "
            f"avg {row['grade_stat_mean_r']:+.2f}R · med {row['grade_stat_median_r']:+.1f}R{tail}"
        )
    return out


def later_counts(results: Mapping[str, pd.DataFrame], cfg: Config, slot: str) -> list[str]:
    """`BO-Watch 3 · MA-surf 1`: alert-tier hits held for the pre-market push."""
    out = []
    for name, hits in results.items():
        scan = cfg.scans[name]
        if scan.action != "push" or pushes_now(scan, slot) or hits.empty:
            continue
        eligible = hits[hits["tier"] == scan["push_tier"]] if "push_tier" in scan.params else hits
        if len(eligible):
            out.append(f"{SCAN_LABELS.get(name, name)} {len(eligible)}")
    return out


def c_counts(
    results: Mapping[str, pd.DataFrame], cfg: Config, slot: str | None = None
) -> list[str]:
    """`EP close 2 · Breakout 3`: alert-tier hits graded C (saved, not pushed)."""
    out = []
    for name, hits in results.items():
        scan = cfg.scans[name]
        if not pushes_now(scan, slot) or hits.empty or not graded(cfg, hits):
            continue
        eligible = hits[hits["tier"] == scan["push_tier"]] if "push_tier" in scan.params else hits
        n = int((push_modes(cfg, eligible, scan) == "count").sum())
        if n:
            out.append(f"{SCAN_LABELS.get(name, name)} {n}")
    return out


def partial_rows(hits: pd.DataFrame) -> pd.Series:
    """Rows shown as one line only (B5-only triggers)."""
    if "push_partial" not in hits:
        return pd.Series(False, index=hits.index)
    return hits["push_partial"].fillna(False).astype(bool)


def _all_pass(hits: pd.DataFrame, flags: Iterable[str]) -> pd.Series:
    flags = list(flags)
    if not set(flags) <= set(hits.columns):
        return pd.Series(False, index=hits.index)
    return hits[flags].fillna(False).astype(bool).all(axis=1)


def _flag_names(flags: Iterable[str]) -> str:
    """`B1-B4` for b1..b4 in a row, else `B1, B3`."""
    nums = [int(f[1:]) for f in flags]
    if nums == list(range(nums[0], nums[-1] + 1)) and len(nums) > 2:
        return f"B{nums[0]}-B{nums[-1]}"
    return ", ".join(f"B{n}" for n in nums)


# ---------------------------------------------------------------- first line of a stock


def _rvol(x: float) -> str:
    return "?" if x != x else f"{x:.0f}" if x >= 10 else f"{x:.1f}"


def format_hit(row: Mapping[str, Any], pct_column: str = "gap_pct", slot: str = "eod") -> str:
    """`ABCD  +14.2%  RVOL 5.1  $82M  📢`: the scan's move, RVOL, dollar volume, and 📢 when
    earnings came out on the signal session.

    Pre-market lines show pre-market volume and dollar volume, since the day's volume fields
    still hold the prior session then.
    """
    if slot == "pm":
        line = (
            f"{row['ticker']}  {row[pct_column]:+.1f}% PM  vol {row['pm_volume'] / 1e6:.1f}M  "
            f"{_money(row['pm_dollar_volume'])}"
        )
    else:
        line = (
            f"{row['ticker']}  {row[pct_column]:+.1f}%  RVOL {_rvol(row['rvol50'])}  "
            f"{_money(row['dollar_volume'])}"
        )
    return line + ("  📢" if bool(row.get("earnings_flag", False)) else "")


def format_pace(row: Mapping[str, Any]) -> str:
    """`ABCD  +6.2%  4.1M → pace 11M  📢` (volume so far, projected day)."""
    line = (
        f"{row['ticker']}  {row['chg_pct']:+.1f}%  {row['volume'] / 1e6:.1f}M → "
        f"pace {row['proj_volume'] / 1e6:.0f}M"
    )
    return line + ("  📢" if bool(row.get("earnings_flag", False)) else "")


def format_pivot(row: Mapping[str, Any]) -> str:
    """`ABCD  +3.1%  over pivot +0.9%  RVOL 2.3` (RVOL at this time of day)."""
    where = "over" if bool(row["pivot_crossed"]) else "under"
    line = f"{row['ticker']}  {row['chg_pct']:+.1f}%  {where} pivot {row['pivot_dist_pct']:+.1f}%"
    rvol = row.get("rvol_at_time_tv")
    return line + ("" if rvol is None or pd.isna(rvol) else f"  RVOL {_rvol(rvol)}")


def _flags(row: Mapping[str, Any], last: int) -> str:
    """B1..B5 as green (passed) and red (failed) squares: `B🟩🟥🟩🟩🟩`."""
    return "B" + "".join("🟩" if bool(row.get(f"b{i}")) else "🟥" for i in range(1, last + 1))


def format_breakout(row: Mapping[str, Any], scan: str) -> str:
    """Trigger: `ABCD  +2.1%  RVOL 3.9  B1,3,5`. Watch: `ABCD  base 12d  B1-4`. The B-flags
    say which criteria passed; the grade stays the human's."""
    if scan == "breakout_trigger":
        return (
            f"{row['ticker']}  {row['chg_pct']:+.1f}%  RVOL {_rvol(row['trig_rvol'])}  "
            f"{_flags(row, 5)}"
        )
    base = row.get("base_len")
    length = "" if base is None or pd.isna(base) else f"base {int(base)}d  "
    return f"{row['ticker']}  {length}{_flags(row, 4)}"


def format_surf(row: Mapping[str, Any]) -> str:
    """`ABCD  MA10 14d  base 9d`: the MA it surfs, for how many closes, and the base."""
    ma, days, base = (row.get(k) for k in ("surf_ma", "surf_days", "surf_base_len"))
    parts = [str(row["ticker"])]
    if ma is not None and not pd.isna(ma):
        parts.append(f"MA{int(ma)} {int(days)}d" if days is not None and not pd.isna(days) else "")
    if base is not None and not pd.isna(base):
        parts.append(f"base {int(base)}d")
    return "  ".join(p for p in parts if p)


def format_parabolic(row: Mapping[str, Any], scan: str) -> str:
    """`ABCD  -38% in 10d · 4 down · ADR 9%`: the move the scan found and its streak."""
    long = scan == "parabolic_long"
    move = row.get("hist_drop_max_pct" if long else "hist_gain_max_pct")
    streak = row.get("hist_consec_down" if long else "hist_consec_up")
    parts = [str(row["ticker"])]
    if move is not None and not pd.isna(move):
        parts.append(f"{-abs(move) if long else move:+.0f}% in 10d")
    if streak is not None and not pd.isna(streak):
        parts.append(f"{int(streak)} {'down' if long else 'up'}")
    adr = row.get("adr20_pct")
    if adr is not None and not pd.isna(adr):
        parts.append(f"ADR {adr:.0f}%")
    return "  ".join(parts[:2]) + "".join(f" · {p}" for p in parts[2:])


def format_weekly(row: Mapping[str, Any], scan: str) -> str:
    """Weekly list lines: the numbers each list is about."""
    t = row["ticker"]
    if scan == "qm_gainers":
        return (
            f"{t}  {row['ret_22']:+.0f}% / {row['ret_63']:+.0f}% / {row['ret_126']:+.0f}%  "
            f"ADR {row['adr20_pct']:.0f}%"
        )
    rev = _pair(row["rev_growth_q"], row["rev_growth_q_prev"])
    if scan == "growth_bucket_1":
        return f"{t}  rev {rev}  TTM {_money(row['revenue_ttm'])}"
    return f"{t}  EPS {_pair(row['eps_growth_q'], row['eps_growth_q_prev'])}  rev {rev}"


def _first_line(row: Mapping[str, Any], scan: str, slot: str) -> str:
    if row.get("carried_from") == "eod":  # found at last night's close: its own numbers
        slot = "eod"
    if slot == "weekly":
        return format_weekly(row, scan)
    if scan.startswith("breakout_"):
        return format_breakout(row, scan)
    if scan == "ma_surf":
        return format_surf(row)
    if scan.startswith("parabolic_"):
        return format_parabolic(row, scan)
    if scan == "ep9m_pace":
        return format_pace(row)
    if scan == "pivot_watch":
        return format_pivot(row)
    return format_hit(row, PCT_COLUMNS.get(scan, "chg_pct"), slot)


# ---------------------------------------------------------------- the lines under it


def plan_lines(row: Mapping[str, Any]) -> list[str]:
    """`Buy 2.35 · stop 1.75 (day low)` and `625 sh · $1.5k · risk $375`; for a breakout
    without an account file, its pivot and order stop."""
    shares = row.get("plan_shares")
    if shares is None or pd.isna(shares):
        pivot, stop = row.get("pivot"), row.get("order_stop")
        if pivot is None or pd.isna(pivot) or stop is None or pd.isna(stop):
            return []
        return [f"Pivot {pivot:.2f} · 🛑 {stop:.2f}"]
    basis = str(row.get("plan_stop_basis") or "")
    buy = "Buy-stop" if "buy-stop" in basis else "Buy"
    basis = basis.replace(", buy-stop at pivot", "").replace(", move to day low", " → day low")
    risk_adr = row.get("risk_adr")
    if basis == "order stop" and risk_adr is not None and not pd.isna(risk_adr):
        basis = f"{risk_adr:.1f} ADR"
    position = row["plan_position_usd"]
    money = f"${position / 1000:.1f}k" if position >= 1000 else f"${position:.0f}"
    capped = " (capped)" if bool(row.get("plan_capped")) else ""
    return [
        f"{buy} {row['plan_entry']:.2f} · 🛑 {row['plan_stop']:.2f} ({basis})",
        f"{int(shares):,} sh · {money}{capped} · risk ${row['plan_risk_usd']:.0f}",
    ]


def wrap(parts: Iterable[str], width: int) -> list[str]:
    """Join phrases with ` · ` into lines of at most `width` characters (a longer phrase
    gets a line of its own)."""
    lines: list[str] = []
    for part in parts:
        if lines and len(lines[-1]) + 3 + len(part) <= width:
            lines[-1] += f" · {part}"
        else:
            lines.append(part)
    return lines


def _block(row: Mapping[str, Any], scan: str, slot: str) -> list[Line]:
    out = [Line("hit", "▸ " + _first_line(row, scan, slot))]
    out += [Line("plan", INDENT + text) for text in grade_lines(row)]
    pm = premarket_line(row)
    if pm:
        out.append(Line("plan", INDENT + pm))
    out += [Line("plan", INDENT + text) for text in plan_lines(row)]
    if context.has_context(row):
        out += [
            Line("fact", INDENT + text)
            for text in wrap(context.parts(row, scan), WIDTH - len(INDENT))
        ]
        found = context.headline(row, max_chars=70)
        if found is not None:
            title, where = found
            source = where.split(",")[0] if where else ""
            out.append(Line("news", INDENT + f"📰 {title}" + (f" ({source})" if source else "")))
    return out


def _grade_line_rows(partial, shown, name, slot) -> list[Line]:
    """Grade B: one line each, under the plan they share."""
    when = ENTRY_TEXT.get(str(partial.iloc[0].get("grade_entry_rule")), "")
    out = [Line("note", "B: " + (when or "see the report") + ":")]
    for row in partial.to_dict("records"):
        seen = shown.get(row["ticker"]) or _earlier(row)
        score = row.get("grade_score")
        tail = "" if score is None or pd.isna(score) else f" · B {score:+.2f}R"
        seen_text = f"  ↑ {seen}" if seen else ""
        out.append(Line("hit", f"▸ {_first_line(row, name, slot)}{tail}{seen_text}"))
    return out


def _earlier(row: Mapping[str, Any]) -> str | None:
    """`seen_earlier`: a note that replaces the hit's block (e.g. flagged last evening)."""
    note = row.get("seen_earlier")
    return note if isinstance(note, str) and note else None


def _partial_lines(name, partial, hits, scan, shown, slot) -> list[Line]:
    """`B5 only · top 5 of 13:` and one line per trigger (its squares show what's missing)."""
    if "grade" in partial and partial["grade"].notna().all():
        return _grade_line_rows(partial, shown, name, slot)
    alerts = hits[hits["tier"] == "alert"] if "tier" in hits else hits
    held = int((~_all_pass(alerts, scan["push_if_all"])).sum())
    out = [Line("note", f"B5 only · top {len(partial)} of {held}:")]
    for row in partial.to_dict("records"):
        first = _first_line(row, name, slot)
        seen = shown.get(row["ticker"])
        out.append(Line("hit", f"▸ {first}" + (f"  ↑ see {seen}" if seen else "")))
    return out


def _quiet(label: str, hits: pd.DataFrame, scan) -> str:
    """How a scan without alerts appears in the closing `Nothing new:` line."""
    if "push_tier" not in scan.params or hits.empty:
        return label
    alerts = hits[hits["tier"] == "alert"] if "tier" in hits else hits.iloc[0:0]
    if len(alerts) and "push_if_all" in scan.params:
        held = int((~_all_pass(alerts, scan["push_if_all"])).sum())
        if held:
            return f"{label} ({held} without {_flag_names(scan['push_if_all'])})"
    if len(alerts):  # the 12:00 check, when every alert went out at 10:15
        return f"{label} ({len(alerts)} sent earlier)"
    return f"{label} ({len(hits)} below alert tier)"


def _title(ctx: RunContext, counts: list[str], icon: str) -> str:
    day = ctx.session
    title = f"{SLOT_LABELS[ctx.slot]} {day:%a} {day.day} {day:%b}"
    title += " · " + (" · ".join(counts) if counts else "no alerts")
    if ctx.forced:
        title += " (manual run)"
    return f"{icon} {title}" if icon else title


def build_message(
    ctx: RunContext,
    results: Mapping[str, pd.DataFrame],
    selected: Mapping[str, pd.DataFrame],
    cfg: Config,
    header_lines: list[str] | None = None,
    click: str | None = None,
) -> Message:
    lines = [Line("head", text) for text in header_lines or []]
    counts, quiet, shown = [], [], {}
    for name, both in selected.items():
        label = SCAN_LABELS.get(name, name)
        chosen, partial = both[~partial_rows(both)], both[partial_rows(both)]
        if both.empty:
            quiet.append(_quiet(label, results[name], cfg.scans[name]))
            continue
        if len(chosen):
            counts.append(f"{TITLE_LABELS.get(name, label)} {len(chosen)}")
        if len(partial):
            graded_line = "grade" in partial and partial["grade"].notna().all()
            counts.append(f"{'B' if graded_line else 'B5-only'} {len(partial)}")
        total = len(results[name])
        more = f" of {total}" if total > len(chosen) else ""
        size = f"{len(chosen)}{more}" if len(chosen) else "no full setup"
        legend = " 1M/3M/6M" if name == "qm_gainers" else ""
        icon = SECTION_ICONS.get(name, "")
        header = f"━━ {icon} {label}{legend} · {size} ━━".replace("  ", " ")
        lines += [Line("gap", ""), Line("section", header)]
        if name in FLAG_LEGENDS:
            lines.append(Line("note", FLAG_LEGENDS[name]))
        lines += [Line("note", text) for text in UNGRADED_PLANS.get(name, [])]
        for row in chosen.to_dict("records"):
            ticker = row["ticker"]
            if ticker in shown:
                first = _first_line(row, name, ctx.slot).split("  ")[:2]
                block = [Line("hit", f"▸ {'  '.join(first)}  ↑ see {shown[ticker]}")]
            elif _earlier(row):
                first = _first_line(row, name, ctx.slot).split("  ")[:2]
                block = [Line("hit", f"▸ {'  '.join(first)}  ↑ {_earlier(row)}")]
            else:
                shown[ticker] = label
                block = _block(row, name, ctx.slot)
            # A blank line between stocks, except between two one-line entries.
            if lines[-1].role not in ("section", "note") and (
                len(block) > 1 or lines[-1].role != "hit"
            ):
                lines.append(Line("gap", ""))
            lines += block
        if len(partial):
            if len(chosen):
                lines.append(Line("gap", ""))
            lines += _partial_lines(name, partial, results[name], cfg.scans[name], shown, ctx.slot)
    if quiet:
        lines += [Line("gap", ""), Line("note", "Nothing new: " + " · ".join(quiet))]
    saved = c_counts(results, cfg, ctx.slot)
    if saved:
        lines += [Line("note", "Study C, saved: " + " · ".join(saved))]
    later = later_counts(results, cfg, ctx.slot)
    if later:
        lines += [Line("note", "In the pre-market push: " + " · ".join(later))]
    if click:
        lines.append(Line("note", "Tap for the full report with charts."))
    first = (header_lines or [""])[0][:1]
    icon = first if first in LIGHT_ICONS.values() else ""
    body = fit(lines) or "No pushing scans ran."
    return Message(title=_title(ctx, counts, icon), body=body, click=click)


def report_url(cfg: Config, path: str) -> str | None:
    """Link to the run's report in the private data repo (needs the repo owner, which the
    GitHub runner provides); None when running locally."""
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    return cfg.notify["report_url"].format(owner=owner, path=path) if owner else None


def send(server: str, topic: str, message: Message, *, timeout: float = 15) -> None:
    """Publish via ntfy's JSON API (keeps non-ASCII titles out of HTTP headers)."""
    payload = {
        "topic": topic,
        "title": message.title,
        "message": message.body,
        "tags": ["chart_with_upwards_trend"],
    }
    if message.click:
        payload["click"] = message.click
    response = requests.post(server.rstrip("/") + "/", json=payload, timeout=timeout)
    response.raise_for_status()


# ---------------------------------------------------------------- size limit


def _join(lines: list[Line]) -> str:
    out: list[str] = []
    for line in lines:
        if line.role == "gap" and (not out or out[-1] == ""):
            continue
        out.append(line.text)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def fit(lines: list[Line], limit: int = NTFY_LIMIT) -> str:
    """The message under ntfy's size limit. Drops headlines from the bottom up, then facts
    from the bottom up (the top names keep theirs), then whole stocks from the end."""
    lines = list(lines)

    def too_big() -> bool:
        return len(_join(lines).encode("utf-8")) > limit

    for role in ("news", "fact"):
        while too_big():
            last = max((i for i, line in enumerate(lines) if line.role == role), default=None)
            if last is None:
                break
            del lines[last]
    if not too_big():
        return _join(lines)
    cut = 0
    while lines and len((_join(lines) + f"\n… {cut} more in the report").encode("utf-8")) > limit:
        if lines.pop().role == "hit":
            cut += 1
    marker = Line("note", f"… {cut} more in the report")
    return _join([*lines, marker])


def _growth(x: float) -> str:
    """Whole percents, capped at ±999 % (growth off a near-zero year-ago base says nothing)."""
    if abs(x) > 999:
        return ">+999%" if x > 0 else "<-999%"
    return f"{round(x) + 0:+d}%"


def _pair(latest: float, previous: float) -> str:
    """`+62% / +55%` (latest / previous quarter), `+62%` when the previous is missing."""
    text = _growth(latest)
    return text if previous != previous else f"{text} / {_growth(previous)}"


def _money(value: float) -> str:
    if value != value:  # NaN
        return "$?"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    return f"${value / 1e6:.0f}M"
