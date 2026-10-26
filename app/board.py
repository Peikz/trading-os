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

from trading_os import clock, ibd, notify, plans, report, ticket

GRADE_COLOURS = {"A+": "#1a7f37", "A": "#2da44e", "B": "#bf8700", "C": "#6e7781"}


def collect(
    runs, cfg, scan_frames: Callable[[str], dict], exchanges=None, everything: bool = False
) -> pd.DataFrame:
    """The pushed scans' alert-tier hits of the newest pre-market, 10:15, 12:00 and EOD runs,
    newest first, one row per ticker and scan. `everything`: every scan's hits, all tiers, one
    row per ticker (its best grade)."""
    latest = []
    for slot in ("pm", "am", "mid", "eod"):
        run = next((r for r in runs if r.slot == slot), None)
        if run is not None:
            latest.append(run)
    # The exchange per ticker from the newest run with a universe file (intraday runs have none)
    listing: dict = {}
    info = pd.DataFrame()
    with_universe = next((r for r in runs if r.universe.exists()), None)
    if exchanges is not None and with_universe is not None:
        listing = exchanges(str(with_universe.universe))
    if with_universe is not None:
        want = ["ticker", "sector", "industry", "float_shares", "earnings_date_next"]
        try:
            info = pd.read_parquet(with_universe.universe, columns=want).drop_duplicates("ticker")
            info = info.set_index("ticker")
        except Exception:  # noqa: BLE001 - the stats strip shows dashes
            info = pd.DataFrame()
    frames = []
    for run in sorted(latest, key=runs.index):
        for scan, hits in scan_frames(str(run.candidates)).items():
            pushed = scan in cfg.scans and cfg.scans[scan].action == "push"
            if not everything and not pushed:
                continue
            alert_only = "tier" in hits and not everything
            shown = hits[hits["tier"] == "alert"] if alert_only else hits
            if shown.empty:
                continue
            if listing and "exchange" not in shown:
                shown = shown.assign(exchange=shown["ticker"].map(listing))
            for column in info.columns:
                if column not in shown:
                    shown = shown.assign(**{column: shown["ticker"].map(info[column])})
            frames.append(
                shown.assign(
                    scan=scan, run_label=run.label, run_slot=run.slot, run_session=run.session
                )
            )
    if not frames:
        return pd.DataFrame()
    out = ibd.relabel(pd.concat(frames, ignore_index=True))
    out = out.drop_duplicates(["ticker", "scan"], keep="first")
    if "grade" not in out:
        out["grade"] = "C"
    out["grade"] = out["grade"].fillna("C")
    out["_g"] = out["grade"].map(notify.GRADE_RANK).fillna(9)
    out["_s"] = pd.to_numeric(out.get("grade_score"), errors="coerce").fillna(-1e9)
    out = out.sort_values(["_g", "_s"], ascending=[True, False])
    return out.drop_duplicates("ticker", keep="first") if everything else out


def watchlist_rows(runs, data_dir, exchanges=None) -> pd.DataFrame:
    """Your own watchlists' stocks as board rows, with the newest EOD snapshot's numbers."""
    from trading_os import my_watchlists

    members = my_watchlists.current(my_watchlists.load(data_dir))
    if members.empty:
        return pd.DataFrame()
    name_col = "list_name" if "list_name" in members else members.columns[0]
    with_universe = next((r for r in runs if r.universe.exists()), None)
    uni = pd.DataFrame()
    if with_universe is not None:
        uni = pd.read_parquet(with_universe.universe).drop_duplicates("ticker").set_index("ticker")
    rows = []
    for m in members.to_dict("records"):
        t = str(m["ticker"])
        base = uni.loc[t].to_dict() if t in uni.index else {}
        rows.append(
            {
                **base,
                "ticker": t,
                "scan": "watchlist",
                "grade": "–",
                "run_label": f"watchlist: {m.get(name_col)}",
                "run_slot": "eod",
                "run_session": with_universe.session if with_universe else None,
            }
        )
    return pd.DataFrame(rows).drop_duplicates("ticker")


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
        st.caption("Not graded A+ / A / B: sized as a B for reference (no study edge).")
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
        lines = notify.grade_lines(row) if grade in ("A+", "A", "B") else []
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


