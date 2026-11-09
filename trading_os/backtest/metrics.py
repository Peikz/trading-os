"""Step 6 of the backtest module (docs/backlog/backtest.md §8): trade and account metrics.

Trade level (per setup x exit x stop variant, or any other grouping): count, win rate, average
win and loss in R, expectancy, profit factor, median days held for winners and losers, the share
stopped on day 1, the longest losing streak, the share of net R from the 10 best trades, the
shakeout rate (stop-outs that closed back past the entry within 3 sessions), and the mean R a
trade gave up or gained through its partial (`r_no_partial - r`).

Account level (per equity curve): CAGR, max drawdown, worst month, share of positive months,
average gross exposure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STOP_EXITS = ("stop", "gap_stop", "breakeven")


def longest_run(flags) -> int:
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def trade_stats(t: pd.DataFrame) -> dict:
    """Metrics for one set of trades (`r` is net R)."""
    r = t["r"].to_numpy(dtype="float64")
    n = len(r)
    if n == 0:
        return {"n": 0}
    win = r > 0
    gains, losses = r[win].sum(), -r[~win].sum()
    order = t.sort_values(["entry_date", "exit_date"]) if "entry_date" in t else t
    stops = t["exit_reason"].isin(STOP_EXITS) if "exit_reason" in t else pd.Series(False, t.index)
    net = r.sum()
    top10 = np.sort(r)[::-1][:10].sum()
    hold = t["hold_days"] if "hold_days" in t else pd.Series(np.nan, t.index)
    return {
        "n": n,
        "win_rate": win.mean(),
        "avg_win_r": r[win].mean() if win.any() else np.nan,
        "avg_loss_r": r[~win].mean() if (~win).any() else np.nan,
        "expectancy_r": r.mean(),
        "profit_factor": gains / losses if losses > 0 else np.inf,
        "net_r": net,
        "median_hold_win": hold[win].median() if win.any() else np.nan,
        "median_hold_loss": hold[~win].median() if (~win).any() else np.nan,
        "day1_stop_rate": t["day1_stop"].mean() if "day1_stop" in t else np.nan,
        "max_losses_in_row": longest_run(order["r"].to_numpy() <= 0),
        "top10_share": top10 / net if net > 0 else np.nan,
        "shakeout_rate": t.loc[stops, "shakeout"].mean()
        if "shakeout" in t and stops.any()
        else np.nan,
        "partial_cost_r": (t["r_no_partial"] - t["r"]).mean() if "r_no_partial" in t else np.nan,
    }


def trade_table(trades: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    rows = [
        {**dict(zip(by, k if isinstance(k, tuple) else (k,), strict=True)), **trade_stats(g)}
        for k, g in trades.groupby(by, sort=True)
    ]
    return pd.DataFrame(rows)


def account_stats(eq: pd.DataFrame) -> dict:
    """Metrics for one daily equity curve (index: session dates)."""
    e = eq["equity"].astype("float64")
    if len(e) < 2:
        return {"cagr_pct": np.nan}
    idx = pd.to_datetime(pd.Index(e.index))
    years = (idx[-1] - idx[0]).days / 365.25
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1 if years > 0 and e.iloc[-1] > 0 else np.nan
    dd = e / e.cummax() - 1
    monthly = pd.Series(e.to_numpy(), index=idx).resample("ME").last()
    mret = monthly.pct_change().dropna()
    first = monthly.iloc[0] / e.iloc[0] - 1
    mret = pd.concat([pd.Series([first], index=monthly.index[:1]), mret])
    return {
        "cagr_pct": cagr * 100,
        "max_dd_pct": dd.min() * 100,
        "worst_month_pct": mret.min() * 100,
        "positive_months": (mret > 0).mean(),
        "avg_gross_pct": eq["gross_pct"].mean() if "gross_pct" in eq else np.nan,
        "end_equity": e.iloc[-1],
    }


def s1_market_check(signals: pd.DataFrame, regime: pd.Series, breadth: pd.Series) -> pd.DataFrame:
    """Weekly S1 signal count next to the share of the week's sessions in each regime and
    breadth state, for §8's question: do weak-bounce shorts cluster in down or weak tapes?"""
    idx = pd.to_datetime(pd.Index(regime.index))
    week = idx.to_period("W-FRI")
    tags = pd.DataFrame(
        {"regime": regime.to_numpy(), "breadth": breadth.reindex(regime.index).to_numpy()},
        index=week,
    )
    out = pd.DataFrame(
        {
            "down_share": tags["regime"].eq("down").groupby(level=0).mean(),
            "up_share": tags["regime"].eq("up").groupby(level=0).mean(),
            "weak_share": tags["breadth"].eq("weak").groupby(level=0).mean(),
        }
    )
    s = signals[(signals["setup"] == "S1") & ~signals["skip"].astype(bool)]
    sw = pd.to_datetime(s["session_date"]).dt.to_period("W-FRI")
    out["s1_signals"] = sw.value_counts().reindex(out.index).fillna(0).astype(int)
    return out


def s1_summary(weekly: pd.DataFrame) -> pd.DataFrame:
    """Average weekly S1 count by the week's dominant regime and breadth state, and how the top
    decile of S1 weeks splits."""
    w = weekly.copy()
    w["regime"] = np.where(
        w["down_share"] > 0.5, "down", np.where(w["up_share"] > 0.5, "up", "sideways")
    )
    w["breadth"] = np.where(w["weak_share"] > 0.5, "weak", "not weak")
    spike = w["s1_signals"] >= w["s1_signals"].quantile(0.9)
    rows = []
    for col in ("regime", "breadth"):
        for v, g in w.groupby(col):
            rows.append(
                {
                    "tag": f"{col}={v}",
                    "weeks": len(g),
                    "mean_s1": g["s1_signals"].mean(),
                    "share_of_spike_weeks": (spike & (w[col] == v)).sum() / max(spike.sum(), 1),
                }
            )
    return pd.DataFrame(rows)
