"""Before-shot charts per alert candidate (SPEC §9, Phase 3).

A daily candle chart as it looked at signal time: the last N sessions up to the signal
session, MA10/20/50, volume, the signal day marked, and pivot / order stop when the scan
has them. PNGs go to the private data repo next to the run's candidates.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display in Actions

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

UP, DOWN = "#2e7d32", "#c62828"
MA_COLORS = {10: "#1565c0", 20: "#ef6c00", 50: "#6a1b9a"}


def chart_path(data_dir: Path, session: dt.date, slot: str, scan: str, ticker: str) -> Path:
    safe = ticker.replace("/", "-").replace(".", "-")
    run = f"{session.isoformat()}_{slot}"
    return Path(data_dir) / "data" / "charts" / str(session.year) / run / f"{scan}_{safe}.png"


def before_shot(
    bars: pd.DataFrame,
    path: Path,
    *,
    title: str,
    signal_session: dt.date,
    sessions: int,
    pivot: float | None = None,
    order_stop: float | None = None,
) -> Path | None:
    """Draw one ticker's bars (session_date, open, high, low, close, volume) up to the signal.

    Returns None when there are no bars to draw. Never overwrites an existing chart.
    """
    if path.exists():
        return path
    data = bars[bars["session_date"] <= signal_session].sort_values("session_date")
    if data.empty:
        return None
    closes = data["close"].astype(float)
    mas = {w: closes.rolling(w).mean() for w in MA_COLORS}
    data = data.tail(sessions).reset_index(drop=True)
    mas = {w: ma.tail(sessions).reset_index(drop=True) for w, ma in mas.items()}
    x = np.arange(len(data))

    fig, (ax, vol) = plt.subplots(
        2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    rising = data["close"] >= data["open"]
    colors = np.where(rising, UP, DOWN)
    ax.vlines(x, data["low"], data["high"], color=colors, linewidth=0.8)
    body_low = np.minimum(data["open"], data["close"])
    body = np.maximum(np.abs(data["close"] - data["open"]), 1e-9)
    ax.bar(x, body, bottom=body_low, color=colors, width=0.6)
    for window, ma in mas.items():
        ax.plot(x, ma, color=MA_COLORS[window], linewidth=1, label=f"MA{window}")
    for level, label, style in ((pivot, "pivot", "--"), (order_stop, "order stop", ":")):
        if level is not None and not pd.isna(level):
            ax.axhline(level, color="#424242", linestyle=style, linewidth=1, label=label)
    signal_x = x[data["session_date"] == signal_session]
    for axis in (ax, vol):
        for sx in signal_x:
            axis.axvline(sx, color="#9e9e9e", linewidth=6, alpha=0.25)
    vol.bar(x, data["volume"], color=colors, width=0.6)
    ax.set_title(title, loc="left", fontsize=11)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.grid(alpha=0.2)
    vol.grid(alpha=0.2)
    step = max(1, len(data) // 8)
    vol.set_xticks(x[::step])
    vol.set_xticklabels([d.isoformat() for d in data["session_date"].iloc[::step]], fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.png")
    fig.savefig(tmp, dpi=80)
    plt.close(fig)
    tmp.rename(path)
    return path


def draw_for_run(
    data_dir: Path,
    session: dt.date,
    slot: str,
    selected: dict[str, pd.DataFrame],
    bars: pd.DataFrame,
    sessions: int,
) -> int:
    """One chart per pushed candidate. `bars` holds history up to the signal session."""
    drawn = 0
    by_ticker = {t: g for t, g in bars.groupby("ticker")} if not bars.empty else {}
    for scan, hits in selected.items():
        for row in hits.to_dict("records"):
            ticker = row["ticker"]
            ticker_bars = by_ticker.get(ticker)
            if ticker_bars is None:
                continue
            path = chart_path(data_dir, session, slot, scan, ticker)
            title = f"{ticker} · {scan} · {session.isoformat()} ({slot})"
            if before_shot(
                ticker_bars,
                path,
                title=title,
                signal_session=session,
                sessions=sessions,
                pivot=row.get("pivot"),
                order_stop=row.get("order_stop"),
            ):
                drawn += 1
    return drawn
