"""Steps 6 and 7 of the backtest module (docs/backlog/backtest.md §8-§10): run everything and
write the run folder.

    uv run python -m trading_os.backtest.run --bars-dir <year files> --data-dir <data repo>

The run folder (`<data repo>/backtests/<run_id>/`) holds `trades.parquet`, `equity.parquet`,
`summary.parquet`, `report.md`, `spot_check.csv` and a copy of `config.yaml`. Stdout gets
counts and the folder name only (this repo's Actions logs are public); results live only in
the private data repo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os.backtest import data, engine, indicators, metrics, portfolio, setups
from trading_os.backtest.config import DEFAULT_PATH, BacktestConfig, load_config
from trading_os.logsafe import status

LIMITS = [
    "Daily-bar stand-ins for setups traded on 1-5 minute charts: entries and stops are wider "
    "than the real ones, and many signals are skipped by the max-stop rule.",
    "No news or catalyst filter; the gap and volume filters stand in for it.",
    "Shorts assume borrow is always available, at no fee.",
    "No point-in-time market cap; that filter is skipped.",
    "Results compare variants on the same data. They are not expected returns.",
]


def build(bars: pd.DataFrame, cfg: BacktestConfig):
    """Wide bars, indicators (with the QQQ regime) and every setup's signals."""
    keep = set(bars.loc[bars["in_universe"], "ticker"]) | set(cfg.data.index_tickers)
    w = indicators.wide(bars[bars["ticker"].isin(keep)])
    idx = cfg.indicators.regime.ticker
    qqq = w["close"].get(idx)
    for k in w:
        w[k] = w[k].drop(columns=list(cfg.data.index_tickers), errors="ignore")
    ind = indicators.compute(w, cfg, qqq)
    sig = setups.signals(w, ind, cfg.setups)
    first = w["close"].index[min(cfg.data.warmup_sessions, len(w["close"]) - 1)]
    sig = sig[sig["session_date"] >= first].reset_index(drop=True)
    return w, ind, sig


def run_portfolios(trades: pd.DataFrame, close: pd.DataFrame, cfg: BacktestConfig):
    curves, stats = [], []
    for group, members in portfolio.groups(cfg, trades["setup"].unique()).items():
        for (ev, kv), sub in trades[trades["setup"].isin(members)].groupby(
            ["exit_variant", "stop_variant"]
        ):
            if group not in ("S1", "S2") and (sub["side"] < 0).any():
                continue
            for sz in cfg.portfolio.sizing:
                eq, _ = portfolio.simulate(sub, close, cfg, sz)
                keys = {"group": group, "exit_variant": ev, "stop_variant": kv, "sizing": sz}
                curves.append(eq.reset_index().assign(**keys))
                stats.append({**keys, **metrics.account_stats(eq)})
    return pd.concat(curves, ignore_index=True), pd.DataFrame(stats)


