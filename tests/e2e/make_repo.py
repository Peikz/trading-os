"""A small, realistic synthetic data repo for the end-to-end tests (`web/e2e/`).

    uv run python -m tests.e2e.make_repo OUT_DIR

writes `OUT_DIR/data-repo` (what `TRADING_OS_DATA` points at) and `OUT_DIR/cache` (the release
files the dashboard would download, for `TRADING_OS_CACHE`). Synthetic data only: every ticker
is built from letters (`sym("W")` is W + "ZQ" + W), so no real symbol appears here, and every
price is a seeded random walk. The dates sit just before today, so the board, the plans and the
daily notes look current whenever the suite runs.

Hand-written human inputs (fills, plans, notes, watchlists, alerts, grades) go through the
package's own writers, so they land exactly where the dashboards write them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import alerts, daily_notes, dashboard, journal, my_watchlists, plans, stock_notes
from trading_os.bars_pack import shard_of
from trading_os.config import load_config


def sym(letter: str) -> str:
    """A synthetic ticker: W -> W + ZQ + W. Never a real symbol."""
    return "".join([letter, "Z", "Q", letter])


TICKERS = [sym(c) for c in "WXYVUTSR"]
SECTOR_ETF = sym("K")  # a synthetic sector fund for the Market page's rotation
INDUSTRIES = [
    ("Tech", "Software"), ("Finance", "Banks"), ("Tech", "Semiconductors"),
    ("Materials", "Mining"), ("Health", "Biotech"), ("Energy", "Oil & Gas"),
    ("Tech", "Software"), ("Consumer", "Retail"),
]  # fmt: skip
WATCHLISTS = {"Leaders": TICKERS[:3], "Earnings soon": TICKERS[3:5]}
# The slots of a day and the scans that run in each (config/scans.yaml); one grade per hit.
SLOT_SCANS = {
    "pm": ["ep_pm"],
    "am": ["ep_am", "pivot_watch"],
    "mid": ["ep9m_pace"],
    "eod": ["ep_day", "mb_up", "vcp", "breakout_watch"],
    "ah": ["ep_ah"],
}
GRADES = ["A+", "A", "B", "C"]
ACCOUNT = "currency: USD\nsize: 100000\nrisk_pct: 0.5\nmax_position_pct: 100\n"
BAR_DAYS = 504  # two years of sessions, like the bars-2y release


def sessions(today: dt.date | None = None, n: int = 3) -> list[dt.date]:
    """The last `n` weekdays before today, oldest first."""
    end = pd.Timestamp(today or dt.date.today()) - pd.offsets.BDay(1)
    return [d.date() for d in pd.bdate_range(end=end, periods=n)]


def bars(last: dt.date) -> pd.DataFrame:
    """Two years of daily bars per ticker: a seeded random walk with an upward drift."""
    rng = np.random.default_rng(7)
    days = pd.bdate_range(end=pd.Timestamp(last), periods=BAR_DAYS)
    frames = []
    for i, t in enumerate(TICKERS):
        steps = rng.normal(0.0015, 0.025, BAR_DAYS)
        close = (8 + 4 * i) * np.exp(np.cumsum(steps))
        open_ = close * (1 + rng.normal(0, 0.008, BAR_DAYS))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.002, 0.03, BAR_DAYS))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.002, 0.03, BAR_DAYS))
        volume = rng.integers(200_000, 3_000_000, BAR_DAYS).astype(float)
        frames.append(
            pd.DataFrame(
                {
                    "ticker": t,
                    "session_date": days.date,
                    "open": open_.round(2),
                    "high": high.round(2),
                    "low": low.round(2),
                    "close": close.round(2),
                    "volume": volume,
                }
            )  # fmt: skip
        )
    return pd.concat(frames, ignore_index=True)


def write_bars(cache: Path, daily: pd.DataFrame, last: dt.date) -> None:
    folder = cache / "bars-2y"
    folder.mkdir(parents=True, exist_ok=True)
    for shard, part in daily.groupby(daily["ticker"].map(shard_of)):
        part.to_parquet(folder / f"bars_2y_{last}_{shard}.parquet", index=False)


def universe(daily: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    rows = []
    for i, t in enumerate(TICKERS):
        own = daily[(daily["ticker"] == t) & (daily["session_date"] <= day)].tail(21)
        last, prev = own.iloc[-1], own.iloc[-2]
        adr = float(((own["high"] / own["low"] - 1) * 100).mean())
        sector, industry = INDUSTRIES[i]
        rows.append({
            "ticker": t, "exchange": "NASDAQ" if i % 2 == 0 else "NYSE", "sector": sector,
            "industry": industry, "float_shares": 2e7 + i * 1e7,
            "earnings_date_next": pd.Timestamp(day) + pd.Timedelta(days=10 + 5 * i),
            "close": float(last["close"]),
            "chg_pct": float((last["close"] / prev["close"] - 1) * 100),
            "volume": float(last["volume"]), "adr20_pct": round(adr, 2), "rs_pct": 40 + 7 * i,
            "market_cap": (5 + i) * 1e8, "rvol50": 1.0 + i / 4,
        })  # fmt: skip
    return pd.DataFrame(rows)


def hits(day: dt.date, slot: str, uni: pd.DataFrame, first: int) -> pd.DataFrame:
    """One run's hits: each scan of the slot hits three stocks graded A+/A/B/C in turn."""
    rows, k = [], first
    for s, scan in enumerate(SLOT_SCANS[slot]):
        for j in range(3):
            i = (k + s) % len(TICKERS)
            u = uni.iloc[i]
            grade = GRADES[k % len(GRADES)]
            entry = round(float(u["close"]) * 1.01, 2)
            stop = round(entry * 0.95, 2)
            shares = int(500 / (entry - stop))
            rows.append({
                "signal_id": f"{day}-{slot}-{scan}-{j}", "session_date": pd.Timestamp(day),
                "slot": slot, "scan": scan, "ticker": u["ticker"], "rank": j + 1,
                "tier": "alert" if j < 2 else "log", "pushed": j < 2 and grade != "C",
                "grade": grade, "grade_score": {"A+": 0.6, "A": 0.4, "B": 0.2, "C": -0.1}[grade],
                "grade_strategy": scan, "grade_why": "synthetic: rank in the scan",
                "grade_stat_trades": 120.0, "grade_stat_win_pct": 45.0,
                "grade_stat_mean_r": 0.3, "grade_stat_median_r": 0.1,
                "grade_stat_years_pos": 4.0, "grade_stat_years": 5.0,
                "grade_stat_days_median": 5.0, "plan_entry": entry, "plan_stop": stop,
                "plan_shares": shares, "plan_position_usd": round(shares * entry, 2),
                "plan_risk_usd": round(shares * (entry - stop), 2), "plan_stop_basis": "day low",
                "pivot": round(entry * 0.995, 2), "close": float(u["close"]),
                "gap_pct": 5.0 + j, "rvol50": float(u["rvol50"]), "adr20_pct": u["adr20_pct"],
                "chg_pct": u["chg_pct"], "exchange": u["exchange"],
            })  # fmt: skip
            k += 1
    return pd.DataFrame(rows)


