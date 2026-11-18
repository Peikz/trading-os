"""The Practice page (øvebane, Emil, 16 Nov 2026; v2 17 Nov 2026): a past signal, the chart up to
the entry, a card of facts known at the entry, and four answers (Skip / 1 / 2 / 3). After the
answer the whole trade is shown. The numbers (and the pools) live in `trading_os.practice`;
this file is only the page.

The chart is the Chart page's: the same Plotly figure builder (`interactive_chart.daily_figure`,
candles, volume, the Indicators menu's lines) and the same drawing component (`chart_draw`). The
lines you draw are saved per signal (`trading_os.practice_drawings`), apart from the real
stocks' chart marks. "Show stock and date" puts the ticker, real dates and real prices on the
chart (rebuilt from the entry date, the NYSE calendar and the entry price); off, it is relative
days and prices with the entry at 100.
"""

from __future__ import annotations

import contextlib
import html as htmllib
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import ui
from chart_draw import chart_draw

from trading_os import interactive_chart as ichart
from trading_os import practice
from trading_os import practice_drawings as drawings

POOL_LABELS = {"practice": "Practice 2016-21", "exam": "Exam 2022-26"}
# The Chart page's lines. MA200 is left out: the practice window is 130 bars before the entry.
LINES = ["MA10", "MA20", "MA50", "EMA9", "EMA21"]
CHART_HEIGHT = 400
VISIBLE_BEFORE = 90  # bars before the entry in view when the chart opens
VISIBLE_AFTER_REVEAL = 60

CSS = """<style>
.st-key-practice_buttons [data-testid="stHorizontalBlock"],
.st-key-practice_tools [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem}
.st-key-practice_buttons [data-testid="stColumn"],
.st-key-practice_tools [data-testid="stColumn"]{min-width:0!important;flex:1 1 0!important}
.st-key-practice_buttons button,.st-key-practice_tools button{min-height:3rem;font-size:1.05rem}
.pr-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.35rem .8rem;
  margin:.3rem 0 .6rem}
.pr-grid div{border-bottom:1px solid #1C2028;padding:.1rem 0}
.pr-grid small{display:block;opacity:.65;font-size:.72rem}
</style>"""


@st.cache_data(show_spinner=False)
def _signals(folder: str) -> pd.DataFrame:
    return practice.load_signals(Path(folder))


@st.cache_data(show_spinner=False, max_entries=64)
def _bars(folder: str, signal_id: str) -> pd.DataFrame:
    return practice.load_bars(Path(folder), signal_id)


def _day_label(rel: int) -> str:
    return "day 0" if rel == 0 else f"day {rel:+d}"


def price_maps(row: pd.Series, shown: bool):
    """(chart price from a normalised one, and back): dollars when the stock is shown, else the
    data's own entry = 100."""
    if shown:
        return (
            lambda v: practice.real_price(v, row["price"]),
            lambda v: practice.normalised_price(v, row["price"]),
        )
    return (lambda v: v), (lambda v: v)


def chart_frame(bars: pd.DataFrame, row: pd.Series, shown: bool):
    """The bars as the chart draws them: (frame with `session_date` = the relative day, x
    labels by relative day). Shown: dates from the NYSE calendar and dollars; hidden: "day -3"
    and the entry at 100."""
    b = bars.sort_values("rel_day").reset_index(drop=True)
    rels = b["rel_day"].astype(int).tolist()
    if shown:
        names = [t.strftime("%Y-%m-%d") for t in practice.session_dates(row["entry_date"], rels)]
    else:
        names = [_day_label(r) for r in rels]
    to_price, _ = price_maps(row, shown)
    frame = pd.DataFrame({"session_date": rels, "volume": b["volume"].fillna(0).astype(float)})
    for col in ("open", "high", "low", "close"):
        frame[col] = to_price(b[col].astype(float))
    return frame, dict(zip(rels, names, strict=True))


def _mark(fig, frame, names, rel, text, above, colour) -> None:
    hit = frame[frame["session_date"] == rel]
    if hit.empty:
        return
    price = float(hit["high"].iloc[0] * 1.01 if above else hit["low"].iloc[0] * 0.99)
    fig.add_trace(
        go.Scatter(
            x=[names[rel]],
            y=[price],
            mode="markers+text",
            text=[text],
            textposition="top center" if above else "bottom center",
            marker={
                "symbol": "triangle-down" if above else "triangle-up",
                "size": 11,
                "color": colour,
            },
            hoverinfo="skip",
            showlegend=False,
        ),
        row=1,
        col=1,
    )


