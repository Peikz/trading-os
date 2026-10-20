"""Interactive charts for the dashboard (Emil, 20 Oct 2026): candles with volume, moving
averages, the scans' past hits, your fills and the levels that matter (pivot, stops), plus an
intraday view of one day's minute bars with VWAP. Plotly figures; the app only displays them.

The x-axis is the trading days themselves (no gaps for weekends and holidays), so the
markers, fills and lines all key on the same date labels.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

UP, DOWN = "#26a69a", "#ef5350"
LINE_COLORS = {
    "MA10": "#1e88e5",
    "MA20": "#fb8c00",
    "MA50": "#8e24aa",
    "MA200": "#546e7a",
    "EMA9": "#00acc1",
    "EMA21": "#c0ca33",
}
LEVEL_STYLES = {"pivot": "dash", "order stop": "dot", "stop": "dot", "plan entry": "dashdot"}


def weekly(bars: pd.DataFrame) -> pd.DataFrame:
    """Daily bars to weeks (Monday-Friday), labelled by the week's last session."""
    df = bars.copy()
    df["week"] = pd.to_datetime(df["session_date"]).dt.to_period("W-FRI")
    out = df.groupby("week").agg(
        session_date=("session_date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return out.reset_index(drop=True)


def lines(close: pd.Series, names: list[str]) -> dict[str, pd.Series]:
    """`MA10` (simple) or `EMA9` (exponential) series for the chosen names."""
    out = {}
    for name in names:
        window = int(name.removeprefix("EMA").removeprefix("MA"))
        if name.startswith("EMA"):
            out[name] = close.ewm(span=window, adjust=False, min_periods=window).mean()
        else:
            out[name] = close.rolling(window).mean()
    return out


def _labels(dates) -> list[str]:
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates]


def daily_figure(
    bars: pd.DataFrame,
    *,
    title: str,
    overlays: list[str] | None = None,
    markers: pd.DataFrame | None = None,
    fills: pd.DataFrame | None = None,
    levels: Mapping[str, float] | None = None,
    sessions: int | None = None,
    height: int = 640,
) -> go.Figure:
    """Candles + volume. `markers`: session_date, label, side (long/short): a scan's hit,
    drawn under (long) or over (short) that day's bar. `fills`: session_date, price, side
    (buy/sell). `levels`: label -> price lines. `sessions`: show only the last N bars (the
    lines are computed on all of them first)."""
    data = bars.sort_values("session_date").reset_index(drop=True)
    drawn = lines(data["close"], overlays or [])
    if sessions:
        start = max(0, len(data) - sessions)
        data = data.iloc[start:].reset_index(drop=True)
        drawn = {k: v.iloc[start:].reset_index(drop=True) for k, v in drawn.items()}
    x = _labels(data["session_date"])
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.02
    )
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            increasing_line_color=UP,
            decreasing_line_color=DOWN,
            name="price",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    for name, series in drawn.items():
        fig.add_trace(
            go.Scatter(
                x=x,
                y=series,
                mode="lines",
                name=name,
                line={"width": 1.2, "color": LINE_COLORS.get(name)},
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )
    rising = data["close"] >= data["open"]
    fig.add_trace(
        go.Bar(
            x=x,
            y=data["volume"],
            marker_color=np.where(rising, UP, DOWN).tolist(),
            name="volume",
            showlegend=False,
        ),
        row=2,
        col=1,
    )
    shown = set(x)
    by_day = data.assign(label=x).set_index("label")
    if markers is not None and len(markers):
        m = markers.assign(label=_labels(markers["session_date"]))
        m = m[m["label"].isin(shown)]
        for side, symbol, offset in (
            ("long", "triangle-up", 0.985),
            ("short", "triangle-down", 1.015),
        ):
            part = m[m["side"] == side]
            if part.empty:
                continue
            anchor = "low" if side == "long" else "high"
            text = part.groupby("label")["label_text"].agg(lambda s: "<br>".join(sorted(set(s))))
            fig.add_trace(
                go.Scatter(
                    x=list(text.index),
                    y=[by_day.loc[d, anchor] * offset for d in text.index],
                    mode="markers",
                    marker={
                        "symbol": symbol,
                        "size": 10,
                        "color": "#ffb300",
                        "line": {"width": 1, "color": "#424242"},
                    },
                    name=f"scan hits ({side})",
                    hovertext=list(text.values),
                    hoverinfo="text+x",
                ),
                row=1,
                col=1,
            )
    if fills is not None and len(fills):
        f = fills.assign(label=_labels(fills["session_date"]))
        f = f[f["label"].isin(shown)]
        for side, symbol, color in (("buy", "triangle-up", UP), ("sell", "triangle-down", DOWN)):
            part = f[f["side"] == side]
            if part.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=part["label"],
                    y=part["price"],
                    mode="markers",
                    marker={
                        "symbol": symbol,
                        "size": 13,
                        "color": color,
                        "line": {"width": 1.5, "color": "#212121"},
                    },
                    name=f"my {side}s",
                    hovertext=[
                        f"{side} {q:g} @ {p:.2f}"
                        for q, p in zip(
                            part.get("quantity", part["price"] * 0), part["price"], strict=True
                        )
                    ],
                    hoverinfo="text+x",
                ),
                row=1,
                col=1,
            )
    for label, price in (levels or {}).items():
        if price is None or not np.isfinite(price):
            continue
        fig.add_hline(
            y=price,
            line_dash=LEVEL_STYLES.get(label, "dash"),
            line_width=1,
            line_color="#616161",
            annotation_text=f"{label} {price:.2f}",
            annotation_position="top left",
            row=1,
            col=1,
        )
    fig.update_layout(
        title={"text": title, "x": 0.01},
        height=height,
        margin={"l": 10, "r": 10, "t": 40, "b": 10},
        xaxis_rangeslider_visible=False,
        dragmode="pan",
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02, "x": 0.3},
        newshape={"line": {"color": "#e53935", "width": 2}},  # the drawing tool's lines
    )
    fig.update_xaxes(type="category", nticks=10)
    return fig


