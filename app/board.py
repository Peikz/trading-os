"""The candidate board (Emil, 26 Oct 2026: the dashboard as the only tool, Saxo for execution).

One card per signal from the latest runs: A+, A and B first (C only on request), each with the
grade, the setup, when and how to buy, the plan's numbers and its tags. The 🎫 ticket opens the
Saxo order with the plan's order type by default and any other on a switch; every value has a
copy button (st.code), and "Placed" saves it as a plan so the fill matches up later. Nothing is
sent to Saxo.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st

from trading_os import board_data, positions_view, report, ticket

GRADE_COLOURS = {"A+": "#1a7f37", "A": "#2da44e", "B": "#bf8700", "C": "#6e7781"}


def _version(path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def collect(
    runs, cfg, scan_frames: Callable[[str], dict], exchanges=None, everything: bool = False
) -> pd.DataFrame:
    """`_collect`, cached until a run file changes: building it took ~0.3 s on every click
    (Emil, 28 Oct 2026: faster dashboard)."""
    version = tuple((str(r.candidates), _version(r.candidates), _version(r.universe)) for r in runs)
    return _collect_cached(version, everything, runs, cfg, scan_frames, exchanges)


@st.cache_data(ttl=600, show_spinner=False, max_entries=8)
def _collect_cached(version, everything, _runs, _cfg, _scan_frames, _exchanges) -> pd.DataFrame:
    return _collect(_runs, _cfg, _scan_frames, _exchanges, everything)


# The queue, card facts, stats and tiles are computed in the package (React dashboard, Nov
# 2026): the API shows the same board.
_collect = board_data.collect
_tags = board_data.tags
_history = board_data.history
_money = board_data.money
_tiles = board_data.tiles


def watchlist_rows(runs, data_dir, exchanges=None) -> pd.DataFrame:
    """Your own watchlists' stocks as board rows (`board_data.watchlist_rows`)."""
    return board_data.watchlist_rows(runs, data_dir)


# A screen's results and the Saxo ticket's sizing live in the package too (React dashboard,
# Nov 2026): both dashboards show the same ticket.
ticker_rows = board_data.ticker_rows
_plan_session = board_data.plan_session
PRICE_LABELS = board_data.PRICE_LABELS


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
    plan_price = ticket.plan_price(row, kind)
    own = b.number_input(
        PRICE_LABELS.get(kind, "Price"),
        min_value=0.0,
        value=round(plan_price, 2) if plan_price else 0.0,
        step=0.01,
        format="%.2f",
        # Per stock and order type, so it starts at that plan's price; type over it to change.
        key=f"{key}_price_{row['ticker']}_{kind}",
        help="The plan's price; type your own to recompute the shares.",
    )
    if account is None or not usd_rate:
        st.caption(board_data.NO_ACCOUNT)
        return
    if not board_data.risk_mult(row, cfg)[1]:
        st.caption(board_data.UNGRADED_NOTE)
    t = board_data.make_ticket(row, kind, cfg, account, usd_rate, own or None)
    if t is None:
        st.warning(board_data.NO_TICKET)
        return
    if t.when:
        st.markdown(f"**When:** {t.when}")
    for label, value in t.lines():  # one column, in the order Saxo's ticket asks for them
        st.caption(label)
        st.code(value, language=None)
    st.caption(board_data.ticket_caption(t, usd_rate, account.currency))
    if st.button("✅ Placed in Saxo: save as plan", key=f"{key}_placed"):
        try:
            board_data.place_plan(data_dir, row, cfg, t, kind)
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
        facts = board_data.card_facts(row)
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


def _everything() -> None:
    """From the push view to every hit of the latest runs; the push link is cleared."""
    st.query_params.clear()
    st.session_state["board_scope"] = "Every scan hit"
    st.session_state["board_i"] = 0


def _jump(i: int) -> None:
    st.session_state["board_i"] = i


