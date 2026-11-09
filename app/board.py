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

from trading_os import board_data, dashboard, notify, positions_view, report, ticket

GRADE_COLOURS = {"A++": "#0b5a26", "A+": "#1a7f37", "A": "#2da44e", "B": "#bf8700", "C": "#6e7781"}


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


def watchlist_rows(runs, data_dir, exchanges=None, name: str | None = None) -> pd.DataFrame:
    """Your own watchlists' stocks as board rows (`board_data.watchlist_rows`); one list when
    `name` is given."""
    return board_data.watchlist_rows(runs, data_dir, name)


LIST_MARK = "📋 "  # a watchlist in Show, by its own name (Emil, 4 Nov 2026)


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


def order_block(row, key: str, cfg, data_dir, account, usd_rate) -> None:
    """The plan card's order (Emil, 4 Nov 2026 redesign): Entry, Stop, Shares and Risk first,
    then the values to type into Saxo, each with a copy button, the plan's order type by
    default; type and price change under "Edit order"."""
    values = st.container()
    default = ticket.default_type(row)
    names = list(ticket.ORDER_TYPES)
    with st.expander("Edit order", key=f"{key}_edit"):
        kind = st.selectbox(
            "Order type",
            names,
            index=names.index(default),
            key=f"{key}_type",
            format_func=lambda k: ticket.ORDER_TYPES[k] + (" (plan)" * (k == default)),
        )
        plan_price = ticket.plan_price(row, kind)
        own = st.number_input(
            PRICE_LABELS.get(kind, "Price"),
            min_value=0.0,
            value=round(plan_price, 2) if plan_price else 0.0,
            step=0.01,
            format="%.2f",
            key=f"{key}_price_{row['ticker']}_{kind}",
            help="The plan's price; type your own and the shares follow, so the risk stays.",
        )
    with values:
        if account is None or not usd_rate:
            st.caption(board_data.NO_ACCOUNT)
            return
        t = board_data.make_ticket(row, kind, cfg, account, usd_rate, own or None)
        if t is None:
            st.caption(board_data.NO_TICKET)
            return
        entry = t.trigger or t.limit or t.est_entry
        a, b = st.columns(2)
        a.metric("Entry", f"{entry:,.2f}")
        b.metric("Stop", f"{t.stop:,.2f}")
        a.metric("Shares", f"{t.shares:,}")
        b.metric("Risk", f"${t.risk_usd:,.0f}")
        if not board_data.risk_mult(row, cfg)[1]:
            st.caption(board_data.UNGRADED_NOTE)
        if st.session_state.get("fc_ticket", True):
            st.caption("Saxo order · copy each value")
            pairs = t.lines()
            for left, right in zip(pairs[0::2], pairs[1::2] + [None], strict=False):
                c1, c2 = st.columns(2)
                for col, pair in ((c1, left), (c2, right)):
                    if pair:
                        col.caption(pair[0])
                        col.code(pair[1], language=None)
            st.caption(board_data.ticket_caption(t, usd_rate, account.currency))
        placed_help = "Saves it as a plan, so your fill matches it in the Journal"
        if st.button("I placed it in Saxo", key=f"{key}_placed", width="stretch", help=placed_help):
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
    st.session_state[FULL_RERUN] = True


def _jump(i: int) -> None:
    st.session_state["board_i"] = i


def _flip_timeframe() -> None:
    # W steps day → week → month → day (monthly bars: Emil, 4 Nov 2026)
    order = ["1D", "1W", "1M"]
    now = st.session_state.get("fc_tf") or "1D"
    st.session_state["fc_tf"] = order[(order.index(now) + 1) % 3 if now in order else 0]


def _toggle(key: str) -> None:
    st.session_state[key] = not st.session_state.get(key, False)


NOTES_TAB = "Notes & alerts"


