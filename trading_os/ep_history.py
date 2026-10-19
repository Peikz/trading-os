"""EP history study (Emil, 19 Oct 2026): every EP in the Massive bars, with what was known that
day and what happened after.

One row per (ticker, session) where the EP-Day rule (§6.2) or the EP9M rule fired, so the
EPStudyDatabase can be filled with thousands of historical examples ("Found Forward? = No").
Point-in-time: every feature uses bars up to the signal session only; outcomes use the bars
after it. Facts only: the five criteria are yes/no columns, never a grade.

- Entry and stop follow the live alert (`sizing.plan` for EP-Day): entry at the gap-day close,
  stop at the day's low within the EP ADR bounds.
- Outcomes per horizon (1, 5, 21, 63, 126, 252 sessions): return, best and worst point, stop
  hit, and R (a stop hit is an exit at the stop, or at the open if it gapped through). Plus a
  trailing exit at the first close under the 10-day and the 20-day MA. A horizon that hasn't
  happened yet stays empty, never zero.
- Market that day: Stockbee 4 % counts and ratios, the 25 %-in-a-quarter counts, QQQ's trend
  and the breadth state (§6.5); the Sunday scan count has no history, so no Market Light.
- Fundamentals (`add_fundamentals`): TradingView keeps 8 years of quarterly EPS and revenue
  but no past report dates, so the quarter is matched by the company's reporting rhythm and
  marked inferred; today's float only. Stocks delisted since have none.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os import breadth, sizing
from trading_os import history_metrics as hm
from trading_os.audit import ordinary_ticker
from trading_os.metrics import NEW_YORK, yoy_growth

HORIZONS = (1, 5, 21, 63, 126, 252)  # next day, week, month, quarter, half year, year
TRAILS = (10, 20)  # exit at the first close under this MA
QUARTER_DAYS = 365.25 / 4


def market_context(g: dict[str, np.ndarray], tickers: pd.Index, cfg) -> pd.DataFrame:
    """Per session: the Stockbee breadth line and QQQ's trend, from the bars alone."""
    o, h, lo, c, v = (g[f] for f in hm.PRICE_FIELDS)
    rules, ml = cfg.scans["breadth"], cfg.market_light
    up, down = cfg.scans["mb_up"], cfg.scans["mb_down"]
    with np.errstate(divide="ignore", invalid="ignore"):
        chg = (c / hm.shift(c, 1) - 1) * 100
        louder = v > hm.shift(v, 1)
        inside = (c >= rules["universe_price_min"]) & (v >= rules["universe_volume_min"])
        ret63 = (c / hm.shift(c, 63) - 1) * 100
        ma50 = hm.rolling_mean(c, 50)
    up4 = (inside & louder & (chg >= up["chg_min_pct"])).sum(axis=1)
    down4 = (inside & louder & (chg <= down["chg_max_pct"])).sum(axis=1)
    out = pd.DataFrame({"mkt_up4": up4, "mkt_down4": down4})
    for days in rules["ratio_windows"]:
        ups = out["mkt_up4"].rolling(days).sum()
        downs = out["mkt_down4"].rolling(days).sum()
        out[f"mkt_ratio_{days}d"] = ups / downs.where(downs > 0)
    q = rules["quarter_move_pct"]
    out["mkt_up25q"] = (inside & (ret63 >= q)).sum(axis=1)
    out["mkt_down25q"] = (inside & (ret63 <= -q)).sum(axis=1)
    with np.errstate(invalid="ignore"):
        out["mkt_pct_above_ma50"] = (inside & (c > ma50)).sum(axis=1) / inside.sum(axis=1) * 100
    symbol = ml["qqq"]["symbol"].split(":")[-1]
    trend = [None] * len(out)
    if symbol in tickers:
        q_close = c[:, tickers.get_loc(symbol)]
        smas = {w: hm.rolling_mean(q_close[:, None], w)[:, 0] for w in (10, 20, 50)}
        before = hm.shift(smas[20][:, None], ml["qqq"]["slope_lookback"])[:, 0]
        for i in range(len(out)):
            if not np.isnan(smas[50][i]):
                trend[i] = breadth.qqq_trend(
                    q_close[i], smas[10][i], smas[20][i], smas[50][i], before[i]
                )
    out["mkt_qqq_trend"] = trend
    out["mkt_breadth_state"] = [
        breadth.breadth_state(r10, r5, int(u), int(d), ml["breadth"])
        for r10, r5, u, d in zip(
            out["mkt_ratio_10d"].fillna(np.nan),
            out["mkt_ratio_5d"].fillna(np.nan),
            out["mkt_up25q"],
            out["mkt_down25q"],
            strict=True,
        )
    ]
    return out


