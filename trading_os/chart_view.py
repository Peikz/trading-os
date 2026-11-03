"""The Chart page's data, without any UI (React dashboard, Nov 2026): moved from
`app/streamlit_app.py` so the Streamlit and the React Chart pages show the same things.

A stock's daily bars (2 years from the compact bars-2y release, or 10 years from Alpaca's
yearly files), the scans' past hits on it, your fills, the pivot / stops / plan entry, anchored
VWAPs, your saved trend lines, and minute bars (the minute study's days, or Alpaca's live feed
when its keys are set). `payload` turns it all into the series a Lightweight Chart draws.
Read-only: drawings and notes are written by `chart_marks` and `stock_notes`.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import (
    board_data,
    chart_series,
    clock,
    dashboard,
    journal,
    long_history,
    my_watchlists,
    notify,
    plans,
    remote_data,
)
from trading_os import chart_series as ichart  # the plotly-free chart helpers

SPANS = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 504, "All": None}
# The Chart page's lines (Streamlit's OVERLAYS) as the chart series' names
LINES = {"MA10": "MA 10", "MA20": "MA 20", "MA50": "MA 50", "MA200": "MA 200",
         "EMA9": "EMA 9", "EMA21": "EMA 21"}  # fmt: skip
AVWAP_COLOURS = ichart.AVWAP_COLORS
LINE_COLOUR = "#e53935"
LEVEL_COLOURS = {"pivot": "#2da44e", "order stop": "#ef5350", "stop": "#ef5350",
                 "plan entry": "#2f81f7"}  # fmt: skip
HIT_COLOUR = "#f2c94c"
LIVE_MARKS = {630: "10:30"}  # the live intraday chart: the EP entry time
NO_KEYS = (
    "Live minute bars need the Alpaca keys where the dashboard runs (ALPACA_API_KEY_ID and "
    "ALPACA_API_SECRET_KEY in its environment)."
)


def _repo(data_dir: Path) -> str:
    return remote_data.repo_of(Path(data_dir))


def release(data_dir: Path, tag: str, pattern: str = "*") -> Path:
    """The cache folder of a data-repo release with the files matching `pattern` fetched
    (offline: whatever the cache already has)."""
    with contextlib.suppress(Exception):
        remote_data.fetch(_repo(data_dir), tag, pattern)
    return remote_data.CACHE / tag


def bars(data_dir: Path, ticker: str, period: str = "2y") -> pd.DataFrame:
    """Daily bars: 2 years (the compact bars-2y file) or 10 years (Alpaca's yearly files)."""
    if period == "2y":
        return board_data.daily_bars(Path(data_dir), ticker)
    import pyarrow.dataset as ds

    files = sorted(release(data_dir, "bars-alpaca", "*.parquet").glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=board_data.BAR_COLUMNS)
    table = ds.dataset(files, format="parquet").to_table(filter=ds.field("ticker") == ticker)
    out = table.to_pandas()
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out.drop_duplicates("session_date").sort_values("session_date")


def all_hits(data_dir: Path, period: str = "2y", strategy_history=None) -> pd.DataFrame:
    """Every scan hit (strategy, session_date, ticker, side), EP-Days included."""
    cols = ["strategy", "session_date", "ticker", "side"]
    if period == "10y":
        long_dir = release(data_dir, "history-10y", "*.parquet")
        hits = long_history.load(long_dir, "strategy", cols)
        eps = long_history.load(long_dir, "ep", ["session_date", "ticker", "is_ep_day", "tier"])
    else:
        from trading_os import strategy_history as sh

        hits = strategy_history if strategy_history is not None else sh.load(data_dir)
        built = sorted((Path(data_dir) / "data" / "ep_history").glob("ep_history_*.parquet"))
        eps = pd.read_parquet(built[-1]) if built else pd.DataFrame()
    frames = [hits[[c for c in cols if c in hits]]] if len(hits) else []
    if len(eps):
        ep = eps[eps["is_ep_day"] & (eps["tier"] == "alert")]
        frames.append(ep[["session_date", "ticker"]].assign(strategy="ep_day", side="long"))
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.date
    return out


def hits_for(hits: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """One stock's past scan hits, labelled with the strategy (the chart's amber triangles)."""
    mine = hits[hits["ticker"] == ticker].copy()
    mine["label_text"] = mine["strategy"]
    mine["side"] = mine["side"].fillna("long") if "side" in mine else "long"
    return mine


def fills_for(data_dir: Path, ticker: str) -> pd.DataFrame:
    """Your fills in one stock (the chart's green buys and red sells)."""
    fills = journal.reconcile(journal.load_fills(data_dir))
    return fills[fills["ticker"] == ticker] if len(fills) else fills


def levels_for(data_dir: Path, runs, cfg, ticker: str, read=pd.read_parquet) -> dict:
    """Pivot and order stop from the newest EOD snapshot; your open position's stop and open
    plans' entries and stops."""
    out: dict[str, float] = {}
    eod = [r for r in runs if r.slot == "eod" and r.universe.exists()]
    if eod:
        uni = read(str(eod[0].universe))
        row = uni[uni["ticker"] == ticker]
        if len(row):
            for column, label in (("bo_pivot", "pivot"), ("bo_order_stop", "order stop")):
                value = row.iloc[0].get(column)
                if value is not None and value == value:
                    out[label] = float(value)
    positions = dashboard.latest_positions(data_dir)
    if len(positions):
        mine = positions[positions["ticker"] == ticker]
        stop = mine.iloc[0].get("order_stop") if len(mine) else None
        if stop is not None and pd.notna(stop):  # a position logged without a stop has none
            out["stop"] = float(stop)
    events = plans.load(data_dir)
    if len(events):
        today = clock.ny_time(cfg.schedule, dt.datetime.now(dt.UTC)).date()
        fills = journal.reconcile(journal.load_fills(data_dir))
        current = plans.status(
            events, fills, cfg.schedule, cfg.journal["plan_valid_sessions"], today
        )
        open_plans = current[(current["ticker"] == ticker) & (current["status"] == "open")]
        if len(open_plans):
            out["plan entry"] = float(open_plans.iloc[0]["entry"])
            out.setdefault("stop", float(open_plans.iloc[0]["stop"]))
    return out


def to_weeks(
    frame: pd.DataFrame | None, weeks: pd.DataFrame, freq: str = "W-FRI"
) -> pd.DataFrame | None:
    """Move each row's session_date to its week's label (the week's last session); months
    with freq="M"."""
    if frame is None or frame.empty:
        return frame
    period = pd.to_datetime(weeks["session_date"]).dt.to_period(freq)
    label = dict(zip(period, weeks["session_date"], strict=True))
    out = frame.copy()
    out["session_date"] = pd.to_datetime(out["session_date"]).dt.to_period(freq).map(label)
    return out.dropna(subset=["session_date"])


def picks(data_dir: Path, runs, frames: Callable[[str], pd.DataFrame] = pd.read_parquet) -> dict:
    """Ticker -> where it comes from: every alert-tier hit of the newest session's runs (pushed
    ones first), then your watchlists and open positions."""
    where: dict[str, str] = {}
    if runs:
        today = [r for r in runs if r.session == runs[0].session]
        hits = pd.concat([frames(str(r.candidates)) for r in today], ignore_index=True)
        if len(hits):
            if "tier" in hits:
                hits = hits[hits["tier"] == "alert"]
            pushed = hits["pushed"] if "pushed" in hits else pd.Series(False, index=hits.index)
            hits = hits.assign(_pushed=pushed.fillna(False).astype(bool))
            hits = hits.sort_values("_pushed", ascending=False, kind="stable")
            for row in hits.to_dict("records"):
                label = notify.SCAN_LABELS.get(row["scan"], row["scan"])
                where.setdefault(row["ticker"], f"{label}{' · pushed' if row['_pushed'] else ''}")
    for t in my_watchlists.current(my_watchlists.load(data_dir))["ticker"]:
        where.setdefault(t, "watchlist")
    positions = dashboard.latest_positions(data_dir)
    for t in positions.get("ticker", []):
        where.setdefault(t, "open position")
    return where


def anchors_for(daily: pd.DataFrame, hits: pd.DataFrame, marks: pd.DataFrame) -> dict:
    """The AVWAP anchors to choose from (quick ones: highest high, lowest low, year start, the
    latest scan hit) and your saved ones (label -> date)."""
    quick = ichart.quick_anchors(daily) if len(daily) else {}
    if len(hits):
        quick["latest scan hit"] = max(hits["session_date"])
    saved = {}
    for m in marks[marks["kind"] == "anchor"].to_dict("records") if len(marks) else []:
        saved[m["label"] or f"{m['anchor']}"] = m["anchor"]
    return {"quick": quick, "saved": saved}


def _day(x) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def payload(
    daily: pd.DataFrame,
    *,
    timeframe: str = "Daily",
    lines: list[str] | None = None,
    sessions: int | None = 252,
    hits: pd.DataFrame | None = None,
    fills: pd.DataFrame | None = None,
    levels: Mapping[str, float] | None = None,
    anchors: Mapping[str, Any] | None = None,
    marks: list[Mapping] | None = None,
) -> dict:
    """A stock's chart as Lightweight Charts series: candles (with volume), MA/EMA lines,
    anchored VWAPs, saved trend lines (daily bars only, each with its mark id, extended to the
    last bar when saved so), markers for scan hits and fills, and the price levels. `sessions`:
    the bars shown at first (all are sent, so you can scroll back)."""
    data = daily.sort_values("session_date").reset_index(drop=True)
    if data.empty:
        return {"candles": [], "lines": [], "avwaps": [], "trend": [], "markers": [],
                "levels": [], "visible": None}  # fmt: skip
    if fills is not None and "session_date" not in fills and "trade_date" in fills:
        fills = fills.rename(columns={"trade_date": "session_date"})
    coarse = timeframe in ("Weekly", "Monthly")  # not daily: no AVWAPs or trend lines
    if timeframe == "Weekly":
        data = chart_series.weekly(data)
        hits, fills = to_weeks(hits, data), to_weeks(fills, data)
        sessions = sessions // 5 if sessions else None
    elif timeframe == "Monthly":  # as on the Streamlit Chart page (Emil, 4 Nov 2026)
        data = chart_series.monthly(data)
        hits, fills = to_weeks(hits, data, "M"), to_weeks(fills, data, "M")
        sessions = max(sessions // 21, 12) if sessions else None
    data["time"] = [_day(d) for d in data["session_date"]]
    candles = [
        {"time": t, "open": float(o), "high": float(h), "low": float(lo), "close": float(c),
         "volume": float(v)}
        for t, o, h, lo, c, v in zip(data["time"], data["open"], data["high"], data["low"],
                                     data["close"], data["volume"], strict=True)
    ]  # fmt: skip
    names = [LINES[n] for n in lines or [] if n in LINES]
    out_lines = chart_series.indicator_lines(data, names)
    avwaps = []
    if anchors and not coarse:
        for k, (label, anchor) in enumerate(anchors.items()):
            values = ichart.anchored_vwap(data, anchor)
            pts = [
                {"time": t, "value": round(float(v), 4)}
                for t, v in zip(data["time"], values, strict=True)
                if v == v
            ]
            if pts:
                colour = AVWAP_COLOURS[k % len(AVWAP_COLOURS)]
                avwaps.append({"name": f"AVWAP {label}", "colour": colour, "pts": pts})
    trend = []
    if not coarse:
        dates = list(data["time"])
        for m in marks or []:
            pts = ichart.trend_line(
                dates, m["x0"], m["y0"], m["x1"], m["y1"], bool(m.get("extend", True))
            )
            if pts is None:
                continue
            xs, ys = pts
            trend.append(
                {
                    "id": str(m["mark_id"]),
                    "label": m.get("label") or "",
                    "colour": LINE_COLOUR,
                    "x0": _day(m["x0"]), "y0": float(m["y0"]),
                    "x1": _day(m["x1"]), "y1": float(m["y1"]),
                    "extend": bool(m.get("extend", True)),
                    "pts": [{"time": xs[0], "value": ys[0]}, {"time": xs[-1], "value": ys[-1]}],
                }
            )  # fmt: skip
    shown = set(data["time"])
    markers = []
    for h in hits.to_dict("records") if hits is not None and len(hits) else []:
        t = _day(h["session_date"])
        if t in shown:
            short = h.get("side") == "short"
            markers.append(
                {
                    "time": t,
                    "position": "aboveBar" if short else "belowBar",
                    "shape": "arrowDown" if short else "arrowUp",
                    "color": HIT_COLOUR,
                    "text": str(h.get("label_text") or ""),
                }
            )
    for f in fills.to_dict("records") if fills is not None and len(fills) else []:
        t = _day(f["session_date"])
        if t in shown:
            buy = f.get("side") == "buy"
            markers.append(
                {
                    "time": t,
                    "position": "belowBar" if buy else "aboveBar",
                    "shape": "arrowUp" if buy else "arrowDown",
                    "color": "#3fb950" if buy else "#f85149",
                    "text": f"{'buy' if buy else 'sell'} {float(f['price']):.2f}",
                }
            )
    markers.sort(key=lambda m: m["time"])
    out_levels = [
        {"name": k, "price": float(v), "colour": LEVEL_COLOURS.get(k, "#8b949e")}
        for k, v in (levels or {}).items()
        if v is not None and v == v
    ]
    first = data["time"].iloc[-sessions] if sessions and len(data) > sessions else None
    return {
        "candles": candles,
        "lines": out_lines,
        "avwaps": avwaps,
        "trend": trend,
        "markers": markers,
        "levels": out_levels,
        "visible": {"from": first, "to": data["time"].iloc[-1]} if first else None,
    }


# --- minute bars


def minute_index(data_dir: Path) -> pd.DataFrame:
    """Every stock-day with minute bars (the release's small minute_index.parquet)."""
    path = release(data_dir, "intraday-minutes", "minute_index.parquet") / "minute_index.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["session_date", "ticker"])
    index = pd.read_parquet(path)
    index["session_date"] = pd.to_datetime(index["session_date"]).dt.date
    return index


def minute_days(index: pd.DataFrame, ticker: str) -> list:
    """Sessions that have minute bars for `ticker` (newest first)."""
    return sorted(set(index.loc[index["ticker"] == ticker, "session_date"]), reverse=True)


def minute_bars(data_dir: Path, ticker: str, day) -> pd.DataFrame:
    """One stock-day's minute bars, New York time, with `minute` after midnight (the month's
    files fetched from GitHub when first needed)."""
    import pyarrow.dataset as ds

    month = f"{day:%Y-%m}"
    root = release(data_dir, "intraday-minutes", f"{month}_*.parquet")
    files = [
        f for f in sorted(root.glob(f"{month}_*.parquet")) if not f.name.endswith(".asked.parquet")
    ]
    if not files:
        return pd.DataFrame()
    flt = (ds.field("ticker") == ticker) & (ds.field("session_date") == day)
    out = ds.dataset(files, format="parquet").to_table(filter=flt).to_pandas()
    if out.empty:
        return out
    out = out.drop_duplicates("ts")
    out["ts"] = pd.to_datetime(out["ts"], utc=True).dt.tz_convert("America/New_York")
    out["minute"] = out["ts"].dt.hour * 60 + out["ts"].dt.minute
    return out[out["ts"].dt.date == day].sort_values("ts")


def has_alpaca(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("ALPACA_API_KEY_ID") and env.get("ALPACA_API_SECRET_KEY"))


def live_minutes(ticker: str, day: dt.date) -> pd.DataFrame:
    """One session's minute bars from Alpaca's free real-time IEX feed (keys from the
    environment), 04:00-20:00 New York; ts in New York time."""
    from trading_os.alpaca import AlpacaClient

    client = AlpacaClient(
        os.environ["ALPACA_API_KEY_ID"], os.environ["ALPACA_API_SECRET_KEY"], per_minute=60
    )
    client.feed = "iex"
    start = dt.datetime.combine(day, dt.time(4, 0), tzinfo=clock.NEW_YORK)
    end = min(
        dt.datetime.combine(day, dt.time(20, 0), tzinfo=clock.NEW_YORK), dt.datetime.now(dt.UTC)
    )
    raw = client.bars([ticker], "1Min", start.astimezone(dt.UTC), end.astimezone(dt.UTC))
    if raw.empty:
        return raw
    ts = pd.to_datetime(raw["ts"], utc=True).dt.tz_convert(clock.NEW_YORK)
    return raw.assign(ts=ts, minute=ts.dt.hour * 60 + ts.dt.minute)


def live_sessions(cfg, n: int = 5) -> list[dt.date]:
    """The last `n` sessions, newest first (the live intraday picker)."""
    today = clock.ny_time(cfg.schedule, dt.datetime.now(dt.UTC)).date()
    return clock.sessions_back(cfg.schedule, today, n)[::-1]


def prior_close(daily: pd.DataFrame, day) -> float | None:
    prior = daily[daily["session_date"] < day]["close"] if len(daily) else pd.Series(dtype=float)
    return float(prior.iloc[-1]) if len(prior) else None


def intraday_payload(
    minutes: pd.DataFrame,
    every: int = 1,
    prev_close: float | None = None,
    levels: Mapping[str, float] | None = None,
    mark_minutes: Mapping[int, str] | None = None,
) -> dict:
    """One day's `every`-minute candles for a Lightweight Chart: times as UTC seconds shifted
    to New York wall time (so the axis reads New York), the VWAP from the 09:30 open, whether
    each bar is outside regular hours, the prior close and the levels. `mark_minutes`: minute
    after midnight -> text, marked on the first candle at or after it (the live chart's 10:30,
    the EP entry time)."""
    if minutes.empty:
        return {"candles": [], "vwap": [], "levels": [], "markers": []}
    if "vwap" not in minutes:
        minutes = minutes.assign(vwap=float("nan"))
    data = ichart.resample_minutes(minutes, every)
    vwap = ichart.session_vwap(data)
    wall = [int(pd.Timestamp(t.replace(tzinfo=None)).timestamp()) for t in data["ts"]]
    candles = [
        {"time": w, "open": float(o), "high": float(h), "low": float(lo), "close": float(c),
         "volume": float(v), "extended": not 570 <= int(m) < 960}
        for w, o, h, lo, c, v, m in zip(wall, data["open"], data["high"], data["low"],
                                        data["close"], data["volume"], data["minute"],
                                        strict=True)
    ]  # fmt: skip
    vw = [
        {"time": w, "value": round(float(v), 4)} for w, v in zip(wall, vwap, strict=True) if v == v
    ]
    lv = [
        {"name": k, "price": float(v), "colour": LEVEL_COLOURS.get(k, "#8b949e")}
        for k, v in (levels or {}).items()
        if v is not None and v == v
    ]
    if prev_close is not None:
        lv.append({"name": "prior close", "price": float(prev_close), "colour": "#8b949e"})
    markers = []
    for minute, text in (mark_minutes or {}).items():
        at = next((w for w, m in zip(wall, data["minute"], strict=True) if int(m) >= minute), None)
        if at is not None:
            markers.append({"time": at, "position": "aboveBar", "shape": "arrowDown",
                            "color": "#9e9e9e", "text": text})  # fmt: skip
    return {"candles": candles, "vwap": vw, "levels": lv, "markers": markers}