def figure(row, bars, *, answered, shown, picked, marks, height=CHART_HEIGHT):
    """The Chart page's figure for one signal. Returns (figure, x labels by relative day)."""
    frame, names = chart_frame(bars, row, shown)
    to_price, _ = price_maps(row, shown)
    fig = ichart.daily_figure(
        frame,
        title="",
        overlays=picked,
        levels={"entry": float(to_price(100.0)), "stop": float(to_price(100 - row["stop_pct"]))},
        height=height,
        x_labels=list(names.values()),
    )
    _mark(fig, frame, names, 0, "entry", False, "#2da44e")
    hold = int(row["hold_days"])
    if answered and hold > 0:
        _mark(fig, frame, names, hold, "exit", True, "#d1d4dc")
    for shape in drawings.shapes(
        marks.to_dict("records"), names, to_price, int(frame["session_date"].max())
    ):
        fig.add_shape(shape)
    first = VISIBLE_AFTER_REVEAL if answered else VISIBLE_BEFORE
    start = int((frame["session_date"] < -first).sum())
    fig.update_xaxes(range=[start - 0.5, len(frame) + 2.5])
    fig.update_layout(
        margin={"l": 10, "r": 10, "t": 30, "b": 10},  # no title: the header has it
        # right-anchored: the Chart page's x=0.3 legend pushes a wide right margin on a phone
        legend={"orientation": "h", "x": 1, "xanchor": "right", "y": 1.02, "yanchor": "bottom"},
    )
    fig.update_layout(
        uirevision=f"{row['signal_id']}|{answered}|{shown}",
        editrevision="|".join(sorted(str(m) for m in marks["mark_id"])),
    )
    return fig, names


def _facts_html(row: pd.Series) -> str:
    cells = "".join(
        f"<div><small>{htmllib.escape(k)}</small>{htmllib.escape(v)}</div>"
        for k, v in practice.card_facts(row)
    )
    return f'<div class="pr-grid">{cells}</div>'


def _shown_now(pool: str) -> bool:
    return bool(st.session_state.get(f"pr_shown_{pool}", pool == "practice"))


def _remember_shown(pool: str) -> None:
    st.session_state[f"pr_shown_{pool}"] = bool(st.session_state[f"pr_shown_w_{pool}"])


def _answer(data_dir: Path, signals: pd.DataFrame, pool: str, choice: str) -> None:
    sid = st.session_state[f"pr_cur_{pool}"]
    note = st.session_state.get(f"pr_note_cur_{sid}", "")
    with contextlib.suppress(practice.AlreadyAnswered):  # a double click: the first answer stands
        practice.save_answer(
            data_dir, signals, sid, pool, choice, note=note, shown=_shown_now(pool)
        )
    st.session_state[f"pr_done_{pool}"] = st.session_state.get(f"pr_done_{pool}") or choice


def _next(pool: str) -> None:
    st.session_state[f"pr_cur_{pool}"] = None
    st.session_state[f"pr_done_{pool}"] = None


def _save_note(data_dir: Path, sid: str, widget_key: str) -> None:
    practice.save_note(data_dir, sid, st.session_state.get(widget_key, ""))
    st.session_state["pr_note_saved"] = sid


def _r(x: float | None, digits: int = 2) -> str:
    return "–" if x is None else f"{x:+.{digits}f} R"