def months_sideways(close: np.ndarray, t: int, band_pct: float) -> float:
    """Months (21 sessions) before the gap with every close within ±band of the pre-gap close."""
    if t < 1 or np.isnan(close[t - 1]):
        return np.nan
    ref, k = close[t - 1], 0
    while t - 2 - k >= 0:
        past = close[t - 2 - k]
        if np.isnan(past) or abs(past / ref - 1) * 100 > band_pct:
            break
        k += 1
    return (k + 1) / 21


def _first(mask: np.ndarray) -> int | None:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if len(idx) else None


def _stop_fill(o: np.ndarray, d: int, stop: float) -> float:
    """A stop is filled at the stop, or at the open when the day gapped through it."""
    return min(o[d], stop) if not np.isnan(o[d]) else stop


def outcomes(
    o: np.ndarray,
    h: np.ndarray,
    lo: np.ndarray,
    c: np.ndarray,
    mas: Mapping[int, np.ndarray],
    t: int,
    entry: float,
    stop: float,
) -> dict[str, Any]:
    """Every horizon and trail for one EP (one ticker's columns, signal at row `t`).

    Entry at the close of `t`. A missing bar inside a window (halt, delisting) leaves that
    outcome unknown rather than guessing an exit.
    """
    row: dict[str, Any] = {}
    n, risk = len(c), entry - stop
    for horizon in HORIZONS:
        end = t + horizon
        keys = [f"{k}_{horizon}d" for k in ("ret", "max_gain", "max_dd", "r", "stop_hit")]
        seg = slice(t + 1, end + 1)
        if end >= n or np.isnan(c[end]) or np.isnan(lo[seg]).any():
            row.update(dict.fromkeys(keys, np.nan))
            continue
        hit = _first(lo[seg] <= stop) if risk > 0 else None
        if risk > 0:
            exit_price = _stop_fill(o, t + 1 + hit, stop) if hit is not None else c[end]
            r = (exit_price - entry) / risk
        else:
            r = np.nan
        row.update(
            {
                f"ret_{horizon}d": (c[end] / entry - 1) * 100,
                f"max_gain_{horizon}d": (h[seg].max() / entry - 1) * 100,
                f"max_dd_{horizon}d": (lo[seg].min() / entry - 1) * 100,
                f"r_{horizon}d": r,
                f"stop_hit_{horizon}d": hit is not None,
            }
        )
    last = min(n - 1, t + max(HORIZONS))
    seg = slice(t + 1, last + 1)
    for window in TRAILS:
        keys = {f"r_trail_ma{window}": np.nan, f"days_trail_ma{window}": np.nan}
        keys[f"open_trail_ma{window}"] = False
        if risk <= 0 or last == t:
            row |= keys | {f"open_trail_ma{window}": last == t}
            continue
        missing, stopped = np.isnan(lo[seg]), lo[seg] <= stop
        with np.errstate(invalid="ignore"):
            below = c[seg] < mas[window][seg]
        first = _first(missing | stopped | below)
        if first is None:  # still riding at the end of the data (or of the year)
            row |= {
                f"r_trail_ma{window}": (c[last] - entry) / risk,
                f"days_trail_ma{window}": float(last - t),
                f"open_trail_ma{window}": last == n - 1,
            }
            continue
        d = t + 1 + first
        if missing[first]:
            row |= keys
            continue
        exit_price = _stop_fill(o, d, stop) if stopped[first] else c[d]
        row |= {
            f"r_trail_ma{window}": (exit_price - entry) / risk,
            f"days_trail_ma{window}": float(d - t),
            f"open_trail_ma{window}": False,
        }
    return row


