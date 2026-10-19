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
    monitor = market_monitor(universe, breadth)

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
        **monitor,
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


def market_monitor(universe: pd.DataFrame, breadth: Mapping[str, Any]) -> dict[str, Any]:
    """The rest of Stockbee's Market Monitor: big moves in a month and in 34 sessions.

    The month uses `ret_22` (exact once history exists, TradingView's Perf.1M before). The
    34-session move exists only with daily history (`hist_ret_34`); `mid_rows` says how many
    stocks had it, so a count from a thin history is never mistaken for the market.
    """
    nan = pd.Series(np.nan, index=universe.index)
    month, mid = universe.get("ret_22", nan), universe.get("hist_ret_34", nan)
    m, big, mid_pct = (
        breadth["month_move_pct"],
        breadth["month_big_move_pct"],
        breadth["mid_move_pct"],
    )
    return {
        "up25m": int((month >= m).sum()),
        "down25m": int((month <= -m).sum()),
        "up50m": int((month >= big).sum()),
        "down50m": int((month <= -big).sum()),
        "up13_34d": int((mid >= mid_pct).sum()),
        "down13_34d": int((mid <= -mid_pct).sum()),
        "mid_rows": int(mid.notna().sum()),
    }


LIGHT_ICONS = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "STOP": "⛔"}
INDEX_MAS = (10, 20, 50, 200)


def _ratio(x: Any) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{x:.2f}"


def monitor_lines(row: Mapping[str, Any]) -> list[str]:
    """Stockbee's quarter, month and 34-day counts (empty for rows stored before 19 Oct)."""
    quarter = f"Qtr 25%: ▲{row['up25q']} ▼{row['down25q']}"
    if row.get("up25m") is None or pd.isna(row.get("up25m")):
        return [quarter]
    covered = row.get("mid_rows", 0) >= 0.5 * max(row.get("breadth_n", 0), 1)
    mid = f"▲{row['up13_34d']} ▼{row['down13_34d']}" if covered else "n/a"
    return [
        f"{quarter} · Mo 25%: ▲{row['up25m']} ▼{row['down25m']}",
        f"Mo 50%: ▲{row['up50m']} ▼{row['down50m']} · 34d 13%: {mid}",
    ]


