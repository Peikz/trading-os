"""Breadth line and Market Light (SPEC §6.2, §6.5).

Breadth (Stockbee Market Monitor style) on the breadth universe (price >= $5, volume >= 100K):
up/down 4 % counts, 5- and 10-day up/down ratios, stocks up/down >= 25 % in a quarter, and
% above MA20/40/50. Past days' counts come from daily bars (our EOD snapshots or Massive),
restricted to today's logged-tier tickers, so the ratios are available as soon as 10
sessions of bars exist.

Market Light (owner's rules, §6.5): QQQ trend + breadth state + the Sunday scan count,
first matching light wins. A light is only given when every input is known.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trading_os import clock, history
from trading_os.config import Config
from trading_os.tv import canonical

COUNTRY_NAMES = {"USA": "United States"}  # config wording -> TradingView `country` value


def in_breadth_universe(df: pd.DataFrame, breadth: Mapping[str, Any]) -> pd.Series:
    return (df["close"] >= breadth["universe_price_min"]) & (
        df["volume"] >= breadth["universe_volume_min"]
    )


def move_flags(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Per-stock up/down flags using the Momentum Burst thresholds from config."""
    up, down = cfg.scans["mb_up"], cfg.scans["mb_down"]
    louder = df["volume"] > df["prev_volume"]
    up4 = (df["chg_pct"] >= up["chg_min_pct"]) & louder
    return pd.DataFrame(
        {
            "up4": up4,
            "mb_up": up4 & (df["close_loc"] >= up["close_loc_min"]),
            "down4": (df["chg_pct"] <= down["chg_max_pct"]) & louder,
        },
        index=df.index,
    ).fillna(False)


def day_counts(df: pd.DataFrame, cfg: Config) -> dict[str, int]:
    breadth = cfg.scans["breadth"]
    universe = df[in_breadth_universe(df, breadth)]
    flags = move_flags(universe, cfg)
    return {
        "breadth_n": len(universe),
        "up4": int(flags["up4"].sum()),
        "mb_up": int(flags["mb_up"].sum()),
        "down4": int(flags["down4"].sum()),
    }


def past_counts(
    data_dir: Path, cfg: Config, sessions: list[dt.date], tickers: set[str]
) -> pd.DataFrame:
    """Counts per past session from daily bars (one extra session for prior-day values)."""
    bars = history.load_bars(data_dir, sessions)
    if bars.empty:
        return pd.DataFrame(columns=["session_date", "breadth_n", "up4", "mb_up", "down4"])
    bars = bars[bars["ticker"].isin(tickers)].sort_values(["ticker", "session_date"])
    by_ticker = bars.groupby("ticker")
    bars = bars.assign(
        prev_close=by_ticker["close"].shift(1),
        prev_volume=by_ticker["volume"].shift(1),
        prev_session=by_ticker["session_date"].shift(1),
    )
    previous = {s: p for p, s in zip(sessions, sessions[1:], strict=False)}
    # Only use a prior bar that really is the previous session (no gaps).
    bars = bars[bars["prev_session"] == bars["session_date"].map(previous)]
    with np.errstate(divide="ignore", invalid="ignore"):
        bars = bars.assign(
            chg_pct=(bars["close"] / bars["prev_close"] - 1) * 100,
            close_loc=(bars["close"] - bars["low"]) / (bars["high"] - bars["low"]),
        )
    rows = [
        {"session_date": session, **day_counts(group, cfg)}
        for session, group in bars.groupby("session_date")
    ]
    return pd.DataFrame(rows)


def ratio(counts: pd.DataFrame, up_column: str, days: int) -> float:
    """Sum of up counts / sum of down counts over the last `days` sessions; NaN if short."""
    last = counts.tail(days)
    if len(last) < days or last["down4"].sum() == 0:
        return float("nan")
    return float(last[up_column].sum() / last["down4"].sum())


def qqq_trend(close: float, sma10: float, sma20: float, sma50: float, sma20_before: float):
    """§6.5 step 1, in order: up, down, else sideways. None when it can't be decided."""
    if close > sma20 and sma10 > sma20:
        return "up"
    if close < sma50:
        if np.isnan(sma20_before):
            return None  # "down" needs SMA20 vs 5 sessions ago
        return "down" if sma20 < sma20_before else "sideways"
    return "sideways"


def breadth_state(r10: float, r5: float, up25: int, down25: int, ml: Mapping[str, Any]):
    """§6.5 step 2. None while the 10-day ratio isn't available."""
    if np.isnan(r10):
        return None
    if r10 >= ml["strong_ratio10_min"] and up25 > down25:
        return "strong"
    if r10 < ml["weak_ratio10_below"] and down25 > up25:
        thrust = not np.isnan(r5) and r5 > ml["thrust_ratio5_gt"]
        return "neutral" if thrust else "weak"
    return "neutral"