def _flip_timeframe() -> None:
    st.session_state["fc_tf"] = "1W" if st.session_state.get("fc_tf", "1D") == "1D" else "1D"


def _toggle(key: str) -> None:
    st.session_state[key] = not st.session_state.get(key, False)


def stats_strip(row) -> None:
    """The key stats under the chart (Emil, 26 Oct 2026: like TradingView's data panel and what
    Qullamaggie reads out): market cap, ADR, dollar volume, float, % from the 52-week high, RS,
    the industry, earnings."""

    chips = board_data.key_stats(row)
    html = " ".join(
        f"<span style='display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;"
        f"border:1px solid #30363d;border-radius:6px;font-size:.85em'>"
        f"<span style='opacity:.6'>{k}</span> <b>{v}</b></span>"
        for k, v in chips
    )
    st.html(html.replace("$", "&#36;"))  # plain HTML: a $ would start math in markdown


FLAGS = board_data.FLAGS


def notes_and_alerts(row, data_dir) -> None:
    """Flags (to the matching watchlist), a note, and a price alert for the stock in focus."""
    from trading_os import alerts, my_watchlists, stock_notes

    t = str(row["ticker"])
    cols = st.columns(3)
    for col, (icon, name) in zip(cols, FLAGS.items(), strict=True):
        if col.button(icon, key=f"flag_{name}_{t}", help=f"Add to '{name}'", width="stretch"):
            my_watchlists.add(data_dir, name, [t])
            st.toast(f"{t} → {name}")
    st.caption("F flags green. The flags are watchlists (Watchlists page).")
    with st.form(f"note_{t}", clear_on_submit=True):
        text = st.text_area(
            "Note",
            key=f"note_text_{t}",
            height=80,
            placeholder="N jumps here. What you see in this chart…",
        )
        if st.form_submit_button("Save note") and text.strip():
            stock_notes.add(data_dir, t, text.strip())
            st.toast("Note saved")
    for n in stock_notes.latest(data_dir, t).to_dict("records"):
        st.caption(f"{n.get('note_date')}: {n.get('text')}")
    default = board_data.alert_default(row)
    with st.form(f"alert_{t}", clear_on_submit=False):
        a, b = st.columns(2)
        level = a.number_input(
            "Alert price", min_value=0.0, value=default, step=0.01, format="%.2f", key=f"al_lvl_{t}"
        )
        side = b.selectbox("When", alerts.DIRECTIONS, key=f"al_dir_{t}")
        if st.form_submit_button("🔔 Add price alert") and level > 0:
            alerts.add(data_dir, t, float(level), side, "from the focus view")
            st.toast(f"Alert: {t} {side} {level:.2f} (pushed to your phone when hit)")
    own = alerts.current(data_dir)
    own = own[own["ticker"] == t] if len(own) else own
    for a_ in own.to_dict("records") if len(own) else []:
        st.caption(f"🔔 {a_['direction']} {a_['level']:.2f}")


def candidate_list(rows: list[dict], i: int) -> None:
    """The queue, TradingView watchlist style: click to jump."""
    for k, r in enumerate(rows):
        label = report.SCAN_LABELS.get(r["scan"], r["scan"])
        chg = r.get("chg_pct")
        move = f" {chg:+.1f}%" if chg is not None and chg == chg else ""
        st.button(
            f"{r.get('grade', 'C')} · {r['ticker']} · {label}{move}",
            key=f"jump_{k}",
            on_click=_jump,
            args=(k,),
            type="primary" if k == i else "secondary",
            width="stretch",
        )


def toolbar() -> tuple[str, list[str]]:
    """Bars and indicators for the focus and grid charts, remembered for the session."""
    from lwchart import DEFAULT, INDICATORS

    # Defaults through session state (the W key sets fc_tf too; a widget default would clash)
    st.session_state.setdefault("fc_tf", "1D")
    st.session_state.setdefault("fc_ind", list(DEFAULT))
    a, b = st.container(key="board_tools").columns([1, 4])
    tf = a.segmented_control("Bars", ["1D", "1W"], key="fc_tf", label_visibility="collapsed")
    picked = b.pills(
        "Indicators",
        list(INDICATORS),
        selection_mode="multi",
        key="fc_ind",
        label_visibility="collapsed",
    )
    return tf or "1D", list(picked or [])