def find(bars: pd.DataFrame, sessions: list, cfg) -> pd.DataFrame:
    """All EP-Day and EP9M rule hits in `bars` with features and outcomes."""
    conf, ep, ep9 = cfg.ep_history, cfg.scans["ep_day"], cfg.scans["ep9m"]
    alert, rules = cfg.universe["alert"], cfg.sizing
    stocks = bars[bars["ticker"].map(ordinary_ticker)]
    g, tickers = hm.grids(stocks, sessions)
    o, h, lo, c, v = (g[f] for f in hm.PRICE_FIELDS)
    with np.errstate(divide="ignore", invalid="ignore"):
        pc = hm.shift(c, 1)
        gap, chg = (o / pc - 1) * 100, (c / pc - 1) * 100
        rvol = v / hm.rolling_mean(hm.shift(v, 1), hm.RVOL_DAYS)
        is_ep = (
            (gap >= ep["gap_min_pct"])
            & (rvol >= ep["rvol_min"])
            & (v >= ep["volume_min"])
            & (c >= ep["price_min"])
        )
        is_ep9m = (v >= ep9["volume_min"]) & (chg >= ep9["chg_min_pct"])
    market = market_context(g, tickers, cfg).to_dict("records")
    rows: list[dict[str, Any]] = []
    for col in np.flatnonzero((is_ep | is_ep9m).any(axis=0)):
        oc, hc, lc, cc, vc = o[:, col], h[:, col], lo[:, col], c[:, col], v[:, col]
        with np.errstate(divide="ignore", invalid="ignore"):
            adr_pct = hm.rolling_mean(((hc / lc - 1) * 100)[:, None], hm.ADR_DAYS)[:, 0]
            avg20 = hm.rolling_mean(hm.shift(vc[:, None], 1), hm.AVG_DAYS)[:, 0]
            ma200 = hm.rolling_mean(cc[:, None], 200)[:, 0]
            prior_high = hm.shift(hc[:, None], 1)
            high_6m = hm.rolling_extreme(prior_high, 126, "max")[:, 0]
            high_52w = hm.rolling_extreme(prior_high, 252, "max")[:, 0]
            mas = {w: hm.rolling_mean(cc[:, None], w)[:, 0] for w in TRAILS}
        for t in np.flatnonzero(is_ep[:, col] | is_ep9m[:, col]):
            entry, prev = cc[t], cc[t - 1] if t else np.nan
            adr_usd = adr_pct[t] * entry / 100
            plan = {"close": entry, "low": lc[t], "adr20_usd": adr_usd}
            _, stop, basis = sizing.plan(plan, "ep_day", rules)
            risk = entry - stop
            before = {
                f"ret_before_{d}d": (prev / cc[t - 1 - d] - 1) * 100 if t - 1 - d >= 0 else np.nan
                for d in (21, 63, 126)
            }
            dollar = entry * vc[t]
            row = {
                "session_date": sessions[t],
                "ticker": tickers[col],
                "variant": "ep_day" if is_ep[t, col] else "ep9m",
                "is_ep_day": bool(is_ep[t, col]),
                "is_ep9m": bool(is_ep9m[t, col]),
                "tier": "alert"
                if entry >= alert["price_min"]
                and avg20[t] >= alert["avg_volume_20d_min"]
                and dollar >= alert["signal_dollar_volume_min"]
                else "log",
                "open": oc[t],
                "high": hc[t],
                "low": lc[t],
                "close": entry,
                "prev_close": prev,
                "volume": vc[t],
                "gap_pct": gap[t, col],
                "chg_pct": chg[t, col],
                "rvol50": rvol[t, col],
                "dollar_volume": dollar,
                "avg_volume_20d": avg20[t],
                "close_loc": (entry - lc[t]) / (hc[t] - lc[t]) if hc[t] > lc[t] else np.nan,
                "adr20_pct": adr_pct[t],
                **before,
                "months_sideways": months_sideways(cc, t, conf["neglect_band_pct"]),
                "pct_from_6m_high": (prev / high_6m[t] - 1) * 100,
                "gap_clears_6m_high": bool(oc[t] > high_6m[t])
                if high_6m[t] == high_6m[t]
                else None,
                "pct_from_52w_high": (prev / high_52w[t] - 1) * 100,
                "above_ma200": bool(entry > ma200[t]) if not np.isnan(ma200[t]) else None,
                "plan_entry": entry,
                "plan_stop": stop,
                "plan_stop_basis": basis,
                "stop_dist": risk,
                "stop_adr": risk / adr_usd if adr_usd > 0 else np.nan,
                # The sheet's C5 is about the low-of-day stop, before the live 1-ADR cap.
                "lod_stop_adr": (entry - lc[t]) / adr_usd if adr_usd > 0 else np.nan,
                **market[t],
                **outcomes(oc, hc, lc, cc, mas, t, entry, stop),
            }
            rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return add_criteria(out, cfg).sort_values(["session_date", "ticker"]).reset_index(drop=True)