def fmt(df: pd.DataFrame, cols: list[str]) -> str:
    """A small markdown table."""
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df[cols].iterrows():
        cells = []
        for c in cols:
            v = r[c]
            cells.append(f"{v:.2f}" if isinstance(v, (float, np.floating)) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def report(
    trade_sum: pd.DataFrame,
    acct: pd.DataFrame,
    s1: pd.DataFrame,
    by_year,
    by_regime,
    by_breadth,
    cfg: BacktestConfig,
    run_id: str,
    n_signals: int,
) -> str:
    base = trade_sum[(trade_sum["exit_variant"] == "E0") & (trade_sum["stop_variant"] == "K1")]
    cols = [
        "setup",
        "n",
        "win_rate",
        "expectancy_r",
        "profit_factor",
        "top10_share",
        "day1_stop_rate",
        "shakeout_rate",
    ]
    parts = [
        data.SURVIVORSHIP_LINE,
        "",
        f"# Backtest {run_id}",
        "",
        f"{n_signals} signals after the {cfg.data.warmup_sessions}-session warm-up. "
        f"Risk {cfg.portfolio.risk_pct} % a trade, "
        f"fill at the {cfg.engine.fill.replace('_', ' ')}.",
        "",
        "## Limits",
        *[f"- {x}" for x in LIMITS],
        "",
        "## Setups on the current exit (E0, K1)",
        fmt(base.sort_values("expectancy_r", ascending=False), cols),
        "",
        "## Every setup x exit x stop variant",
        fmt(
            trade_sum.sort_values(["setup", "exit_variant", "stop_variant"]),
            [
                "setup",
                "exit_variant",
                "stop_variant",
                "n",
                "expectancy_r",
                "win_rate",
                "profit_factor",
                "partial_cost_r",
                "max_losses_in_row",
            ],
        ),
        "",
        "## Phase 2 answers (B0 = buy stop as specced; B0C = buy at the close if it passes)",
        "Partial (E0 a third on day 3-5, E1 15 % at +3R, E2 none; K1):",
        fmt(
            trade_sum[
                trade_sum["setup"].isin(["B0", "B0C"])
                & (trade_sum["stop_variant"] == "K1")
                & trade_sum["exit_variant"].isin(["E0", "E1", "E2"])
            ],
            ["setup", "exit_variant", "n", "expectancy_r", "win_rate", "partial_cost_r"],
        ),
        "",
        "Stop handling (K0 keep vs K1 raise to the entry-day low; E0):",
        fmt(
            trade_sum[trade_sum["setup"].isin(["B0", "B0C"]) & (trade_sum["exit_variant"] == "E0")],
            [
                "setup",
                "stop_variant",
                "n",
                "expectancy_r",
                "win_rate",
                "day1_stop_rate",
                "shakeout_rate",
            ],
        ),
        "",
        "Sizing (P0 max 3 vs P1 2 % open risk), account per group on E0/K1:",
        fmt(
            acct[(acct["exit_variant"] == "E0") & (acct["stop_variant"] == "K1")].sort_values(
                ["group", "sizing"]
            ),
            [
                "group",
                "sizing",
                "cagr_pct",
                "max_dd_pct",
                "worst_month_pct",
                "positive_months",
                "avg_gross_pct",
            ],
        ),
        "",
        "## By year (E0, K1)",
        fmt(by_year, ["setup", "year", "n", "expectancy_r", "win_rate"]),
        "",
        "## By QQQ regime (E0, K1)",
        fmt(by_regime, ["setup", "regime", "n", "expectancy_r", "win_rate"]),
        "",
        "## By breadth (E0, K1)",
        fmt(by_breadth, ["setup", "breadth", "n", "expectancy_r", "win_rate"]),
        "",
        "## S1 as a market signal (weekly count)",
        fmt(s1, ["tag", "weeks", "mean_s1", "share_of_spike_weeks"]),
        "",
        "Every account is in `summary.parquet` (kind = account); every trade in `trades.parquet`.",
    ]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the daily-bar backtest and write the run folder")
    ap.add_argument("--config", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--bars-dir", type=Path)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--seed", type=int, default=0, help="for the spot-check sample")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    run_id = args.run_id or dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    files = data.bar_files(cfg, args.bars_dir, args.data_dir)
    if not files:
        status("Backtest: no bar files")
        return 1
    table = args.data_dir / "data" / "ep_enrich" / "tickers.parquet"
    listed = pd.read_parquet(table, columns=["ticker", "name", "type"]) if table.exists() else None
    bars = data.prepare(cfg, files, listed)
    status(data.SURVIVORSHIP_LINE)
    w, ind, sig = build(bars, cfg)
    del bars
    status(
        f"Backtest: {w['close'].shape[1]} tickers, {len(sig)} signals, "
        f"{int((~sig['skip']).sum())} tradable"
    )
    trades = engine.run(sig, w, ind, cfg)
    trades = portfolio.attach_rank(trades, ind, cfg.portfolio.rank_by)
    status(f"Backtest: {len(trades)} trade rows")
    curves, acct = run_portfolios(trades, w["close"], cfg)
    status(f"Backtest: {acct.shape[0]} account runs")
    trade_sum = metrics.trade_table(trades, ["setup", "exit_variant", "stop_variant"])
    cur = trades[(trades["exit_variant"] == "E0") & (trades["stop_variant"] == "K1")]
    cur = cur.assign(year=pd.to_datetime(cur["entry_date"]).dt.year)
    by_year = metrics.trade_table(cur, ["setup", "year"])
    by_regime = metrics.trade_table(cur, ["setup", "regime"])
    by_breadth = metrics.trade_table(cur, ["setup", "breadth"])
    s1 = metrics.s1_summary(metrics.s1_market_check(sig, ind["regime"], ind["breadth"]["tag"]))
    out = args.data_dir / "backtests" / run_id
    out.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(out / "trades.parquet", index=False)
    curves.to_parquet(out / "equity.parquet", index=False)
    summary = pd.concat(
        [trade_sum.assign(kind="trades"), acct.assign(kind="account")], ignore_index=True
    )
    summary.to_parquet(out / "summary.parquet", index=False)
    spot = cur.sample(min(20, len(cur)), random_state=args.seed)
    spot[
        [
            "setup",
            "ticker",
            "signal_date",
            "entry_date",
            "entry",
            "stop",
            "exit_date",
            "exit_price",
            "exit_reason",
        ]
    ].to_csv(out / "spot_check.csv", index=False)
    (out / "report.md").write_text(
        report(trade_sum, acct, s1, by_year, by_regime, by_breadth, cfg, run_id, len(sig)),
        encoding="utf-8",
    )
    shutil.copy(args.config, out / "config.yaml")
    status(f"Backtest: run folder backtests/{run_id} written (6 files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