def hotkeys(row, data_dir) -> None:
    """Hidden-ish buttons that carry the keyboard shortcuts: W bars, F green flag, N note,
    T ticket (the arrows are on ◀ ▶)."""
    from trading_os import my_watchlists

    cols = st.container(key="board_hotkeys").columns(4)
    cols[0].button("W · 1D/1W", key="hk_w", shortcut="W", on_click=_flip_timeframe, width="stretch")
    if cols[1].button("F · 🟩 flag", key="hk_f", shortcut="F", width="stretch"):
        my_watchlists.add(data_dir, FLAGS["🟩"], [str(row["ticker"])])
        st.toast(f"{row['ticker']} → {FLAGS['🟩']}")
    cols[2].button(
        "N · note", key="hk_n", shortcut="N", on_click=_toggle, args=("fc_notes",), width="stretch"
    )
    cols[3].button(
        "T · ticket",
        key="hk_t",
        shortcut="T",
        on_click=_toggle,
        args=("fc_ticket",),
        width="stretch",
    )


# The board on a phone (Emil, 28 Oct 2026): ◀ count ▶ stays one row (Streamlit stacks columns
# under 640 px), the toolbar scrolls sideways instead of wrapping, and the hotkey buttons
# (keyboard only) are hidden; the ticket, flags and notes stay in the tabs.
BOARD_CSS = """<style>
.st-key-board_nav [data-testid="stHorizontalBlock"]{flex-wrap:nowrap;gap:.5rem}
.st-key-board_nav [data-testid="stColumn"]{min-width:0!important;flex:1 1 0!important}
.st-key-board_nav [data-testid="stColumn"]:nth-child(2){flex:2 1 0!important}
@media (max-width:640px){
.st-key-board_hotkeys{display:none}
.st-key-board_tools [data-testid="stHorizontalBlock"]{flex-wrap:nowrap;gap:.5rem}
.st-key-board_tools [data-testid="stColumn"]{min-width:0!important;width:auto!important}
.st-key-board_tools [data-testid="stColumn"]:last-child{overflow-x:auto;flex:1 1 0!important}
.st-key-board_tools [data-testid="stColumn"]:last-child div[role="group"]{flex-wrap:nowrap}
}
</style>"""