def light(trend, state, count, thresholds: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """§6.5 step 4, first matching row wins. Returns (light, missing inputs)."""
    missing = [
        name
        for name, value in (("QQQ trend", trend), ("breadth", state), ("scan count", count))
        if value is None
    ]
    if missing:
        return None, missing
    if (trend == "down" and state == "weak") or count < thresholds["stop_count_below"]:
        return "STOP", []
    if trend == "down" or state == "weak" or count < thresholds["red_count_below"]:
        return "RED", []
    if trend == "up" and state != "weak" and count >= thresholds["green_count_min"]:
        return "GREEN", []
    return "YELLOW", []


def scan_count(df: pd.DataFrame, cfg: Config) -> int:
    """§6.5 step 3: the Sunday screen (country, price, average volume, quarter, SMA20)."""
    sc = cfg.market_light["scan_count"]
    avg_volume = df[canonical(sc["avg_volume_field"])]
    hit = (
        (df["country"] == COUNTRY_NAMES.get(sc["country"], sc["country"]))
        & (df["close"] > sc["price_gt"])
        & (avg_volume > sc["avg_volume_gt"])
        & (df["perf_3m_tv"] >= sc["perf_3m_min_pct"])
        & (df["close"] > df[f"ma{sc['above_sma']}"])
    )
    return int(hit.fillna(False).sum())


def latest_scan_count(data_dir: Path, session: dt.date) -> tuple[int | None, dt.date | None]:
    """The most recent Sunday scan count on or before `session`."""
    files = sorted((Path(data_dir) / "data" / "market_light_count").glob("*/*.parquet"))
    best, best_day = None, None
    for f in files:
        day = dt.date.fromisoformat(f.stem.split("_")[0])
        if day <= session:
            best, best_day = f, day
    if best is None:
        return None, None
    row = pd.read_parquet(best).iloc[0]
    return int(row["scan_count"]), best_day


def stored_qqq_sma20(data_dir: Path, session: dt.date) -> float:
    name = f"{session.isoformat()}_eod.parquet"
    path = Path(data_dir) / "data" / "breadth" / str(session.year) / name
    if not path.exists():
        return float("nan")
    return float(pd.read_parquet(path, columns=["qqq_sma20"]).iloc[0]["qqq_sma20"])


def breadth_row(
    uni: pd.DataFrame,
    qqq: Mapping[str, float],
    cfg: Config,
    data_dir: Path,
    session: dt.date,
) -> dict[str, Any]:
    """Everything for today's breadth.parquet row and the two push lines."""
    breadth, ml = cfg.scans["breadth"], cfg.market_light
    windows = list(breadth["ratio_windows"])
    sessions = clock.sessions_back(cfg.schedule, session, max(windows) + 1)
    past = past_counts(data_dir, cfg, sessions[:-1], set(uni["ticker"]))
    today = {"session_date": session, **day_counts(uni, cfg)}
    counts = pd.concat([past, pd.DataFrame([today])], ignore_index=True)
    counts = counts[counts["session_date"].isin(sessions[1:])].sort_values("session_date")
    up_col = "up4" if breadth["up_count_rule"] == "stockbee_4pct" else "mb_up"
    ratios = {d: ratio(counts, up_col, d) for d in windows}

    universe = uni[in_breadth_universe(uni, breadth)]
    q = breadth["quarter_move_pct"]
    up25 = int((universe["ret_63"] >= q).sum())
    down25 = int((universe["ret_63"] <= -q).sum())
    above = {
        w: float((universe["close"] > universe[f"ma{w}"]).mean() * 100) if len(universe) else np.nan
        for w in breadth["ma_windows"]
    }

    lookback = ml["qqq"]["slope_lookback"]
    before = clock.sessions_back(cfg.schedule, session, lookback + 1)[0]
    sma20_before = stored_qqq_sma20(data_dir, before)
    trend = qqq_trend(qqq["close"], qqq["sma10"], qqq["sma20"], qqq["sma50"], sma20_before)
    state = breadth_state(ratios[10], ratios[5], up25, down25, ml["breadth"])
    count, count_date = latest_scan_count(data_dir, session)
    count_basis = f"sunday {count_date}" if count is not None else None
    if count is None:  # before the first Sunday run: today's screen, flagged as such
        count, count_basis = scan_count(uni, cfg), "eod-bootstrap"
    the_light, missing = light(trend, state, count, ml["thresholds"])
    return {
        "session_date": session,
        **{k: today[k] for k in ("breadth_n", "up4", "mb_up", "down4")},
        "up_count_rule": breadth["up_count_rule"],
        **{f"ratio_{d}d": ratios[d] for d in windows},
        "ratio_days_available": int(len(counts)),
        "up25q": up25,
        "down25q": down25,
        "quarter_basis": "tv:Perf.3M",
        **{f"pct_above_ma{w}": above[w] for w in breadth["ma_windows"]},
        "qqq_close": qqq["close"],
        "qqq_sma10": qqq["sma10"],
        "qqq_sma20": qqq["sma20"],
        "qqq_sma50": qqq["sma50"],
        "qqq_sma20_5ago": sma20_before,
        "qqq_trend": trend,
        "breadth_state": state,
        "scan_count": count,
        "scan_count_basis": count_basis,
        "light": the_light,
        "light_missing": ", ".join(missing),
    }


def push_lines(row: Mapping[str, Any]) -> list[str]:
    def r(x):
        return "n/a" if x is None or np.isnan(x) else f"{x:.2f}"

    up = row["up4"] if row["up_count_rule"] == "stockbee_4pct" else row["mb_up"]
    above = "  ".join(
        f">MA{k[len('pct_above_ma') :]} {v:.0f}%"
        for k, v in row.items()
        if k.startswith("pct_above_ma")
    )
    breadth_line = (
        f"Breadth: up {up} / down {row['down4']}  5d {r(row['ratio_5d'])}  "
        f"10d {r(row['ratio_10d'])}  Q +{row['up25q']} / -{row['down25q']}  {above}"
    )
    if row["light"]:
        light_line = (
            f"Market Light: {row['light']}  (QQQ {row['qqq_trend']}, breadth "
            f"{row['breadth_state']}, scan count {row['scan_count']})"
        )
    else:
        light_line = f"Market Light: n/a (waiting for {row['light_missing']})"
    return [breadth_line, light_line]
