"""Step 2 of the backtest module (docs/backlog/backtest.md §3): the shared definitions.

Every value on day t uses only bars up to and including t (the no-lookahead test in
`tests/test_backtest_indicators.py` checks this by rewriting the future). Frames are wide:
one row per session, one column per ticker. Percentages are percent numbers (25 = 25 %).

| Name | Definition |
|---|---|
| `adr_pct` | mean over `adr_days` of (high / low - 1) x 100 |
| `adr_usd` | `adr_pct` / 100 x close |
| `ema<n>`, `sma<n>` | exponential / simple MAs of close (NaN until n sessions exist) |
| `vol<n>` | `vol_avg_days` average volume |
| `perf<n>` | (close / close n sessions ago - 1) x 100 |
| `leader` | in the universe, top `top_pct` % of the universe on any perf window, close > SMA |
| `avwap` | VWAP of (H+L+C)/3 from the highest-volume up day in the last `avwap_lookback` sessions |
| `regime` | QQQ up / down / sideways (§3) |
| `breadth` | universe up >= `move_pct` vs down <= -`move_pct`: strong / weak / neutral |
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trading_os.backtest.config import BacktestConfig, IndicatorConfig

PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
AVWAP_CHUNK = 200  # tickers per block in the anchor search (memory)


def wide(bars: pd.DataFrame, columns=PRICE_COLUMNS + ("in_universe",)) -> dict[str, pd.DataFrame]:
    """Long bars (one row per session and ticker) as one session x ticker frame per column."""
    out = {}
    for col in columns:
        frame = bars.pivot(index="session_date", columns="ticker", values=col).sort_index()
        out[col] = frame.fillna(False).astype(bool) if col == "in_universe" else frame
    return out


def ema(close: pd.DataFrame, span: int) -> pd.DataFrame:
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def sma(x: pd.DataFrame, window: int) -> pd.DataFrame:
    return x.rolling(window, min_periods=window).mean()


def rising(ma: pd.DataFrame | pd.Series, lookback: int):
    """MA today above the MA `lookback` sessions ago (False where either is missing)."""
    return ma > ma.shift(lookback)


def falling(ma: pd.DataFrame | pd.Series, lookback: int):
    return ma < ma.shift(lookback)


def adr_pct(high: pd.DataFrame, low: pd.DataFrame, days: int) -> pd.DataFrame:
    return sma((high / low - 1) * 100, days)


def perf(close: pd.DataFrame, n: int) -> pd.DataFrame:
    return (close / close.shift(n) - 1) * 100


def top_share(values: pd.DataFrame, universe: pd.DataFrame, top_pct: float) -> pd.DataFrame:
    """True where a universe stock ranks in the top `top_pct` % of that session's universe."""
    ranks = values.where(universe).rank(axis=1, pct=True)
    return (ranks >= 1 - top_pct / 100) & universe


def leader(
    close: pd.DataFrame,
    universe: pd.DataFrame,
    perfs: dict[int, pd.DataFrame],
    cfg: IndicatorConfig,
) -> pd.DataFrame:
    top = None
    for p in perfs.values():
        hit = top_share(p, universe, cfg.leader.top_pct)
        top = hit if top is None else top | hit
    return top & (close > sma(close, cfg.leader.above_sma)) & universe


