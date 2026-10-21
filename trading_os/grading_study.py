"""Grading study (Emil, 20 Oct 2026): the 10-year minute study rebuilt for grading setups.
Facts, not advice.

It runs the same entries and exits as `intraday_study.run_year`, with four differences:

1. Stocks only. ETFs, ETNs and funds (Massive's types, `regime_study.non_stocks`) are left out
   before anything runs. Dividend-adjusted T-bill funds made a new high almost every day on
   a 1-ADR stop of a few cents and scored +20R a trade, which is where the minute study's
   "+0.65R breakout" came from.
2. Every trade keeps its features: the setup's own (pivot, B-flags, gap, pace, touch...),
   the daily facts known at the entry (all taken at the last close before the entry day,
   so nothing from the entry day itself), the signal day's facts for next-day entries
   (from the 10-year histories), and the market regime of the session before the entry day.
3. Every exit keeps its holding days, and the partial exits their two legs, so a portfolio
   can be simulated and any partial fraction priced later.
4. The exits look `exit_sessions` ahead (config `intraday_study:`), longer than the minute
   study's quarter, plus the mean-reversion and R-target exits.

Costs, real (unadjusted) prices and fundamentals are joined at analysis time: they come from
separate releases (`bars-alpaca-raw`, `sec-10y`).

Output: `grading_<year>.parquet` per year (GitHub job per year, release `grading-10y`).
Logs print counts only.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import history_metrics as hm
from trading_os import intraday_study as study
from trading_os import long_history, minervini

# Candidate columns every trade keeps (on top of the entry's own features).
KEEP = (
    *study.KEEP,
    "avg_volume_20d",
    "pivot",
    "order_stop",
    "base_adr_usd",
    "contractions",
    "last_depth_pct",
    "last_low",
    "ema_fast",
    "ema_mid",
    "avwap",
    "base_days",
    "lead",
    "mid_rising",
    "signal_high",
    "signal_low",
    "setup",
    *sorted({c for cols in study.SETUP_KEEP.values() for c in cols}),
)
# Signal-day columns of the 10-year strategy histories, for next-day entries (prefix sig_).
SIGNAL_COLUMNS = (
    "b1",
    "b2",
    "b3",
    "b4",
    "base_len",
    "risk_adr",
    "gain_max_pct",
    "drop_max_pct",
    "consec_up",
    "consec_down",
    "contractions",
    "last_depth_pct",
    "dryup_ratio",
    "vol_ratio",
    "base_days",
    "tightness_adr",
    "triggered_within_days",
)
# EP-Day columns of the 10-year EP histories (prefix ep_): all known at the gap day's close,
# so only next-day entries get them.
EP_COLUMNS = (
    "months_sideways",
    "ret_before_21d",
    "ret_before_63d",
    "ret_before_126d",
    "pct_from_6m_high",
    "gap_clears_6m_high",
    "gap_pct",
    "rvol50",
    "close_loc",
    "chg_pct",
    "lod_stop_adr",
    "c1_gap",
    "c2_volume",
    "c4_neglect",
    "c5_stop",
)
REGIME_COLUMNS = ("light", "qqq_trend", "breadth_state", "scan_count", "mkt_ratio_10d")
NEGLECT_BAND = 0.25  # "sideways": every close within ±25 % (as ep_history's months_sideways)
NEGLECT_MONTHS = 12


def _roll(a: np.ndarray, window: int, how: str) -> np.ndarray:
    """Rolling max/min/mean over the last `window` rows, NaN until `window` values exist."""
    frame = pd.DataFrame(a).rolling(window, min_periods=window)
    return getattr(frame, how)().to_numpy()


def daily_features(g: Mapping[str, np.ndarray], rs: np.ndarray | None = None) -> dict:
    """Session x ticker arrays; the value at row r uses rows <= r only. A trade entered on
    session t reads row t - 1: the last close before its entry day."""
    o, h, lo, c, v = (g[f] for f in ("open", "high", "low", "close", "volume"))
    out: dict[str, np.ndarray] = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        adr_pct = hm.rolling_mean((h / lo - 1) * 100, hm.ADR_DAYS)
        adr_usd = adr_pct * c / 100
        out["adr_pct"] = adr_pct
        out["adr5_ratio"] = hm.rolling_mean((h / lo - 1) * 100, 5) / adr_pct
        out["dvol20"] = hm.rolling_mean(c * v, hm.AVG_DAYS)
        out["rvol"] = v / hm.shift(hm.rolling_mean(v, hm.RVOL_DAYS), 1)
        out["chg_pct"] = (c / hm.shift(c, 1) - 1) * 100
        out["close_loc"] = (c - lo) / (h - lo)
        for w in (5, 22, 63, 126):
            out[f"ret_{w}"] = (c / hm.shift(c, w) - 1) * 100
        if rs is not None:
            out["rs"] = rs
        out["from_52w_high"] = (c / _roll(h, 252, "max") - 1) * 100
        hi20, lo20 = _roll(h, 20, "max"), _roll(lo, 20, "min")
        out["range20_pos"] = (c - lo20) / (hi20 - lo20)
        out["gain10_pct"] = (c / _roll(lo, 10, "min") - 1) * 100
        out["drop10_pct"] = (c / _roll(h, 10, "max") - 1) * 100
        mas = {w: hm.rolling_mean(c, w) for w in (10, 20, 50, 200)}
        for w, ma in mas.items():
            out[f"dist_ma{w}_adr"] = (c - ma) / adr_usd
        for w in (10, 20, 50):
            out[f"ma{w}_slope"] = (mas[w] / hm.shift(mas[w], 5) - 1) * 100
        out["ma200_rising"] = (mas[200] > hm.shift(mas[200], 22)).astype(float)
        out["ma_stack"] = ((mas[10] > mas[20]) & (mas[20] > mas[50])).astype(float)
        out["above_ma200"] = (c > mas[200]).astype(float)
        out["surf10"] = hm.rolling_mean((c >= mas[10]).astype(float), 20)
        out["surf20"] = hm.rolling_mean((c >= mas[20]).astype(float), 40)
        for w in (5, 10):
            out[f"tight{w}_adr"] = (_roll(h, w, "max") - _roll(lo, w, "min")) / adr_usd
        out["vol_dry"] = hm.rolling_mean(v, 10) / hm.rolling_mean(v, 50)
        out["up_days"] = hm.consecutive(c > hm.shift(c, 1))
        out["neglect_months"] = neglect_months(c)
    return out


def neglect_months(close: np.ndarray, band: float = NEGLECT_BAND) -> np.ndarray:
    """Whole months (21 sessions) back from each row with every close within ±band of that
    row's close, up to NEGLECT_MONTHS (EP history's "months sideways", at any row)."""
    count = np.zeros(close.shape)
    alive = np.ones(close.shape, dtype=bool)
    with np.errstate(invalid="ignore"):
        for m in range(1, NEGLECT_MONTHS + 1):
            w = 21 * m + 1  # the row itself and 21 * m sessions before it
            inside = (_roll(close, w, "max") <= close * (1 + band)) & (
                _roll(close, w, "min") >= close * (1 - band)
            )
            alive &= inside
            count += alive
    return np.where(np.isnan(close), np.nan, count)


def gather(arrays: Mapping[str, np.ndarray], rows: np.ndarray, cols: np.ndarray) -> dict:
    """Each array's value at (rows, cols); NaN where a row is before the first session."""
    ok = rows >= 0
    safe = np.where(ok, rows, 0)
    return {k: np.where(ok, a[safe, cols], np.nan).astype("float32") for k, a in arrays.items()}


