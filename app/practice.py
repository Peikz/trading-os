"""The Practice page (øvebane, Emil, 16 Nov 2026): a blind past signal, the chart up to the
entry, a card of facts known at the entry, and four answers (Skip / 1 / 2 / 3). After the
answer the whole trade is shown. The numbers (and the pools) live in `trading_os.practice`;
this file is only the page. Tickers and dates stay hidden until the answer.
"""

from __future__ import annotations

import contextlib
import html as htmllib
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from lwchart import LIB

from trading_os import practice

POOL_LABELS = {"practice": "Practice 2016-21", "exam": "Exam 2022-26"}
BASE = 86400 * 20000  # synthetic day 0; one chart "day" is one session (rel_day)

CSS = """<style>
.st-key-practice_buttons [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem}
.st-key-practice_buttons [data-testid="stColumn"]{min-width:0!important;flex:1 1 0!important}
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


def chart_html(bars: pd.DataFrame, stop_pct: float, hold_days: int | None, height: int) -> str:
    """Candles and volume against relative days (0 = the entry session), prices with the entry
    at 100. `bars` is already filtered by `practice.visible_bars`. The entry and the stop are
    price lines; once the entry session is in `bars` it is marked, and so is the exit."""
    b = bars.sort_values("rel_day")
    t = (BASE + b.rel_day.astype(int) * 86400).tolist()
    candles = [
        {"time": a, "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}
        for a, o, h, lo, c in zip(t, b.open, b.high, b.low, b.close, strict=True)
    ]
    volume = [
        {"time": a, "value": float(v), "color": "#26a69a55" if c >= o else "#ef535055"}
        for a, v, o, c in zip(t, b.volume.fillna(0), b.open, b.close, strict=True)
    ]
    rels = set(b.rel_day.astype(int))
    markers = []
    if 0 in rels:
        markers.append({"time": BASE, "position": "belowBar", "color": "#2da44e", "text": "entry"})
    if hold_days and hold_days in rels and hold_days > 0:
        markers.append(
            {
                "time": BASE + hold_days * 86400,
                "position": "aboveBar",
                "color": "#d1d4dc",
                "text": "exit",
            }
        )
    data = json.dumps(
        {
            "candles": candles,
            "volume": volume,
            "markers": markers,
            "stop": 100.0 - float(stop_pct),
            "base": BASE,
            "last": int(b.rel_day.max()),
            "first": int(b.rel_day.min()),
        }
    )
    return f"""<div style="position:relative;width:100%;height:{height}px">
<div id="c" style="width:100%;height:{height}px"></div>
<div id="lg" style="position:absolute;left:6px;top:4px;z-index:5;pointer-events:none;
  font:11px -apple-system,Segoe UI,Roboto,sans-serif;color:#d1d4dc"></div></div>