def breadth_row(day: dt.date, i: int) -> dict:
    """An EOD breadth row with the fields the breadth job writes (`breadth.eod_breadth`)."""
    return {
        "session_date": pd.Timestamp(day), "breadth_n": 2400, "up4": 300 + 5 * i, "mb_up": 280,
        "down4": 120 + i, "up_count_rule": "stockbee_4pct", "ratio_5d": 1.4, "ratio_10d": 1.3,
        "ratio_days_available": 10, "up25q": 400, "down25q": 150, "quarter_basis": "tv:Perf.3M",
        "up25m": 90, "down25m": 40, "up50m": 20, "down50m": 8, "up13_34d": 300,
        "down13_34d": 120, "mid_rows": 2300, "pct_above_ma20": 61.0, "pct_above_ma50": 58.0,
        "pct_above_ma200": 55.0, "qqq_close": 90.0 + i, "qqq_sma10": 88.0, "qqq_sma20": 87.0,
        "qqq_sma50": 84.0, "qqq_sma20_5ago": 86.0, "qqq_sma10_5ago": 87.0, "qqq_light": "GREEN",
        "qqq_chg_pct": 0.6, "qqq_trend": "up", "breadth_state": "strong", "scan_count": 60 + i,
        "scan_count_basis": "eod-bootstrap", "light": "GO", "light_missing": "",
        "spy_close": 100.0 + i, "spy_chg_pct": 0.4, "spy_pm_change_pct": 0.1,
        "vix_close": 15.0 - i / 10, "vix_chg_pct": -1.5,
    }  # fmt: skip


