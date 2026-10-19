"""Outcome statistics per scan (SPEC §9, Phase 6 groundwork). Descriptive only: no model,
no grading, no thresholds changed. Written by the weekly job to reports/stats/ in the data repo.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os.notify import SCAN_LABELS


def summarize(candidates: pd.DataFrame, outcomes: pd.DataFrame, min_signals: int) -> pd.DataFrame:
    """One row per (scan, tier, horizon) with at least `min_signals` outcomes."""
    if candidates.empty or outcomes.empty:
        return pd.DataFrame()
    keys = candidates[["signal_id", "tier", "pushed"]].drop_duplicates("signal_id")
    joined = outcomes.merge(keys, on="signal_id", how="left")
    rows = []
    for (scan, tier, horizon), group in joined.groupby(["scan", "tier", "horizon"]):
        if len(group) < min_signals:
            continue
        stop = group["hit_order_stop"].dropna()
        r = group["r_hypothetical"].dropna()
        rows.append(
            {
                "scan": scan,
                "tier": tier,
                "horizon": int(horizon),
                "signals": len(group),
                "win_rate_pct": float((group["close_ret_pct"] > 0).mean() * 100),
                "median_ret_pct": float(group["close_ret_pct"].median()),
                "mean_ret_pct": float(group["close_ret_pct"].mean()),
                "mean_max_gain_pct": float(group["max_gain_pct"].mean()),
                "mean_max_dd_pct": float(group["max_drawdown_pct"].mean()),
                "stop_hit_pct": float(stop.astype(bool).mean() * 100) if len(stop) else np.nan,
                "mean_r": float(r.mean()) if len(r) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["scan", "tier", "horizon"]).reset_index(drop=True)


def to_markdown(table: pd.DataFrame, as_of: dt.date, total_outcomes: int, min_signals: int) -> str:
    lines = [
        f"# Outcome statistics · {as_of.isoformat()}",
        "",
        f"{total_outcomes} outcomes so far. "
        f"Groups with fewer than {min_signals} signals are left out.",
        "Returns are from the signal's entry (EOD close, or the open for pre-market signals).",
        "",
    ]
    if table.empty:
        return "\n".join([*lines, "_Not enough outcomes yet._", ""])
    header = (
        "| Scan | Tier | Horizon | Signals | Win % | Median % | Mean % | Max gain % | Max DD % "
        "| Stop hit % | Mean R |"
    )
    lines += [header, "|" + "---|" * 11]

    def f(x, spec=".1f"):
        return "" if pd.isna(x) else format(x, spec)

    for r in table.to_dict("records"):
        lines.append(
            f"| {SCAN_LABELS.get(r['scan'], r['scan'])} | {r['tier']} | {r['horizon']}d | "
            f"{r['signals']} | {f(r['win_rate_pct'], '.0f')} | {f(r['median_ret_pct'], '+.1f')} | "
            f"{f(r['mean_ret_pct'], '+.1f')} | {f(r['mean_max_gain_pct'], '+.1f')} | "
            f"{f(r['mean_max_dd_pct'], '+.1f')} | {f(r['stop_hit_pct'], '.0f')} | "
            f"{f(r['mean_r'], '+.2f')} |"
        )
    return "\n".join(lines) + "\n"


def load_outcomes(data_dir: Path) -> pd.DataFrame:
    files = sorted((Path(data_dir) / "data" / "outcomes").glob("*/*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
