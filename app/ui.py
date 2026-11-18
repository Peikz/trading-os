"""Shared UI pieces of the dashboard (UX pass 1): one header, one picker, one empty state, one
table style and one footer, so every page looks and behaves the same. UI only: nothing here
reads or writes data."""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd
import streamlit as st

from trading_os import screens

MUTED = "#98A2B3"

# ---------------------------------------------------------------- headers


def page_header(title: str, subtitle: str | None = None, *, show_title: bool = False) -> None:
    """The top of a page. The tab (or the place in the top bar) already shows the page's name,
    so no H1 by default; at most one muted line under it."""
    if show_title:
        st.subheader(title)
    if subtitle:
        st.caption(subtitle)


def section(title: str, help: str | None = None) -> None:  # noqa: A002 - Streamlit's name
    """A section header: the same size everywhere; long explanations go in the tooltip."""
    st.subheader(title, help=help)


def about(text: str, label: str = "About this table") -> None:
    """A long explanation, out of the way: a collapsed expander (every fact stays reachable)."""
    with st.expander(label, expanded=False):
        st.markdown(text)


def note(text: str, limit: int = 110) -> None:
    """Explanation text, out of the way: one muted line when it is short; when it is long, its
    first sentence as the line and the whole text in the tooltip (every fact stays reachable;
    no wall of text above or below the content)."""
    if len(text) <= limit:
        st.caption(text)
        return
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind(": "), cut.rfind("; "))
    first = cut[: stop + 1] if stop > 30 else cut[: cut.rfind(" ")] + "…"
    st.caption(first, help=text)


def empty_state(title: str, hint: str | None = None) -> None:
    """A quiet empty state: muted text, no coloured box."""
    body = f"<b>{html.escape(title)}</b>"
    if hint:
        body += f"<br><span style='opacity:.85'>{html.escape(hint)}</span>"
    st.html(f"<div style='color:{MUTED};padding:.5rem 0 .8rem;line-height:1.45'>{body}</div>")


def footer(runs_count: int, session: str, today: str) -> None:
    """The one muted line at the bottom of every page."""
    st.caption(f"{runs_count} runs · {today} · session {session}")


# ---------------------------------------------------------------- pickers


def keep(key: str, fallback: Any) -> None:
    """A segmented control can be clicked off; keep the last pick instead of nothing."""
    if st.session_state.get(key) is None:
        st.session_state[key] = st.session_state.get(f"_last_{key}", fallback)
    st.session_state[f"_last_{key}"] = st.session_state[key]


MAX_SEGMENTS = 6


def choose(
    label: str,
    options: Sequence[Any],
    key: str,
    *,
    default: Any = None,
    format_func: Callable[[Any], str] = str,
    help: str | None = None,  # noqa: A002 - Streamlit's name
    visible_label: bool = False,
) -> Any:
    """Pick one of N: a segmented control up to six options (it cannot be clicked off), a
    select box beyond that. The one control for this job on every page."""
    options = list(options)
    first = options[0] if default is None else default
    if st.session_state.get(key) not in options:
        last = st.session_state.get(f"_last_{key}")
        st.session_state[key] = last if last in options else first
    visibility = "visible" if visible_label else "collapsed"
    if len(options) <= MAX_SEGMENTS:
        value = st.segmented_control(
            label,
            options,
            key=key,
            format_func=format_func,
            help=help,
            label_visibility=visibility,
        )
    else:
        value = st.selectbox(
            label,
            options,
            key=key,
            format_func=format_func,
            help=help,
            label_visibility=visibility,
        )
    if value is None:  # clicked off: the last pick stays (restored before the next draw)
        return st.session_state.get(f"_last_{key}", first)
    st.session_state[f"_last_{key}"] = value
    return value


# ---------------------------------------------------------------- tables

