"""Facts behind each pushed EP and breakout, for the human's grade (never a verdict).

SPEC: no AI at runtime and code never grades. This module only gathers deterministic facts
that Qullamaggie's EP and breakout criteria look at:

- EP: the catalyst (earnings on the signal session and when; EPS and revenue growth for the
  last two quarters and the surprise vs estimates; the latest headline), how neglected the
  stock was before the gap (6-month move excluding today), whether the gap clears the
  52-week high and the 200-day, and how much of the float traded.
- Breakout: the prior move into the base, relative strength (3- and 6-month returns,
  distance from the 52-week high), ADR, MA stack, growth.

One extra TradingView request for the pushed names; headlines from Massive (rate limited,
capped per run). Facts are stored with the candidates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from trading_os.metrics import NEW_YORK, yoy_growth

DETAIL_FIELDS = {
    "eps_surprise_percent_fq": "ctx_eps_surprise_pct",
    "revenue_surprise_percent_fq": "ctx_rev_surprise_pct",
    "earnings_release_time": "ctx_earnings_time",
    "Perf.Y": "ctx_perf_1y",
    "total_revenue_fq_h": "ctx_rev_hist",
    "earnings_per_share_diluted_fq_h": "ctx_eps_hist",
}
PREMARKET_SCANS = ("ep_pm", "ep9m_early", "watchlist_gappers")
EP_SCANS = ("ep_day", "ep9m", *PREMARKET_SCANS)
BREAKOUT_SCANS = ("breakout_trigger", "breakout_watch")
CONTEXT_COLUMNS = [
    "ctx_eps_surprise_pct",
    "ctx_rev_surprise_pct",
    "ctx_earnings_time",
    "ctx_perf_1y",
    "ctx_eps_growth_q",
    "ctx_eps_growth_q_prev",
    "ctx_rev_growth_q",
    "ctx_rev_growth_q_prev",
    "ctx_prior_6m_pct",
    "ctx_float_turnover",
    "ctx_news_title",
    "ctx_news_publisher",
    "ctx_news_time",
    "ctx_news_url",
]
TIMING = {-1.0: "before open", 1.0: "after close"}


def growth_columns(details: pd.DataFrame) -> pd.DataFrame:
    """Latest and previous quarter YoY growth from the history arrays (latest first)."""
    out = details.copy()
    for kind, hist, abs_base in (("eps", "ctx_eps_hist", True), ("rev", "ctx_rev_hist", False)):
        series = out[hist] if hist in out else pd.Series(None, index=out.index, dtype=object)
        out[f"ctx_{kind}_growth_q"] = series.map(lambda h, a=abs_base: yoy_growth(h, 0, abs_base=a))
        out[f"ctx_{kind}_growth_q_prev"] = series.map(
            lambda h, a=abs_base: yoy_growth(h, 1, abs_base=a)
        )
    return out.drop(columns=["ctx_eps_hist", "ctx_rev_hist"], errors="ignore")


def add_context(
    hits: pd.DataFrame,
    details: pd.DataFrame,
    news: Callable[[str], dict[str, str] | None] | None = None,
    *,
    premarket: bool = False,
) -> pd.DataFrame:
    """`hits` plus ctx_* columns. `details` is indexed by tv_ticker; `news(ticker)` returns the
    latest headline or None. Before the open, TradingView's 6-month return still ends at the
    last close and the gap's volume is the pre-market volume."""
    out = hits.copy()
    joined = out.join(details, on="tv_ticker") if "tv_ticker" in out and len(details) else out
    for column in CONTEXT_COLUMNS:
        out[column] = joined.get(column)
    nan = pd.Series(float("nan"), index=out.index)
    chg = 0 if premarket else out.get("chg_pct", nan).fillna(0) / 100
    perf6 = out.get("perf_6m_tv", out.get("ret_126", nan))
    out["ctx_prior_6m_pct"] = ((1 + perf6 / 100) / (1 + chg) - 1) * 100
    floats = out.get("float_shares", nan)
    traded = out.get("pm_volume" if premarket else "volume", nan)
    out["ctx_float_turnover"] = traded / floats.where(floats > 0)
    out["ctx_done"] = True
    if news is not None:
        for i, ticker in out["ticker"].items():
            item = news(ticker)
            if item:
                out.at[i, "ctx_news_title"] = item.get("title")
                out.at[i, "ctx_news_publisher"] = item.get("publisher")
                out.at[i, "ctx_news_time"] = item.get("published_utc")
                out.at[i, "ctx_news_url"] = item.get("url")
    return out


def _pct(x: Any, spec: str = "+.0f") -> str | None:
    return None if x is None or pd.isna(x) else f"{x:{spec}}%"


def _growth(latest: Any, previous: Any, surprise: Any) -> str | None:
    if latest is None or pd.isna(latest):
        return None
    text = _pct(latest)
    if previous is not None and not pd.isna(previous):
        text += f" / {_pct(previous)}"
    if surprise is not None and not pd.isna(surprise):
        text += f" (beat {_pct(surprise)})" if surprise >= 0 else f" (miss {_pct(surprise)})"
    return text


