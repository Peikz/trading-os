"""Industry strength (Emil, 19 Oct 2026): which groups lead, for facts lines and the weekly push.

Qullamaggie trades the leading groups. Per TradingView industry, over the logged-tier universe:
member count, median 1-month and 3-month return, and how many members make the QM gainers top
lists (§6.3, run on the same universe). Ranked by the mean of the two medians (proposed);
industries with fewer than `context.industry_min_members` stocks are left out, so a two-stock
group can't top the table. Facts only: the rank is shown, never used to filter or grade.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from trading_os.scans.weekly import qm_gainers

COLUMNS = [
    "industry",
    "sector",
    "members",
    "med_ret_22",
    "med_ret_63",
    "qm_members",
    "score",
    "industry_rank",
    "industry_of",
]


def rank(uni: pd.DataFrame, cfg) -> pd.DataFrame:
    """One row per ranked industry, strongest first."""
    named = uni[uni["industry"].fillna("").astype(str).str.strip() != ""]
    if named.empty:
        return pd.DataFrame(columns=COLUMNS)
    qm = qm_gainers(named, cfg.scans["qm_gainers"])
    grouped = named.groupby("industry")
    table = pd.DataFrame(
        {
            "sector": grouped["sector"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else ""),
            "members": grouped.size(),
            "med_ret_22": grouped["ret_22"].median(),
            "med_ret_63": grouped["ret_63"].median(),
        }
    )
    table["qm_members"] = qm.groupby("industry").size().reindex(table.index).fillna(0).astype(int)
    table = table[table["members"] >= cfg.context["industry_min_members"]]
    table["score"] = table[["med_ret_22", "med_ret_63"]].mean(axis=1)
    table = table.dropna(subset=["score"]).sort_values(
        ["score", "qm_members"], ascending=[False, False]
    )
    table["industry_rank"] = np.arange(1, len(table) + 1)
    table["industry_of"] = len(table)
    return table.reset_index()[COLUMNS]


def add_rank(uni: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """`industry_rank` / `industry_of` on every row of a ranked industry (NaN elsewhere)."""
    keyed = table.set_index("industry")[["industry_rank", "industry_of"]]
    return uni.join(keyed, on="industry")


def label(row: Mapping[str, Any]) -> str | None:
    """`Semiconductors (#3 of 120)`, or the bare industry when it isn't ranked."""
    industry = row.get("industry")
    if not isinstance(industry, str) or not industry:
        return None
    place, of = row.get("industry_rank"), row.get("industry_of")
    if place is None or pd.isna(place):
        return industry
    return f"{industry} (#{int(place)} of {int(of)})"


def _pct(x: float) -> str:
    return f"{round(x) + 0:+d}%"  # whole percents, never "-0%"


def lines(table: pd.DataFrame, top_n: int) -> list[str]:
    """Weekly push: `Leading industries (median 1M / 3M, QM gainers):` + the top names."""
    if table.empty:
        return []
    out = ["Leading industries (median 1M / 3M, QM gainers):"]
    for row in table.head(top_n).to_dict("records"):
        out.append(
            f"{row['industry_rank']}. {row['industry']}  {_pct(row['med_ret_22'])} / "
            f"{_pct(row['med_ret_63'])}  QM {row['qm_members']} of {row['members']}"
        )
    return out