def index_fields(quotes: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
    """Flat breadth-row columns for SPY and VIX (whatever was fetched)."""
    out: dict[str, Any] = {}
    for name, q in quotes.items():
        out[f"{name}_close"] = q["close"]
        out[f"{name}_chg_pct"] = q["chg_pct"]
        out[f"{name}_pm_change_pct"] = q["pm_change_pct"]
        for w in INDEX_MAS:
            out[f"{name}_sma{w}"] = q[f"sma{w}"]
    return out


def _ma_side(row: Mapping[str, Any], name: str) -> str:
    """`above MA200 · below 10, 20, 50`."""
    close = row[f"{name}_close"]
    above = [str(w) for w in INDEX_MAS if close > row.get(f"{name}_sma{w}", np.inf)]
    below = [str(w) for w in INDEX_MAS if close <= row.get(f"{name}_sma{w}", -np.inf)]
    parts = ([f"above MA{', '.join(above)}"] if above else []) + (
        [f"below {', '.join(below)}"] if below else []
    )
    return " · ".join(parts)


def index_lines(row: Mapping[str, Any], premarket: bool = False) -> list[str]:
    """`SPY 767.59 +0.6% · VIX 18.6 -7.1%`, then (at the close) SPY against its MAs."""
    parts, spy = [], row.get("spy_close")
    if spy is not None and not pd.isna(spy):
        change = row["spy_pm_change_pct"] if premarket else row["spy_chg_pct"]
        label = "SPY pre-market" if premarket else f"SPY {spy:.2f}"
        parts.append(label + ("" if pd.isna(change) else f" {change:+.1f}%"))
    vix = row.get("vix_close")
    if vix is not None and not pd.isna(vix):
        change = row.get("vix_chg_pct")
        parts.append(f"VIX {vix:.1f}" + ("" if pd.isna(change) else f" {change:+.1f}%"))
    lines = [" · ".join(parts)] if parts else []
    if not premarket and spy is not None and not pd.isna(spy):
        lines.append(f"SPY {_ma_side(row, 'spy')}")
    return lines


def light_lines(row: Mapping[str, Any], suffix: str = "") -> list[str]:
    """`🟡 Market Light YELLOW` and its three inputs, or why it's missing."""
    if not row.get("light"):
        return [f"⚪ Market Light n/a{suffix} (needs {row.get('light_missing')})"]
    icon = LIGHT_ICONS.get(row["light"], "")
    return [
        f"{icon} Market Light {row['light']}{suffix}".strip(),
        f"QQQ {row['qqq_trend']} · breadth {row['breadth_state']} · count {row['scan_count']}",
    ]


def breadth_lines(row: Mapping[str, Any]) -> list[str]:
    up = row["up4"] if row["up_count_rule"] == "stockbee_4pct" else row["mb_up"]
    above = " · ".join(
        f"MA{k[len('pct_above_ma') :]} {v:.0f}%"
        for k, v in row.items()
        if k.startswith("pct_above_ma")
    )
    ratios = f"5d {_ratio(row['ratio_5d'])} · 10d {_ratio(row['ratio_10d'])}"
    return [
        f"4%: ▲{up} ▼{row['down4']} · {ratios}",
        *monitor_lines(row),
        f"Above {above}",
    ]


def push_lines(row: Mapping[str, Any]) -> list[str]:
    """EOD market header (push, report, dashboard): light, breadth, SPY and VIX."""
    return [*light_lines(row), *breadth_lines(row), *index_lines(row)]


# --- pre-market (Emil, 19 Oct 2026: breadth also runs pre-market; SPEC §6.1)


def latest_eod_row(data_dir: Path, before: dt.date) -> dict[str, Any] | None:
    """The newest canonical EOD breadth row for a session before `before`."""
    best = None
    for f in (Path(data_dir) / "data" / "breadth").glob("*/*_eod.parquet"):
        day = dt.date.fromisoformat(f.stem.split("_")[0])
        if day < before and (best is None or day > best[0]):
            best = (day, f)
    if best is None:
        return None
    return pd.read_parquet(best[1]).iloc[0].to_dict()


def premarket_row(
    uni: pd.DataFrame,
    qqq: Mapping[str, float],
    cfg: Config,
    session: dt.date,
    last: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Pre-market movers in the breadth universe (prior close and prior-day volume floors),
    QQQ's pre-market change, and the light set at the last close."""
    universe = uni[in_breadth_universe(uni, cfg.scans["breadth"])]
    up, down = cfg.scans["mb_up"], cfg.scans["mb_down"]
    last = last or {}
    last_session = last.get("session_date")
    return {
        "session_date": session,
        "pm_breadth_n": len(universe),
        "pm_up4": int((universe["pm_change_pct"] >= up["chg_min_pct"]).sum()),
        "pm_down4": int((universe["pm_change_pct"] <= down["chg_max_pct"]).sum()),
        "qqq_pm_change_pct": qqq.get("pm_change_pct", float("nan")),
        "last_eod_session": pd.Timestamp(last_session).date() if last_session is not None else None,
        "light": last.get("light"),
        "light_missing": last.get("light_missing", "an EOD run"),
        "qqq_trend": last.get("qqq_trend"),
        "breadth_state": last.get("breadth_state"),
        "scan_count": last.get("scan_count"),
    }


def premarket_lines(row: Mapping[str, Any], last: Mapping[str, Any] | None) -> list[str]:
    """Light for today's orders, last close's breadth, and the pre-market movers."""
    day = row["last_eod_session"]
    when = f" (from the {day:%m-%d} close)" if day is not None and row["light"] else ""
    lines = light_lines(row, suffix=when)
    if last:
        lines.append(f"Last close {breadth_lines(last)[0]}")
    qqq = row["qqq_pm_change_pct"]
    qqq_text = "" if qqq is None or np.isnan(qqq) else f" · QQQ {qqq:+.1f}%"
    lines.append(f"Pre-market 4%: ▲{row['pm_up4']} ▼{row['pm_down4']}{qqq_text}")
    return [*lines, *index_lines(row, premarket=True)]