def _shares(x: float) -> str:
    return f"{x / 1e9:.1f}B" if x >= 1e9 else f"{x / 1e6:.0f}M"


def _missing(x: Any) -> bool:
    return x is None or pd.isna(x)


def _et(when: Any, fmt: str) -> str:
    if _missing(when) or when == "":
        return ""
    stamp = pd.Timestamp(when)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
    return stamp.tz_convert(NEW_YORK).strftime(fmt)


def ep_line(row: Mapping[str, Any], *, premarket: bool = False) -> str:
    parts = []
    if bool(row.get("earnings_flag")):
        day = _et(row.get("earnings_date_last"), "%m-%d")
        timing = TIMING.get(row.get("ctx_earnings_time"), "")
        parts.append(" ".join(p for p in ("earnings", day, timing) if p))
    else:
        parts.append("no earnings on this session")
    eps = _growth(
        row.get("ctx_eps_growth_q"),
        row.get("ctx_eps_growth_q_prev"),
        row.get("ctx_eps_surprise_pct"),
    )
    rev = _growth(
        row.get("ctx_rev_growth_q"),
        row.get("ctx_rev_growth_q_prev"),
        row.get("ctx_rev_surprise_pct"),
    )
    if eps:
        parts.append(f"EPS {eps}")
    if rev:
        parts.append(f"rev {rev}")
    floats, turnover = row.get("float_shares"), row.get("ctx_float_turnover")
    if floats is not None and not pd.isna(floats) and floats > 0:
        traded = (
            f" ({turnover:.1f}x traded)" if turnover is not None and not pd.isna(turnover) else ""
        )
        parts.append(f"float {_shares(floats)}{traded}")
    prior = _pct(row.get("ctx_prior_6m_pct"))
    if prior:
        parts.append(f"6M before {prior}")
    price = row.get("pm_price" if premarket else "close")
    high, ma200 = row.get("high_52w"), row.get("ma200")
    if not _missing(price) and not _missing(high) and high > 0:
        off = (price / high - 1) * 100
        parts.append("at 52w high" if off >= -1 else f"{off:.0f}% from 52w high")
    if not _missing(price) and not _missing(ma200) and ma200 > 0:
        parts.append("above 200d" if price > ma200 else "below 200d")
    if isinstance(row.get("industry"), str) and row["industry"]:
        parts.append(row["industry"])
    return "   " + " · ".join(parts)


def breakout_line(row: Mapping[str, Any], scan: str) -> str:
    prefix = "trig_" if scan == "breakout_trigger" else "bo_"
    parts = []
    prior = row.get(f"{prefix}prior_move_pct", row.get("bo_prior_move_pct"))
    if prior is not None and not pd.isna(prior):
        parts.append(f"prior move {prior:+.0f}%")
    for label, column in (("3M", "ret_63"), ("6M", "ret_126")):
        value = _pct(row.get(column))
        if value:
            parts.append(f"{label} {value}")
    high = row.get("pct_from_52w_high")
    if high is not None and not pd.isna(high):
        parts.append("at 52w high" if high >= -1 else f"{high:.0f}% from 52w high")
    adr = row.get("adr20_pct")
    if adr is not None and not pd.isna(adr):
        parts.append(f"ADR {adr:.1f}%")
    stacked = row.get(f"{prefix}ma_stacked", row.get("bo_ma_stacked"))
    if stacked is not None and not pd.isna(stacked):
        parts.append("MA 10>20>50" if bool(stacked) else "MAs not stacked")
    eps = _growth(row.get("ctx_eps_growth_q"), None, None)
    rev = _growth(row.get("ctx_rev_growth_q"), None, None)
    if eps:
        parts.append(f"EPS {eps}")
    if rev:
        parts.append(f"rev {rev}")
    if isinstance(row.get("industry"), str) and row["industry"]:
        parts.append(row["industry"])
    return "   " + " · ".join(parts)


def headline(row: Mapping[str, Any], max_chars: int = 110) -> tuple[str, str] | None:
    """(title, "publisher, time ET") of the stored headline, or None."""
    title = row.get("ctx_news_title")
    if not isinstance(title, str) or not title:
        return None
    title = title if len(title) <= max_chars else title[: max_chars - 1] + "…"
    try:
        stamp = _et(row.get("ctx_news_time"), "%m-%d %H:%M ET")
    except (ValueError, TypeError):
        stamp = ""
    source = row.get("ctx_news_publisher")
    source = source if isinstance(source, str) else ""
    return title, ", ".join(x for x in (source, stamp) if x)


def news_line(row: Mapping[str, Any], max_chars: int = 110) -> str | None:
    found = headline(row, max_chars)
    if found is None:
        return None
    title, where = found
    return f'   news: "{title}"' + (f" ({where})" if where else "")


def has_context(row: Mapping[str, Any]) -> bool:
    done = row.get("ctx_done")
    return done is not None and not pd.isna(done) and bool(done)


def lines(row: Mapping[str, Any], scan: str) -> list[str]:
    if scan in EP_SCANS:
        news = news_line(row)
        return [ep_line(row, premarket=scan in PREMARKET_SCANS), *([news] if news else [])]
    if scan in BREAKOUT_SCANS:
        return [breakout_line(row, scan)]
    return []
