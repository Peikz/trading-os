"""Your own screens, TradingView style (Emil, 29 Oct 2026): filter the whole stock universe on
any of the fields below and keep the screens you like.

A screen is a list of filters (field, operator, value) plus a sort. It runs on the newest EOD
universe snapshot (about 4,000 US stocks with every metric the scans use), or on a live
TradingView fetch with the snapshot's history fields joined in. Saved screens are a small JSON
file in the private data repo (data/screens/my_screens.json). No grades and no buys: a screen
is a list to look at, not a tested setup.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

# field -> (label, kind, group). kind: num | pct | money | bool | text
FIELDS: dict[str, tuple[str, str, str]] = {
    "close": ("Price", "money", "Price & volume"),
    "chg_pct": ("Change %", "pct", "Price & volume"),
    "gap_pct": ("Gap %", "pct", "Price & volume"),
    "close_loc": ("Close in day's range (0-1)", "num", "Price & volume"),
    "volume": ("Volume", "num", "Price & volume"),
    "dollar_volume": ("$ volume today", "money", "Price & volume"),
    "avg_volume_20d": ("Avg volume 20d", "num", "Price & volume"),
    "avg_dollar_volume_20d": ("Avg $ volume 20d", "money", "Price & volume"),
    "rvol50": ("Relative volume (50d)", "num", "Price & volume"),
    "market_cap": ("Market cap", "money", "Size"),
    "float_shares": ("Float shares", "num", "Size"),
    "adr20_pct": ("ADR % (20d)", "pct", "Volatility"),
    "hist_range_nd": ("10-day range in ADRs (tightness)", "num", "Volatility"),
    "ret_22": ("Return 1M %", "pct", "Performance"),
    "ret_63": ("Return 3M %", "pct", "Performance"),
    "ret_126": ("Return 6M %", "pct", "Performance"),
    "rs_pct": ("RS percentile (1-99)", "num", "Performance"),
    "pct_from_52w_high": ("From 52-week high %", "pct", "Performance"),
    "hist_consec_up": ("Up days in a row", "num", "Performance"),
    "dist_ma10_adr": ("Distance to MA10 (ADRs)", "num", "Trend"),
    "above_ma10": ("Above MA10", "bool", "Trend"),
    "above_ma20": ("Above MA20", "bool", "Trend"),
    "above_ma50": ("Above MA50", "bool", "Trend"),
    "above_ma200": ("Above MA200", "bool", "Trend"),
    "hist_ma10_rising": ("MA10 rising", "bool", "Trend"),
    "hist_ma20_rising": ("MA20 rising", "bool", "Trend"),
    "hist_ma50_rising": ("MA50 rising", "bool", "Trend"),
    "hist_ma200_rising": ("MA200 rising", "bool", "Trend"),
    "earnings_in_sessions": ("Earnings in (sessions)", "num", "Fundamentals"),
    "rev_growth_q": ("Revenue growth q/q-y %", "pct", "Fundamentals"),
    "eps_growth_q": ("EPS growth q/q-y %", "pct", "Fundamentals"),
    "revenue_ttm": ("Revenue TTM", "money", "Fundamentals"),
    "pm_change_pct": ("Pre-market change %", "pct", "Extended hours"),
    "pm_volume": ("Pre-market volume", "num", "Extended hours"),
    "ah_change_pct": ("After-hours change %", "pct", "Extended hours"),
    "ah_volume": ("After-hours volume", "num", "Extended hours"),
    "sector": ("Sector", "text", "Group"),
    "industry": ("Industry", "text", "Group"),
    "industry_rank": ("Industry rank (1 = best)", "num", "Group"),
    "exchange": ("Exchange", "text", "Group"),
    "minervini_tt": ("Minervini trend template", "bool", "Setups"),
    "vcp_watch": ("VCP base", "bool", "Setups"),
    "ma_surf": ("MA-surf", "bool", "Setups"),
    "luk_flush": ("Luk flush", "bool", "Setups"),
    "on_bo_watch": ("On BO-Watch", "bool", "Setups"),
    "on_ep_watch": ("On EP-Watch", "bool", "Setups"),
}
OPS = {
    "num": [">=", "<=", "between"],
    "pct": [">=", "<=", "between"],
    "money": [">=", "<=", "between"],
    "bool": ["is yes", "is no"],
    "text": ["is one of", "is not one of"],
}
SHOWN = ["ticker", "close", "chg_pct", "rvol50", "adr20_pct", "avg_dollar_volume_20d",
         "market_cap", "rs_pct", "pct_from_52w_high", "industry"]  # fmt: skip
# The fields a live TradingView fetch brings (the rest come from the last EOD snapshot)
LIVE = {"close", "chg_pct", "gap_pct", "volume", "dollar_volume", "market_cap", "float_shares",
        "pm_change_pct", "pm_volume", "ah_change_pct", "ah_volume", "close_loc", "rvol50",
        "above_ma10", "above_ma20", "above_ma50", "above_ma200", "sector", "industry",
        "exchange", "earnings_in_sessions"}  # fmt: skip


def label(field: str) -> str:
    return FIELDS.get(field, (field,))[0]


def kind(field: str) -> str:
    return FIELDS[field][1] if field in FIELDS else "num"


def check(filters: Iterable[Mapping[str, Any]]) -> list[dict]:
    """The filters as plain dicts; unknown fields or operators raise ValueError."""
    out = []
    for f in filters:
        field, op = f.get("field"), f.get("op")
        if field not in FIELDS:
            raise ValueError(f"unknown field: {field}")
        if op not in OPS[kind(field)]:
            raise ValueError(f"{label(field)}: unknown operator {op}")
        out.append({"field": field, "op": op, "value": f.get("value")})
    return out


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def mask(df: pd.DataFrame, f: Mapping[str, Any]) -> pd.Series:
    """True where the stock passes one filter (a missing value never passes)."""
    field, op, value = f["field"], f["op"], f.get("value")
    if field not in df:
        return pd.Series(False, index=df.index)
    col = df[field]
    if op in ("is yes", "is no"):
        truth = col.astype("boolean").fillna(False).astype(bool)
        return truth if op == "is yes" else ~truth & col.notna()
    if op in ("is one of", "is not one of"):
        wanted = {str(v) for v in (value or [])}
        hit = col.astype(str).isin(wanted)
        return hit if op == "is one of" else ~hit & col.notna()
    x = pd.to_numeric(col, errors="coerce")
    if op == "between":
        lo, hi = (list(value) + [None, None])[:2] if value is not None else (None, None)
        lo, hi = _num(lo), _num(hi)
        out = x.notna()
        if lo is not None:
            out &= x >= lo
        if hi is not None:
            out &= x <= hi
        return out
    v = _num(value)
    if v is None:
        return x.notna()
    return (x >= v) if op == ">=" else (x <= v)


def run(
    df: pd.DataFrame, filters: Iterable[Mapping[str, Any]], sort: str | None = None,
    descending: bool = True,
) -> pd.DataFrame:  # fmt: skip
    """The stocks passing every filter, one row per ticker, sorted."""
    keep = pd.Series(True, index=df.index)
    for f in check(filters):
        keep &= mask(df, f)
    out = df[keep].drop_duplicates("ticker")
    if sort and sort in out:
        out = out.sort_values(sort, ascending=not descending, na_position="last")
    return out.reset_index(drop=True)


def describe(f: Mapping[str, Any]) -> str:
    """`ADR % (20d) >= 4` for the screen's summary line."""
    op, value = f["op"], f.get("value")
    if op in ("is yes", "is no"):
        return f"{label(f['field'])} {op[3:]}"
    if op in ("is one of", "is not one of"):
        return f"{label(f['field'])} {op} {', '.join(map(str, value or []))}"
    if op == "between":
        lo, hi = (list(value or []) + [None, None])[:2]
        return (
            f"{label(f['field'])} {lo if lo is not None else '…'}–{hi if hi is not None else '…'}"
        )
    return f"{label(f['field'])} {op} {value}"


