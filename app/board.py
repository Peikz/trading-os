"""The candidate board (Emil, 26 Oct 2026: the dashboard as the only tool, Saxo for execution).

One card per signal from the latest runs: A+, A and B first (C only on request), each with the
grade, the setup, when and how to buy, the plan's numbers and its tags. The 🎫 ticket opens the
Saxo order with the plan's order type by default and any other on a switch; every value has a
copy button (st.code), and "Placed" saves it as a plan so the fill matches up later. Nothing is
sent to Saxo.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import pandas as pd
import streamlit as st

from trading_os import clock, notify, plans, report, ticket

GRADE_COLOURS = {"A+": "#1a7f37", "A": "#2da44e", "B": "#bf8700", "C": "#6e7781"}


def collect(runs, cfg, scan_frames: Callable[[str], dict]) -> pd.DataFrame:
    """The pushed scans' alert-tier hits of the newest pre-market, 10:15, 12:00 and EOD runs,
    newest first, one row per ticker and scan."""
    latest = []
    for slot in ("pm", "am", "mid", "eod"):
        run = next((r for r in runs if r.slot == slot), None)
        if run is not None:
            latest.append(run)
    frames = []
    for run in sorted(latest, key=runs.index):
        for scan, hits in scan_frames(str(run.candidates)).items():
            if scan not in cfg.scans or cfg.scans[scan].action != "push":
                continue
            shown = hits[hits["tier"] == "alert"] if "tier" in hits else hits
            if shown.empty:
                continue
            frames.append(
                shown.assign(
                    scan=scan, run_label=run.label, run_slot=run.slot, run_session=run.session
                )
            )
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(["ticker", "scan"], keep="first")
    if "grade" not in out:
        out["grade"] = "C"
    out["grade"] = out["grade"].fillna("C")
    out["_g"] = out["grade"].map(notify.GRADE_RANK).fillna(9)
    out["_s"] = pd.to_numeric(out.get("grade_score"), errors="coerce").fillna(-1e9)
    return out.sort_values(["_g", "_s"], ascending=[True, False])


def _tags(row) -> list[str]:
    out = []
    for key in ("heat_tag", "si_tag", "ibd_tag"):
        v = row.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return out


def _history(row) -> str:
    n, mean, win = (row.get(f"grade_stat_{k}") for k in ("trades", "mean_r", "win_pct"))
    if n is None or pd.isna(n) or mean is None or pd.isna(mean):
        return ""
    w = f" · {win:.0f}% win" if win is not None and not pd.isna(win) else ""
    return f"📚 {int(n)} trades · avg {mean:+.2f}R{w} (2016-26)"


def _plan_session(row, cfg) -> dt.date:
    """The session the order is for: an EOD find trades the next session."""
    day = pd.Timestamp(row["run_session"]).date()
    if row.get("run_slot") == "eod":
        return clock.sessions_after(cfg.schedule, day, 1, day + dt.timedelta(days=10))[0]
    return day


def ticket_view(row, key: str, cfg, data_dir, account, usd_rate) -> None:
    """The Saxo ticket: order type (the plan's by default), an own price, the values to type."""
    default = ticket.default_type(row)
    names = list(ticket.ORDER_TYPES)
    a, b = st.columns(2)
    kind = a.selectbox(
        "Order type",
        names,
        index=names.index(default),
        key=f"{key}_type",
        format_func=lambda k: ticket.ORDER_TYPES[k] + (" (plan)" * (k == default)),
    )
    own = b.number_input(
        "Own price (0 = the plan's)",
        min_value=0.0,
        value=0.0,
        step=0.01,
        format="%.2f",
        key=f"{key}_price",
    )
    if account is None or not usd_rate:
        st.caption("Add settings/account.yaml in the data repo for share sizes.")
        return
    mult = row.get("grade_risk_mult")
    if mult is None or pd.isna(mult):
        mult = cfg.grading["risk_mult"].get(row.get("grade"), 0.0)
    if not mult:
        st.caption("Grade C: no size (no edge after costs in the study).")
        mult = cfg.grading["risk_mult"].get("B", 1.0)
    t = ticket.build(
        row,
        kind,
        account.risk_usd(usd_rate) * float(mult),
        account.size_usd(usd_rate),
        account.max_position_pct,
        own or None,
    )
    if t is None:
        st.warning("No ticket: the price must be over the stop, and the plan needs both.")
        return
    if t.when:
        st.markdown(f"**When:** {t.when}")
    for label, value in t.lines():  # one column, in the order Saxo's ticket asks for them
        st.caption(label)
        st.code(value, language=None)
    risk_local = t.risk_usd * usd_rate
    st.caption(
        f"Risk {t.risk_usd:,.0f} USD ({risk_local:,.0f} {account.currency}) · position "
        f"{t.position_usd:,.0f} USD · sized on {t.est_entry:.2f}"
        + (" · capped by your max position" if t.capped else "")
    )
    if st.button("✅ Placed in Saxo: save as plan", key=f"{key}_placed"):
        try:
            plans.create(
                data_dir,
                _plan_session(row, cfg),
                str(row["ticker"]),
                "long",
                t.est_entry,
                t.stop,
                t.shares,
                str(row["scan"]),
                f"board: {ticket.ORDER_TYPES[kind]}, {row.get('grade')}",
            )
            st.success("Saved as a plan. Your fill will match it in the Journal.")
        except ValueError as exc:
            st.error(str(exc))


def card(row, n: int, cfg, data_dir, account, usd_rate, open_chart, inline: bool = False) -> None:
    """One candidate: grade, setup, when to buy, the plan, tags, history, why; the chart button
    and the ticket (a popover in the list, open under the card in the focus view)."""
    grade = row.get("grade", "C")
    label = report.SCAN_LABELS.get(row["scan"], row["scan"])
    colour = GRADE_COLOURS.get(grade, "#6e7781")
    with st.container(border=True):
        st.markdown(
            f"<span style='background:{colour};color:white;padding:2px 8px;"
            f"border-radius:6px;font-weight:600'>{grade}</span>&nbsp; "
            f"<b style='font-size:1.15em'>{row['ticker']}</b> &nbsp;·&nbsp; {label} "
            f"&nbsp;<span style='opacity:.6'>{row['run_label']}</span>",
            unsafe_allow_html=True,
        )
        lines = notify.grade_lines(row) if grade != "C" else []
        facts = [*lines[1:2], *notify.plan_lines(row), *_tags(row)]
        hist = _history(row)
        if hist:
            facts.append(hist)
        why = row.get("grade_why")
        if isinstance(why, str) and why:
            facts.append(f"Why: {why}")
        if facts:
            st.markdown("\n".join(f"- {f}" for f in facts))
        if inline:
            st.markdown("**🎫 Saxo ticket**")
            ticket_view(row, f"focus_{n}", cfg, data_dir, account, usd_rate)
            return
        a, b = st.columns(2)
        a.button(
            "📈 Chart",
            key=f"board_{n}_chart",
            on_click=open_chart,
            args=(row["ticker"],),
            width="stretch",
        )
        with b.popover("🎫 Saxo ticket", width="stretch"):
            ticket_view(row, f"board_{n}", cfg, data_dir, account, usd_rate)


def _step(n: int, by: int) -> None:
    st.session_state["board_i"] = (st.session_state.get("board_i", 0) + by) % n


def show(runs, cfg, data_dir, account, usd_rate, scan_frames, open_chart, chart) -> None:
    """The board, best first: a focus view (the chart of one candidate, its card and ticket,
    flipped with the arrow keys) or the list of cards."""
    hits = collect(runs, cfg, scan_frames)
    head, view, more = st.columns([2, 1, 1])
    head.subheader("Candidates")
    focus = view.toggle(
        "Focus view",
        value=True,
        key="board_focus",
        help="One candidate at a time with its chart; ◀ ▶ or the arrow keys",
    )
    with_c = more.toggle("Show C", value=False, key="board_c", help="C: no edge after costs")
    if hits.empty:
        st.info("No signals in the latest runs.")
        return
    graded = hits[hits["grade"].isin(["A+", "A", "B"])]
    shown = hits if with_c else graded
    if shown.empty:
        st.info("No A+ / A / B today. Flip 'Show C' to see the rest (no edge after costs).")
        return
    rows = shown.to_dict("records")
    if not focus:
        st.caption(
            f"{len(graded)} graded A+ / A / B · {len(hits) - len(graded)} C hidden"
            if not with_c
            else f"{len(hits)} signals"
        )
        for n, row in enumerate(rows):
            card(row, n, cfg, data_dir, account, usd_rate, open_chart)
        return
    i = st.session_state.get("board_i", 0) % len(rows)
    prev, where, nxt = st.columns([1, 2, 1])
    prev.button(
        "◀ Previous",
        key="board_prev",
        shortcut="Left",
        on_click=_step,
        args=(len(rows), -1),
        width="stretch",
    )
    where.markdown(
        f"<div style='text-align:center;padding-top:.4rem'>{i + 1} of {len(rows)}"
        f"{'' if with_c else f' · {len(hits) - len(graded)} C hidden'}</div>",
        unsafe_allow_html=True,
    )
    nxt.button(
        "Next ▶",
        key="board_next",
        shortcut="Right",
        on_click=_step,
        args=(len(rows), 1),
        width="stretch",
    )
    row = rows[i]
    left, right = st.columns([5, 2])
    with left:
        chart(str(row["ticker"]))
    with right:
        card(row, i, cfg, data_dir, account, usd_rate, open_chart, inline=True)
