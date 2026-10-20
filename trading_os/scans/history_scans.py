"""Scans that need daily history: Parabolic Short/Long (SPEC §6.2), tight bases (§6.3).

They read the `hist_*` columns from enrich.attach_history and find nothing until enough
history exists.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trading_os.config import ScanConfig
from trading_os.scans.ep import ranked


def _mask(condition: pd.Series) -> pd.Series:
    return condition.fillna(False).astype(bool)


def parabolic_short(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Up >= 50 % within <= 10 sessions (>= 200 % under $1B) and >= 3 up days in a row.

    Distance above MA10 in ADR is stored, not filtered. Ranked by the gain.
    """
    large = df["market_cap"] >= scan["large_cap_min"]
    needed = np.where(large, scan["gain_min_pct_large_cap"], scan["gain_min_pct_small_cap"])
    hit = _mask(
        (df["hist_gain_max_pct"] >= needed) & (df["hist_consec_up"] >= scan["consec_up_min"])
    )
    return ranked(df, hit, "hist_gain_max_pct")


def parabolic_long(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Down >= 30 % within <= 10 sessions and >= 3 down days in a row. Ranked by the drop."""
    hit = _mask(
        (df["hist_drop_max_pct"] >= scan["drop_min_pct"])
        & (df["hist_consec_down"] >= scan["consec_down_min"])
    )
    return ranked(df, hit, "hist_drop_max_pct")


def tight_bases(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Near the 52-week high, volatile enough, above MA50, a tight and quiet last 10 days.

    Ranked tightest first (10-day range in ADR $).
    """
    out = df.copy()
    adr_usd = out["hist_adr20_usd"].where(out["hist_adr20_usd"] > 0)
    out["tightness_adr"] = out["hist_range_nd"] / adr_usd
    hit = _mask(
        (out["pct_from_52w_high"] >= -scan["high_52w_within_pct"])
        & (out["hist_adr20_pct"] >= scan["adr_min_pct"])
        & (out["close"] > out[f"ma{scan['above_ma']}"])
        & (out["tightness_adr"] < scan["range_adr_mult_below"])
        & (out["hist_avg_volume_short"] < out["hist_avg_volume_long"])
    )
    return ranked(out, hit, "tightness_adr", ascending=True)


_WATCH = {
    "pivot": "bo_pivot",
    "order_stop": "bo_order_stop",
    "risk_adr": "bo_risk_adr",
    "base_len": "bo_base_len",
    "contraction_depths": "bo_contraction_depths",
    "b1": "bo_b1",
    "b2": "bo_b2",
    "b3": "bo_b3",
    "b4": "bo_b4",
}
_TRIGGER = {
    "pivot": "trig_pivot",
    "order_stop": "trig_order_stop",
    "risk_adr": "trig_risk_adr",
    "base_len": "trig_base_len",
    "contraction_depths": "trig_contraction_depths",
    "b1": "trig_b1",
    "b2": "trig_b2",
    "b3": "trig_b3",
    "b4": "trig_b4",
    "b5": "trig_b5",
}


def _with_breakout_fields(hits: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Copy the detector's columns into the candidates' SPEC §7 breakout fields."""
    for target, source in mapping.items():
        hits[target] = hits.get(source, pd.NA)
    return hits


def breakout_watch(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """B1-B4 all pass on the base ending today: a BO-Watch name. Tightest right side first."""
    if "bo_b1" not in df:
        return df.iloc[0:0].assign(rank=pd.Series(dtype="int64"))
    hit = _mask(df["bo_b1"] & df["bo_b2"] & df["bo_b3"] & df["bo_b4"])
    hits = ranked(df, hit, "bo_right_side_range_adr", ascending=True)
    hits = _with_breakout_fields(hits, _WATCH)
    hits["b5"] = pd.NA
    return hits


def breakout_trigger(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """B5 at the close against yesterday's base; B1-B4 stored for the human's grade."""
    if "trig_b5" not in df:
        return df.iloc[0:0].assign(rank=pd.Series(dtype="int64"))
    hits = ranked(df, _mask(df["trig_b5"]), "trig_rvol")
    return _with_breakout_fields(hits, _TRIGGER)


def luk_flush(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Martin Luk's AVWAP flush (Emil, 20 Oct 2026): the rows `luk_live.attach` marked.
    Ranked by dollar volume, largest first."""
    if "luk_flush" not in df:
        return df.iloc[0:0].assign(rank=pd.Series(dtype=int))
    return ranked(df, _mask(df["luk_flush"]), "dollar_volume")
