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
    "eod": "EOD",
    "weekly": "Weekly",
}
SCAN_LABELS = {
    "ep_pm": "EP-PM",
    "ep9m_early": "EP9M early",
    "watchlist_gappers": "Watchlist gappers",
    "ep_day": "EP-Day",
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
}
# An icon per section, so the eye finds the setup type (no meaning beyond the type).
SECTION_ICONS = {
    "ep_day": "⚡",
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
    "ep_ah": "ah_change_pct",
    "ep9m": "chg_pct",
}

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


def select_for_push(results: Mapping[str, pd.DataFrame], cfg: Config) -> dict[str, pd.DataFrame]:
    """Hits that go into the message: push scans only, push tier only, top N by rank."""
    limit = cfg.notify["max_tickers_per_scan"]
    selected = {}
    for name, hits in results.items():
        scan = cfg.scans[name]
        if scan.action != "push":
            continue
        eligible = hits
        if "push_tier" in scan.params:
            eligible = hits[hits["tier"] == scan["push_tier"]]
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
    if slot == "weekly":
        return format_weekly(row, scan)
    if scan.startswith("breakout_"):
        return format_breakout(row, scan)
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


def _partial_lines(name, partial, hits, scan, shown, slot) -> list[Line]:
    """`B5 only · top 5 of 13:` and one line per trigger (its squares show what's missing)."""
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
            counts.append(f"B5-only {len(partial)}")
        total = len(results[name])
        more = f" of {total}" if total > len(chosen) else ""
        size = f"{len(chosen)}{more}" if len(chosen) else "no full setup"
        legend = " 1M/3M/6M" if name == "qm_gainers" else ""
        icon = SECTION_ICONS.get(name, "")
        header = f"━━ {icon} {label}{legend} · {size} ━━".replace("  ", " ")
        lines += [Line("gap", ""), Line("section", header)]
        if name in FLAG_LEGENDS:
            lines.append(Line("note", FLAG_LEGENDS[name]))
        for row in chosen.to_dict("records"):
            ticker = row["ticker"]
            if ticker in shown:
                first = _first_line(row, name, ctx.slot).split("  ")[:2]
                block = [Line("hit", f"▸ {'  '.join(first)}  ↑ see {shown[ticker]}")]
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
