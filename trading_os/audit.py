"""Breakout hand audit (SPEC §9 Phase 2: "Breakout candidates audited by hand on 20 random hits").

Replays the B1-B5 detector over past sessions of Massive history, samples random hits and
writes an audit sheet to the private data repo (docs/breakout_audit_<date>.md) with each
hit's chart (pivot and order stop drawn), every criterion and intermediate value, and a
checklist. LOCAL USE ONLY: the sheet names tickers.

Massive bars cover every US listing (ETFs, warrants, units too), so the replay keeps
ordinary-looking tickers with price >= $1 and day dollar volume >= $5M (the alert-tier
floors) to stay close to what the live scans would see.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

import pandas as pd

from trading_os import breakouts, charts, clock, history
from trading_os import history_metrics as hm
from trading_os.config import Config, load_config

TICKER_SHAPE = re.compile(r"^[A-Z]{1,5}$")  # skips class/preferred forms like AB.U, AB-P


def ordinary_ticker(ticker: str) -> bool:
    """Letters only; a 5-letter NASDAQ symbol ending in W/U/R is a warrant, unit or right."""
    t = str(ticker)
    return bool(TICKER_SHAPE.match(t)) and not (len(t) == 5 and t[-1] in "WUR")


def replay(
    bars: pd.DataFrame, sessions: list[dt.date], replay_days: int, cfg: Config
) -> pd.DataFrame:
    """Watch and trigger hits for each of the last `replay_days` sessions."""
    lookback = cfg.breakout["base_max_days"] + cfg.breakout["prior_move_max_days"] + 60
    universe = bars[bars["ticker"].map(ordinary_ticker)]
    floors = cfg.universe["alert"]
    rows = []
    for end in range(len(sessions) - replay_days, len(sessions)):
        window = sessions[max(0, end - lookback) : end + 1]
        day = sessions[end]
        today = universe[universe["session_date"] == day]
        liquid = today[
            (today["close"] >= floors["price_min"])
            & (today["close"] * today["volume"] >= floors["signal_dollar_volume_min"])
        ]["ticker"]
        part = universe[
            universe["ticker"].isin(set(liquid)) & universe["session_date"].isin(window)
        ]
        if part.empty:
            continue
        grid, tickers = hm.grids(part, window)
        found = breakouts.detect(grid, tickers, window, cfg.breakout)
        if found.empty:
            continue
        criteria = ["bo_b1", "bo_b2", "bo_b3", "bo_b4"]
        if set(criteria) <= set(found.columns):
            watch = found[found[criteria].fillna(False).astype(bool).all(axis=1)]
        else:
            watch = found.iloc[0:0]
        for r in watch.to_dict("records"):
            rows.append({"kind": "watch", **_fields(r, "bo_")})
        if "trig_b5" in found:
            for r in found[found["trig_b5"].fillna(False).astype(bool)].to_dict("records"):
                rows.append({"kind": "trigger", **_fields(r, "trig_")})
    return pd.DataFrame(rows)


def _yes(value) -> bool:
    return value is not None and not pd.isna(value) and bool(value)


def _fields(row: dict, prefix: str) -> dict:
    keep = (
        "pivot",
        "order_stop",
        "risk_adr",
        "base_len",
        "contraction_depths",
        "b1",
        "b2",
        "b3",
        "b4",
        "b5",
        "range_adr",
        "rvol",
    )
    out = {"ticker": row["ticker"], "session_date": row["session_date"]}
    for key in keep:
        if f"{prefix}{key}" in row:
            out[key] = row[f"{prefix}{key}"]
    return out


def write_sheet(
    hits: pd.DataFrame, bars: pd.DataFrame, data_dir: Path, n: int, seed: int, today: dt.date
) -> Path:
    """Sample `n` hits and write the audit sheet with charts."""
    folder = Path(data_dir) / "docs" / f"breakout_audit_{today.isoformat()}"
    picked = hits.sample(n=min(n, len(hits)), random_state=seed) if len(hits) else hits
    lines = [
        f"# Breakout hand audit · {today.isoformat()}",
        "",
        f"{len(picked)} random hits out of {len(hits)} found by replaying B1-B5 over Massive "
        f"history (seed {seed}). Tick each criterion you agree with; note what the code got "
        "wrong.",
        "",
    ]
    by_ticker = {t: g for t, g in bars.groupby("ticker")}
    for i, row in enumerate(picked.sort_values("session_date").to_dict("records"), start=1):
        flags = " ".join(
            f"B{k}={'yes' if _yes(row.get(f'b{k}')) else 'no'}"
            for k in range(1, 6)
            if row.get(f"b{k}") is not None
        )
        lines += [
            f"## {i}. {row['ticker']} · {row['kind']} · {row['session_date']}",
            "",
            f"- Pivot {row['pivot']:.2f} · order stop {row['order_stop']:.2f} · risk "
            f"{row['risk_adr']:.2f} ADR · base {int(row['base_len'])} days",
            f"- Contractions (%): {row.get('contraction_depths') or 'none'}",
            f"- Code says: {flags}",
            "",
        ]
        chart = folder / f"{i:02d}_{row['ticker']}.png"
        ticker_bars = by_ticker.get(row["ticker"])
        if ticker_bars is not None:
            charts.before_shot(
                ticker_bars,
                chart,
                title=f"{row['ticker']} · {row['kind']} · {row['session_date']}",
                signal_session=row["session_date"],
                sessions=120,
                pivot=row["pivot"],
                order_stop=row["order_stop"],
            )
            lines += [f"![{row['ticker']}]({folder.name}/{chart.name})", ""]
        lines += [
            "- [ ] B1 prior move   - [ ] B2 base   - [ ] B3 trend   - [ ] B4 tight right side"
            "   - [ ] B5 trigger (if trigger)   - [ ] pivot right   - [ ] stop right",
            "- Notes: ",
            "",
        ]
    sheet = Path(data_dir) / "docs" / f"breakout_audit_{today.isoformat()}.md"
    sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return sheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Breakout hand-audit sheet from history replay")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--replay-days", type=int, default=60)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261019)
    args = parser.parse_args(argv)

    cfg = load_config()
    until = clock.session_date(cfg.schedule, "eod", dt.datetime.now(dt.UTC))
    need = (
        args.replay_days + cfg.breakout["base_max_days"] + cfg.breakout["prior_move_max_days"] + 60
    )
    sessions = clock.sessions_back(cfg.schedule, until, need)
    bars = history.load_bars(args.data_dir, sessions)
    if bars.empty or bars["session_date"].nunique() < need // 2:
        print("Audit: not enough history yet (run the Massive backfill first)")
        return 1
    hits = replay(bars, sessions, args.replay_days, cfg)
    sheet = write_sheet(hits, bars, args.data_dir, args.n, args.seed, until)
    print(f"Audit: {len(hits)} hits over {args.replay_days} sessions; sheet {sheet}")
    return 0