def add_daily_features(trades: pd.DataFrame, g, tickers, sessions) -> pd.DataFrame:
    """The features at the last close before each trade's entry day (computed once per
    stock-day, then joined), plus the entry day's opening gap for entries made after the
    open (pre-market and after-hours entries can't know it)."""
    index = {d: i for i, d in enumerate(sessions)}
    col = {t: j for j, t in enumerate(tickers)}
    days = trades[["session_date", "ticker"]].drop_duplicates().reset_index(drop=True)
    t = days["session_date"].map(index).to_numpy(dtype=int)
    j = days["ticker"].map(col).to_numpy(dtype=int)
    rs = minervini.rs_rating(g["close"])
    feats = gather(daily_features(g, rs), t - 1, j)
    prev_close = gather({"c": g["close"]}, t - 1, j)["c"]
    with np.errstate(divide="ignore", invalid="ignore"):
        feats["open_gap_pct"] = ((g["open"][t, j] / prev_close - 1) * 100).astype("float32")
    table = pd.concat([days, pd.DataFrame(feats)], axis=1)
    table = table.rename(columns={k: f"d_{k}" for k in feats if k != "open_gap_pct"})
    out = trades.merge(table, on=["session_date", "ticker"], how="left")
    out.loc[out["entry"].isin(study.OFF_SESSION), "open_gap_pct"] = np.nan
    return out