# --- saved screens (data repo, user layer) ---------------------------------


def path(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "screens" / "my_screens.json"


def load(data_dir: Path) -> dict[str, dict]:
    p = path(data_dir)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save(data_dir: Path, name: str, filters: Iterable[Mapping[str, Any]], sort: str | None,
         descending: bool = True) -> None:  # fmt: skip
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the screen a name.")
    screens = load(data_dir)
    screens[name] = {"filters": check(filters), "sort": sort, "descending": descending}
    p = path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(screens, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def delete(data_dir: Path, name: str) -> None:
    screens = load(data_dir)
    if screens.pop(name, None) is not None:
        path(data_dir).write_text(json.dumps(screens, indent=1, sort_keys=True) + "\n",
                                  encoding="utf-8")  # fmt: skip


# A few starting points (Qullamaggie / Minervini style); saved screens are your own.
EXAMPLES: dict[str, dict] = {
    "Momentum leaders": {
        "filters": [
            {"field": "close", "op": ">=", "value": 5},
            {"field": "avg_dollar_volume_20d", "op": ">=", "value": 10_000_000},
            {"field": "adr20_pct", "op": ">=", "value": 4},
            {"field": "ret_63", "op": ">=", "value": 50},
            {"field": "above_ma20", "op": "is yes", "value": None},
        ],
        "sort": "ret_63",
        "descending": True,
    },
    "Tight near the high": {
        "filters": [
            {"field": "close", "op": ">=", "value": 5},
            {"field": "avg_dollar_volume_20d", "op": ">=", "value": 5_000_000},
            {"field": "pct_from_52w_high", "op": ">=", "value": -10},
            {"field": "hist_range_nd", "op": "<=", "value": 2.5},
            {"field": "rs_pct", "op": ">=", "value": 80},
        ],
        "sort": "rs_pct",
        "descending": True,
    },
    "Gappers on volume": {
        "filters": [
            {"field": "gap_pct", "op": ">=", "value": 5},
            {"field": "rvol50", "op": ">=", "value": 2},
            {"field": "close", "op": ">=", "value": 3},
        ],
        "sort": "gap_pct",
        "descending": True,
    },
}