def _open_notes() -> None:
    """N opens Notes & alerts under the plan (Emil, 4 Nov 2026); pressed again it closes."""
    st.session_state["fc_notes_open"] = not st.session_state.get("fc_notes_open", False)


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
    for icon, name in FLAGS.items():
        if st.button(f"{icon} {name}", key=f"flag_{name}_{t}", help=f"Add to '{name}' (F)"):
            my_watchlists.add(data_dir, name, [t])
            st.toast(f"{t} → {name}")
    st.caption("Flag green is a watchlist: pick 📋 Flag green in Show to flip through it.")
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
    """Bars and indicators for the focus and grid charts, remembered for the session. The
    indicators sit behind one button (Emil, 4 Nov 2026 redesign: less above the chart)."""
    from lwchart import DEFAULT, INDICATORS

    # Defaults through session state (the W key sets fc_tf too; a widget default would clash)
    st.session_state.setdefault("fc_tf", "1D")
    st.session_state.setdefault("fc_ind", list(DEFAULT))
    a, b, _ = st.container(key="board_tools").columns([1.7, 1.3, 2.5])
    tf = a.segmented_control("Bars", ["1D", "1W", "1M"], key="fc_tf", label_visibility="collapsed")
    with b.popover("Indicators", width="stretch"):
        picked = st.pills(
            "Indicators",
            list(INDICATORS),
            selection_mode="multi",
            key="fc_ind",
            label_visibility="collapsed",
        )
    return tf or "1D", list(picked or [])