def trade_view(data_dir, row, *, answered, shown, picked, view, actions=None) -> None:
    """The chart (drawable, lines saved per signal), the line list and a note box of one signal.
    `view`: "cur" for the signal being practised, "rev" for an answered one opened again.
    `actions`: drawn under the note, above the line list (the answer buttons)."""
    sid = row["signal_id"]
    bars = practice.visible_bars(_bars(str(data_dir), sid), answered)
    marks = drawings.current(data_dir, sid)
    if shown:
        st.markdown(
            f"**{htmllib.escape(str(row['ticker']))}** · {htmllib.escape(row['setup_name'])}"
        )
    fig, names = figure(row, bars, answered=answered, shown=shown, picked=picked, marks=marks)
    _, to_norm = price_maps(row, shown)
    report = chart_draw(
        fig,
        ticker=sid,
        config=ichart.SAVE_CONFIG,
        key=f"pr_chart_{view}_{sid}",
        height=CHART_HEIGHT,
    )
    seq_key = f"pr_seq_{view}_{sid}"
    if report and report.get("seq") != st.session_state.get(seq_key):
        st.session_state[seq_key] = report["seq"]  # each report is saved once
        if any(drawings.apply_drawn(data_dir, sid, report, names, to_norm).values()):
            st.rerun()
    st.caption(
        "Pan and zoom like the Chart page. The line tool (top right of the chart) draws a "
        "trend line that is saved for this signal; drag it to move it, or click it and use "
        "the eraser."
    )
    st.markdown(_facts_html(row), unsafe_allow_html=True)
    st.text_area(
        "Note",
        value=practice.current_notes(data_dir).get(sid, ""),
        key=f"pr_note_{view}_{sid}",
        height=90,
        placeholder="Why this call? Saved with your answer; you can edit it afterwards.",
    )
    if answered:
        st.button(
            "Save note",
            key=f"pr_note_btn_{view}_{sid}",
            on_click=_save_note,
            args=(data_dir, sid, f"pr_note_{view}_{sid}"),
            width="stretch",
        )
        if st.session_state.get("pr_note_saved") == sid:
            st.caption("Note saved.")
    if actions:
        actions()
    with st.expander("Horizontal lines and saved lines"):
        rels = sorted(names)
        lo, hi = max(rels[0], -VISIBLE_BEFORE), rels[-1]
        to_price, _ = price_maps(row, shown)
        price = st.number_input(
            "Price" if shown else "Price (entry = 100)",
            min_value=0.0,
            value=round(float(to_price(100.0)), 2),
            step=0.01,
            format="%.2f",
            key=f"pr_lvl_{view}_{sid}",
        )
        if st.button("＋ Horizontal line", key=f"pr_lvl_add_{view}_{sid}", width="stretch"):
            try:
                drawings.add_level(data_dir, sid, to_norm(price), lo, hi)
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))
        if not len(marks):
            st.caption("No lines yet.")
        for m in marks.to_dict("records"):
            a, b = st.columns([5, 1], vertical_alignment="center")
            a.markdown(drawings.describe(m))
            if b.button("✕", key=f"pr_rm_{view}_{m['mark_id']}", help="Remove", width="stretch"):
                drawings.remove(data_dir, m["mark_id"], sid)
                st.rerun()


def _split_table(split: dict) -> pd.DataFrame:
    rows = []
    for name, key in (("Blind (stock and date hidden)", "blind"), ("Shown", "shown")):
        part = split[key]
        rows.append(
            {
                "Answered with": name,
                "Answers": part["answered"],
                "Your picks / signal": _r(part["picks_r_per_signal"]),
                "Take all / signal": _r(part["equal_r_per_signal"]),
            }
        )
    return pd.DataFrame(rows)


def stats_panel(signals: pd.DataFrame, answers: pd.DataFrame, pool: str) -> None:
    s = practice.stats(signals, answers, pool)
    st.caption(f"{s['answered']} answered, {s['remaining']} left of {s['pool_size']}.")
    if not s["answered"]:
        st.write("No answers yet.")
        return
    rows = [
        {
            "Choice": "Skip" if c == "skip" else f"{c} ({practice.MULTIPLIER[c]:g}x size)",
            "Answers": s["by_choice"][c]["count"],
            "Mean net R": _r(s["by_choice"][c]["mean_r"]),
        }
        for c in practice.CHOICES
    ]
    ui.show_df(pd.DataFrame(rows), hide_index=True, width="stretch")
    a, b = st.columns(2)
    a.metric("Your picks, total", _r(s["picks_r"], 1), _r(s["picks_r_per_signal"]) + " / signal")
    b.metric("Take every signal", _r(s["equal_r"], 1), _r(s["equal_r_per_signal"]) + " / signal")
    st.caption("Picks: net R times your size (skip 0, 1 = 0.5x, 2 = 1x, 3 = 1.5x).")
    st.markdown("**Blind vs shown**")
    ui.show_df(_split_table(s["by_shown"]), hide_index=True, width="stretch")
    big, los = s["big"], s["losers"]
    st.write(
        f"Trades of 5R or more: {big['total']} shown, you took {big['taken']} and skipped "
        f"{big['skipped']}. Losing trades: {los['total']} shown, you took {los['taken']} and "
        f"skipped {los['skipped']}."
    )