def show(
    runs, cfg, data_dir, account, usd_rate, scan_frames, open_chart, chart, exchanges=None
) -> None:
    """The board, best first: a focus view (one candidate's chart, its key stats, its card and
    ticket, the queue, notes and alerts; arrows and hotkeys), a 2x2 grid, or the list of cards."""
    head, view, more = st.columns([2, 2, 2])
    head.subheader("Candidates")
    mode = view.segmented_control(
        "View",
        ["Focus", "Grid", "List"],
        default="Focus",
        key="board_mode",
        label_visibility="collapsed",
    )
    scopes = ["A+ / A / B", "Pushed, incl. C", "Every scan hit", "My watchlists"]
    # Opened from a push (Emil, 27 Oct 2026): ?push=ah&session=...&t=A,B shows that push's
    # stocks first, with every other hit one click away.
    from_push = [t for t in str(st.query_params.get("t", "")).split(",") if t]
    # Opened from the Screener (Emil, 29 Oct 2026): ?screen=Name&t=A,B flips through its stocks
    screen_name = str(st.query_params.get("screen", "") or "")
    pinned = f"From the screen: {screen_name}" if screen_name else "From the push"
    if from_push:
        scopes = [pinned, *scopes]
        if st.session_state.get("board_scope") not in scopes:
            st.session_state["board_scope"] = pinned
    scope = more.selectbox(
        "Show",
        scopes,
        key="board_scope",
        label_visibility="collapsed",
        help="C: no edge after costs. Every scan hit: all scans and tiers",
    )
    if scope.startswith("From the screen"):
        hits = ticker_rows(runs, from_push, f"screen: {screen_name}")
    elif scope == "From the push":
        st.button(
            "Show everything this run found",
            key="board_all_hits",
            on_click=_everything,
            help="Every scan's hits, the C strategies too",
        )
        every = collect(runs, cfg, scan_frames, exchanges, everything=True)
        order = {t: i for i, t in enumerate(from_push)}
        hits = every[every["ticker"].isin(order)] if len(every) else every
        if len(hits):
            hits = hits.assign(_o=hits["ticker"].map(order)).sort_values("_o").drop(columns="_o")
    elif scope == "My watchlists":
        hits = watchlist_rows(runs, data_dir, exchanges)
    else:
        hits = collect(runs, cfg, scan_frames, exchanges, everything=scope == "Every scan hit")
    with_c = scope != "A+ / A / B"
    if hits.empty:
        st.info(
            "No stocks in your watchlists yet: flag one here (F, or 🟥 🟨 🟩 under Notes & "
            "alerts) or add lists on the Watchlists page (also from a TradingView export)."
            if scope == "My watchlists"
            else "No signals in the latest runs."
        )
        return
    graded = hits[hits["grade"].isin(["A+", "A", "B"])]
    shown = hits if with_c else graded
    if shown.empty:
        st.info("No A+ / A / B today. Pick 'Pushed, incl. C' or more in 'Show' for the rest.")
        return
    rows = shown.to_dict("records")
    hidden = "" if with_c else f" · {len(hits) - len(graded)} C hidden"
    if mode == "List":
        st.caption(f"{len(rows)} signals{hidden}")
        for n, row in enumerate(rows):
            card(row, n, cfg, data_dir, account, usd_rate, open_chart)
        return
    per_page = 4 if mode == "Grid" else 1
    pages = (len(rows) + per_page - 1) // per_page
    page_i = st.session_state.get("board_i", 0) % (pages if mode == "Grid" else len(rows))
    st.markdown(BOARD_CSS, unsafe_allow_html=True)
    prev, where, nxt = st.container(key="board_nav").columns([1, 2, 1])
    prev.button(
        "◀",
        key="board_prev",
        shortcut="Left",
        on_click=_step,
        args=(pages if mode == "Grid" else len(rows), -1),
        width="stretch",
        help="Previous (← key)",
    )
    if mode == "Grid":
        first = page_i * 4
        where_text = f"{first + 1}-{min(first + 4, len(rows))} of {len(rows)}{hidden}"
    else:
        where_text = f"{page_i + 1} of {len(rows)}{hidden}"
    where.markdown(
        f"<div style='text-align:center;padding-top:.4rem'>{where_text}</div>",
        unsafe_allow_html=True,
    )
    nxt.button(
        "▶",
        key="board_next",
        shortcut="Right",
        on_click=_step,
        args=(pages if mode == "Grid" else len(rows), 1),
        width="stretch",
        help="Next (→ key)",
    )
    tf, picked = toolbar()
    if mode == "Grid":
        group = rows[page_i * 4 : page_i * 4 + 4]
        for pair in (group[:2], group[2:]):
            cols = st.columns(2)
            for col, row in zip(cols, pair, strict=False):
                with col:
                    grade = row.get("grade", "C")
                    label = report.SCAN_LABELS.get(row["scan"], row["scan"])
                    st.markdown(f"**{grade} · {row['ticker']}** · {label}")
                    chart(str(row["ticker"]), row, tf, picked, 330)
                    stats_strip(row)
        return
    row = rows[page_i]
    left, right = st.columns([5, 2])
    with left:
        chart(str(row["ticker"]), row, tf, picked, 520)
        stats_strip(row)
        hotkeys(row, data_dir)
    with right:
        plan_tab, list_tab, notes_tab = st.tabs(["Plan", f"List ({len(rows)})", "Notes & alerts"])
        with plan_tab:
            card(
                row,
                page_i,
                cfg,
                data_dir,
                account,
                usd_rate,
                open_chart,
                inline=st.session_state.get("fc_ticket", True),
            )
        with list_tab:
            candidate_list(rows, page_i)
        with notes_tab:
            notes_and_alerts(row, data_dir)
        if st.session_state.get("fc_notes"):
            st.info("Notes & alerts: the third tab above.")


