"""Monthly live check (Emil, 21 Oct 2026): how the live A+ / A signals did by their study plan,
against the history each grade carried, and how Emil's own trades did against the plan of the
signal they came from. Writes `docs/live-tracking/<date>.md` in the data repo (private) and
pushes one summary. Public logs: counts only.

uv run python scripts/live_check.py --data-dir ../trading-os-data --no-push
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

import pandas as pd

from trading_os import clock, dashboard, history, notify, outcomes, report
from trading_os import live_tracking as lt
from trading_os.config import load_config
from trading_os.logsafe import run_guarded, status

LOOKBACK = 400  # sessions of daily bars searched for the live signals' paths


def table_md(df: pd.DataFrame, cols: list[str]) -> list[str]:
    def cell(v):
        if isinstance(v, float):
            return "" if v != v else f"{v:+.2f}" if abs(v) < 100 else f"{v:,.0f}"
        return str(v)

    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(cell(r[c]) for c in cols) + " |" for r in df.to_dict("records")]
    return out


def build(data_dir: Path, today: dt.date) -> tuple[list[str], list[str], dict]:
    """(report lines, push lines, counts)."""
    cfg = load_config()
    cands = outcomes.load_candidates(data_dir)
    live = cands[cands["grade"].isin(lt.LIVE_GRADES)] if "grade" in cands else cands.iloc[0:0]
    head = [f"# Live check, {today:%d %B %Y}", ""]
    if live.empty:
        line = "No live A+ / A signals yet."
        return [*head, line], [line], {"signals": 0}
    sessions = [
        s
        for s in clock.sessions_back(cfg.schedule, today, LOOKBACK)
        if s >= min(live["session_date"])
    ]
    bars = history.load_bars(data_dir, sessions)
    bars = bars[bars["ticker"].isin(set(live["ticker"]))]
    res = lt.plan_results(live, bars)
    table = lt.compare(res)
    trades = dashboard.latest_journal(data_dir)
    if not trades.empty and "r_multiple" in trades:
        trades = trades.dropna(subset=["r_multiple"])
    gaps = lt.execution(res, trades, sessions)
    labels = report.SCAN_LABELS | {"ep": "EP", "ep9m": "EP9M", "luk_avwap_flush": "Luk flush"}
    pushes = lt.push_lines(table, labels)
    if len(gaps):
        pushes.append(
            f"Your trades: {len(gaps)} matched · you {gaps['your_r'].mean():+.2f}R vs plan "
            f"{gaps['plan_r'].mean():+.2f}R"
        )
    lines = [
        *head,
        "How the live A+ / A signals did by their study plan (bought at the plan's price, out at "
        "the stop or at the close after the plan's sessions, net of the study's cost), against "
        "the history each grade carried. 'Below the study' needs at least "
        f"{lt.MIN_TRADES} closed trades and both the mean R and the win rate clearly under the "
        "study's. Facts, not advice.",
        "",
        "## Per grade",
        "",
        *table_md(
            table,
            [
                "grade_strategy",
                "entry_rule",
                "grade",
                "closed",
                "open",
                "live_mean_r",
                "live_win_pct",
                "study_mean_r",
                "study_win_pct",
                "verdict",
            ],
        ),  # fmt: skip
        "",
        "## By IBD market state (tracked, not a rule)",
        "",
        "In the 2016-26 study MA-surf A and EP9M A+ did better in an IBD uptrend than in a "
        "correction, but that was found with both periods in view. This split decides it.",
        "",
        *table_md(
            lt.by_market(res),
            ["grade_strategy", "grade", "ibd_state", "closed", "live_mean_r", "live_win_pct"],
        ),
        "",
        "## Your trades against the plan",
        "",
        *(
            table_md(
                gaps,
                ["ticker", "signal_session", "grade", "entry_rule", "plan_r", "your_r", "gap_r"],
            )
            if len(gaps)
            else ["No closed journal trades matched to a live A+ / A signal yet."]
        ),
        "",
        "## Every live signal",
        "",
        *table_md(
            res.sort_values("session_date"),
            [
                "session_date",
                "ticker",
                "grade_strategy",
                "entry_rule",
                "grade",
                "entry",
                "stop",
                "status",
                "sessions",
                "r_net",
            ],
        ),  # fmt: skip
    ]
    counts = {
        "signals": len(res),
        "closed": int((res["status"] == "closed").sum()),
        "open": int((res["status"] == "open").sum()),
        "matched_trades": len(gaps),
        "below_study": int((table["verdict"] == "below the study").sum()),
    }
    return lines, pushes, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("DATA_DIR"))
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args(argv)
    if args.data_dir is None:
        parser.error("--data-dir or DATA_DIR is required")

    def run() -> int:
        today = clock.ny_time(load_config().schedule, dt.datetime.now(dt.UTC)).date()
        lines, pushes, counts = build(args.data_dir, today)
        out = args.data_dir / "docs" / "live-tracking" / f"{today.isoformat()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        status("Live check: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        topic = os.environ.get("NTFY_TOPIC", "")
        if not args.no_push and topic:
            cfg = load_config()
            message = notify.Message(f"Trading OS · live check {today:%d %b}", "\n".join(pushes))
            notify.send(cfg.notify["server"], topic, message)
            status("Push: sent")
        return 0

    return run_guarded(run, args.data_dir / "logs", "live-check")


if __name__ == "__main__":
    raise SystemExit(main())
