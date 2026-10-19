"""Weekly scans (SPEC §6.3): Qullamaggie gainers and the two growth buckets."""

from __future__ import annotations

import pandas as pd

from trading_os.config import ScanConfig


def qm_gainers(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Top `top_pct` % by each return window, then ADR, dollar-volume and price floors.

    The percentile is taken over the whole logged-tier universe (the market), before the
    floors. One merged list; `qm_lists` says which window(s) each name made.
    """
    out = df.copy()
    windows = list(scan["return_windows"])
    quantile = 1 - scan["top_pct"] / 100
    for days in windows:
        column = f"ret_{days}"
        out[f"top_{days}"] = (out[column] >= out[column].quantile(quantile)).fillna(False)
    tops = out[[f"top_{d}" for d in windows]]
    floors = (
        (out["adr20_pct"] >= scan["adr_min_pct"])
        & (out["avg_dollar_volume_20d"] >= scan["avg_dollar_volume_20d_min"])
        & (out["close"] > scan["price_gt"])
    )
    hits = out.loc[tops.any(axis=1) & floors].copy()
    hit_tops = hits[[f"top_{d}" for d in windows]]
    hits["qm_list_count"] = hit_tops.sum(axis=1).astype(int)
    hits["qm_lists"] = hit_tops.apply(
        lambda row: ",".join(f"{d}d" for d in windows if row[f"top_{d}"]), axis=1
    ).astype("string")
    sort_by = ["qm_list_count", f"ret_{windows[1] if len(windows) > 1 else windows[0]}", "ticker"]
    hits = hits.sort_values(sort_by, ascending=[False, False, True])
    hits = hits.drop(columns=[f"top_{d}" for d in windows])
    return hits.assign(rank=range(1, len(hits) + 1)).reset_index(drop=True)


def _two_quarters(latest: pd.Series, previous: pd.Series, minimum: float, quarters: int):
    """Latest quarter must pass; the previous one too when it exists (SPEC §6.3)."""
    ok = latest >= minimum
    if quarters >= 2:
        ok &= previous.isna() | (previous >= minimum)
    return ok


def growth_bucket_1(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """Sales growth YoY over the last two quarters, price, volume and annual-revenue floors."""
    quarters = scan["quarters_to_check"]
    hit = (
        (df["close"] > scan["price_gt"])
        & (df["avg_volume_20d"] > scan["avg_volume_gt"])
        & (df["revenue_ttm"] > scan["annual_revenue_gt"])
        & _two_quarters(
            df["rev_growth_q"], df["rev_growth_q_prev"], scan["rev_growth_q_min_pct"], quarters
        )
    )
    hits = df.loc[hit].copy()
    hits["growth_quarters_checked"] = _checked(hits, ["rev_growth_q_prev"], quarters)
    return _rank(hits, "rev_growth_q")


def growth_bucket_2(df: pd.DataFrame, scan: ScanConfig) -> pd.DataFrame:
    """EPS growth and sales growth YoY over the last two quarters, price and volume floors."""
    quarters = scan["quarters_to_check"]
    hit = (
        (df["close"] > scan["price_gt"])
        & (df["avg_volume_20d"] > scan["avg_volume_gt"])
        & _two_quarters(
            df["eps_growth_q"], df["eps_growth_q_prev"], scan["eps_growth_q_min_pct"], quarters
        )
        & _two_quarters(
            df["rev_growth_q"], df["rev_growth_q_prev"], scan["rev_growth_q_min_pct"], quarters
        )
    )
    hits = df.loc[hit].copy()
    hits["growth_quarters_checked"] = _checked(
        hits, ["eps_growth_q_prev", "rev_growth_q_prev"], quarters
    )
    return _rank(hits, "eps_growth_q")


def _checked(hits: pd.DataFrame, previous_columns: list[str], quarters: int) -> pd.Series:
    """2 when every previous-quarter value was there to check, else 1."""
    if quarters < 2:
        return pd.Series(1, index=hits.index)
    complete = hits[previous_columns].notna().all(axis=1)
    return complete.map({True: 2, False: 1}).astype(int)


def _rank(hits: pd.DataFrame, by: str) -> pd.DataFrame:
    hits = hits.sort_values([by, "ticker"], ascending=[False, True])
    return hits.assign(rank=range(1, len(hits) + 1)).reset_index(drop=True)
