"""ntfy.sh notifications (SPEC §8): one message per job, never one per ticker.

The topic is a secret. Messages go straight to ntfy and are never printed to logs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

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
    "qm_gainers": "QM gainers",
    "growth_bucket_1": "Growth 1",
    "growth_bucket_2": "Growth 2",
}

# The percent shown on each line: the move that triggered the scan.
PCT_COLUMNS = {
    "ep_pm": "pm_change_pct",
    "ep9m_early": "pm_gap_pct",
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


def build_message(
    ctx: RunContext,
    results: Mapping[str, pd.DataFrame],
    selected: Mapping[str, pd.DataFrame],
) -> Message:
    title = f"Trading OS · {SLOT_LABELS[ctx.slot]} {ctx.session.isoformat()}"
    if ctx.forced:
        title += " (manual)"
    blocks = []
    for name, chosen in selected.items():
        label = SCAN_LABELS.get(name, name)
        total = len(results[name])
        if chosen.empty:
            suffix = f" ({total} below alert tier)" if total else ""
            blocks.append(f"{label}: no alerts{suffix}")
            continue
        header = f"{label}: {len(chosen)} alert" + (f" of {total} hits" if total else "")
        pct_column = PCT_COLUMNS.get(name, "chg_pct")
        lines = [format_hit(row, pct_column, ctx.slot) for row in chosen.to_dict("records")]
        blocks.append("\n".join([header, *lines]))
    return Message(title=title, body="\n\n".join(blocks) or "No pushing scans ran.")


def send(server: str, topic: str, message: Message, *, timeout: float = 15) -> None:
    """Publish via ntfy's JSON API (keeps non-ASCII titles out of HTTP headers)."""
    response = requests.post(
        server.rstrip("/") + "/",
        json={"topic": topic, "title": message.title, "message": message.body, "tags": ["chart"]},
        timeout=timeout,
    )
    response.raise_for_status()


def _money(value: float) -> str:
    if value != value:  # NaN
        return "$?"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    return f"${value / 1e6:.0f}M"
