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


def collect(runs, cfg, scan_frames: Callable[[str], dict], exchanges=None) -> pd.DataFrame:
    """The pushed scans' alert-tier hits of the newest pre-market, 10:15, 12:00 and EOD runs,
    newest first, one row per ticker and scan."""
    latest = []
    for slot in ("pm", "am", "mid", "eod"):
        run = next((r for r in runs if r.slot == slot), None)
        if run is not None:
            latest.append(run)
    # The exchange per ticker from the newest run with a universe file (intraday runs have none)
    listing: dict = {}
    if exchanges is not None:
        with_universe = next((r for r in runs if r.universe.exists()), None)
        listing = exchanges(str(with_universe.universe)) if with_universe else {}
    frames = []
    for run in sorted(latest, key=runs.index):
        for scan, hits in scan_frames(str(run.candidates)).items():
            if scan not in cfg.scans or cfg.scans[scan].action != "push":
                continue
            shown = hits[hits["tier"] == "alert"] if "tier" in hits else hits
            if shown.empty:
                continue
            if listing and "exchange" not in shown:
                shown = shown.assign(exchange=shown["ticker"].map(listing))
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


def show(
    runs, cfg, data_dir, account, usd_rate, scan_frames, open_chart, chart, exchanges=None
) -> None:
    """The board, best first: a focus view (the chart of one candidate, its card and ticket,
    flipped with the arrow keys) or the list of cards."""
    hits = collect(runs, cfg, scan_frames, exchanges)
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
        chart(str(row["ticker"]), row)
    with right:
        card(row, i, cfg, data_dir, account, usd_rate, open_chart, inline=True)


def _signed(v) -> str | None:
    return None if v is None or pd.isna(v) else f"{v:+.1f}%"


def market_tiles(row: dict | None, ibd_info: dict | None, heat_text: str | None) -> None:
    """The market as tiles (Emil, 26 Oct 2026: tiles, not bullet text): the QQQ light, the heat,
    the IBD state, SPY, QQQ and VIX. The full lines stay in 'Market details' below."""
    if not row:
        st.info("No market row yet.")
        return
    icons = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}
    light = row.get("qqq_light")
    tiles = [
        ("QQQ light", f"{icons.get(light, '⚪')} {light or 'n/a'}", None),
        ("Market heat", heat_text or "n/a", None),
        (
            "IBD market",
            (ibd_info or {}).get("state", "n/a"),
            f"{ibd_info['dist_count']} dist. days" if ibd_info else None,
        ),
    ]
    for name in ("spy", "qqq", "vix"):
        close = row.get(f"{name}_close")
        if close is not None and not pd.isna(close):
            tiles.append((name.upper(), f"{close:,.2f}", _signed(row.get(f"{name}_chg_pct"))))
    cols = st.columns(3)
    for i, (label, value, delta) in enumerate(tiles):
        cols[i % 3].metric(
            label, value, delta, delta_color="off" if label == "IBD market" else "normal"
        )


def position_cards(
    view: pd.DataFrame, plan_check: pd.DataFrame, prices: dict, source: str, open_chart
) -> None:
    """The positions cockpit: one card per open position, with the price (live when the Alpaca
    keys are set), open R and P&L, the distance to the stop, and what the plan says today."""
    plan = plan_check.set_index("ticker") if len(plan_check) else pd.DataFrame()
    st.caption(f"Prices: {source}")
    for n, p in enumerate(view.to_dict("records")):
        t = p["ticker"]
        price = prices.get(t, p.get("last_close"))
        sign = 1 if p.get("direction") == "long" else -1
        entry, stop, qty = p.get("entry_avg"), p.get("order_stop"), abs(p.get("open_quantity") or 0)
        risk = (entry - stop) * sign if stop == stop and stop is not None else float("nan")
        r_now = (price - entry) * sign / risk if risk and risk > 0 else float("nan")
        pnl = (price - entry) * sign * qty
        to_stop = (price - stop) * sign / price * 100 if risk == risk else float("nan")
        info = plan.loc[t] if t in plan.index else {}
        with st.container(border=True):
            st.markdown(
                f"<b style='font-size:1.15em'>{t}</b> &nbsp;·&nbsp; {p.get('setup') or ''}"
                f" &nbsp;<span style='opacity:.6'>{p.get('direction')} · {qty:,.0f} sh"
                f" · in {p.get('entry_date')}</span>",
                unsafe_allow_html=True,
            )
            a, b, c = st.columns(3)
            a.metric("Price", f"{price:,.2f}", f"{(price / entry - 1) * 100 * sign:+.1f}%")
            b.metric("Open R", f"{r_now:+.2f}R" if r_now == r_now else "n/a", f"${pnl:,.0f}")
            c.metric(
                "To stop",
                f"{to_stop:.1f}%" if to_stop == to_stop else "no stop",
                f"stop {stop:,.2f}" if stop == stop and stop is not None else None,
                delta_color="off",
            )
            facts = []
            if len(info):
                rule, held, hold = info.get("rule"), info.get("held"), info.get("hold")
                if rule == "hold" and hold == hold and hold:
                    facts.append(
                        f"Plan: sell at the close after {int(hold)} sessions · day "
                        f"{int(held)} of {int(hold)}"
                    )
                elif rule == "trail_ma20":
                    facts.append("Plan: trail the 20-day MA, out on a close under it")
                elif rule == "cover_ma20":
                    facts.append("Plan: cover on a close over the 20-day MA")
                action = info.get("action")
                if isinstance(action, str) and action:
                    facts.append(f"**⚠️ {action}**")
                earn = info.get("earnings")
                if earn is not None and not pd.isna(earn):
                    facts.append(f"📅 Earnings {earn}")
            if facts:
                st.markdown("\n".join(f"- {f}" for f in facts))
            st.button("📈 Chart", key=f"pos_{n}_chart", on_click=open_chart, args=(t,))
