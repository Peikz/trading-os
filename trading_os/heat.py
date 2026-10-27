"""Market heat (Emil, 21 Oct 2026): which setups held up in a market as hot as today's.

Heat is the Sunday scan count (stocks up 50 %+ in a quarter, SPEC §6.5), the one market
variable that held up when tested blind (data repo docs/research/how-we-test.md).
`scripts/heat_stats.py` scores every setup's study plan per heat band, separately on 2016-2021
and 2022-2026 (net R a trade after costs, capped at 20R like the study's tables), into
`data/grading/heat_stats.json`. This module reads that file and puts today's band in the market
lines of the push and on the dashboard. Facts about past rules, not advice.

A setup "held" in a band when it made money per trade and per signal day in both periods, with
at least `min_trades` trades in each. It "lost" when it lost money per trade in both, however
few the trades (the cautious side: a loss needs no minimum to be shown).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

STATS = Path("data") / "grading" / "heat_stats.json"
PERIODS = ("2016-21", "2022-26")
VERDICT_ICONS = {"held": "✅", "lost": "❌", "mixed": "➖", "too few trades": "·"}
MAX_PUSHED = 4  # C setups listed in the push; the dashboard shows them all


def load(data_dir: Path) -> dict | None:
    path = Path(data_dir) / STATS
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def band(count: Any, bands: list) -> str | None:
    """The band a scan count falls in: `bands` is [[upper bound, exclusive, name], ...] with
    None as the last upper bound."""
    try:
        value = float(count)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    for upper, name in bands:
        if upper is None or value < upper:
            return name
    return None


def verdict(periods: Mapping[str, Mapping[str, Any]], min_trades: int) -> str:
    """'held' / 'lost' / 'mixed' / 'too few trades' from one setup's rows in one band."""
    rows = [periods.get(p) for p in PERIODS]
    if any(r is None or r["trades"] < min_trades for r in rows):
        lost = all(r is not None and r["trades"] and r["mean_r"] < 0 for r in rows)
        return "lost" if lost else "too few trades"
    if all(r["mean_r"] > 0 and r["day_mean_r"] > 0 for r in rows):
        return "held"
    if all(r["mean_r"] < 0 for r in rows):
        return "lost"
    return "mixed"


def table(stats: Mapping[str, Any], heat: str) -> pd.DataFrame:
    """One row per setup in band `heat`: both periods side by side and the verdict."""
    cols = ["setup", "short", "kind", "plan"]
    for p in PERIODS:
        cols += [f"r_{p}", f"day_r_{p}", f"trades_{p}", f"years_up_{p}"]
    cols.append("verdict")
    rows = []
    for s in stats.get("setups", []):
        per = {
            r["period"]: r
            for r in stats.get("rows", [])
            if r["setup"] == s["key"] and r["heat"] == heat
        }
        row = {"setup": s["label"], "short": s.get("short", s["label"]), "kind": s["kind"]}
        row["plan"] = s["plan"]
        for p in PERIODS:
            r = per.get(p)
            row[f"r_{p}"] = r["mean_r"] if r else math.nan
            row[f"day_r_{p}"] = r["day_mean_r"] if r else math.nan
            row[f"trades_{p}"] = r["trades"] if r else 0
            row[f"years_up_{p}"] = f"{r['years_up']}/{r['years']}" if r else ""
        row["verdict"] = verdict(per, stats.get("min_trades", 30))
        rows.append(row)
    return pd.DataFrame(rows, columns=cols)


def _pair(row: Mapping[str, Any]) -> str:
    return "/".join(
        "n/a" if math.isnan(row[f"r_{p}"]) else f"{row[f'r_{p}']:+.2f}" for p in PERIODS
    )


# Live scan -> its study setup in heat_stats.json, for the per-hit heat tag (Emil, 22 Oct 2026).
SCAN_KEYS = {
    "ep_am": "ep_a_1030", "ep_ah": "ep_a_ah", "ep9m_pace": "ep9m_a", "luk_flush": "luk_flush_a",
    "ma_surf": "qm_surf", "ep9m_avwap": "ep9m_avwap_b", "vcp": "vcp",
    "luk_pullback": "luk_pullback", "mb_up": "mb_up",
    "mb_down": "mb_down", "parabolic_long": "parabolic_long",
    "parabolic_short": "parabolic_short", "breakout_watch": "breakout",
    "breakout_trigger": "breakout", "ep_day": "ep_next_day",
}  # fmt: skip
VERDICT_WORDS = {"held": "held", "lost": "lost", "mixed": "mixed", "too few trades": "few trades"}


def tag(stats: Mapping[str, Any] | None, count: Any, scan: str) -> str | None:
    """`🌡 warm: held · +0.28/+0.92R (n 39/60)`: how this scan's setup did at today's heat on
    2016-21 and 2022-26 (net R a trade). None without stats, a count or a study setup."""
    key = SCAN_KEYS.get(scan)
    if not stats or key is None:
        return None
    band_name = band(count, stats["bands"])
    if band_name is None:
        return None
    label = next((s["label"] for s in stats["setups"] if s["key"] == key), None)
    t = table(stats, band_name)
    mine = t[t["setup"] == label]
    if mine.empty:
        return None
    row = mine.iloc[0].to_dict()
    n = "/".join(str(row[f"trades_{p}"]) for p in PERIODS)
    word = VERDICT_WORDS.get(row["verdict"], row["verdict"])
    return f"🌡 {band_name}: {word} · {_pair(row)}R (n {n})"


def short_line(stats: Mapping[str, Any] | None, count: Any) -> list[str]:
    """`🌡 Warm market (count 70, 45-80)`: the push's one heat line (Emil, 23 Oct 2026)."""
    if not stats:
        return []
    heat = band(count, stats["bands"])
    if heat is None:
        return []
    label = stats.get("band_labels", {}).get(heat, "")
    return [f"🌡 {heat.capitalize()} market (count {int(float(count))}, {label})"]


def push_lines(stats: Mapping[str, Any] | None, count: Any) -> list[str]:
    """The heat band of today's count, how the graded setups did in it, and the other setups
    that held in both periods."""
    if not stats:
        return []
    heat = band(count, stats["bands"])
    if heat is None:
        return []
    label = stats.get("band_labels", {}).get(heat, "")
    t = table(stats, heat)
    graded = []
    for row in t[t["kind"] == "A"].to_dict("records"):
        n = "/".join(str(row[f"trades_{p}"]) for p in PERIODS)
        if not any(row[f"trades_{p}"] for p in PERIODS):
            graded.append(f"{row['short']} none")
        else:
            graded.append(f"{row['short']} {_pair(row)} (n {n})")
    held = t[(t["kind"] == "C") & (t["verdict"] == "held")]
    held = held.sort_values(f"r_{PERIODS[-1]}", ascending=False)
    others = [f"{r['short']} {_pair(r)}" for r in held.head(MAX_PUSHED).to_dict("records")]
    more = len(held) - MAX_PUSHED
    lines = [
        f"🌡 {heat.capitalize()} market (count {int(float(count))}, {label}) · "
        f"net R a trade {PERIODS[0]}/{PERIODS[1]}:",
        "A: " + " · ".join(graded),
    ]
    if others:
        tail = f" · +{more} more" if more > 0 else ""
        lines.append("Held here too (C): " + " · ".join(others) + tail)
    else:
        lines.append("No other setup held in both periods at this heat.")
    return lines