def _jump(i: int) -> None:
    st.session_state["board_i"] = i


def _flip_timeframe() -> None:
    st.session_state["fc_tf"] = "1W" if st.session_state.get("fc_tf", "1D") == "1D" else "1D"


def _toggle(key: str) -> None:
    st.session_state[key] = not st.session_state.get(key, False)


def _money(x) -> str:
    if x is None or pd.isna(x):
        return "–"
    x = float(x)
    return f"${x / 1e9:.1f}B" if x >= 1e9 else f"${x / 1e6:.0f}M" if x >= 1e6 else f"${x:,.0f}"


def stats_strip(row) -> None:
    """The key stats under the chart (Emil, 26 Oct 2026: like TradingView's data panel and what
    Qullamaggie reads out): market cap, ADR, dollar volume, float, % from the 52-week high, RS,
    the industry, earnings."""

    def num(k):
        v = row.get(k)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    chips = [("Mkt cap", _money(num("market_cap")))]
    adr = num("adr20_pct")
    chips.append(("ADR", f"{adr:.1f}%" if adr is not None else "–"))
    chips.append(("$ vol 20d", _money(num("avg_dollar_volume_20d"))))
    fl = num("float_shares")
    chips.append(("Float", f"{fl / 1e6:,.0f}M" if fl is not None else "–"))
    hi = num("pct_from_52w_high")
    chips.append(("From 52w high", f"{hi:+.0f}%" if hi is not None else "–"))
    rs = num("rs_pct")
    chips.append(("RS", f"{rs:.0f}" if rs is not None else "–"))
    rank, of = num("industry_rank"), num("industry_of")
    ind = row.get("industry") if isinstance(row.get("industry"), str) else ""
    chips.append(("Industry", f"{ind} #{int(rank)}/{int(of)}" if rank and of else ind or "–"))
    soon = num("earnings_in_sessions")
    nxt = row.get("earnings_date_next")
    if soon is not None:
        chips.append(("Earnings", f"in {int(soon)} sessions"))
    elif nxt is not None and not pd.isna(nxt):
        chips.append(("Earnings", f"{pd.Timestamp(nxt):%d %b}"))
    html = " ".join(
        f"<span style='display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;"
        f"border:1px solid #30363d;border-radius:6px;font-size:.85em'>"
        f"<span style='opacity:.6'>{k}</span> <b>{v}</b></span>"
        for k, v in chips
    )
    st.html(html.replace("$", "&#36;"))  # plain HTML: a $ would start math in markdown


FLAGS = {"🟥": "Flag red", "🟨": "Flag yellow", "🟩": "Flag green"}


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
    mine = stock_notes.current(data_dir, t)
    for n in mine.tail(3).to_dict("records")[::-1] if len(mine) else []:
        st.caption(f"{n.get('note_date')}: {n.get('text')}")
    levels = {k: row.get(k) for k in ("pivot", "plan_entry", "plan_stop")}
    default = next((float(v) for v in levels.values() if v is not None and v == v and v), 0.0)
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
    a, b = st.columns([1, 4])
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

    cols = st.columns(4)
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
    scope = more.selectbox(
        "Show",
        scopes,
        key="board_scope",
        label_visibility="collapsed",
        help="C: no edge after costs. Every scan hit: all scans and tiers",
    )
    if scope == "My watchlists":
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
    prev, where, nxt = st.columns([1, 2, 1])
    prev.button(
        "◀ Previous",
        key="board_prev",
        shortcut="Left",
        on_click=_step,
        args=(pages if mode == "Grid" else len(rows), -1),
        width="stretch",
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
        "Next ▶",
        key="board_next",
        shortcut="Right",
        on_click=_step,
        args=(pages if mode == "Grid" else len(rows), 1),
        width="stretch",
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
            ibd.words(ibd_info["state"], ibd_info["dist_count"]) if ibd_info else "n/a",
            ibd.sell_days(ibd_info["state"], ibd_info["dist_count"]) if ibd_info else None,
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
