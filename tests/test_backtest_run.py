"""Backtest step 6: metrics by hand, and an end-to-end run on synthetic bars."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
import yaml

from trading_os.backtest import metrics as mt
from trading_os.backtest import run as rn
from trading_os.backtest.config import DEFAULT_PATH


def test_trade_stats_by_hand():
    d = [dt.date(2021, 1, i) for i in range(1, 6)]
    t = pd.DataFrame(
        {
            "r": [2.0, -1.0, -1.0, 3.0, -1.0],
            "entry_date": d,
            "exit_date": d,
            "hold_days": [10, 1, 2, 20, 1],
            "exit_reason": ["trail", "stop", "stop", "trail", "gap_stop"],
            "day1_stop": [False, True, False, False, True],
            "shakeout": [False, True, False, False, False],
            "r_no_partial": [2.5, -1.0, -1.0, 3.5, -1.0],
        }
    )
    s = mt.trade_stats(t)
    assert s["n"] == 5 and s["win_rate"] == pytest.approx(0.4)
    assert s["avg_win_r"] == pytest.approx(2.5) and s["avg_loss_r"] == pytest.approx(-1.0)
    assert s["expectancy_r"] == pytest.approx(0.4)
    assert s["profit_factor"] == pytest.approx(5 / 3)
    assert s["median_hold_win"] == 15 and s["median_hold_loss"] == 1
    assert s["day1_stop_rate"] == pytest.approx(0.4)
    assert s["max_losses_in_row"] == 2
    assert s["top10_share"] == pytest.approx(1.0)  # five trades: the top 10 are all of them
    assert s["shakeout_rate"] == pytest.approx(1 / 3)  # one of the three stop-outs
    assert s["partial_cost_r"] == pytest.approx(0.2)


def test_top10_share_with_many_trades():
    t = pd.DataFrame({"r": [5.0] * 10 + [-0.5] * 40})
    s = mt.trade_stats(t)
    assert s["top10_share"] == pytest.approx(50 / 30)  # the top 10 made more than the net


def test_account_stats_by_hand():
    idx = pd.bdate_range("2021-01-01", "2022-01-01")
    e = np.linspace(100, 200, len(idx))
    e[100] = 50  # a one-day 50 %+ hole
    eq = pd.DataFrame({"equity": e, "gross_pct": 50.0}, index=idx.date)
    s = mt.account_stats(eq)
    years = (idx[-1] - idx[0]).days / 365.25
    assert s["cagr_pct"] == pytest.approx(((200 / 100) ** (1 / years) - 1) * 100)
    assert s["max_dd_pct"] == pytest.approx((50 / e[99] - 1) * 100)
    assert s["avg_gross_pct"] == 50


def test_s1_market_check_counts_by_week():
    days = pd.bdate_range("2021-03-01", periods=10).date
    regime = pd.Series(["down"] * 5 + ["up"] * 5, index=days)
    breadth = pd.Series(["weak"] * 5 + ["strong"] * 5, index=days)
    sig = pd.DataFrame(
        {
            "setup": ["S1", "S1", "S1", "L2"],
            "skip": [False, False, True, False],
            "session_date": [days[0], days[2], days[3], days[6]],
        }
    )
    wk = mt.s1_market_check(sig, regime, breadth)
    assert wk["s1_signals"].tolist() == [2, 0]  # the skipped one and the L2 don't count
    assert wk["down_share"].tolist() == [1.0, 0.0]
    summary = mt.s1_summary(wk)
    assert set(summary["tag"]) >= {"regime=down", "regime=up", "breadth=weak", "breadth=not weak"}


def synthetic_bars(path, n_days=420, n_tickers=40, seed=3):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2020-01-01", periods=n_days).date
    rows = []
    for j in range(n_tickers + 1):
        name = (
            "QQQ" if j == n_tickers else "T" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[j % 26] * (1 + j // 26)
        )
        c = 30 * np.exp(np.cumsum(rng.normal(0.001, 0.035, n_days)))
        h = c * (1 + rng.uniform(0, 0.05, n_days))
        lo = c * (1 - rng.uniform(0, 0.05, n_days))
        o = lo + (h - lo) * rng.uniform(0, 1, n_days)
        v = rng.lognormal(14.5, 0.7, n_days)
        rows.append(
            pd.DataFrame(
                {
                    "session_date": days,
                    "ticker": name,
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": v,
                }
            )
        )
    bars = pd.concat(rows)
    years = sorted({d.year for d in days})
    for y in years:
        bars[[d.year == y for d in bars["session_date"]]].to_parquet(path / f"{y}.parquet")
    return years


def test_end_to_end_run_writes_the_folder_and_logs_counts_only(tmp_path, capsys):
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    years = synthetic_bars(bars_dir)
    raw = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    raw["data"]["years"] = years
    raw["universe"]["avg_volume_min"] = 100_000
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    data_dir = tmp_path / "data"
    assert (
        rn.main(
            [
                "--config",
                str(cfg_path),
                "--bars-dir",
                str(bars_dir),
                "--data-dir",
                str(data_dir),
                "--run-id",
                "test",
            ]
        )
        == 0
    )
    out = data_dir / "backtests" / "test"
    for name in (
        "trades.parquet",
        "equity.parquet",
        "summary.parquet",
        "report.md",
        "spot_check.csv",
        "config.yaml",
    ):
        assert (out / name).exists(), name
    rep = (out / "report.md").read_text(encoding="utf-8")
    assert rep.splitlines()[0].startswith("Survivorship:")
    assert "## Phase 2 answers" in rep
    summary = pd.read_parquet(out / "summary.parquet")
    assert {"trades", "account"} <= set(summary["kind"])
    logged = capsys.readouterr().out
    assert "TA" not in logged and "QQQ" not in logged  # no tickers in the log
