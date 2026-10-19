"""ntfy.sh notifications (SPEC §8): one message per job, never one per ticker.

The topic is a secret. Messages go straight to ntfy and are never printed to logs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from trading_os import context, sizing
from trading_os.config import Config
from trading_os.store import RunContext

SLOT_LABELS = {"pm": "Pre-market", "eod": "EOD", "weekly": "Weekly"}
SCAN_LABELS = {
    "ep_pm": "EP-PM",
    "ep9m_early": "EP9M early",
    "watchlist_gappers": "Watchlist gappers",
    "ep_day": "EP-Day",
    "ep_ah": "EP-AH",
    "ep9m": "EP9M",
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

# The percent shown on each line: the move that triggered the scan.
PCT_COLUMNS = {
    "ep_pm": "pm_change_pct",
    "ep9m_early": "pm_gap_used",
    "watchlist_gappers": "pm_gap_used",
    "ep_day": "gap_pct",
    "ep_ah": "ah_change_pct",
    "ep9m": "chg_pct",
}


@dataclass(frozen=True)
class Message:
    title: str
    body: str


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
        selected[name] = eligible.sort_values("rank").head(limit)
    return selected


def format_hit(row: Mapping[str, Any], pct_column: str = "gap_pct", slot: str = "eod") -> str:
    """`TICKER  +14.2%  RVOL 5.1  $82M  [earnings]` (scan's move %, RVOL, dollar volume).

    Pre-market lines show pre-market volume and dollar volume instead, since the day's
    volume fields still hold the prior session then.
    """
    if slot == "pm":
        line = (
            f"{row['ticker']}  {row[pct_column]:+.1f}%  PM vol {row['pm_volume'] / 1e6:.1f}M  "
            f"{_money(row['pm_dollar_volume'])}"
        )
    else:
        line = (
            f"{row['ticker']}  {row[pct_column]:+.1f}%  RVOL {row['rvol50']:.1f}  "
            f"{_money(row['dollar_volume'])}"
        )
    if bool(row.get("earnings_flag", False)):
        line += "  [earnings]"
    return line


def format_weekly(row: Mapping[str, Any], scan: str) -> str:
    """Weekly list lines: the numbers each list is about."""
    t = row["ticker"]
    if scan == "qm_gainers":
        return (
            f"{t}  1M {row['ret_22']:+.0f}%  3M {row['ret_63']:+.0f}%  6M {row['ret_126']:+.0f}%  "
            f"ADR {row['adr20_pct']:.1f}%  [{row['qm_lists']}]"
        )
    rev = _pair(row["rev_growth_q"], row["rev_growth_q_prev"])
    if scan == "growth_bucket_1":
        return f"{t}  rev {rev}  TTM {_money(row['revenue_ttm'])}"
    return f"{t}  EPS {_pair(row['eps_growth_q'], row['eps_growth_q_prev'])}  rev {rev}"


def format_breakout(row: Mapping[str, Any], scan: str) -> str:
    """Pivot, order stop and risk in ADR; the B-flags are for the human's grade."""
    flags = "".join(
        str(i) if bool(row.get(f"b{i}")) else "-"
        for i in range(1, 6 if scan == "breakout_trigger" else 5)
    )
    line = (
        f"{row['ticker']}  pivot {row['pivot']:.2f}  stop {row['order_stop']:.2f}  "
        f"risk {row['risk_adr']:.1f} ADR  B{flags}"
    )
    if scan == "breakout_trigger":
        line = (
            f"{row['ticker']}  {row['chg_pct']:+.1f}%  RVOL {row['trig_rvol']:.1f}  "
            + line[len(row["ticker"]) + 2 :]
        )
    return line


def build_message(
    ctx: RunContext,
    results: Mapping[str, pd.DataFrame],
    selected: Mapping[str, pd.DataFrame],
    cfg: Config,
    header_lines: list[str] | None = None,
) -> Message:
    title = f"Trading OS · {SLOT_LABELS[ctx.slot]} {ctx.session.isoformat()}"
    if ctx.forced:
        title += " (manual)"
    blocks = []
    for name, chosen in selected.items():
        label = SCAN_LABELS.get(name, name)
        total = len(results[name])
        tiered = "push_tier" in cfg.scans[name].params
        if chosen.empty:
            if not tiered:
                blocks.append(f"{label}: no hits")
            else:
                suffix = f" ({total} below alert tier)" if total else ""
                blocks.append(f"{label}: no alerts{suffix}")
            continue
        noun = "alert" if tiered else "shown"
        header = f"{label}: {len(chosen)} {noun}" + (f" of {total} hits" if total else "")
        records = chosen.to_dict("records")
        if ctx.slot == "weekly":
            lines = [format_weekly(row, name) for row in records]
        elif name.startswith("breakout_"):
            lines = [_with_extras(format_breakout(row, name), row, name) for row in records]
        else:
            pct_column = PCT_COLUMNS.get(name, "chg_pct")
            lines = [
                _with_extras(format_hit(row, pct_column, ctx.slot), row, name) for row in records
            ]
        blocks.append("\n".join([header, *lines]))
    if header_lines:
        blocks.insert(0, "\n".join(header_lines))
    return Message(title=title, body=fit("\n\n".join(blocks) or "No pushing scans ran."))


def send(server: str, topic: str, message: Message, *, timeout: float = 15) -> None:
    """Publish via ntfy's JSON API (keeps non-ASCII titles out of HTTP headers)."""
    response = requests.post(
        server.rstrip("/") + "/",
        json={"topic": topic, "title": message.title, "message": message.body, "tags": ["chart"]},
        timeout=timeout,
    )
    response.raise_for_status()


def _with_extras(line: str, row: Mapping[str, Any], scan: str) -> str:
    """The alert line, its position size and (for the top names) the facts behind it."""
    out = [line]
    plan = sizing.plan_line(row)
    if plan:
        out.append(plan)
    if context.has_context(row):
        out.extend(context.lines(row, scan))
    return "\n".join(out)


NTFY_LIMIT = 3900  # ntfy turns longer messages into attachments (4096 bytes)


def fit(body: str, limit: int = NTFY_LIMIT) -> str:
    """Keep the message under ntfy's size limit: drop headlines, then facts, then cut."""
    if len(body.encode("utf-8")) <= limit:
        return body
    lines = [x for x in body.split("\n") if not x.startswith("   news: ")]
    body = "\n".join(lines)
    if len(body.encode("utf-8")) <= limit:
        return body
    keep = [x for x in lines if not x.startswith("   ") or x.startswith("   buy ")]
    body = "\n".join(keep)
    if len(body.encode("utf-8")) <= limit:
        return body
    return (
        body.encode("utf-8")[: limit - 40].decode("utf-8", errors="ignore")
        + "\n… (full list in the report)"
    )


def _pair(latest: float, previous: float) -> str:
    """`+62% / +55%` (latest / previous quarter), `+62%` when the previous is missing."""
    text = f"{latest:+.0f}%"
    return text if previous != previous else f"{text} / {previous:+.0f}%"


def _money(value: float) -> str:
    if value != value:  # NaN
        return "$?"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    return f"${value / 1e6:.0f}M"
