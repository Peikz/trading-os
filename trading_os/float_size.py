"""Float in dollars on every hit, tracked live (Emil, 12 Nov 2026: "add it live so I can see the
difference"). Facts, not rules: no grade changes.

In the 2016-26 study (the private data repo's docs/research/2026-11-10-search-for-better-return.md,
batches 16a-16b) small floats were weaker in the recent period but not in the earlier one, so
it is a warning on the card and in the push, and the monthly live check splits by float band.

Float here is TradingView's float shares x the hit's price (current, unlike the SEC cover's
yearly value used in the study).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

SMALL, BIG = 300e6, 2e9
BANDS = ("<300M", "300M-2B", ">2B")
NOTE = "weaker in the 2022-26 study, not in 2016-21 (research doc, 12 Nov)"


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def band(float_usd: Any) -> str | None:
    """The float band, or None when unknown."""
    x = _num(float_usd)
    if not x > 0:
        return None
    return BANDS[0] if x < SMALL else BANDS[1] if x <= BIG else BANDS[2]


def money(x: float) -> str:
    return f"${x / 1e9:.1f}B" if x >= 1e9 else f"${x / 1e6:.0f}M"


def tag(float_usd: Any) -> str | None:
    """The card and push line for a small float, else None."""
    x = _num(float_usd)
    if band(x) != BANDS[0]:
        return None
    return f"🔸 Small float {money(x)} · {NOTE}"


def attach(results: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """`float_usd`, `float_band`, `float_tag` on every hit frame that has float shares and a
    price; other frames go out unchanged."""
    out = {}
    for name, hits in results.items():
        if hits.empty or "float_shares" not in hits or "close" not in hits:
            out[name] = hits
            continue
        usd = pd.to_numeric(hits["float_shares"], errors="coerce") * pd.to_numeric(
            hits["close"], errors="coerce"
        )
        out[name] = hits.assign(
            float_usd=usd,
            float_band=[band(v) for v in usd],
            float_tag=[tag(v) for v in usd],
        )
    return out