def hotkeys(row, data_dir, n_rows: int = 1) -> None:
    """Small buttons that carry the keyboard shortcuts: ← → flip, W bars, F watch, N note,
    T the Saxo values (hidden on a phone)."""
    from trading_os import my_watchlists

    cols = st.container(key="board_hotkeys").columns(6)
    cols[0].button("Prev", key="board_prev", shortcut="Left", on_click=_step,
                   args=(n_rows, -1), width="stretch")  # fmt: skip
    cols[1].button("Next", key="board_next", shortcut="Right", on_click=_step,
                   args=(n_rows, 1), width="stretch")  # fmt: skip
    cols[2].button("Bars", key="hk_w", shortcut="W", on_click=_flip_timeframe, width="stretch")
    if cols[3].button("Watch", key="hk_f", shortcut="F", width="stretch"):
        my_watchlists.add(data_dir, FLAGS["🟩"], [str(row["ticker"])])
        st.toast(f"{row['ticker']} → {FLAGS['🟩']}")
    cols[4].button("Note", key="hk_n", shortcut="N", on_click=_open_notes, width="stretch")
    cols[5].button(
        "Values",
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


TODAY = "Today's list"  # the default Show: to act on, your positions, watching


def plan_card(row, n: int, cfg, data_dir, account, usd_rate, open_chart) -> None:
    """The right column (Emil, 4 Nov 2026 redesign): the decision first (grade, when to buy,
    Entry / Stop / Shares / Risk, the Saxo values), then why, then watch and notes."""
    grade = row.get("grade", "C")
    section = row.get("_section", "act")
    label = report.SCAN_LABELS.get(row["scan"], row["scan"])
    colour = GRADE_COLOURS.get(grade, "#6e7781")
    lines: list[str] = []
    with st.container(border=True):
        badge = {"own": "Open position", "watch": "Watching"}.get(section, f"Grade {grade}")
        bg = {"own": "#1f6f50", "watch": "#7a5a12"}.get(section, colour)
        st.markdown(
            f"<span style='background:{bg};color:white;padding:3px 10px;border-radius:999px;"
            f"font-weight:700;font-size:.9em'>{badge}</span>&nbsp; "
            f"<span style='color:#98A2B3'>{label} · {row['run_label']}</span>",
            unsafe_allow_html=True,
        )
        if section == "own":
            st.markdown("#### Your open position")
            st.caption("Its stop, open R and what the plan says today are under Journal.")
            st.button("Open Positions", key=f"own_{n}", on_click=_go_positions, width="stretch")
            return
        if section == "watch":
            st.markdown("#### On your watchlist")
            st.caption("No setup today. It shows here while it is on Flag green.")
            return
        lines = notify.grade_lines(row) if grade in ("A++", "A+", "A", "B") else []
        when = lines[1] if len(lines) > 1 else "Not graded: no study edge"
        st.markdown(f"#### {when[:1].upper()}{when[1:]}")
        order_block(row, f"plan_{n}", cfg, data_dir, account, usd_rate)
    facts = board_data.card_facts(row)
    reasons = facts[1 + len(notify.plan_lines(row)) :] if lines else facts
    if reasons:
        with st.container(border=True):
            st.markdown(f"**Why {grade}**")
            st.markdown("\n".join(f"- {f}" for f in reasons))


def _go_positions() -> None:
    st.session_state["place"] = "Journal"
    st.session_state["tab_Journal"] = "Positions"


def _pick(i: int) -> None:
    st.session_state["board_i"] = i
    st.session_state["board_picked"] = True


def _scope(name: str) -> None:
    st.session_state["board_scope"] = name
    st.session_state["board_i"] = 0
    st.session_state[FULL_RERUN] = True


SECTIONS = [("act", "TO ACT ON"), ("own", "YOUR POSITIONS"), ("watch", "WATCHING")]
EMPTY = {
    "act": "No A+, A or B setup today.",
    "own": "No open positions.",
    "watch": "Watch a stock (F) to see it here.",
}


def queue(rows: list[dict], i: int, c_count: int) -> None:
    """The left column: TO ACT ON, YOUR POSITIONS, WATCHING (Emil, 4 Nov 2026 redesign), each
    stock one click; the C setups one click further."""
    for key, title in SECTIONS:
        members = [(k, r) for k, r in enumerate(rows) if r.get("_section", "act") == key]
        st.caption(f"**{title}** · {len(members)}")
        if not members:
            st.caption(EMPTY[key])
        for k, r in members:
            chg = r.get("chg_pct")
            move = f" · {chg:+.1f}%" if chg is not None and chg == chg else ""
            grade = r.get("grade", "C") if key == "act" else ""
            setup = report.SCAN_LABELS.get(r["scan"], r["scan"]) if key == "act" else ""
            text = " · ".join(x for x in (grade, f"**{r['ticker']}**", setup) if x) + move
            st.button(
                text,
                key=f"q_{k}",
                on_click=_pick,
                args=(k,),
                width="stretch",
                type="primary" if k == i else "secondary",
            )
    if c_count:
        st.button(
            f"{c_count} C setups saved · show them",
            key="q_c",
            type="tertiary",
            on_click=_scope,
            args=("Pushed, incl. C",),
        )


def quiet_day(n_own: int, n_watch: int) -> None:
    """No A+ / A / B today (Emil, 4 Nov 2026 redesign): a calm screen, never a dead end."""
    with st.container(border=True):
        st.markdown("### Nothing to buy today")
        own = f"{n_own} open position" + ("s" if n_own != 1 else "")
        watch = f"{n_watch} watched stock" + ("s" if n_watch != 1 else "")
        st.markdown(
            "No A+, A or B setup came up. That is a normal day: the edge is in waiting. "
            f"Your {own} and {watch} are on the left."
        )
        a, b = st.columns(2)
        a.button(
            "Show the C setups",
            key="quiet_c",
            on_click=_scope,
            args=("Pushed, incl. C",),
            width="stretch",
        )
        b.button(
            "Every scan hit",
            key="quiet_all",
            on_click=_scope,
            args=("Every scan hit",),
            width="stretch",
        )
        st.caption(
            "Next scans: 10:15 and 12:00 New York, and after the close. "
            "A push comes if anything shows up."
        )


# The new Today on a phone: the chart and the plan first, the queue after them.
TODAY_CSS = """<style>
.st-key-today_cols [data-testid="stColumn"] button p{white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.st-key-today_cols [data-testid="stMetricValue"]{font-size:1.35rem}
@media (max-width:640px){
.st-key-today_cols>div>[data-testid="stHorizontalBlock"]{flex-direction:column}
.st-key-today_cols>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(1){order:3}
.st-key-today_cols>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(2){order:1}
.st-key-today_cols>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(3){order:2}
.st-key-today_cols [data-testid="stColumn"] [data-testid="stHorizontalBlock"]{flex-direction:row;
  flex-wrap:nowrap}
.st-key-today_cols [data-testid="stColumn"] [data-testid="stColumn"]{min-width:0!important}
}
</style>"""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("s" if n != 1 else "")


def today_rows(runs, cfg, data_dir, scan_frames, exchanges) -> tuple[pd.DataFrame, int]:
    """Today's list: the A+ / A / B hits, your open positions, your Flag green list (each row
    tagged with its `_section`), and how many C hits were left out."""
    found = collect(runs, cfg, scan_frames, exchanges)
    graded = found[found["grade"].isin(["A++", "A+", "A", "B"])] if len(found) else found
    parts = [graded.assign(_section="act")] if len(graded) else []
    held = dashboard.latest_positions(data_dir)
    if len(held) and "ticker" in held:
        own = ticker_rows(runs, list(held["ticker"]), "your position")
        parts.append(own.assign(_section="own"))
    watch = watchlist_rows(runs, data_dir, exchanges, FLAGS["🟩"])
    if len(watch):
        parts.append(watch.assign(_section="watch"))
    rows = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return rows, len(found) - len(graded)


# The view and the list sit outside the board fragment (Emil, 4 Nov 2026: Grid, List and Show
# did nothing). A full rerun re-registers the fragment, so a stale one (the browser sends an id
# the server no longer has, e.g. after the laptop's network slept) heals the moment either changes.
FULL_RERUN = "board_full_rerun"  # set by a callback in the fragment that changes the list


def _from_push() -> tuple[list[str], str, str]:
    """A push link (?push=ah&session=...&t=A,B; Emil, 27 Oct 2026) or a Screener link
    (?screen=Name&t=A,B; 29 Oct 2026): its stocks, the screen's name, and the list's label."""
    from_push = [t for t in str(st.query_params.get("t", "")).split(",") if t]
    screen_name = str(st.query_params.get("screen", "") or "")
    pinned = f"From the screen: {screen_name}" if screen_name else "From the push"
    return from_push, screen_name, pinned


def controls(data_dir) -> None:
    """Today's title row: the heading, the view (Focus, Grid, List) and the list (Show). Called
    outside the fragment, so changing either reruns the whole page."""
    lists = board_data.watchlist_names(data_dir)
    scopes = [TODAY, "Pushed, incl. C", "Every scan hit", *(LIST_MARK + n for n in lists)]
    from_push, _, pinned = _from_push()
    if from_push:
        scopes = [pinned, *scopes]
        if st.session_state.get("board_scope") not in scopes:
            st.session_state["board_scope"] = pinned
    if st.session_state.get("board_scope") not in scopes:
        st.session_state["board_scope"] = TODAY
    title, view, more = st.columns([3, 2, 2], vertical_alignment="center")
    title.header("Today")
    view.segmented_control(
        "View",
        ["Focus", "Grid", "List"],
        default="Focus",
        key="board_mode",
        label_visibility="collapsed",
    )
    more.selectbox(
        "Show",
        scopes,
        key="board_scope",
        label_visibility="collapsed",
        help="Today's list: to act on, your positions, watching. C: no edge after costs.",
    )


def show(
    runs, cfg, data_dir, account, usd_rate, scan_frames, open_chart, chart, exchanges=None
) -> None:
    """Today (Emil, 4 Nov 2026 redesign): the queue on the left (to act on, your positions,
    watching), the chart in the middle, the plan on the right with the decision first. Grid and
    List show several at once; Show picks another list (C setups, every hit, a watchlist). The
    view and the list come from `controls`, drawn above this fragment."""
    if st.session_state.pop(FULL_RERUN, False):
        st.rerun(scope="app")  # the list changed: redraw Show too
    from_push, screen_name, _ = _from_push()
    mode = st.session_state.get("board_mode") or "Focus"
    scope = st.session_state.get("board_scope", TODAY)
    c_count = 0
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
    elif scope.startswith(LIST_MARK):
        hits = watchlist_rows(runs, data_dir, exchanges, scope.removeprefix(LIST_MARK))
    elif scope == TODAY:
        hits, c_count = today_rows(runs, cfg, data_dir, scan_frames, exchanges)
    else:
        hits = collect(runs, cfg, scan_frames, exchanges, everything=scope == "Every scan hit")
    sections = hits["_section"] if "_section" in hits else pd.Series(dtype=str)
    if scope == TODAY:
        n_act, n_own = int((sections == "act").sum()), int((sections == "own").sum())
        n_watch = int((sections == "watch").sum())
        act_words = _plural(n_act, "setup") + " to act on" if n_act else "Nothing to buy"
        st.markdown(
            f"<span style='color:#98A2B3;font-size:1.05rem'>{act_words} · "
            f"{_plural(n_own, 'position')} · {n_watch} on watch</span>",
            unsafe_allow_html=True,
        )
    if hits.empty and scope != TODAY:
        st.info(
            "This watchlist is empty: flag a stock here (F, or 🟩 under Notes & alerts) "
            "or add to it on the Watchlists page (also from a TradingView export)."
            if scope.startswith(LIST_MARK)
            else "No signals in the latest runs."
        )
        return
    rows = hits.to_dict("records") if len(hits) else []
    if mode == "List":
        st.caption(f"{len(rows)} signals")
        for n, row in enumerate(rows):
            card(row, n, cfg, data_dir, account, usd_rate, open_chart)
        return
    st.markdown(BOARD_CSS, unsafe_allow_html=True)
    if mode == "Grid":
        if not rows:
            st.info("Nothing in this list.")
            return
        pages = (len(rows) + 3) // 4
        page_i = st.session_state.get("board_i", 0) % pages
        first = page_i * 4
        prev, where, nxt = st.container(key="board_nav").columns([1, 2, 1])
        prev.button(
            "◀",
            key="board_prev",
            shortcut="Left",
            on_click=_step,
            args=(pages, -1),
            width="stretch",
            help="Previous (← key)",
        )
        where.markdown(
            f"<div style='text-align:center;padding-top:.4rem'>"
            f"{first + 1}-{min(first + 4, len(rows))} of {len(rows)}</div>",
            unsafe_allow_html=True,
        )
        nxt.button(
            "▶",
            key="board_next",
            shortcut="Right",
            on_click=_step,
            args=(pages, 1),
            width="stretch",
            help="Next (→ key)",
        )
        tf, picked = toolbar()
        group = rows[first : first + 4]
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

    # Focus: queue · chart · plan
    st.markdown(TODAY_CSS, unsafe_allow_html=True)
    n_rows = max(len(rows), 1)
    page_i = st.session_state.get("board_i", 0) % n_rows
    has_act = bool((sections == "act").any()) if scope == TODAY else bool(rows)
    quiet = scope == TODAY and not has_act and not st.session_state.get("board_picked")
    left, middle, right = st.container(key="today_cols").columns([1.15, 3.3, 1.75])
    with left:
        if scope == TODAY:
            queue(rows, -1 if quiet else page_i, c_count)
        else:
            st.caption(f"**{scope.upper()}** · {len(rows)}")
            candidate_list(rows, page_i)
    if quiet or not rows:
        with middle:
            quiet_day(int((sections == "own").sum()), int((sections == "watch").sum()))
        return
    row = rows[page_i]
    with middle:
        chg = row.get("chg_pct")
        close = row.get("close")
        price = f"{close:,.2f}" if isinstance(close, float) and close == close else ""
        move = ""
        if chg is not None and chg == chg:
            colour = "#2BC48A" if chg >= 0 else "#F0616D"
            move = f"<span style='color:{colour};font-weight:600'>{chg:+.1f}%</span>"
        st.markdown(
            "<div style='display:flex;align-items:baseline;gap:12px;flex-wrap:wrap'>"
            "<span style='font-size:1.7rem;font-weight:700;letter-spacing:-.02em'>"
            f"{row['ticker']}</span><span style='font-size:1.15rem;font-weight:600'>{price}"
            f"</span>{move}<span style='color:#98A2B3'>{page_i + 1} of {len(rows)}</span></div>",
            unsafe_allow_html=True,
        )
        tf, picked = toolbar()
        chart(str(row["ticker"]), row, tf, picked, 470)
        stats_strip(row)
        hotkeys(row, data_dir, len(rows))
    with right:
        plan_card(row, page_i, cfg, data_dir, account, usd_rate, open_chart)
        a, b = st.columns(2)
        if a.button("☆ Watch (F)", key=f"watch_{row['ticker']}", width="stretch"):
            from trading_os import my_watchlists

            my_watchlists.add(data_dir, FLAGS["🟩"], [str(row["ticker"])])
            st.toast(f"{row['ticker']} → {FLAGS['🟩']}")
        b.button(
            "Full chart",
            key=f"full_{row['ticker']}",
            on_click=open_chart,
            args=(row["ticker"],),
            width="stretch",
        )
        st.session_state.setdefault("fc_notes_open", False)
        with st.expander(NOTES_TAB, key="fc_notes_open"):
            notes_and_alerts(row, data_dir)


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