def market_tiles(row: dict | None, ibd_info: dict | None, heat_text: str | None) -> None:
    """The market as tiles (Emil, 26 Oct 2026: tiles, not bullet text): the QQQ light, the heat,
    the IBD state, SPY, QQQ and VIX. The full lines stay in 'Market details' below."""
    if not row:
        st.info("No market row yet.")
        return
    tiles = _tiles(row, ibd_info, heat_text)
    cols = st.columns(3)
    for i, (label, value, delta) in enumerate(tiles):
        cols[i % 3].metric(
            label, value, delta, delta_color="off" if label == "IBD market" else "normal"
        )


def market_strip(row: dict | None, ibd_info: dict | None, heat_text: str | None) -> None:
    """The same tiles as one compact row of chips above the candidates (Emil, 28 Oct 2026: the
    market at a glance, also on the phone); the full tiles and lines are under 'Market'."""
    if not row:
        return
    chips = []
    for label, value, delta in _tiles(row, ibd_info, heat_text):
        colour = ""
        if delta and label != "IBD market":
            up = not delta.startswith("-")
            colour = "#3fb950" if up != (label == "VIX") else "#f85149"
        extra = f" <span style='color:{colour}'>{delta}</span>" if delta and colour else ""
        if delta and not colour:
            extra = f" <span style='opacity:.6'>{delta}</span>"
        chips.append(
            "<span style='display:inline-block;margin:2px 6px 2px 0;padding:3px 9px;"
            "border:1px solid #30363d;border-radius:8px'>"
            f"<span style='opacity:.6'>{label}</span> <b>{value}</b>{extra}</span>"
        )
    st.html(" ".join(chips).replace("$", "&#36;"))


def position_cards(
    view: pd.DataFrame, plan_check: pd.DataFrame, prices: dict, source: str, open_chart
) -> None:
    """The positions cockpit: one card per open position, with the price (live when the Alpaca
    keys are set), open R and P&L, the distance to the stop, and what the plan says today
    (the numbers: `positions_view.cards`)."""
    st.caption(f"Prices: {source}")
    for n, c in enumerate(positions_view.cards(view, plan_check, prices)):
        t, stop, r_now, to_stop = c["ticker"], c["stop"], c["open_r"], c["to_stop_pct"]
        with st.container(border=True):
            st.markdown(
                f"<b style='font-size:1.15em'>{t}</b> &nbsp;·&nbsp; {c['setup']}"
                f" &nbsp;<span style='opacity:.6'>{c['direction']} · {c['shares']:,.0f} sh"
                f" · in {c['entry_date']}</span>",
                unsafe_allow_html=True,
            )
            a, b, d = st.columns(3)
            a.metric("Price", f"{c['price']:,.2f}", f"{c['move_pct']:+.1f}%")
            b.metric("Open R", f"{r_now:+.2f}R" if r_now == r_now else "n/a", f"${c['pnl']:,.0f}")
            d.metric(
                "To stop",
                f"{to_stop:.1f}%" if to_stop == to_stop else "no stop",
                f"stop {stop:,.2f}" if stop == stop else None,
                delta_color="off",
            )
            facts = [f"**{f}**" if f.startswith("⚠️") else f for f in c["facts"]]
            if facts:
                st.markdown("\n".join(f"- {f}" for f in facts))
            st.button("📈 Chart", key=f"pos_{n}_chart", on_click=open_chart, args=(t,))