def add_signal_features(trades: pd.DataFrame, hits_dir, year: int) -> pd.DataFrame:
    """Signal-day columns of the 10-year histories for next-day entries (the signal day's
    close is known at the next day's entry): strategy hits (sig_) and EP-Days (ep_)."""
    if hits_dir is None or "signal_date" not in trades:
        return trades
    years = [f for f in (year - 1, year)]
    frames, eps = [], []
    for y in years:
        path = Path(hits_dir) / f"strategy_{y}.parquet"
        if path.exists():
            frames.append(_read(path, ["strategy", "session_date", "ticker", *SIGNAL_COLUMNS]))
        path = Path(hits_dir) / f"ep_{y}.parquet"
        if path.exists():
            ep = _read(path, ["session_date", "ticker", "is_ep_day", "tier", *EP_COLUMNS])
            eps.append(ep[ep["is_ep_day"] & (ep["tier"] == "alert")])
    out = trades
    if frames:
        sig = pd.concat(frames, ignore_index=True).drop_duplicates(
            ["strategy", "session_date", "ticker"]
        )
        sig = sig.rename(columns={c: f"sig_{c}" for c in SIGNAL_COLUMNS if c in sig})
        sig = sig.rename(columns={"session_date": "signal_date"})
        out = out.merge(sig, on=["strategy", "signal_date", "ticker"], how="left")
    if eps:
        ep = pd.concat(eps, ignore_index=True).drop_duplicates(["session_date", "ticker"])
        ep = ep.drop(columns=["is_ep_day", "tier"])
        ep = ep.rename(columns={c: f"ep_{c}" for c in EP_COLUMNS if c in ep})
        ep = ep.rename(columns={"session_date": "signal_date"}).assign(strategy="ep_day")
        out = out.merge(ep, on=["strategy", "signal_date", "ticker"], how="left")
    return out


def _read(path, columns) -> pd.DataFrame:
    import pyarrow.parquet as pq

    names = set(pq.read_schema(path).names)
    df = pd.read_parquet(path, columns=[c for c in columns if c in names])
    df["session_date"] = pd.to_datetime(df["session_date"]).dt.date
    return df


def add_regime(trades: pd.DataFrame, regime: pd.DataFrame | None, sessions) -> pd.DataFrame:
    """The regime of the session before each trade's entry day (known when the order went in)."""
    if regime is None or regime.empty:
        return trades
    table = regime.copy()
    table["session_date"] = pd.to_datetime(table["session_date"]).dt.date
    keep = [c for c in REGIME_COLUMNS if c in table]
    table = table.set_index("session_date")[keep]
    if {"spy_close", "spy_sma200"} <= set(regime.columns):
        r = regime.set_index(pd.to_datetime(regime["session_date"]).dt.date)
        table["spy_above_ma200"] = (r["spy_close"] > r["spy_sma200"]).astype(float)
    if {"qqq_close", "qqq_sma50"} <= set(regime.columns):
        r = regime.set_index(pd.to_datetime(regime["session_date"]).dt.date)
        table["qqq_above_ma50"] = (r["qqq_close"] > r["qqq_sma50"]).astype(float)
    prior = {d: sessions[i - 1] for i, d in enumerate(sessions) if i}
    before = trades["session_date"].map(prior)
    joined = table.reindex(before.to_numpy())
    joined.columns = [f"mkt_{c}" for c in joined.columns]
    return pd.concat([trades.reset_index(drop=True), joined.reset_index(drop=True)], axis=1)