def write_market(root: Path, days: list[dt.date]) -> None:
    for i, day in enumerate(days):
        folder = root / "data" / "breadth" / str(day.year)
        folder.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([breadth_row(day, i)]).to_parquet(folder / f"{day}_eod.parquet")
    # Industries: a week's moves need six saved runs before the newest
    for i, day in enumerate(pd.bdate_range(end=pd.Timestamp(days[-1]), periods=7).date):
        folder = root / "data" / "industries" / str(day.year)
        folder.mkdir(parents=True, exist_ok=True)
        names = sorted({ind for _, ind in INDUSTRIES})
        sector = {ind: sec for sec, ind in INDUSTRIES}
        order = names if i < 6 else names[::-1]
        pd.DataFrame({
            "industry": order, "sector": [sector[n] for n in order],
            "industry_rank": range(1, len(order) + 1), "med_ret_22": 5.0, "med_ret_63": 9.0,
            "members": 10,
        }).to_parquet(folder / f"{day}_eod.parquet")  # fmt: skip
    folder = root / "data" / "sectors" / str(days[-1].year)
    folder.mkdir(parents=True, exist_ok=True)
    rows = [("SPY", "S&P 500", "Index", 1.0, 2.0), (SECTOR_ETF, "Synthetic", "Sector", 3.0, -1.0)]
    pd.DataFrame([
        {"symbol": f"AMEX:{t}", "ticker": t, "name": n, "group": g, "chg_pct": 0.5,
         "ret_1w": w, "ret_1m": m, "ret_3m": 4.0, "ret_ytd": 9.0, "close": 10.0, "sma50": 9.0,
         "sma200": 8.0, "rvol": 1.1}
        for t, n, g, w, m in rows
    ]).to_parquet(folder / f"{days[-1]}_eod.parquet")  # fmt: skip
    heat = {
        "built": str(days[-1]),
        "bands": [[18, "cool"], [45, "mild"], [81, "warm"], [None, "hot"]],
        "band_labels": {"cool": "under 18", "mild": "18-44", "warm": "45-80", "hot": "over 80"},
        "min_trades": 30,
        "setups": [{"key": "surf", "label": "MA-surf", "short": "MA-surf", "kind": "C",
                    "side": "long", "plan": "10:00 over the pivot"}],
        "rows": [
            {"setup": "surf", "heat": "warm", "period": p, "trades": 40, "signal_days": 30,
             "mean_r": 0.5, "day_mean_r": 0.4, "win_pct": 30.0, "years_up": 3, "years": 4}
            for p in ("2016-21", "2022-26")
        ],
    }  # fmt: skip
    grades = {  # the study's grade stats (Research → Grades, Today's grade block)
        "source": "docs/research/grading.md",
        "period": "out of sample 2019-2026",
        "strategies": {
            "ep": {"grades": {g: {"trades": 300 - 50 * i, "win_pct": 50.0 - 5 * i,
                                  "mean_r": 0.6 - 0.2 * i} for i, g in enumerate(GRADES)}},
        },
    }  # fmt: skip
    (root / "data" / "grading").mkdir(parents=True, exist_ok=True)
    (root / "data" / "grading" / "heat_stats.json").write_text(json.dumps(heat))
    (root / "data" / "grading" / "grade_stats.json").write_text(json.dumps(grades))


def write_scan_watchlists(root: Path, day: dt.date) -> None:
    folder = root / "data" / "watchlists" / str(day.year)
    folder.mkdir(parents=True, exist_ok=True)
    rows = [
        (TICKERS[0], "ep_watch", "active", "ep_day gap"),
        (TICKERS[1], "bo_watch", "active", "tight base"),
        (TICKERS[2], "bo_watch", "triggered", "broke out"),
    ]
    pd.DataFrame([
        {"ticker": t, "list": wl, "status": status, "status_date": day, "added_date": day,
         "source_signal_id": f"{day}-eod-ep_day-0", "reason": why,
         "run_ts": pd.Timestamp(day) + pd.Timedelta(hours=21)}
        for t, wl, status, why in rows
    ]).to_parquet(folder / f"{day}_eod.parquet")  # fmt: skip


def write_research(root: Path, cache: Path, days: list[dt.date], daily: pd.DataFrame) -> None:
    docs = root / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "how-we-test.md").write_text("# How we test\n\nSynthetic write-up for the tests.\n")
    (docs / f"{days[0]}-study.md").write_text(
        "# A synthetic study\n\n| setup | trades |\n|---|---|\n| ep | 120 |\n"
    )
    # The strategy history build (Research → History)
    sample = pd.bdate_range(end=pd.Timestamp(days[-1]) - pd.offsets.BDay(30), periods=40)
    rows = []
    for i, day in enumerate(sample):
        rows.append({
            "strategy": "mb_up" if i % 2 else "qm_gainers", "side": "long",
            "session_date": day.date(), "ticker": TICKERS[i % 4], "entry": 10.0, "stop": 9.0,
            "stop_adr": 1.0, "close": 10.0 + i % 5, "chg_pct": 1.0, "mkt_breadth_state": "strong",
            "mkt_qqq_trend": "up", "above_ma200": True, "pnl_1d": 1.0 - i % 3, "pnl_5d": 2.0,
            "pnl_21d": 3.0, "pnl_63d": 4.0, "r_5d": 0.5, "r_21d": 1.0 - i % 2, "r_63d": 1.5,
            "stop_hit_5d": False, "r_trail_ma20": 0.8, "r_trail_ema9": 0.4,
        })  # fmt: skip
    build = root / "data" / "strategy_history" / str(days[-1])
    build.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(build / "all.parquet")
    # Entries & exits, 2 years: the intraday study's summary (a release file)
    folder = cache / "intraday-2y"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "strategy": ["ep", "ep", "breakout"], "entry": ["open", "t_1030", "open"],
        "stop_rule": ["lod", "adr", "lod"], "trades": [120, 80, 60],
        "stopped_same_day%": [10.0, 5.0, 8.0], "R_hold_5d": [0.3, 0.5, 0.1],
        "win_hold_5d%": [50.0, 55.0, 40.0], "R_hold_21d": [0.4, 0.2, 0.0],
        "win_hold_21d%": [45.0, 50.0, 30.0],
    }).to_parquet(folder / "summary_none.parquet")  # fmt: skip


