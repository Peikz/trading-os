"""Chart series without any UI (React dashboard, Nov 2026): weekly bars and the indicator lines
(MA / EMA, an anchored VWAP from the signal day, an RS line against QQQ), shared by the
Streamlit focus chart (`app/lwchart.py`) and the API (`api/`).
"""

from __future__ import annotations

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