def extra_exits(cfg) -> dict:
    conf = cfg.intraday_study
    return {
        "mrev_mas": list(conf["mrev_mas"]),
        "r_targets": list(conf["r_targets"]),
        "r_target_days": conf["r_target_days"],
    }


def run_year(
    cfg,
    year: int,
    bars_dir,
    hits_dir,
    minutes_dir,
    cands: pd.DataFrame | None,
    funds: set[str] = frozenset(),
    regime: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Every stock trade entered in `year`, with its features and every exit."""
    from trading_os.logsafe import status

    k = cfg.intraday_study["exit_sessions"]
    if cands is None or cands.empty:
        cands = study.long_candidates(cfg, bars_dir, hits_dir, year, year)
    cands = cands[pd.to_datetime(cands["session_date"]).dt.year == year]
    before = len(cands)
    cands = cands[~cands["ticker"].isin(funds)]
    status(f"Grading {year}: {len(cands)} candidate stock-days ({before - len(cands)} funds out)")
    bars = long_history.load_years(bars_dir, year - 2, year + 1)
    bars = bars[~bars["ticker"].isin(funds)]
    if bars.empty or cands.empty:
        return pd.DataFrame()
    sessions, inside = long_history.window(cfg.schedule, year, bars["session_date"].max())
    sessions = sessions[: sessions.index(inside[-1]) + 1 + k + 7]
    have = set(bars["session_date"])
    sessions = [s for s in sessions if s in have]
    g, tickers = study.daily(bars[bars["session_date"].isin(set(sessions))], sessions)
    del bars
    trades = study.run_study(
        g, tickers, sessions, cands, minutes_dir, cfg, KEEP, extra_exits(cfg), k
    )
    if trades.empty:
        return trades
    trades = add_daily_features(trades, g, tickers, sessions)
    trades = add_signal_features(trades, hits_dir, year)
    trades = add_regime(trades, regime, sessions)
    return slim(trades)


def slim(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.select_dtypes("float64").columns:
        out[column] = out[column].astype("float32")
    for column in out.columns:
        if out[column].dtype == object and column not in ("session_date", "signal_date"):
            sample = out[column].dropna()
            if len(sample) and isinstance(sample.iloc[0], bool | np.bool_):
                out[column] = out[column].astype("float32")
    return out


def main(argv: list[str] | None = None) -> int:
    from trading_os.logsafe import run_guarded

    return run_guarded(lambda: _main(argv), None, "Grading study")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    from trading_os import regime_study
    from trading_os.config import load_config
    from trading_os.logsafe import status
    from trading_os.store import PARQUET_OPTIONS

    parser = argparse.ArgumentParser(description="One year of the grading study")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--data-dir", type=Path, required=True, help="for Massive's types")
    parser.add_argument("--bars", type=Path, required=True, help="Alpaca YYYY.parquet files")
    parser.add_argument("--hits", type=Path, required=True, help="history-10y files")
    parser.add_argument("--minutes", type=Path, required=True, help="the year's minute files")
    parser.add_argument("--cands", type=Path, help="candidates_10y.parquet, when present")
    parser.add_argument("--regime", type=Path, help="regime_daily.parquet")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--groups", default="", help="only these candidate groups (comma list)")
    parser.add_argument("--suffix", default="", help="added to the output name, e.g. _ep")
    args = parser.parse_args(argv)
    cfg = load_config()
    cands = None
    if args.cands and args.cands.exists():
        cands = pd.read_parquet(args.cands)
        cands["session_date"] = pd.to_datetime(cands["session_date"]).dt.date
    if cands is not None and args.groups:
        cands = cands[cands["group"].isin(args.groups.split(","))]
    regime = pd.read_parquet(args.regime) if args.regime and args.regime.exists() else None
    funds = regime_study.non_stocks(args.data_dir)
    trades = run_year(cfg, args.year, args.bars, args.hits, args.minutes, cands, funds, regime)
    args.out.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(args.out / f"grading_{args.year}{args.suffix}.parquet", **PARQUET_OPTIONS)
    counts = trades.groupby("strategy").size().to_dict() if len(trades) else {}
    status(f"Grading {args.year}: {len(trades)} trades, {len(trades.columns)} columns {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