# The short names of the universe / watchlist / scan columns (the Screener's longer names stay
# there, `screens.FIELDS`); anything not listed falls back to the Screener's label.
COLUMN_LABELS: dict[str, str] = {
    "ticker": "Ticker",
    "chart": "Chart",
    "close": "Close",
    "chg_pct": "Change %",
    "gap_pct": "Gap %",
    "rvol50": "Rel. volume",
    "vol_build": "Vol build",
    "adr20_pct": "ADR %",
    "rs_pct": "RS",
    "pct_from_52w_high": "From 52w high %",
    "ret_22": "1M %",
    "ret_63": "3M %",
    "ret_126": "6M %",
    "above_ma10": "Over 10d",
    "above_ma20": "Over 20d",
    "above_ma50": "Over 50d",
    "above_ma200": "Over 200d",
    "to_pivot_pct": "To pivot %",
    "earnings_in_sessions": "Earnings in (sessions)",
    "in_scans": "Scans hit",
    "industry": "Industry",
    "sector": "Sector",
    "note": "Note",
    "status": "Status",
    "added_date": "Added",
    "status_date": "Status date",
    "reason": "Reason",
    "level": "Level",
    "direction": "When",
    "fired_ts": "Fired",
    "kind": "Kind",
    "price": "Price",
    "market_cap": "Market cap",
    "float_shares": "Float",
    "avg_dollar_volume_20d": "Avg $ volume 20d",
}
_COMPACT = {"volume", "avg_volume_20d", "float_shares", "pm_volume", "ah_volume", "market_cap",
            "avg_dollar_volume_20d", "dollar_volume", "revenue_ttm"}  # fmt: skip
_INTS = {"earnings_in_sessions", "rs_pct", "industry_rank", "hist_consec_up"}


def column_label(name: str) -> str:
    return COLUMN_LABELS.get(name) or screens.label(name)


def column_config(df: pd.DataFrame) -> dict[str, Any]:
    """Labels and number formats for the known columns of `df` (others are left alone)."""
    out: dict[str, Any] = {}
    cfg = st.column_config
    for col in df.columns:
        if col not in COLUMN_LABELS and col not in screens.FIELDS:
            continue
        label = column_label(col)
        series = df[col]
        if col == "chart":
            out[col] = cfg.LinkColumn(label, display_text="TV ↗")
        elif pd.api.types.is_bool_dtype(series):
            out[col] = cfg.CheckboxColumn(label)
        elif pd.api.types.is_numeric_dtype(series):
            if col in _COMPACT:
                out[col] = cfg.NumberColumn(label, format="compact")
            elif col in _INTS:
                out[col] = cfg.NumberColumn(label, format="%d")
            else:
                out[col] = cfg.NumberColumn(label, format="%.2f")
        else:
            out[col] = cfg.Column(label)
    return out


def show_df(data: Any, **kwargs: Any) -> Any:
    """`st.dataframe` the one way: no index, the screen's width (it scrolls inside itself), the
    shared column labels and number formats. Own `column_config` entries win."""
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("width", "stretch")
    if isinstance(data, pd.DataFrame):
        kwargs["column_config"] = {**column_config(data), **(kwargs.get("column_config") or {})}
    return st.dataframe(data, **kwargs)


# ---------------------------------------------------------------- market tiles

_DOT = {"GREEN": "#2BC48A", "YELLOW": "#E5B341", "RED": "#F0616D"}
_EMOJI_DOT = {"🟢": "#2BC48A", "🟡": "#E5B341", "🔴": "#F0616D", "⚪": "#6B7280"}
_NUMBER_TILES = {"SPY", "QQQ", "VIX"}


def market_tiles(tiles: Sequence[tuple]) -> None:
    """The market as tiles: words (light, heat, IBD state) as a small label with a coloured dot
    and the full word, wrapping instead of cut off; numbers (SPY, QQQ, VIX) as metrics. Five or
    six in a row on a desktop, two per row on a phone (`NAV_CSS`)."""
    if not tiles:
        return
    with st.container(key="mtiles"):
        cols = st.columns(len(tiles))
        for col, (label, value, delta) in zip(cols, tiles, strict=True):
            with col:
                if label in _NUMBER_TILES:
                    st.metric(label, value, delta)
                    continue
                text = str(value)
                dot = ""
                for emoji, colour in _EMOJI_DOT.items():
                    if text.startswith(emoji):
                        text = text[len(emoji) :].strip()
                        dot = f"<span style='color:{colour}'>●</span> "
                        break
                if text in _DOT:
                    dot = f"<span style='color:{_DOT[text]}'>●</span> "
                extra = (
                    f"<div style='color:{MUTED};font-size:.8rem'>{html.escape(str(delta))}</div>"
                    if delta
                    else ""
                )
                word = text.capitalize() if text.isupper() else text
                st.html(
                    f"<div class='wordtile'><div class='wt-label'>{html.escape(label)}</div>"
                    f"<div class='wt-value'>{dot}{html.escape(word)}</div>{extra}</div>"
                )