def session_vwap(minutes: pd.DataFrame) -> pd.Series:
    """VWAP from the regular-session open (bar VWAP x volume, cumulative)."""
    regular = minutes["minute"].between(570, 959)
    pv = (minutes["vwap"].fillna(minutes["close"]) * minutes["volume"]).where(regular, 0.0)
    v = minutes["volume"].where(regular, 0.0)
    out = pv.cumsum() / v.cumsum().replace(0, np.nan)
    return out.where(minutes["minute"] >= 570)


def intraday_figure(
    minutes: pd.DataFrame,
    *,
    title: str,
    prev_close: float | None = None,
    levels: Mapping[str, float] | None = None,
    every: int = 1,
    height: int = 560,
) -> go.Figure:
    """One day's minute bars (`every` minutes per candle): candles, VWAP, volume, the prior
    close and `levels`. `minutes`: ts (New York), minute (after midnight), open, high, low,
    close, volume, vwap. Pre- and post-market are shaded."""
    data = minutes.sort_values("ts").reset_index(drop=True)
    if every > 1:
        key = (data["minute"] - 570) // every
        data = (
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
    vwap = session_vwap(data)
    x = [t.strftime("%H:%M") for t in data["ts"]]
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.02
    )
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            increasing_line_color=UP,
            decreasing_line_color=DOWN,
            name="price",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=x, y=vwap, mode="lines", name="VWAP", line={"width": 1.3, "color": "#7e57c2"}),
        row=1,
        col=1,
    )
    rising = data["close"] >= data["open"]
    fig.add_trace(
        go.Bar(
            x=x,
            y=data["volume"],
            marker_color=np.where(rising, UP, DOWN).tolist(),
            name="volume",
            showlegend=False,
        ),
        row=2,
        col=1,
    )
    all_levels = dict(levels or {})
    if prev_close is not None and np.isfinite(prev_close):
        all_levels["prior close"] = prev_close
    for label, price in all_levels.items():
        if price is None or not np.isfinite(price):
            continue
        fig.add_hline(
            y=price,
            line_dash=LEVEL_STYLES.get(label, "dash"),
            line_width=1,
            line_color="#616161",
            annotation_text=f"{label} {price:.2f}",
            annotation_position="top left",
            row=1,
            col=1,
        )
    outside = data["minute"].lt(570) | data["minute"].ge(960)
    if outside.any() and not outside.all():
        first_regular = x[int(np.flatnonzero(~outside.to_numpy())[0])]
        last_regular = x[int(np.flatnonzero(~outside.to_numpy())[-1])]
        for x0, x1 in ((x[0], first_regular), (last_regular, x[-1])):
            if x0 != x1:
                fig.add_vrect(x0=x0, x1=x1, fillcolor="#9e9e9e", opacity=0.12, line_width=0)
    fig.update_layout(
        title={"text": title, "x": 0.01},
        height=height,
        margin={"l": 10, "r": 10, "t": 40, "b": 10},
        xaxis_rangeslider_visible=False,
        dragmode="pan",
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02, "x": 0.3},
        newshape={"line": {"color": "#e53935", "width": 2}},  # the drawing tool's lines
    )
    fig.update_xaxes(type="category", nticks=12)
    return fig


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


def add_avwaps(fig: go.Figure, bars: pd.DataFrame, anchors: Mapping[str, object], shown: list):
    """Draw anchored VWAPs (label -> anchor date) on the price panel of `fig`."""
    data = bars.sort_values("session_date").reset_index(drop=True)
    labels = _labels(data["session_date"])
    keep = set(shown)
    for k, (label, anchor) in enumerate(anchors.items()):
        series = anchored_vwap(data, anchor)
        pts = [(x, y) for x, y in zip(labels, series, strict=True) if x in keep and y == y]
        if not pts:
            continue
        fig.add_trace(
            go.Scatter(
                x=[p[0] for p in pts],
                y=[p[1] for p in pts],
                mode="lines",
                name=f"AVWAP {label}",
                line={"width": 1.4, "dash": "dot", "color": AVWAP_COLORS[k % len(AVWAP_COLORS)]},
            ),
            row=1,
            col=1,
        )


def add_trend_lines(fig: go.Figure, shown: list, marks: list[Mapping]):
    """Draw saved trend lines (x0, y0, x1, y1, label, extend) on the price panel."""
    for mark in marks:
        pts = trend_line(
            shown, mark["x0"], mark["y0"], mark["x1"], mark["y1"], bool(mark.get("extend", True))
        )
        if pts is None:
            continue
        fig.add_trace(
            go.Scatter(
                x=pts[0],
                y=pts[1],
                mode="lines",
                name=mark.get("label") or "trend line",
                line={"width": 1.6, "color": "#e53935"},
            ),
            row=1,
            col=1,
        )


AVWAP_COLORS = ["#6a1b9a", "#ad1457", "#283593", "#00695c", "#ef6c00"]
DRAW_CONFIG = {
    "modeBarButtonsToAdd": ["drawline", "drawopenpath", "eraseshape"],
    "scrollZoom": True,
    "displaylogo": False,
}
