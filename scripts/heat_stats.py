"""Setup results per market heat (Emil, 21 Oct 2026: "which strategies work in this market").

Reads the grading study's trades (release `grading-10y`: `validated_trades_v3.parquet`, one row
per trade of each setup's study plan, and the market's scan count per session from the yearly
`grading_<year>.parquet` files), cuts them by the heat band of the signal day's scan count,
and scores each setup separately on 2016-2021 and 2022-2026. Writes
`data/grading/heat_stats.json` in the data repo, read by `trading_os/heat.py` for the push and
the dashboard. Research only: run locally after the grading study changes, never in Actions.

uv run python scripts/heat_stats.py --data-dir ../trading-os-data
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from trading_os import heat, remote_data

REPO = "Peikz/trading-os-data"
# Heat bands of the research (how-we-test.md): cool under 18, mild 18-44, warm 45-80, hot 81+.
BANDS = [[18, "cool"], [45, "mild"], [81, "warm"], [None, "hot"]]
BAND_LABELS = {"cool": "under 18", "mild": "18-44", "warm": "45-80", "hot": "over 80"}
MIN_TRADES = 30
ENTRY_TEXT = {
    "t_1030": "10:30",
    "t_1015": "10:15",
    "ah_1645": "16:45 after hours",
    "next_1030": "next day 10:30",
    "next_open": "next open",
    "close": "signal-day close",
    "pivot_close": "the close, over the pivot",
    "pivot_cross": "a stop order at the pivot",
    "pivot_1000": "10:00 over the pivot",
}
STOP_TEXT = {
    "adr": "stop 1 ADR under",
    "signal": "stop at the signal day's low",
    "order": "the setup's own stop",
}
EXIT_TEXT = {"hold_21d": "hold 21 sessions", "trail_ma20": "trail the 20-day MA"}
# (key, label, kind, rows): kind A = a live grade, C = a setup without a grade.
SHORT = {"ep_a_1030": "EP A+", "ep_a_ah": "EP-AH A+", "luk_flush_a": "Luk A"}  # push names
SETUPS = [
    ("ep_a_1030", "EP A+ 10:30", "A", "strategy == 'ep' and entry == 't_1030' and quality >= 5"),
    (
        "ep_a_ah",
        "EP-AH A+ 16:45",
        "A",
        "strategy == 'ep' and entry == 'ah_1645' and stop_rule == 'adr' and quality >= 5",
    ),
    ("ep9m_a", "EP9M A+", "A", "strategy == 'ep9m' and entry == 't_1015' and quality >= 5"),
    (
        "luk_flush_a",
        "Luk flush A",
        "A",
        "strategy == 'luk_avwap_flush' and entry == 'next_1030' and luk_market_tight == 1",
    ),
    ("breakout", "Breakouts B1-B5", "C", "strategy == 'breakout'"),
    ("mb_up", "Momentum Burst up", "C", "strategy == 'mb_up'"),
    ("parabolic_long", "Parabolic long", "C", "strategy == 'parabolic_long'"),
    ("luk_pullback", "Luk pullback", "C", "strategy == 'luk_pullback'"),
    ("luk_inside_day", "Luk inside day", "C", "strategy == 'luk_inside_day'"),
    ("vcp", "VCP", "C", "strategy == 'vcp_breakout'"),
    ("qm_surf", "MA-surf", "C", "strategy == 'qm_surf'"),
    ("pocket_pivot", "Pocket pivot", "C", "strategy == 'pocket_pivot'"),
    ("ep_next_day", "EP next day", "C", "strategy == 'ep_day'"),
    ("mb_down", "Momentum Burst down (short)", "C", "strategy == 'mb_down'"),
    ("parabolic_short", "Parabolic short (short)", "C", "strategy == 'parabolic_short'"),
]


def plan_text(rows: pd.DataFrame) -> str:
    """The plan in words, from the trades' own entry, stop and exit."""

    def one(col: str, words: dict) -> str:
        values = sorted(set(rows[col].astype(str)))
        return ", ".join(words.get(v, v) for v in values)

    return f"{one('entry', ENTRY_TEXT)}; {one('stop_rule', STOP_TEXT)}; {one('exit', EXIT_TEXT)}"


def score(rows: pd.DataFrame) -> dict:
    r = rows["net_capped"]
    day = rows.groupby("session_date")["net_capped"].mean()
    years = rows.groupby("year")["net_capped"].mean()
    return {
        "trades": len(rows),
        "signal_days": len(day),
        "mean_r": round(float(r.mean()), 3),
        "day_mean_r": round(float(day.mean()), 3),
        "win_pct": round(float((r > 0).mean() * 100), 1),
        "years_up": int((years > 0).sum()),
        "years": len(years),
    }


def build(trades: pd.DataFrame, counts: pd.DataFrame) -> dict:
    t = trades.copy()
    t["session_date"] = pd.to_datetime(t["session_date"]).dt.date
    t = t.merge(counts, on="session_date", how="left")
    t["heat"] = t["mkt_scan_count"].map(lambda c: heat.band(c, BANDS))
    t["period"] = (t["year"] >= 2022).map({False: heat.PERIODS[0], True: heat.PERIODS[1]})
    setups, out = [], []
    for key, label, kind, query in SETUPS:
        rows = t.query(query)
        side = "short" if (rows["side"] < 0).all() and len(rows) else "long"
        setups.append(
            {
                "key": key,
                "label": label,
                "short": SHORT.get(key, label),
                "kind": kind,
                "side": side,
                "plan": plan_text(rows),
            }
        )
        for (band, period), part in rows.groupby(["heat", "period"]):
            out.append({"setup": key, "heat": band, "period": period, **score(part)})
    return {
        "built": dt.date.today().isoformat(),
        "source": "release grading-10y: validated_trades_v3 + scan count from grading_<year>",
        "r": "net R a trade after costs, capped at 20R; signal days averaged first for day_mean_r",
        "bands": BANDS,
        "band_labels": BAND_LABELS,
        "periods": list(heat.PERIODS),
        "min_trades": MIN_TRADES,
        "unmatched_trades": int(t["heat"].isna().sum()),
        "setups": setups,
        "rows": out,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")
    # Read now: the yearly files fill the cache, which then drops its least recently used file.
    trades = pd.read_parquet(
        remote_data.fetch(REPO, "grading-10y", "validated_trades_v3.parquet")[0]
    )
    years = remote_data.fetch(REPO, "grading-10y", "grading_20[12][0-9].parquet")
    cols = ["session_date", "mkt_scan_count"]
    counts = pd.concat(
        pq.read_table(f, columns=cols).to_pandas().drop_duplicates("session_date") for f in years
    ).drop_duplicates("session_date")
    counts["session_date"] = pd.to_datetime(counts["session_date"]).dt.date
    stats = build(trades, counts)
    out = args.data_dir / heat.STATS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(f"Heat stats: {len(stats['rows'])} rows, {stats['unmatched_trades']} trades unmatched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
