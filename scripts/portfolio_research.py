"""Portfolio research around the graded setups (Emil, 21 Oct 2026): the report in the data
repo's docs/research/2026-10-21-portfolio-research.md. Prints the tables; writes nothing to
this public repo. Needs the benchmark curves first:

uv run python -m trading_os.portfolio_study --data-dir ../trading-os-data --out <private folder>
uv run python scripts/portfolio_research.py --data-dir ../trading-os-data --bench <private folder>

The trades are the grading study's out-of-sample trades 2019-2026 (`grading-10y` release,
portfolio_trades_oos_v1.parquet), graded with the confirmed bands in config `grading:`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from trading_os import portfolio_sim as sim
from trading_os import portfolio_study as ps
from trading_os import remote_data
from trading_os.config import load_config

QM_BASE = {"A+": 1.0, "A": 0.75, "B": 0.5}
TRADES = "portfolio_trades_oos_v1.parquet"


def graded_trades(path: Path, cfg) -> pd.DataFrame:
    """The out-of-sample trades with the confirmed grades, ready for portfolio_sim."""
    bands = {s: rule["bands"] for s, rule in cfg.grading["strategies"].items()}
    t = pd.read_parquet(path)
    t = t[t["strategy"].isin(bands)].copy()
    grade = pd.Series("C", index=t.index, dtype=object)
    for strat, rule_bands in bands.items():
        mine = t["strategy"] == strat
        for floor, label in reversed(rule_bands):
            grade[mine & (t["pred"] >= floor)] = label
    t["grade"] = grade
    t["session_date"] = pd.to_datetime(t["session_date"]).dt.date
    t = t.reset_index(drop=True)
    t["trade_id"], t["priority"], t["side"] = np.arange(len(t)), t["pred"], t["side"].astype(int)
    t["frac_1"], t["days_1"], t["r_1"] = 1.0, t["days"].fillna(0).astype(int), t["net"]
    t["cost_pct"] = 0.0  # the costs are inside the net R
    return t


def closes(files, tickers) -> tuple[list, list, np.ndarray]:
    bars = (
        ds.dataset([str(f) for f in files])
        .to_table(
            columns=["ticker", "session_date", "close"],
            filter=ds.field("ticker").isin(list(tickers)),
        )
        .to_pandas()
    )
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    wide = bars.drop_duplicates(["session_date", "ticker"]).pivot(
        index="session_date", columns="ticker", values="close"
    )
    return list(wide.index), list(wide.columns), wide.to_numpy(dtype=float)


def switches(t: pd.DataFrame, sessions: list, spy: np.ndarray) -> pd.DataFrame:
    """`spy_up`: SPY over its 200-day average at the close before the entry day. `curve_ok`:
    the strategy's last 50 closed graded trades (exits before the entry day) averaged >= 0 R,
    or fewer than 20 had closed."""
    pos = {d: i for i, d in enumerate(sessions)}
    s = pd.Series(spy, index=sessions)
    t = t.copy()
    t["spy_up"] = t["session_date"].map((s > s.rolling(200).mean()).shift(1)).fillna(False)
    t["t_in"] = t["session_date"].map(pos)
    t["t_out"] = t["t_in"] + t["days"].fillna(0).astype(int)
    graded = t["grade"].isin(["A", "B"])
    ok = pd.Series(True, index=t.index)
    for _, part in t[graded].groupby("strategy"):
        done = part.sort_values("t_out")[["t_out", "net"]].to_numpy()
        for i in part.index:
            past = done[done[:, 0] < t.at[i, "t_in"]][-50:, 1]
            ok[i] = len(past) < 20 or past.mean() >= 0
    t["curve_ok"] = ok
    return t


def variants(t: pd.DataFrame) -> dict:
    return {
        "base (A 0.75 %, B 0.5 %)": (t, {}),
        "B capped at 4": (t, {"max_by_grade": {"B": 4}}),
        "B capped at 6": (t, {"max_by_grade": {"B": 6}}),
        "B capped at 8": (t, {"max_by_grade": {"B": 8}}),
        "A grades only": (t, {"risk_pct": {"A+": 1.0, "A": 0.75}}),
        "Luk flush only": (t[t.strategy == "luk_avwap_flush"], {}),
        "EP only": (t[t.strategy == "ep"], {}),
        "EP9M only": (t[t.strategy == "ep9m"], {}),
        "Luk flush + EP (no EP9M)": (t[t.strategy != "ep9m"], {}),
        "base, no new trades with SPY under 200d": (t[t.spy_up], {}),
        "base, strategy equity-curve switch": (t[t.curve_ok], {}),
        "best grade first (the 20 Oct table)": (t.assign(entry_minute=0), {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--bench", type=Path, required=True, help="portfolio_study --out folder")
    args = parser.parse_args()
    cfg = load_config()
    repo = remote_data.repo_of(args.data_dir)
    t = graded_trades(remote_data.fetch(repo, "grading-10y", TRADES)[0], cfg)
    files = remote_data.fetch(repo, "bars-alpaca", "20[12][0-9].parquet")
    recent = [f for f in files if int(f.stem) >= 2019]
    sessions, tickers, cl = closes(recent, set(t.ticker) | {"SPY"})
    t = switches(t, sessions, cl[:, tickers.index("SPY")])
    bench = pd.read_parquet(args.bench / "benchmark_curves.parquet")
    pd.set_option("display.width", 250)

    rows, curves = [], {}
    for name, (part, extra) in variants(t).items():
        rules = sim.Rules(**{"risk_pct": QM_BASE} | extra)
        curve, taken = sim.simulate(part, cl, sessions, tickers, rules)
        m = sim.summary(curve, taken)
        rows.append(
            {
                "variant": name,
                "cagr": m["cagr_pct"],
                "max_dd": m["max_dd_pct"],
                "sharpe": m["sharpe"],
                "exposure": m["avg_long_pct"],
                "trades_yr": m["trades_per_year"],
            }
        )
        curves[name] = curve.assign(session_date=pd.to_datetime(curve["session_date"])).set_index(
            "session_date"
        )
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    parks = {
        "BIL (cash)": "BIL (cash)",
        "SPY": "SPY",
        "SPY above 200d": "SPY above 200d, else BIL",
        "QQQ": "QQQ",
        "QQQ above 200d": "QQQ above 200d, else BIL",
    }
    rows, blended = [], {}
    for mix in ("base (A 0.75 %, B 0.5 %)", "B capped at 4", "A grades only", "Luk flush only"):
        c = curves[mix]
        for label, col in parks.items():
            curve = ps.with_idle_cash_in(c["equity"], c["long_pct"] / 100, bench[col])
            blended[f"{mix} | idle in {label}"] = curve
            rows.append({"mix": mix, "idle cash in": label} | ps.curve_stats(curve))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    for first in ("QQQ above 200d, else BIL", "QQQ"):
        frame = pd.DataFrame(
            {first: bench[first], "SPY": bench["SPY"]}
            | {k: blended[k] for k in blended if "A grades" in k or "Luk flush" in k}
        ).dropna()
        print(f"Bootstrap against {first}")
        print(ps.bootstrap(frame.pct_change().dropna(), draws=2000).round(2).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