def answered_list(data_dir, signals, answers, picked) -> None:
    """Your answered signals with their notes, newest first; one can be opened again, with its
    chart, lines and note."""
    if answers.empty:
        st.caption("Nothing answered yet.")
        return
    notes = practice.current_notes(data_dir, answers)
    cols = ["signal_id", "ticker", "setup_name", "net_r", "entry_date", "hold_days"]
    joined = answers.merge(signals[cols], on="signal_id", how="inner")
    joined = joined.sort_values("answered_at", ascending=False).reset_index(drop=True)
    table = pd.DataFrame(
        {
            "Answered": joined["answered_at"].dt.strftime("%Y-%m-%d"),
            "Pool": joined["pool"],
            "Stock": joined["ticker"],
            "Setup": joined["setup_name"],
            "Pick": joined["choice"],
            "Net R": joined["net_r"].map("{:+.2f}".format),
            "Shown": joined["shown"].map({True: "shown", False: "blind"}),
            "Note": joined["signal_id"].map(notes).fillna(""),
        }
    )
    ui.show_df(table, hide_index=True, width="stretch")
    label = {
        r.signal_id: f"{r.ticker} · {r.setup_name} · {r.answered_at:%Y-%m-%d}"
        for r in joined.itertuples()
    }
    pick = st.selectbox(
        "Open an answered signal",
        ["—", *label],
        key="pr_review_pick",
        format_func=lambda i: i if i == "—" else label[i],
    )
    if pick == "—":
        return
    row = signals[signals["signal_id"] == pick].iloc[0]
    mine = answers[answers["signal_id"] == pick].iloc[0]
    st.markdown(
        f"**{htmllib.escape(str(row['ticker']))}**, entry {row['entry_date']} · net "
        f"**{float(row['net_r']):+.2f} R** in {int(row['hold_days'])} days · your pick "
        f"{mine['choice']}"
    )
    trade_view(
        data_dir, row, answered=True, shown=_shown_now(mine["pool"]), picked=picked, view="rev"
    )


def render(data_dir: Path) -> None:
    ui.page_header(
        "Practice",
        "A past signal: the chart up to the entry and the facts known then. Pick a size "
        "(Skip, 1, 2 or 3), see how it went, and check whether your picks beat taking all.",
    )
    st.markdown(CSS, unsafe_allow_html=True)
    if not practice.available(data_dir):
        ui.empty_state(
            "No practice data yet.", "It is exported to the data repo (data/research/practice)."
        )
        return
    signals = _signals(str(data_dir))
    pool = st.segmented_control(
        "Pool",
        list(POOL_LABELS),
        format_func=POOL_LABELS.get,
        default="practice",
        key="practice_pool",
        label_visibility="collapsed",
    ) or st.session_state.get("_pr_last_pool", "practice")
    st.session_state["_pr_last_pool"] = pool
    if pool == "exam":
        st.caption(
            "Take the exam once you are ready: each signal is answered once and the result "
            "counts once. Practice first."
        )
    with st.container(key="practice_tools"):
        a, b = st.columns([13, 10], vertical_alignment="center")
        shown = a.toggle(
            "Show stock and date",
            value=_shown_now(pool),
            key=f"pr_shown_w_{pool}",
            on_change=_remember_shown,
            args=(pool,),
        )
        with b.popover("Indicators", width="stretch"):
            picked = st.multiselect(
                "Lines",
                LINES,
                default=["MA10", "MA20", "MA50"],
                key="pr_lines",
                help="MA200 needs 200 bars; the practice window has 130 before the entry.",
            )
    answers = practice.load_answers(data_dir)
    cur_key, done_key = f"pr_cur_{pool}", f"pr_done_{pool}"
    st.session_state.setdefault(done_key, None)
    if st.session_state.get(cur_key) is None:
        st.session_state[cur_key] = practice.next_signal(signals, answers, pool)
    sid = st.session_state[cur_key]
    if sid is None:
        st.success("Every signal in this pool is answered.")
    else:
        row = signals[signals["signal_id"] == sid].iloc[0]
        choice = st.session_state[done_key]

        def actions() -> None:
            if choice is None:
                with st.container(key="practice_buttons"):
                    cols = st.columns(4)
                    for col, c in zip(cols, practice.CHOICES, strict=True):
                        col.button(
                            "Skip" if c == "skip" else c,
                            key=f"pr_btn_{c}",
                            on_click=_answer,
                            args=(data_dir, signals, pool, c),
                            width="stretch",
                        )
                return
            r = float(row["net_r"])
            mine = r * practice.MULTIPLIER[choice]
            st.markdown(
                f"**{htmllib.escape(str(row['ticker']))}**, entry {row['entry_date']} · "
                f"net **{r:+.2f} R** in {int(row['hold_days'])} days · your pick "
                f"{'skip' if choice == 'skip' else choice} = {mine:+.2f} R"
            )
            st.button(
                "Next", key="pr_next", on_click=_next, args=(pool,), type="primary", width="stretch"
            )

        trade_view(
            data_dir,
            row,
            answered=choice is not None,
            shown=shown,
            picked=picked,
            view="cur",
            actions=actions,
        )
    answers = practice.load_answers(data_dir)
    st.subheader("Your numbers")
    tabs = st.tabs([POOL_LABELS[p] for p in practice.POOLS])
    for tab, p in zip(tabs, practice.POOLS, strict=True):
        with tab:
            stats_panel(signals, answers, p)
    st.subheader("Your answered signals")
    answered_list(data_dir, signals, answers, picked)