<script src="{LIB}"></script>
<script>
const d = {data};
const day = t => Math.round((t - d.base) / 86400);
const chart = LightweightCharts.createChart(document.getElementById('c'), {{
  autoSize: true,
  layout: {{background: {{color: '#0e1117'}}, textColor: '#d1d4dc'}},
  grid: {{vertLines: {{color: '#1e222d'}}, horzLines: {{color: '#1e222d'}}}},
  rightPriceScale: {{scaleMargins: {{top: 0.08, bottom: 0.25}}}},
  timeScale: {{rightOffset: 3, tickMarkFormatter: t => String(day(t)), timeVisible: false}},
  localization: {{timeFormatter: t => 'day ' + day(t)}},
  crosshair: {{mode: 0}},
}});
const s = chart.addCandlestickSeries({{upColor: '#26a69a', downColor: '#ef5350',
  borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350'}});
s.setData(d.candles);
if (d.markers.length) s.setMarkers(d.markers);
const v = chart.addHistogramSeries({{priceFormat: {{type: 'volume'}}, priceScaleId: 'vol'}});
chart.priceScale('vol').applyOptions({{scaleMargins: {{top: 0.84, bottom: 0}}}});
v.setData(d.volume);
s.createPriceLine({{price: 100, color: '#2da44e', lineWidth: 1, lineStyle: 2,
  axisLabelVisible: true, title: 'entry'}});
s.createPriceLine({{price: d.stop, color: '#ef5350', lineWidth: 1, lineStyle: 2,
  axisLabelVisible: true, title: 'stop'}});
const n = d.candles.length;
chart.timeScale().setVisibleLogicalRange({{from: Math.max(0, n - 130), to: n + 3}});
const at = {{}}; d.candles.forEach((c, i) => {{ at[c.time] = i; }});
const f = x => x.toFixed(1);
function legend(i) {{
  const c = d.candles[i];
  document.getElementById('lg').innerHTML = 'day ' + day(c.time) + ' &nbsp;O ' + f(c.open) +
    ' H ' + f(c.high) + ' L ' + f(c.low) + ' C ' + f(c.close) +
    ' &nbsp;vol ' + d.volume[i].value.toFixed(1) + 'x';
}}
legend(n - 1);
chart.subscribeCrosshairMove(p => {{
  const i = p && p.time !== undefined ? at[p.time] : undefined;
  legend(i === undefined ? n - 1 : i);
}});
</script>"""


def _facts_html(row: pd.Series) -> str:
    cells = "".join(
        f"<div><small>{htmllib.escape(k)}</small>{htmllib.escape(v)}</div>"
        for k, v in practice.card_facts(row)
    )
    return f'<div class="pr-grid">{cells}</div>'


def _answer(data_dir: Path, signals: pd.DataFrame, pool: str, choice: str) -> None:
    sid = st.session_state[f"pr_cur_{pool}"]
    with contextlib.suppress(practice.AlreadyAnswered):  # a double click: the first answer stands
        practice.save_answer(data_dir, signals, sid, pool, choice)
    st.session_state[f"pr_done_{pool}"] = st.session_state.get(f"pr_done_{pool}") or choice


def _next(pool: str) -> None:
    st.session_state[f"pr_cur_{pool}"] = None
    st.session_state[f"pr_done_{pool}"] = None


def _r(x: float | None, digits: int = 2) -> str:
    return "–" if x is None else f"{x:+.{digits}f} R"


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
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    a, b = st.columns(2)
    a.metric("Your picks, total", _r(s["picks_r"], 1), _r(s["picks_r_per_signal"]) + " / signal")
    b.metric("Take every signal", _r(s["equal_r"], 1), _r(s["equal_r_per_signal"]) + " / signal")
    st.caption("Picks: net R times your size (skip 0, 1 = 0.5x, 2 = 1x, 3 = 1.5x).")
    big, los = s["big"], s["losers"]
    st.write(
        f"Trades of 5R or more: {big['total']} shown, you took {big['taken']} and skipped "
        f"{big['skipped']}. Losing trades: {los['total']} shown, you took {los['taken']} and "
        f"skipped {los['skipped']}."
    )


def render(data_dir: Path) -> None:
    st.header("Practice")
    st.caption(
        "A past signal, blind: the chart up to the entry and the facts known then. Pick a size "
        "(Skip, 1, 2 or 3), see how it went, and check whether your picks beat taking all."
    )
    st.markdown(CSS, unsafe_allow_html=True)
    if not practice.available(data_dir):
        st.info("No practice data yet: it is exported to the data repo (data/research/practice).")
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
        bars = practice.visible_bars(_bars(str(data_dir), sid), choice is not None)
        st.iframe(
            chart_html(bars, row["stop_pct"], int(row["hold_days"]) if choice else None, 380),
            height=390,
        )
        st.markdown(_facts_html(row), unsafe_allow_html=True)
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
        else:
            r = float(row["net_r"])
            mine = r * practice.MULTIPLIER[choice]
            st.markdown(
                f"**{htmllib.escape(str(row['ticker']))}**, entry {row['entry_date']} · "
                f"net **{r:+.2f} R** in {int(row['hold_days'])} days · your pick "
                f"{'skip' if choice == 'skip' else choice} = {mine:+.2f} R"
            )
            st.button("Next", key="pr_next", on_click=_next, args=(pool,), type="primary")
    st.subheader("Your numbers")
    answers = practice.load_answers(data_dir)
    tabs = st.tabs([POOL_LABELS[p] for p in practice.POOLS])
    for tab, p in zip(tabs, practice.POOLS, strict=True):
        with tab:
            stats_panel(signals, answers, p)
