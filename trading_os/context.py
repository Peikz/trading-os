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

from trading_os import industries
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
EP_SCANS = ("ep_day", "ep_close", "ep_am", "ep_ah", "ep9m", "ep9m_pace", *PREMARKET_SCANS)
BREAKOUT_SCANS = ("breakout_trigger", "breakout_watch", "pivot_watch", "luk_flush")
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


GROWTH_CAP = 999  # beyond this the base is near zero and the number says nothing


def _pct(x: Any) -> str | None:
    """`+128%`; whole percents, no `-0%`, capped at ±999 % (tiny year-ago bases)."""
    if x is None or pd.isna(x):
        return None
    if abs(x) > GROWTH_CAP:
        return f">+{GROWTH_CAP}%" if x > 0 else f"<-{GROWTH_CAP}%"
    return f"{round(x) + 0:+d}%"


def _growth(latest: Any, previous: Any, surprise: Any) -> str | None:
    if latest is None or pd.isna(latest):
        return None
    text = _pct(latest)
    if previous is not None and not pd.isna(previous):
        text += f" / {_pct(previous)}"
    if surprise is not None and not pd.isna(surprise):
        if round(surprise) == 0:
            text += " (in line)"
        else:
            text += f" (beat {_pct(surprise)})" if surprise > 0 else f" (miss {_pct(surprise)})"
    return text


def _traded(turnover: Any) -> str:
    """Share of the float that traded: `8.8x` from one float up, `12%` below."""
    if turnover is None or pd.isna(turnover):
        return ""
    if turnover >= 1:
        return f" ({turnover:.1f}x traded)"
    return f" ({turnover:.0%} traded)" if turnover >= 0.005 else " (<1% traded)"


def _shares(x: float) -> str:
    return f"{x / 1e9:.1f}B" if x >= 1e9 else f"{x / 1e6:.0f}M"


def _missing(x: Any) -> bool:
    return x is None or pd.isna(x)


def _high_text(price: Any, high_52w: Any, high_all: Any) -> str | None:
    """`at all-time high`, `at 52w high` or `-12% from 52w high` (within 1 % counts as at)."""
    if _missing(price):
        return None
    if not _missing(high_all) and high_all > 0 and price >= 0.99 * high_all:
        return "at all-time high"
    if _missing(high_52w) or not high_52w > 0:
        return None
    off = (price / high_52w - 1) * 100
    return "at 52w high" if off >= -1 else f"{off:.0f}% from 52w high"


def _common_tail(row: Mapping[str, Any]) -> list[str]:
    """Shared ending of both lines: RS, earnings soon, industry with its rank."""
    parts = []
    rs = row.get("rs_pct")
    if not _missing(rs):
        parts.append(f"RS {int(rs)}")
    soon, flagged = row.get("earnings_in_sessions"), row.get("earnings_soon")
    if not _missing(flagged) and bool(flagged):  # within context.earnings_soon_sessions
        parts.append("📅 earnings today" if soon == 0 else f"📅 earnings in {int(soon)} days")
    group = industries.label(row)
    if group:
        parts.append(group)
    return parts


def _et(when: Any, fmt: str) -> str:
    if _missing(when) or when == "":
        return ""
    stamp = pd.Timestamp(when)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
    return stamp.tz_convert(NEW_YORK).strftime(fmt)


def ep_line(row: Mapping[str, Any], *, premarket: bool = False) -> str:
    return "   " + " · ".join(ep_parts(row, premarket=premarket))


def ep_parts(row: Mapping[str, Any], *, premarket: bool = False) -> list[str]:
    """The EP facts, each a short phrase (joined into one line in the report, wrapped on
    the phone)."""
    parts = []
    if bool(row.get("earnings_flag")):  # silence otherwise: no line means no report
        day = _et(row.get("earnings_date_last"), "%m-%d")
        timing = TIMING.get(row.get("ctx_earnings_time"), "")
        parts.append(" ".join(p for p in ("📢 earnings", day, timing) if p))
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
        parts.append(f"float {_shares(floats)}{_traded(turnover)}")
    prior = _pct(row.get("ctx_prior_6m_pct"))
    if prior:
        parts.append(f"6M before {prior}")
    price = row.get("pm_price" if premarket else "close")
    high = _high_text(price, row.get("high_52w"), row.get("high_all_tv"))
    if high:
        parts.append(high)
    ma200 = row.get("ma200")
    if not _missing(price) and not _missing(ma200) and ma200 > 0:
        parts.append("✅ above 200d" if price > ma200 else "❌ below 200d")
    parts.extend(_common_tail(row))
    return parts


def breakout_line(row: Mapping[str, Any], scan: str) -> str:
    return "   " + " · ".join(breakout_parts(row, scan))


def breakout_parts(row: Mapping[str, Any], scan: str) -> list[str]:
    """The breakout facts, each a short phrase."""
    prefix = "trig_" if scan == "breakout_trigger" else "bo_"
    parts = []
    prior = row.get(f"{prefix}prior_move_pct", row.get("bo_prior_move_pct"))
    if prior is not None and not pd.isna(prior):
        parts.append(f"prior move {prior:+.0f}%")
    for label, column in (("3M", "ret_63"), ("6M", "ret_126")):
        value = _pct(row.get(column))
        if value:
            parts.append(f"{label} {value}")
    high = _high_text(row.get("close"), row.get("high_52w"), row.get("high_all_tv"))
    if high is None and not _missing(row.get("pct_from_52w_high")):
        off = row["pct_from_52w_high"]
        high = "at 52w high" if off >= -1 else f"{off:.0f}% from 52w high"
    if high:
        parts.append(high)
    adr = row.get("adr20_pct")
    if adr is not None and not pd.isna(adr):
        parts.append(f"ADR {adr:.1f}%")
    stacked = row.get(f"{prefix}ma_stacked", row.get("bo_ma_stacked"))
    if stacked is not None and not pd.isna(stacked):
        parts.append("✅ MA 10>20>50" if bool(stacked) else "❌ MAs not stacked")
    eps = _growth(row.get("ctx_eps_growth_q"), None, None)
    rev = _growth(row.get("ctx_rev_growth_q"), None, None)
    if eps:
        parts.append(f"EPS {eps}")
    if rev:
        parts.append(f"rev {rev}")
    parts.extend(_common_tail(row))
    return parts


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


def parts(row: Mapping[str, Any], scan: str) -> list[str]:
    """The fact phrases for a pushed row of `scan` (empty for scans without facts)."""
    if scan in EP_SCANS:
        return ep_parts(row, premarket=scan in PREMARKET_SCANS)
    if scan in BREAKOUT_SCANS:
        return breakout_parts(row, scan)
    return []


def lines(row: Mapping[str, Any], scan: str) -> list[str]:
    if scan in EP_SCANS:
        news = news_line(row)
        return [ep_line(row, premarket=scan in PREMARKET_SCANS), *([news] if news else [])]
    if scan in BREAKOUT_SCANS:
        return [breakout_line(row, scan)]
    return []