def avwap(w: dict[str, pd.DataFrame], lookback: int) -> pd.DataFrame:
    """Anchored VWAP from the highest-volume up day (close above the prior close) within the last
    `lookback` sessions including today; the latest one wins a tie. NaN when the window has no
    up day."""
    high, low, close, vol = (
        w[k].to_numpy(dtype="float64") for k in ("high", "low", "close", "volume")
    )
    tp_v = np.nan_to_num((high + low + close) / 3 * vol)
    v = np.nan_to_num(vol)
    cum_pv = np.vstack([np.zeros((1, tp_v.shape[1])), np.cumsum(tp_v, axis=0)])
    cum_v = np.vstack([np.zeros((1, v.shape[1])), np.cumsum(v, axis=0)])
    prev = np.vstack([np.full((1, close.shape[1]), np.nan), close[:-1]])
    with np.errstate(invalid="ignore"):
        score = np.where(close > prev, vol, -np.inf)
    score = np.where(np.isnan(score), -np.inf, score)
    n, m = score.shape
    out = np.full((n, m), np.nan)
    pad = np.vstack([np.full((lookback - 1, m), -np.inf), score])
    rows = np.arange(n)[:, None]
    for c0 in range(0, m, AVWAP_CHUNK):
        block = pad[:, c0 : c0 + AVWAP_CHUNK]
        win = np.lib.stride_tricks.sliding_window_view(block, lookback, axis=0)  # (n, cols, L)
        back = win[..., ::-1]  # index 0 = today
        k = back.argmax(axis=2)  # latest highest
        best = np.take_along_axis(back, k[..., None], axis=2)[..., 0]
        anchor = np.maximum(rows - k, 0)  # session index of the anchor (pad rows are masked)
        cols = np.arange(c0, c0 + block.shape[1])
        num = cum_pv[rows + 1, cols] - cum_pv[anchor, cols]
        den = cum_v[rows + 1, cols] - cum_v[anchor, cols]
        with np.errstate(invalid="ignore", divide="ignore"):
            val = num / den
        out[:, cols] = np.where(np.isfinite(best) & (den > 0), val, np.nan)
    return pd.DataFrame(out, index=w["close"].index, columns=w["close"].columns)


def regime(close: pd.Series, cfg: IndicatorConfig) -> pd.Series:
    """QQQ up: close > SMA mid and SMA fast > SMA mid. Down: close < SMA slow and SMA mid below
    itself `slope_lookback` sessions ago. Else sideways (also while the MAs warm up)."""
    r = cfg.regime
    s_fast, s_mid, s_slow = (
        close.rolling(n, min_periods=n).mean() for n in (r.fast_sma, r.mid_sma, r.slow_sma)
    )
    up = (close > s_mid) & (s_fast > s_mid)
    down = (close < s_slow) & (s_mid < s_mid.shift(r.slope_lookback))
    out = pd.Series("sideways", index=close.index, dtype=object)
    out[down] = "down"
    out[up] = "up"
    return out


def breadth(close: pd.DataFrame, universe: pd.DataFrame, cfg: IndicatorConfig) -> pd.DataFrame:
    """Per session: universe stocks up >= move_pct and down <= -move_pct over perf_window, their
    ratio and the tag (strong if ratio >= strong_ratio_min, weak if < weak_ratio_below)."""
    b = cfg.breadth
    p = perf(close, b.perf_window).where(universe)
    up = (p >= b.move_pct).sum(axis=1)
    down = (p <= -b.move_pct).sum(axis=1)
    ratio = up / down.where(down > 0)
    ratio = ratio.where(down > 0, np.where(up > 0, np.inf, np.nan))
    tag = pd.Series("neutral", index=close.index, dtype=object)
    tag[ratio >= b.strong_ratio_min] = "strong"
    tag[ratio < b.weak_ratio_below] = "weak"
    return pd.DataFrame({"up": up, "down": down, "ratio": ratio, "tag": tag})


def compute(
    w: dict[str, pd.DataFrame], cfg: BacktestConfig, index_close: pd.Series | None = None
) -> dict:
    """Every §3 indicator for the stocks in `w`, plus the regime from `index_close` (QQQ)."""
    ind = cfg.indicators
    c = w["close"]
    out: dict = {"adr_pct": adr_pct(w["high"], w["low"], ind.adr_days)}
    out["adr_usd"] = out["adr_pct"] / 100 * c
    for n in ind.ema_spans:
        out[f"ema{n}"] = ema(c, n)
    for n in ind.sma_windows:
        out[f"sma{n}"] = sma(c, n)
    out[f"vol{ind.vol_avg_days}"] = sma(w["volume"], ind.vol_avg_days)
    perfs = {n: perf(c, n) for n in ind.perf_windows}
    for n, p in perfs.items():
        out[f"perf{n}"] = p
    out["leader"] = leader(c, w["in_universe"], perfs, ind)
    out["avwap"] = avwap(w, ind.avwap_lookback)
    out["breadth"] = breadth(c, w["in_universe"], ind)
    if index_close is not None:
        out["regime"] = regime(index_close.reindex(c.index), ind)
    return out