def write_journal(root: Path, days: list[dt.date], daily: pd.DataFrame) -> None:
    """A closed trade, an open position with its stop, a plan, notes, alerts and a grade."""
    cfg = load_config()
    (root / "settings").mkdir(exist_ok=True)
    (root / "settings" / "account.yaml").write_text(ACCOUNT)

    def close_on(t: str, day) -> float:
        own = daily[(daily["ticker"] == t) & (daily["session_date"] <= day)]
        return float(own.iloc[-1]["close"])

    opened = (pd.Timestamp(days[0]) - pd.offsets.BDay(15)).date()
    closed = (pd.Timestamp(days[0]) - pd.offsets.BDay(5)).date()
    won, held = TICKERS[4], TICKERS[5]
    entry = close_on(won, opened)
    stop = round(entry * 0.95, 2)
    fills = [
        (journal.manual_fill(opened, won, "buy", 100, entry, 1.0, "ep_day"), stop),
        (journal.manual_fill(closed, won, "sell", 100, close_on(won, closed), 1.0), None),
    ]
    entry = close_on(held, days[0])
    fills.append(
        (journal.manual_fill(days[0], held, "buy", 50, entry, 1.0, "vcp"), round(entry * 0.94, 2))
    )
    for fill, stop in fills:
        journal.log_manual(root, cfg, fill, stop)
    plan_entry = close_on(TICKERS[6], days[-1])
    plans.create(root, days[-1], TICKERS[6], "long", round(plan_entry * 1.01, 2),
                 round(plan_entry * 0.95, 2), 40, "breakout_watch", "synthetic plan")  # fmt: skip
    noted = TICKERS[0]
    stock_notes.add(root, noted, f"Tight flag on {noted}; waiting for volume.", days[-2])
    stock_notes.add(root, noted, "Second note: earnings in two weeks.", days[-1])
    for name, members in WATCHLISTS.items():
        my_watchlists.add(root, name, members, note="synthetic")
    alerts.add(root, TICKERS[1], round(close_on(TICKERS[1], days[-1]) * 1.05, 2), "above", "pivot")
    daily_notes.add(root, f"Market strong; watching ${TICKERS[0]}.", days[-1])
    daily_notes.add(root, "Quiet day, no trades.", days[-2])
    dashboard.save_note(root, "signal", f"{days[-1]}-eod-ep_day-0", "A", "clean gap", "ep", [])


def build(out: Path, today: dt.date | None = None) -> tuple[Path, Path]:
    """Write the repo and the cache under `out` (replacing them); returns (repo, cache)."""
    out = Path(out)
    root, cache = out / "data-repo", out / "cache"
    for folder in (root, cache):
        if folder.exists():
            shutil.rmtree(folder)
        (folder).mkdir(parents=True)
    (root / "data").mkdir()
    days = sessions(today)
    daily = bars(days[-1])
    write_bars(cache, daily, days[-1])
    k = 0
    for day in days:
        uni = universe(daily, day)
        for slot in SLOT_SCANS:
            frame = hits(day, slot, uni, k)
            k += len(frame)
            folder = root / "data" / "candidates" / str(day.year)
            folder.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(folder / f"{day}_{slot}.parquet")
            if slot == "eod":
                ufolder = root / "data" / "universe" / str(day.year)
                ufolder.mkdir(parents=True, exist_ok=True)
                uni.to_parquet(ufolder / f"{day}_eod.parquet")
    write_market(root, days)
    write_scan_watchlists(root, days[-1])
    write_research(root, cache, days, daily)
    write_journal(root, days, daily)
    (out / "manifest.json").write_text(
        json.dumps(
            {"tickers": TICKERS, "sessions": [str(d) for d in days], "watchlists": WATCHLISTS},
            indent=1,
        )  # fmt: skip
    )
    return root, cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    root, cache = build(args.out)
    print(f"wrote {root} and {cache}")


if __name__ == "__main__":
    main()