def add_criteria(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """The EPStudyDatabase's five hard criteria as yes/no facts (the sheet grades, not code).
    C3 waits for `add_fundamentals`."""
    conf = cfg.ep_history
    out = df.copy()
    out["c1_gap"] = out["gap_pct"] >= conf["c1_gap_min_pct"]
    out["c2_volume"] = out["rvol50"] >= conf["c2_rvol_min"]
    out["c4_neglect"] = out["months_sideways"] >= conf["c4_neglect_min_months"]
    out["c5_stop"] = out["lod_stop_adr"] <= conf["c5_stop_adr_max"]
    return out


def infer_quarter(event: pd.Timestamp, last_report: pd.Timestamp, match_days: float):
    """(quarters back from the latest report, earnings on the event day?) by the reporting
    rhythm: a report every quarter, the latest on `last_report`."""
    offset = (last_report - event).days / QUARTER_DAYS
    if offset < 0:
        return 0, abs(offset * QUARTER_DAYS) <= match_days
    nearest = round(offset)
    if abs(offset - nearest) * QUARTER_DAYS <= match_days:
        return nearest, True  # the report that came out around the gap is known at the close
    return math.ceil(offset), False


DETAIL_FIELDS = {
    "total_revenue_fq_h": "rev_hist",
    "earnings_per_share_diluted_fq_h": "eps_hist",
    "earnings_release_date": "earnings_date_last",
    "float_shares_outstanding": "float_shares",
}


def fetch_details(tv_tickers: list[str], fetch, chunk: int = 400) -> pd.DataFrame:
    """TradingView histories and last report date for still-listed stocks, `chunk` symbols a
    request (a handful of requests for a few thousand names). `fetch` is tv.fetch_details."""
    parts = [
        fetch(tv_tickers[i : i + chunk], list(DETAIL_FIELDS))
        for i in range(0, len(tv_tickers), chunk)
    ]
    if not parts:
        return pd.DataFrame(columns=list(DETAIL_FIELDS.values()))
    out = pd.concat(parts).rename(columns=DETAIL_FIELDS)
    out["earnings_date_last"] = pd.to_datetime(out["earnings_date_last"], unit="s", utc=True)
    return out


def add_fundamentals(df: pd.DataFrame, details: pd.DataFrame, cfg) -> pd.DataFrame:
    """EPS and sales growth as known on each EP's day (inferred quarter), today's float, and
    C3. `details` is indexed by ticker with TradingView's histories and last report date."""
    conf = cfg.ep_history
    out = df.copy()
    columns = {
        "earnings_inferred": None,
        "eps_growth_yoy": np.nan,
        "sales_growth_yoy": np.nan,
        "float_m_now": np.nan,
    }
    for name, default in columns.items():
        out[name] = default
    for i, row in out.iterrows():
        if row["ticker"] not in details.index:
            continue
        d = details.loc[row["ticker"]]
        floats = d.get("float_shares")
        out.at[i, "float_m_now"] = (
            floats / 1e6 if floats is not None and floats == floats else np.nan
        )
        last = d.get("earnings_date_last")
        if last is None or pd.isna(last):
            continue
        last_day = pd.Timestamp(pd.Timestamp(last).tz_convert(NEW_YORK).date())
        k, on_day = infer_quarter(pd.Timestamp(row["session_date"]), last_day, conf["match_days"])
        out.at[i, "earnings_inferred"] = on_day
        out.at[i, "eps_growth_yoy"] = yoy_growth(d.get("eps_hist"), k, abs_base=True)
        out.at[i, "sales_growth_yoy"] = yoy_growth(d.get("rev_hist"), k, abs_base=False)
    best = out[["eps_growth_yoy", "sales_growth_yoy"]].max(axis=1)
    out["c3_growth"] = (best >= conf["c3_growth_min_pct"]).where(best.notna())
    return out


def summary(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Per horizon: matured count, win rate, median return and mean R (optionally per group)."""
    groups = df.groupby(by, dropna=False) if by else [("all", df)]
    rows = []
    for key, part in groups:
        for horizon in HORIZONS:
            ret, r = part[f"ret_{horizon}d"], part[f"r_{horizon}d"]
            matured = ret.notna()
            rows.append(
                {
                    "group": key,
                    "horizon_d": horizon,
                    "n": int(matured.sum()),
                    "win_rate_pct": float((ret[matured] > 0).mean() * 100)
                    if matured.any()
                    else np.nan,
                    "median_ret_pct": float(ret[matured].median()) if matured.any() else np.nan,
                    "mean_r": float(r[matured].mean()) if matured.any() else np.nan,
                    "stop_hit_pct": float(part.loc[matured, f"stop_hit_{horizon}d"].mean() * 100)
                    if matured.any()
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


# The EPStudyDatabase "EP Log" input columns, in the sheet's order (A-Q, then AN), and where
# each comes from. Percent columns are fractions so the sheet's % format shows them right.
SHEET_COLUMNS: list[tuple[str, str | None, float]] = [
    ("Date Found", "session_date", 1),
    ("Ticker", "ticker", 1),
    ("Variant", "variant_label", 1),
    ("Found Forward?", "found_forward", 1),
    ("Catalyst — the surprise in one sentence", None, 1),
    ("Gap %", "gap_pct", 0.01),
    ("Vol vs 50d ADV (x)", "rvol50", 1),
    ("EPS Growth YoY", "eps_growth_yoy", 0.01),
    ("Sales Growth YoY", "sales_growth_yoy", 0.01),
    ("Months Sideways Before", "months_sideways", 1),
    ("Float (M shares)", "float_m_now", 1),
    ("Price ($)", "close", 1),
    ("ADR %", "adr20_pct", 0.01),
    ("Planned Entry ($)", "plan_entry", 1),
    ("Planned Stop ($)", "plan_stop", 1),
    ("Stop Dist ($)", "stop_dist", 1),
    ("Stop ÷ ADR", "stop_adr", 1),
    ("If Not Traded: 20-day % Move", "ret_21d", 0.01),
]
VARIANT_LABELS = {"ep_day": "Day-1 Classic", "ep9m": "EP9M"}


def sheet_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The EP Log's input columns first (so the sheet's own formulas grade), then every
    extra this study has, unchanged."""
    out = df.assign(
        variant_label=df["variant"].map(VARIANT_LABELS),
        found_forward="No (history)",
    )
    sheet = pd.DataFrame(index=out.index)
    for header, column, scale in SHEET_COLUMNS:
        sheet[header] = (
            out[column] * scale if column and scale != 1 else (out[column] if column else "")
        )
    extras = out.drop(columns=["variant_label", "found_forward"])
    return pd.concat([sheet, extras.add_prefix("x_")], axis=1)


def label_counts(df: pd.DataFrame) -> Mapping[str, int]:
    """Counts for the public log (no tickers)."""
    return {
        "events": len(df),
        "ep_day": int(df["is_ep_day"].sum()) if len(df) else 0,
        "ep9m": int(df["is_ep9m"].sum()) if len(df) else 0,
        "alert_tier": int((df["tier"] == "alert").sum()) if len(df) else 0,
    }


PERCENT_HEADERS = {h for h, _, scale in SHEET_COLUMNS if scale == 0.01}


def latest_universe(data_dir) -> pd.DataFrame:
    """ticker -> tv_ticker from the newest universe snapshot (scheduled or manual run)."""
    from pathlib import Path

    root = Path(data_dir) / "data"
    files = [*root.glob("universe/*/*.parquet"), *root.glob("manual/*/universe.parquet")]
    if not files:
        return pd.DataFrame(columns=["ticker", "tv_ticker"])
    newest = max(files, key=lambda f: f.stat().st_mtime)
    return pd.read_parquet(newest, columns=["ticker", "tv_ticker"]).drop_duplicates("ticker")


def write_sheet(df: pd.DataFrame, path) -> None:
    """The EP-Day events in the EP Log's column order, % columns formatted as percents."""
    sheet = sheet_frame(df[df["is_ep_day"]])
    sheet["Date Found"] = pd.to_datetime(sheet["Date Found"]).dt.date
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="EP history", index=False)
        ws = writer.sheets["EP history"]
        for col, header in enumerate(sheet.columns, start=1):
            if header in PERCENT_HEADERS:
                for cell in ws.iter_cols(min_col=col, max_col=col, min_row=2):
                    for c in cell:
                        c.number_format = "0.0%"
        ws.freeze_panes = "C2"
    tmp.rename(path)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import datetime as dt
    from pathlib import Path

    from trading_os import history, tv
    from trading_os.config import load_config
    from trading_os.logsafe import status
    from trading_os.store import PARQUET_OPTIONS

    parser = argparse.ArgumentParser(description="EP history study over the Massive bars")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--no-fundamentals", action="store_true", help="skip TradingView")
    args = parser.parse_args(argv)
    cfg = load_config()
    files = sorted((args.data_dir / "data" / "bars").rglob("*.parquet"))
    sessions = sorted({dt.date.fromisoformat(f.stem[:10]) for f in files})
    if len(sessions) < 60:
        status("EP history: not enough bars yet (run the Massive backfill first)")
        return 1
    asof = sessions[-1].isoformat()
    out_path = args.data_dir / "data" / "ep_history" / f"ep_history_{asof}.parquet"
    if out_path.exists():
        status(f"EP history: {out_path.name} already built")
        return 0
    df = find(history.load_bars(args.data_dir, sessions), sessions, cfg)
    status(f"EP history: {label_counts(df)} over {len(sessions)} sessions")
    if not args.no_fundamentals and len(df):
        listed = latest_universe(args.data_dir)
        listed = listed[listed["ticker"].isin(set(df["ticker"]))]
        details = fetch_details(listed["tv_ticker"].tolist(), tv.fetch_details)
        by_ticker = details.join(listed.set_index("tv_ticker")["ticker"]).set_index("ticker")
        df = add_fundamentals(df, by_ticker, cfg)
        status(f"EP history: fundamentals for {len(by_ticker)} still-listed stocks")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, **PARQUET_OPTIONS)
    write_sheet(df, args.data_dir / "data" / "exports" / f"ep_history_{asof}.xlsx")
    status(f"EP history: saved {out_path.name} and the EP Log export")
    return 0
