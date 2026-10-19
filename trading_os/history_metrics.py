"""SPEC §5 metrics on full daily history (Phase 2).

Computed on a session × ticker grid over a contiguous list of sessions, so a session a ticker
is missing from shows up as NaN and never shifts a rolling window. Every window needs full
data (no partial windows): a 50-day RVOL on 30 days of history is NaN, not a guess.

The grid math is plain NumPy so ~10k tickers × 2 years stays fast; pandas only builds the
output rows that are kept.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

MA_WINDOWS = (10, 20, 50, 200)
RETURN_WINDOWS = (22, 63, 126)
MA_SLOPE_LOOKBACK = 5  # SPEC §5: "MA today > MA 5 trading days ago"
ADR_DAYS = 20
RVOL_DAYS = 50
AVG_DAYS = 20
PRICE_FIELDS = ("open", "high", "low", "close", "volume")

# Sessions of history needed before the latest session has every metric.
LOOKBACK_SESSIONS = max(max(MA_WINDOWS) + MA_SLOPE_LOOKBACK, max(RETURN_WINDOWS), RVOL_DAYS) + 1


def grids(bars: pd.DataFrame, sessions: list[dt.date]) -> tuple[dict[str, np.ndarray], pd.Index]:
    """Each price field as a sessions × tickers array; missing (ticker, session) pairs are NaN."""
    unique = bars.drop_duplicates(["session_date", "ticker"], keep="last")
    wide = unique.set_index(["session_date", "ticker"])[list(PRICE_FIELDS)].unstack("ticker")
    index = pd.Index(sessions, name="session_date")
    tickers = wide["close"].columns
    arrays = {f: wide[f].reindex(index).to_numpy(dtype="float64") for f in PRICE_FIELDS}
    return arrays, tickers


def shift(a: np.ndarray, rows: int) -> np.ndarray:
    """Values from `rows` sessions earlier (NaN at the start)."""
    out = np.full(a.shape, np.nan)
    if rows < len(a):
        out[rows:] = a[:-rows]
    return out


def rolling_mean(a: np.ndarray, window: int) -> np.ndarray:
    """Mean of the last `window` rows; NaN unless all `window` values are present."""
    valid = ~np.isnan(a)
    zero = np.zeros((1, a.shape[1]))
    sums = np.vstack([zero, np.cumsum(np.where(valid, a, 0.0), axis=0)])
    counts = np.vstack([zero, np.cumsum(valid, axis=0)])
    out = np.full(a.shape, np.nan)
    if len(a) >= window:
        full = (counts[window:] - counts[:-window]) == window
        out[window - 1 :] = np.where(full, (sums[window:] - sums[:-window]) / window, np.nan)
    return out


def rolling_extreme(a: np.ndarray, window: int, how: str) -> np.ndarray:
    """Min or max of the last `window` rows; NaN if any of them is missing."""
    out = np.full(a.shape, np.nan)
    if len(a) >= window:
        view = sliding_window_view(a, window, axis=0)
        out[window - 1 :] = view.min(axis=-1) if how == "min" else view.max(axis=-1)
    return out


def consecutive(flags: np.ndarray) -> np.ndarray:
    """Length of the run of True values ending at each row (0 where False)."""
    counts = np.cumsum(flags, axis=0)
    # counts never decreases, so the count at the last break is the running max of breaks.
    at_last_break = np.maximum.accumulate(np.where(flags, 0, counts), axis=0)
    return (counts - at_last_break).astype("float64")


@dataclass(frozen=True)
class ScanWindows:
    """Windows some scans add on top of SPEC §5; values come from config/scans.yaml."""

    gain_days: int = 10  # Parabolic Short: largest gain within <= N sessions
    drop_days: int = 10  # Parabolic Long: largest drop within <= N sessions
    range_days: int = 10  # tight bases: high-low range over N sessions
    volume_short_days: int = 10  # tight bases: N-day average volume ...
    volume_long_days: int = 50  # ... below the M-day average


def compute(
    bars: pd.DataFrame,
    sessions: list[dt.date],
    keep: list[dt.date] | None = None,
    windows: ScanWindows | None = None,
) -> pd.DataFrame:
    """SPEC §5 metrics per (session, ticker), long format, NaN where unknown.

    `sessions` is the contiguous history the windows run over; `keep` limits the output to
    some of them (the EOD job only needs the latest), which keeps memory small.
    """
    g, tickers = grids(bars, sessions)
    return compute_from_grids(g, tickers, sessions, keep, windows)


def compute_from_grids(
    g: dict[str, np.ndarray],
    tickers: pd.Index,
    sessions: list[dt.date],
    keep: list[dt.date] | None = None,
    windows: ScanWindows | None = None,
) -> pd.DataFrame:
    windows = windows or ScanWindows()
    o, h, lo, c, v = (g[f] for f in PRICE_FIELDS)
    pc = shift(c, 1)
    m: dict[str, np.ndarray] = {"open": o, "high": h, "low": lo, "close": c, "volume": v}
    with np.errstate(divide="ignore", invalid="ignore"):
        m["prev_close"] = pc
        m["prev_volume"] = shift(v, 1)
        m["gap_pct"] = (o / pc - 1) * 100
        m["chg_pct"] = (c / pc - 1) * 100
        m["dollar_volume"] = c * v
        m["close_loc"] = np.where(h > lo, (c - lo) / (h - lo), np.nan)
        m["adr20_pct"] = rolling_mean((h / lo - 1) * 100, ADR_DAYS)
        m["adr20_usd"] = m["adr20_pct"] * c / 100
        m["rvol50"] = v / rolling_mean(shift(v, 1), RVOL_DAYS)
        m["avg_volume_20d"] = rolling_mean(v, AVG_DAYS)
        m["avg_dollar_volume_20d"] = rolling_mean(c * v, AVG_DAYS)
        for days in RETURN_WINDOWS:
            m[f"ret_{days}"] = (c / shift(c, days) - 1) * 100
        for window in MA_WINDOWS:
            ma = rolling_mean(c, window)
            before = shift(ma, MA_SLOPE_LOOKBACK)
            m[f"ma{window}"] = ma
            m[f"ma{window}_rising"] = np.where(np.isnan(ma) | np.isnan(before), np.nan, ma > before)
        adr_usd = np.where(m["adr20_usd"] > 0, m["adr20_usd"], np.nan)
        m["dist_ma10_adr"] = (c - m["ma10"]) / adr_usd
        known = ~np.isnan(pc) & ~np.isnan(c)
        m["consec_up"] = np.where(known, consecutive((c > pc) & known), np.nan)
        m["consec_down"] = np.where(known, consecutive((c < pc) & known), np.nan)
        # Largest close-to-close gain / drop over the last 1..N sessions (Parabolic, §6.2).
        m["gain_max_pct"] = (c / rolling_extreme(pc, windows.gain_days, "min") - 1) * 100
        m["drop_max_pct"] = (1 - c / rolling_extreme(pc, windows.drop_days, "max")) * 100
        # Tight bases (§6.3): recent range and volume dry-up.
        m["range_nd"] = rolling_extreme(h, windows.range_days, "max") - rolling_extreme(
            lo, windows.range_days, "min"
        )
        m["avg_volume_short"] = rolling_mean(v, windows.volume_short_days)
        m["avg_volume_long"] = rolling_mean(v, windows.volume_long_days)

    out_sessions = list(keep) if keep is not None else list(sessions)
    position = {s: i for i, s in enumerate(sessions)}
    rows = [position[s] for s in out_sessions]
    long = pd.DataFrame(
        {
            "session_date": np.repeat(np.array(out_sessions, dtype=object), len(tickers)),
            "ticker": np.tile(tickers.to_numpy(), len(rows)),
            **{name: values[rows].ravel() for name, values in m.items()},
        }
    )
    long = long.dropna(subset=["close"])
    for name in [n for n in long.columns if n.endswith("_rising")]:
        long[name] = long[name].map({1.0: True, 0.0: False}).astype("boolean")
    for name in ("consec_up", "consec_down"):
        long[name] = long[name].astype("Int64")
    long["metrics_basis"] = "history"
    return long.sort_values(["ticker", "session_date"]).reset_index(drop=True)


def latest(metrics: pd.DataFrame, session: dt.date) -> pd.DataFrame:
    """One row per ticker for `session`."""
    return metrics[metrics["session_date"] == session].reset_index(drop=True)
