"""Chart series without any UI (React dashboard, Nov 2026): weekly bars and the indicator lines
(MA / EMA, an anchored VWAP from the signal day, an RS line against QQQ), shared by the
Streamlit focus chart (`app/lwchart.py`) and the API (`api/`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

INDICATORS = {  # name -> (kind, length, colour)
    "MA 10": ("sma", 10, "#f2c94c"),
    "MA 20": ("sma", 20, "#f2994a"),
    "MA 50": ("sma", 50, "#9b51e0"),
    "MA 200": ("sma", 200, "#56ccf2"),
    "EMA 9": ("ema", 9, "#27ae60"),
    "EMA 21": ("ema", 21, "#eb5757"),
    "AVWAP (signal day)": ("avwap", 0, "#e0e0e0"),
    "RS vs QQQ": ("rs", 0, "#2f80ed"),
}
DEFAULT = ["MA 10", "MA 20", "MA 50"]


def weekly(bars: pd.DataFrame) -> pd.DataFrame:
    """Daily bars to weekly (the week's first open, high, low, last close, summed volume),
    dated by the week's first session."""
    b = bars.sort_values("session_date").copy()
    d = pd.to_datetime(b["session_date"])
    b["wk"] = d - pd.to_timedelta(d.dt.weekday, unit="D")
    w = b.groupby("wk").agg(
        session_date=("session_date", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return w.reset_index(drop=True)


def _points(times: pd.Series, values: pd.Series) -> list[dict]:
    return [
        {"time": t, "value": round(float(v), 4)}
        for t, v in zip(times, values, strict=True)
        if v is not None and v == v
    ]


def indicator_lines(
    b: pd.DataFrame, picked: list[str], anchor=None, bench: pd.DataFrame | None = None
) -> list[dict]:
    """The picked indicators as line series: name, colour, scale ('right' or 'rs'), points."""
    out = []
    for name in picked:
        kind, n, colour = INDICATORS[name]
        if kind == "sma":
            values = b["close"].rolling(n).mean()
        elif kind == "ema":
            values = b["close"].ewm(span=n, adjust=False).mean()
        elif kind == "avwap":
            if anchor is None:
                continue
            on = pd.to_datetime(b["session_date"]) >= pd.Timestamp(anchor)
            tp = (b["high"] + b["low"] + b["close"]) / 3
            values = (tp * b["volume"]).where(on).cumsum() / b["volume"].where(on).cumsum()
        elif kind == "rs":
            if bench is None or bench.empty:
                continue
            q = bench.drop_duplicates("session_date").set_index(
                pd.to_datetime(bench.drop_duplicates("session_date")["session_date"])
            )["close"]
            q_on = q.reindex(pd.to_datetime(b["session_date"])).to_numpy()
            values = pd.Series(b["close"].to_numpy() / q_on, index=b.index)
        else:
            continue
        scale = "rs" if kind == "rs" else "right"
        out.append(
            {"name": name, "colour": colour, "scale": scale, "pts": _points(b["time"], values)}
        )
    return out


# --- moved from interactive_chart (React dashboard, Nov 2026): plain pandas, no plotly, so the
# API image (which has no plotly) can draw AVWAPs, trend lines and minute candles too.

AVWAP_COLORS = ["#6a1b9a", "#ad1457", "#283593", "#00695c", "#ef6c00"]


def session_vwap(minutes: pd.DataFrame) -> pd.Series:
    """VWAP from the regular-session open (bar VWAP x volume, cumulative)."""
    regular = minutes["minute"].between(570, 959)
    pv = (minutes["vwap"].fillna(minutes["close"]) * minutes["volume"]).where(regular, 0.0)
    v = minutes["volume"].where(regular, 0.0)
    out = pv.cumsum() / v.cumsum().replace(0, np.nan)
    return out.where(minutes["minute"] >= 570)


def resample_minutes(minutes: pd.DataFrame, every: int = 1) -> pd.DataFrame:
    """Minute bars to `every`-minute candles counted from the 09:30 open (first open, high,
    low, last close, summed volume, mean bar VWAP), oldest first."""
    data = minutes.sort_values("ts").reset_index(drop=True)
    if every <= 1:
        return data
    key = (data["minute"] - 570) // every
    return (
        data.assign(key=key)
        .groupby("key")
        .agg(
            ts=("ts", "first"),
            minute=("minute", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            vwap=("vwap", "mean"),
        )
        .reset_index(drop=True)
    )


def anchored_vwap(bars: pd.DataFrame, anchor) -> pd.Series:
    """VWAP from the session `anchor` on (NaN before it): each day's own VWAP weighted by its
    volume (the typical price (H+L+C)/3 where a bar has no VWAP)."""
    data = bars.sort_values("session_date").reset_index(drop=True)
    typical = (data["high"] + data["low"] + data["close"]) / 3
    price = data["vwap"].fillna(typical) if "vwap" in data else typical
    after = pd.to_datetime(data["session_date"]) >= pd.Timestamp(anchor)
    pv = (price * data["volume"]).where(after, 0.0).cumsum()
    v = data["volume"].where(after, 0.0).cumsum()
    return (pv / v.replace(0, np.nan)).where(after)


def quick_anchors(bars: pd.DataFrame, lookback: int = 250) -> dict[str, object]:
    """Common AVWAP anchors: the highest high and lowest low of the last `lookback` sessions,
    and the start of the current year."""
    data = bars.sort_values("session_date").tail(lookback).reset_index(drop=True)
    if data.empty:
        return {}
    last = pd.Timestamp(data["session_date"].iloc[-1])
    year = data[pd.to_datetime(data["session_date"]) >= pd.Timestamp(last.year, 1, 1)]
    out = {
        "highest high": data.loc[data["high"].idxmax(), "session_date"],
        "lowest low": data.loc[data["low"].idxmin(), "session_date"],
    }
    if len(year):
        out["year start"] = year["session_date"].iloc[0]
    return out


def trend_line(dates: list[str], x0, y0: float, x1, y1: float, extend: bool = True):
    """Points of a straight line through (x0, y0) and (x1, y1) on the trading-day axis, from
    x0 to x1 or, `extend`ed, on to the last date. None when a point isn't on the chart."""
    labels = list(dates)
    a, b = pd.Timestamp(x0).strftime("%Y-%m-%d"), pd.Timestamp(x1).strftime("%Y-%m-%d")
    if a not in labels or b not in labels:
        return None
    i0, i1 = labels.index(a), labels.index(b)
    if i0 == i1:
        return None
    if i0 > i1:
        i0, i1, y0, y1 = i1, i0, y1, y0
    end = len(labels) - 1 if extend else i1
    slope = (y1 - y0) / (i1 - i0)
    xs = labels[i0 : end + 1]
    ys = [y0 + slope * (i - i0) for i in range(i0, end + 1)]
    return xs, ys
