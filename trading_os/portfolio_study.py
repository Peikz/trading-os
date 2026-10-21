"""Portfolio construction around the graded setups (Emil, 21 Oct 2026): what an account built
from them would have done next to simple alternatives, 2019-2026. Research code for the data
repo's report; facts about rules applied to history, not advice.

- Benchmarks from the same daily bars (split- and dividend-adjusted, so an ETF's close is a
  total-return series): an index held outright, the same index only while it closes above its
  200-day average (cash in BIL otherwise), and a plain cross-sectional momentum portfolio of
  the same stock universe (the top N by 6-month return, skipping the last month, rebalanced
  monthly).
- Blends: the setup portfolio's daily returns with its idle cash in an index, and fixed mixes.
- Statistics per curve (CAGR, drawdown, volatility, Sharpe, worst year) and block-bootstrap
  intervals by calendar month, so a difference between two curves can be told from noise.

Signals use only closes known before the day they act on: a trend switch decided at one
close earns the next session's return.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

TRADING_DAYS = 252
SWITCH_COST_PCT = 0.10  # commission and spread to move the whole index position in or out


def curve_stats(equity: pd.Series) -> dict[str, float]:
    """CAGR, maximum drawdown, volatility, Sharpe (no risk-free), MAR, worst and best year,
    the share of calendar years up, for a daily equity curve indexed by date."""
    equity = equity.dropna()
    returns = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    drawdown = (equity / equity.cummax() - 1).min()
    vol = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = returns.mean() / returns.std() * np.sqrt(TRADING_DAYS) if returns.std() else np.nan
    by_year = yearly(equity)
    return {
        "cagr_pct": 100 * cagr,
        "max_dd_pct": 100 * drawdown,
        "vol_pct": 100 * vol,
        "sharpe": sharpe,
        "mar": cagr / -drawdown if drawdown < 0 else np.nan,
        "worst_year_pct": by_year.min(),
        "best_year_pct": by_year.max(),
        "years_up_pct": 100 * (by_year > 0).mean(),
    }


def yearly(equity: pd.Series) -> pd.Series:
    """Calendar-year returns in %, from the last close of each year (the first year from the
    curve's start)."""
    equity = equity.dropna()
    ends = equity.groupby(equity.index.year).last()
    starts = pd.concat([pd.Series([equity.iloc[0]]), ends.iloc[:-1]], ignore_index=True)
    return pd.Series(100 * (ends.to_numpy() / starts.to_numpy() - 1), index=ends.index)


def index_curve(
    close: pd.Series,
    cash: pd.Series | None = None,
    trend: int | None = None,
    switch_cost_pct: float = SWITCH_COST_PCT,
) -> pd.Series:
    """An index held outright (`trend` None), or held only while its previous close was above
    its `trend`-day average and in `cash` (a total-return series such as BIL) otherwise.
    Returns the daily equity, starting at 1 on the first date with a full average."""
    close = close.dropna().astype(float)
    ret = close.pct_change()
    cash_ret = (
        cash.reindex(close.index).ffill().pct_change().fillna(0.0)
        if cash is not None
        else pd.Series(0.0, index=close.index)
    )
    if trend is None:
        held = pd.Series(1.0, index=close.index)
    else:
        above = (close > close.rolling(trend).mean()).astype(float)
        above[close.rolling(trend).mean().isna()] = np.nan
        held = above.shift(1)  # decided at the previous close
    daily = held * ret + (1 - held) * cash_ret
    switches = held.diff().abs().fillna(0.0)
    daily = daily - switches * switch_cost_pct / 100
    start = held.first_valid_index()
    daily = daily.loc[start:].fillna(0.0)
    daily.iloc[0] = 0.0
    return (1 + daily).cumprod()


def month_ends(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The last session of each calendar month."""
    s = pd.Series(dates, index=dates)
    return pd.DatetimeIndex(s.groupby([dates.year, dates.month]).last().to_numpy())


def momentum_curve(
    close: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    *,
    top: int = 20,
    top_frac: float | None = None,
    lookback: int = 126,
    skip: int = 21,
    min_price: float = 5.0,
    min_dvol: float = 20e6,
    cost_pct_per_side: float = 0.18,
    hold_if: pd.Series | None = None,
    cash: pd.Series | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Equal-weight top-`top` stocks (or the top `top_frac` of the eligible ones, at least
    `top`) by return over `lookback` sessions ending `skip` sessions ago, chosen at each
    month's last close among those at `min_price`+ with a 20-day average dollar volume of
    `min_dvol`+, held to the next month end (a stock that stops trading is held at its last
    close). `hold_if`: date -> bool, checked at each rebalance; when False
    the month is spent in `cash` instead. Costs: `cost_pct_per_side` on the traded fraction.
    Returns the daily equity and the picks (rebalance date, ticker)."""
    close = close.sort_index()
    dates = close.index
    filled = close.ffill()
    adv = dollar_volume.reindex_like(close).rolling(20, min_periods=15).mean()
    score = filled.shift(skip) / filled.shift(skip + lookback) - 1
    cash_ret = (
        cash.reindex(dates).ffill().pct_change().fillna(0.0)
        if cash is not None
        else pd.Series(0.0, index=dates)
    )
    rebalances = [d for d in month_ends(dates) if score.loc[d].notna().any()]
    equity = pd.Series(np.nan, index=dates)
    picks, held_before = [], set()
    value = 1.0
    for k, day in enumerate(rebalances):
        end = rebalances[k + 1] if k + 1 < len(rebalances) else dates[-1]
        span = dates[(dates > day) & (dates <= end)]
        equity.loc[day] = value
        if len(span) == 0:
            break
        invest = hold_if is None or bool(hold_if.get(day, True))
        chosen: list[str] = []
        if invest:
            ok = (close.loc[day] >= min_price) & (adv.loc[day] >= min_dvol) & score.loc[day].notna()
            n = max(top, round(top_frac * int(ok.sum()))) if top_frac else top
            chosen = list(score.loc[day][ok].nlargest(n).index)
        bought = len(set(chosen) - held_before) / max(len(chosen), 1)
        sold = len(held_before - set(chosen)) / max(len(held_before), 1)
        value *= 1 - (bought + sold) * cost_pct_per_side / 100
        if chosen:
            growth = filled.loc[span, chosen].div(filled.loc[day, chosen]).mean(axis=1)
            path = value * growth
        else:
            path = value * (1 + cash_ret.loc[span]).cumprod()
        equity.loc[span] = path.to_numpy()
        value = float(path.iloc[-1])
        picks += [(day, t) for t in chosen]
        held_before = set(chosen)
    equity = equity.loc[rebalances[0] :].ffill() if rebalances else equity
    return equity, pd.DataFrame(picks, columns=["rebalance", "ticker"])


def with_idle_cash_in(
    strategy_equity: pd.Series, exposure: pd.Series, index_equity: pd.Series
) -> pd.Series:
    """The setup portfolio with its uninvested cash earning an index's (or a trend-filtered
    index's) daily return. `exposure`: the fraction of equity in positions at each close."""
    dates = strategy_equity.index.intersection(index_equity.index)
    strat = strategy_equity.reindex(dates).pct_change().fillna(0.0)
    idx = index_equity.reindex(dates).pct_change().fillna(0.0)
    idle = (1 - exposure.reindex(dates).ffill().fillna(0.0).clip(0, 1)).shift(1).fillna(1.0)
    return (1 + strat + idle * idx).cumprod()


def blend(curves: Mapping[str, pd.Series], weights: Mapping[str, float]) -> pd.Series:
    """Fixed weights, rebalanced daily, on the curves' common dates."""
    frame = pd.DataFrame({k: curves[k] for k in weights}).dropna()
    daily = frame.pct_change().fillna(0.0)
    mixed = sum(daily[k] * w for k, w in weights.items())
    return (1 + mixed).cumprod()


def bootstrap(
    returns: pd.DataFrame, draws: int = 2000, block: str = "M", seed: int = 7
) -> pd.DataFrame:
    """Resample whole calendar months (all curves together, so their link is kept) to the
    original length, `draws` times. Per curve: CAGR and maximum drawdown at the 5th, 50th
    and 95th percentile, and how often each curve's CAGR beat the first column's."""
    rng = np.random.default_rng(seed)
    returns = returns.dropna()
    keys = returns.index.to_period(block)
    blocks = [returns.loc[keys == k].to_numpy() for k in keys.unique()]
    n_days = len(returns)
    years = n_days / TRADING_DAYS
    cagr = np.empty((draws, returns.shape[1]))
    dd = np.empty((draws, returns.shape[1]))
    for i in range(draws):
        sample, total = [], 0
        while total < n_days:
            b = blocks[rng.integers(len(blocks))]
            sample.append(b)
            total += len(b)
        path = np.cumprod(1 + np.vstack(sample)[:n_days], axis=0)
        cagr[i] = path[-1] ** (1 / years) - 1
        dd[i] = (path / np.maximum.accumulate(path, axis=0) - 1).min(axis=0)
    out = pd.DataFrame(index=returns.columns)
    for q in (5, 50, 95):
        out[f"cagr_p{q}"] = 100 * np.percentile(cagr, q, axis=0)
        out[f"max_dd_p{q}"] = 100 * np.percentile(dd, q, axis=0)  # p5 = the deep tail
    out["p_beats_first"] = (cagr > cagr[:, [0]]).mean(axis=0)
    return out


INDEXES = ("SPY", "QQQ", "BIL")


def stock_tickers(data_dir) -> set[str]:
    """Tickers Massive lists as a common stock or ADR (the minute study's universe)."""
    from pathlib import Path

    from trading_os.regime_study import STOCK_TYPES

    path = Path(data_dir) / "data" / "ep_enrich" / "tickers.parquet"
    listed = pd.read_parquet(path, columns=["ticker", "type"])
    return set(listed.loc[listed["type"].isin(STOCK_TYPES), "ticker"])


def load_wide(files, keep: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily close and dollar volume (date x ticker, float32) for the `keep` tickers, from the
    bars-alpaca year files, one year at a time to stay inside a laptop's memory."""
    closes, dvols = [], []
    for path in sorted(files):
        bars = pd.read_parquet(path, columns=["session_date", "ticker", "close", "volume"])
        bars = bars[bars["ticker"].isin(keep)]
        bars["session_date"] = pd.to_datetime(bars["session_date"])
        bars["dvol"] = bars["close"] * bars["volume"]
        closes.append(bars.pivot_table("close", "session_date", "ticker").astype("float32"))
        dvols.append(bars.pivot_table("dvol", "session_date", "ticker").astype("float32"))
        del bars
    return pd.concat(closes).sort_index(), pd.concat(dvols).sort_index()


def benchmarks(close: pd.DataFrame, dvol: pd.DataFrame, start, end) -> dict[str, pd.Series]:
    """The yardstick curves, each rebased to 1 at `start`."""
    cash = close["BIL"]
    spy_trend = close["SPY"] > close["SPY"].rolling(200).mean()  # known at that close
    stocks = close.drop(columns=[c for c in INDEXES if c in close])
    curves = {
        "SPY": index_curve(close["SPY"]),
        "SPY above 200d, else BIL": index_curve(close["SPY"], cash, trend=200),
        "QQQ": index_curve(close["QQQ"]),
        "QQQ above 200d, else BIL": index_curve(close["QQQ"], cash, trend=200),
        "BIL (cash)": index_curve(cash),
    }
    # The textbook construction: 12-month return skipping the last month, top decile.
    decile = {"top": 10, "top_frac": 0.10, "lookback": 231, "skip": 21}
    curves["Momentum 12-1, top 10 %"] = momentum_curve(stocks, dvol, **decile)[0]
    curves["Momentum 12-1, top 10 %, SPY above 200d"] = momentum_curve(
        stocks, dvol, **decile, hold_if=spy_trend, cash=cash
    )[0]
    curves["Equal weight, all eligible"] = momentum_curve(
        stocks, dvol, top=10, top_frac=1.0, lookback=231, skip=21
    )[0]
    # The most extreme winners (what a "biggest gainers" list buys): kept as a finding.
    curves["Momentum 6-1, top 10 names"] = momentum_curve(stocks, dvol, top=10)[0]
    out = {}
    for name, curve in curves.items():
        part = curve.loc[start:end].dropna()
        out[name] = part / part.iloc[0]
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from trading_os import remote_data

    parser = argparse.ArgumentParser(description="Benchmarks for the portfolio study")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--start", default="2019-01-02")
    parser.add_argument("--end", default="2026-10-16")
    parser.add_argument("--out", type=Path, required=True, help="a private folder")
    args = parser.parse_args(argv)
    repo = remote_data.repo_of(args.data_dir)
    files = remote_data.fetch(repo, "bars-alpaca", "20[12][0-9].parquet")
    files = [f for f in files if int(f.stem) >= int(args.start[:4]) - 2]
    keep = stock_tickers(args.data_dir) | set(INDEXES)
    close, dvol = load_wide(files, keep)
    curves = benchmarks(close, dvol, args.start, args.end)
    args.out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(curves).to_parquet(args.out / "benchmark_curves.parquet")
    table = pd.DataFrame({k: curve_stats(v) for k, v in curves.items()}).T
    table.to_csv(args.out / "benchmark_stats.csv")
    print(f"Benchmarks: {len(curves)} curves, {close.shape[1]} tickers, saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
