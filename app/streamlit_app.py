"""Trading OS dashboard: a private web app over the local clone of the data repo.

    uv run --group app streamlit run app/streamlit_app.py

Reads runs, charts, breadth, watchlists, outcomes and the journal; writes your grades, notes
and screenshots back to the data repo (append-only) and can pull / push it. Never deploy this
from the public repo with data in it: the data stays in the private repo.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import os
import sys
from pathlib import Path

import board  # app/board.py: Today's candidate board and Saxo ticket
import lwchart  # app/lwchart.py: the focus view's fast chart
import pandas as pd
import streamlit as st
from chart_draw import chart_draw  # app/chart_draw.py: the Chart page's drawable chart

from trading_os import (
    alerts,
    board_data,
    breadth,
    chart_marks,
    chart_view,
    clock,
    daily_notes,
    dashboard,
    health,
    heat,
    history,
    ibd,
    journal,
    journal_view,
    live_tracking,
    market_view,
    my_watchlists,
    notify,
    plans,
    positions_view,
    remote_data,
    report,
    research_view,
    review,
    runs_view,
    scan_editor,
    scans_view,
    screens,
    search,
    sizing,
    stock_notes,
    strategy_history,
    timer,
    validation,
)
from trading_os import interactive_chart as ichart
from trading_os.config import DEFAULT_PATH as CONFIG_PATH
from trading_os.config import ConfigError, load_config

st.set_page_config(
    page_title="Trading OS", page_icon="📈", layout="wide", initial_sidebar_state="collapsed"
)


@st.cache_resource(show_spinner=False)
def config_at(path: str, mtime: float):
    """The config, parsed once per version of the file (an edit on the Scans page changes
    its time, so the next click reads it again): parsing it took ~0.5 s on every click."""
    return load_config(path)


CFG = config_at(str(CONFIG_PATH), CONFIG_PATH.stat().st_mtime)
_cli = argparse.ArgumentParser()
_cli.add_argument("--data-dir", default=None)  # streamlit run app/streamlit_app.py -- --data-dir X
_args, _ = _cli.parse_known_args(sys.argv[1:])
DEFAULT_DATA = Path(
    _args.data_dir
    or os.environ.get("TRADING_OS_DATA", Path(__file__).resolve().parents[2] / "trading-os-data")
)
# Five places in a top bar, each with its pages as tabs (Emil, 4 Nov 2026 redesign: the 12
# pages of the sidebar, none removed, grouped by the question they answer).
PLACES = {
    "Today": ["Today"],  # what do I do today?
    "Stocks": ["Screener", "Watchlists", "Chart"],  # find and study a stock
    "Market": ["Market"],  # what is the market doing?
    "Journal": ["Positions", "Journal", "Live results"],  # how am I doing?
    "Lab": ["Research", "Runs", "System health", "Guide"],  # how does it work?
}
PLACE_OF = {page: place for place, pages in PLACES.items() for page in pages}
PAGES = [page for pages in PLACES.values() for page in pages]


def go(page: str) -> None:
    """Open a page (a button's callback, e.g. a stock on the Chart page or a screen on Today)."""
    place = PLACE_OF[page]
    st.session_state["place"] = place
    st.session_state[f"tab_{place}"] = page


# Research and Live results gather the history pages. One section runs at a time: tabs would
# run every section's code (and its downloads) on each click.
RESEARCH = {
    "Strategy rules": (
        "Strategy rules",
        "How every strategy is defined (live scans and the ones tested only), with the exact "
        "numbers from the config and how it did in each kind of market.",
    ),
    "How it was tested": (
        "How it was tested",
        "How every setup was tested on 10 years of data, the best time to buy, where the stop "
        "goes, and what makes a trade A+, A, B or C.",
    ),
    "Grades": (
        "Study grades",
        "Net of costs and out of sample (2019-2026): the grade rules you confirmed and what each "
        "grade returned. These are the numbers to decide on.",
    ),
    "History": (
        "History",
        "Every scan hit in the daily-bar replay. The graded section at the top is net of costs; "
        "the tables below it are gross (no costs).",
    ),
    "Entries & exits": (
        "Entries & exits",
        "The minute-bar study: entry, stop and exit per strategy, gross of costs. The grades "
        "add the costs.",
    ),
    "Market regime": (
        "Market regime",
        "Whether skipping trades in a weak market would have helped.",
    ),
    "Study notes": (
        "Study notes",
        "Every research write-up from the data repo (docs/research), newest first.",
    ),
}
LIVE = {
    "Grades live vs study": "Live grades",
    "All signals": "Stats",
    "Signals you graded": "Graded signals",
}
HEALTH = {"Jobs and data": "System health", "Validation against TradingView": "Validation"}


# ---------------------------------------------------------------- top bar

# The top bar (Emil, 4 Nov 2026 redesign): the five places, the market in one word, search and
# a gear for the settings. Each place's pages are tabs under it. No sidebar.
NAV_CSS = """<style>
.block-container{padding-top:1.2rem;padding-bottom:2rem;max-width:1640px}
h1,h2,h3{letter-spacing:-.015em}h1{margin-bottom:.2rem}
[data-testid="stAppViewContainer"]{font-feature-settings:'tnum' 1}
.st-key-topbar{border-bottom:1px solid #1C2028;padding-bottom:.7rem;margin-bottom:.2rem}
.st-key-topbar [data-testid="stHorizontalBlock"]{align-items:center;gap:.75rem}
.st-key-topbar [data-testid="stMarkdownContainer"] p{margin:0}
@media (max-width:640px){
.st-key-topbar>div>[data-testid="stHorizontalBlock"]{flex-wrap:wrap;flex-direction:row}
.st-key-topbar>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:0!important}
.st-key-topbar>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(1){display:none}
.st-key-topbar>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(2){
  flex:1 1 100%!important;order:1}
.st-key-topbar>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(3){
  flex:1 1 0!important;order:2}
.st-key-topbar>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(5){
  flex:0 0 64px!important;width:64px!important;order:3}
.st-key-topbar>div>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(4){
  flex:1 1 100%!important;order:4}
.st-key-topbar div[role="group"]{flex-wrap:nowrap;overflow-x:auto}
}
</style>"""
st.markdown(NAV_CSS, unsafe_allow_html=True)


def _keep(key: str, fallback: str) -> None:
    """A segmented control can be clicked off; keep the last pick instead of nothing."""
    if st.session_state.get(key) is None:
        st.session_state[key] = st.session_state.get(f"_last_{key}", fallback)
    st.session_state[f"_last_{key}"] = st.session_state[key]


@st.cache_data(ttl=600, show_spinner=False)
def auto_pull(folder: str) -> tuple[bool, str]:
    """Pull the newest runs at most every 10 minutes (Emil, 4 Nov 2026: no Pull button to
    remember). Save & push stays a button in the settings: it publishes your edits."""
    return dashboard.pull(Path(folder))


@st.cache_data(ttl=120, show_spinner=False)
def market_now(folder: str, newest_run: str) -> tuple[dict | None, dict | None, str | None]:
    """The market tiles' inputs, read once per new run (the pill shows on every page)."""
    runs_now = dashboard.list_runs(Path(folder), include_manual=False)
    return board_data.market_inputs(Path(folder), runs_now)


st.session_state.setdefault("place", "Today")
st.session_state.setdefault("data_folder", str(DEFAULT_DATA))
st.session_state.setdefault("manual_runs", True)
st.session_state.setdefault("auto_pull", True)
data_dir = Path(st.session_state["data_folder"])
include_manual = bool(st.session_state["manual_runs"])
if st.session_state["auto_pull"] and (data_dir / ".git").exists():
    pulled_ok, pulled_out = auto_pull(str(data_dir))
else:
    pulled_ok, pulled_out = True, ""

with st.container(key="topbar"):
    brand, nav, pill_col, find, gear = st.columns(
        [1.2, 3.4, 1.9, 2.4, 0.55], vertical_alignment="center"
    )
    brand.markdown("**Trading OS**")
    nav.segmented_control(
        "Place",
        list(PLACES),
        key="place",
        label_visibility="collapsed",
        on_change=_keep,
        args=("place", "Today"),
    )
    query = find.text_input(
        "Search",
        key="search",
        placeholder="Search a stock, notes or the guide",
        label_visibility="collapsed",
    )
    with gear.popover("⚙", help="Settings: data folder, test runs, pull and save"):
        st.text_input("Data repo folder", key="data_folder")
        st.toggle("Show manual test runs", key="manual_runs")
        st.toggle("Pull new runs by itself (every 10 minutes)", key="auto_pull")
        if not pulled_ok:
            st.warning(f"The last automatic pull failed: {pulled_out}")
        left, right = st.columns(2)
        if left.button("Pull now", width="stretch"):
            ok, out = dashboard.pull(data_dir)
            (st.success if ok else st.error)(out or "up to date")
            st.cache_data.clear()
        if right.button("Save & push", width="stretch", help="Send your notes, grades, journal "
                        "and watchlists to the private data repo"):  # fmt: skip
            ok, out = dashboard.save_and_push(data_dir)
            (st.success if ok else st.error)(out or "saved")

if not (data_dir / "data").exists():
    st.error(f"No data folder at {data_dir}. Clone trading-os-data there or fix it under ⚙.")
    st.stop()

# The market in one word, its reasons and numbers one click away (Emil, 4 Nov 2026)
_newest = dashboard.list_runs(data_dir, include_manual=False)
m_row, m_ibd, m_heat = market_now(str(data_dir), _newest[0].label if _newest else "")
m_word, m_reasons = board_data.market_word(m_row, m_ibd, m_heat)
with pill_col.popover(f":{board_data.MARKET_COLOUR[m_word]}[●] {m_word} market"):
    for reason in m_reasons or ["No market data yet."]:
        st.markdown(f"- {reason}")
    if m_row:
        numbers = [f"{label} **{value}** {delta or ''}" for label, value, delta in
                   board_data.tiles(m_row, m_ibd, m_heat)[3:]]  # fmt: skip
        st.markdown(" · ".join(numbers).replace("$", "\\$"))
        with st.expander("Every market line"):
            for line in board_data.market_details(m_row):
                st.markdown(f"- {line}")
    st.button("Open the Market page", on_click=go, args=("Market",), width="stretch")

place = st.session_state.get("place") or "Today"
tabs = PLACES[place]
if len(tabs) > 1:
    st.session_state.setdefault(f"tab_{place}", tabs[0])
    st.segmented_control(
        "Page",
        tabs,
        key=f"tab_{place}",
        label_visibility="collapsed",
        on_change=_keep,
        args=(f"tab_{place}", tabs[0]),
    )
    page = st.session_state.get(f"tab_{place}") or tabs[0]
else:
    page = tabs[0]


# ---------------------------------------------------------------- cached loaders


@st.fragment
def board_fragment(runs, account, usd_rate) -> None:
    """The candidate board as a fragment: ◀ ▶, the hotkeys and the ticket rerun only the board,
    not the whole page (Emil, 28 Oct 2026: faster dashboard)."""
    board.show(
        runs,
        CFG,
        data_dir,
        account,
        usd_rate,
        scan_frames,
        open_chart,
        focus_chart,
        exchanges_of,
    )


@st.cache_data(ttl=60)
def runs_cached(folder: str, manual: bool) -> list[dashboard.Run]:
    return dashboard.list_runs(Path(folder), include_manual=manual)


@st.cache_data(ttl=60)
def read_parquet(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


CHART_CACHE = Path(os.environ.get("TEMP", "/tmp")) / "trading-os-charts"


# Big read-only tables are cached as resources: shared, never copied on each rerun (the
# copies made Entries & exits and History slow). Pages filter them into new frames.
@st.cache_resource(ttl=600)
def strategy_cached(folder: str) -> pd.DataFrame:
    return strategy_history.load(folder)


@st.cache_resource(ttl=3600)
def data_repo(folder: str) -> str:
    return remote_data.repo_of(Path(folder))


def from_github(tag: str, pattern: str = "*") -> Path:
    """The cache folder of a data-repo release, with the files matching `pattern` fetched
    (the large study data lives only on GitHub; see remote_data)."""
    with st.spinner(f"Fetching {tag} from GitHub…"):
        remote_data.fetch(data_repo(str(data_dir)), tag, pattern)
    return remote_data.CACHE / tag


def history_graded() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every History strategy net of costs and graded walk-forward (`research_view`)."""
    with st.spinner("Fetching grading-10y from GitHub…"):
        return research_view.history_graded(data_dir)


def show_history_graded() -> None:
    summary, by_grade = history_graded()
    with st.expander("Net of costs and graded: every strategy, 10 years", expanded=True):
        if summary.empty:
            st.info("Not built yet (data repo release grading-10y).")
            return
        st.caption(research_view.GRADED_CAPTION)
        show = summary.rename(columns=research_view.GRADED_RENAME)
        st.dataframe(show.round(3), hide_index=True, width="stretch")
        pick = st.selectbox(
            "Grades out of sample (2019-2026) for", summary["strategy"].tolist(), key="hist_grade"
        )
        rows = by_grade[by_grade["strategy"] == pick].drop(columns=["strategy"])
        st.dataframe(rows.round(3), hide_index=True, width="stretch")
        st.caption(
            "A+/A/B/C: predicted net R of at least +0.5 / +0.3 / +0.1, else C. daily_mean_r "
            "weighs every signal day the same: what an account with a few slots could reach."
        )


@st.cache_resource(ttl=600)
def read_big(path: str, columns: tuple | None = None) -> pd.DataFrame:
    """A large parquet file, shared between reruns (no copy); treat as read-only."""
    return pd.read_parquet(path, columns=list(columns) if columns else None)


@st.cache_data(ttl=600)
def ticker_bars(folder: str, ticker: str) -> pd.DataFrame:
    """One stock's 2-year daily bars from the compact bars-2y file (fetched from GitHub)."""
    return board_data.ticker_bars(bars_file(folder, ticker), ticker)


def bars_file(folder: str, ticker: str) -> Path | None:
    """The compact 2-year bars file holding `ticker` (`board_data.bars_file`)."""
    return board_data.bars_file(Path(folder), ticker)


def bars_date(folder: str):
    """The newest session in the published compact bars (from the file names, no download)."""
    with contextlib.suppress(Exception):
        found = remote_data.names(data_repo(folder), "bars-2y", "bars_2y_*.parquet")
        if found:
            return dt.date.fromisoformat(found[-1].split("_")[2])
    return None


def candidates_of(run: dashboard.Run) -> pd.DataFrame:
    return read_parquet(str(run.candidates))


@st.cache_data(ttl=600, show_spinner=False)
def scan_frames(path: str) -> dict[str, pd.DataFrame]:
    """A run's hits split per scan, each with only the columns that scan fills. A run file
    holds every scan's fields (hundreds of columns), and every filter on it copied them all:
    the Today page spent ~1 s a click on that."""
    return board_data.scan_frames(path)


FORMATS = {"money": "compact", "shares": "compact", "int": "%d"}


@st.cache_data(ttl=300, show_spinner="Fetching live data from TradingView…")
def live_universe(snapshot_path: str) -> pd.DataFrame:
    """The Screener's live data (Emil, 29 Oct 2026): one TradingView fetch of the universe
    (at most once per 5 minutes), with the last close's history fields joined in."""
    return screens.live_data(CFG, read_parquet(snapshot_path))


def tradingview_url(ticker: str, exchange: str | None = None) -> str:
    """The stock's TradingView chart (`board_data.tradingview_url`)."""
    return board_data.tradingview_url(ticker, exchange)


def tradingview_list(tickers, exchanges: dict | None = None) -> str:
    """A TradingView import (`board_data.tradingview_list`)."""
    return board_data.tradingview_list(tickers, exchanges)


@st.cache_data(ttl=600)
def exchanges_of(universe_path: str) -> dict[str, str]:
    """Ticker -> exchange from a run's universe snapshot (intraday runs have none)."""
    return board_data.exchanges_of(universe_path)


def show_table(scan: str, hits: pd.DataFrame, exchanges: dict | None = None) -> None:
    """The same columns and number formats as the Markdown report, plus a TradingView link."""
    columns = [("Rank", "rank", "int"), ("Ticker", "ticker", "text")]
    columns += [("Study grade", "grade", "text"), ("Why", "grade_why", "text")]
    columns += [("Pred. R", "grade_score", "+.2f")]
    columns += [("Short", "si_tag", "text")]  # heavily shorted, as in the push (Emil, 25 Oct 2026)
    columns += [("IBD", "ibd_tag", "text")]  # IBD market state, tracked not a rule (`ibd`)
    columns += [("Vol build", "vol_build", ".1f")]  # 5d / 50d volume before, a fact
    columns += [("Chart", "tradingview", "link"), ("Tier", "tier", "text")]
    columns += report.COLUMNS.get(scan, [])
    # Only the columns the table shows (and the sort needs), before sorting: a run file
    # carries every scan's fields.
    wanted = {c for _, c, _ in columns} | {"grade", "grade_score", "rank", "ticker"}
    wanted |= {f"b{i}" for i in range(1, 6)} | {"ibd_state", "ibd_dist"}
    hits = ibd.relabel(hits[[c for c in hits.columns if c in wanted]])
    view = notify.best_first(hits).copy()  # best quality on top (Emil, 22 Oct 2026)
    view["tradingview"] = [tradingview_url(t, (exchanges or {}).get(t)) for t in view["ticker"]]
    if scan.startswith("breakout_"):  # from the five flag columns, not whole rows
        flags = [c for c in (f"b{i}" for i in range(1, 6)) if c in view]
        view["b_flags"] = [report._b_flags(r) for r in view[flags].to_dict("records")]
    present = [(h, c, f) for h, c, f in columns if c in view.columns]
    config = {}
    for header, _, fmt in present:
        if fmt == "flag":
            config[header] = st.column_config.CheckboxColumn(header)
        elif fmt == "link":
            config[header] = st.column_config.LinkColumn(header, display_text="TradingView ↗")
        elif fmt != "text":
            config[header] = st.column_config.NumberColumn(
                header, format=FORMATS.get(fmt, f"%{fmt}")
            )
    view = view[[c for _, c, _ in present]].rename(columns={c: h for h, c, _ in present})
    st.dataframe(view, hide_index=True, width="stretch", column_config=config)


# The grade rules in words, the strategy list and the History tables live in the package
# (React dashboard, Nov 2026): both dashboards show the same research pages.
feature_points = research_view.feature_points
FEATURE_TEXT = research_view.FEATURE_TEXT
condition_text = research_view.condition_text
quality_rules = research_view.quality_rules


def grade_blocks(hits: pd.DataFrame) -> None:
    """The A+, A and B hits as their push shows them: the study grade, when to buy, the exit,
    the history behind the grade, why, and the plan (C hits are saved, not shown)."""
    if "grade" not in hits:
        return
    keep = hits["grade"].isin(["A+++", "A++", "A+", "A", "B"])
    if not keep.any():  # most scans, most days: nothing to show
        return
    graded = hits[keep]
    graded = graded.assign(_order=graded["grade"].map(notify.GRADE_RANK)).sort_values("_order")
    for row in graded.to_dict("records"):
        lines = notify.grade_lines(row)
        if not lines:
            continue
        why = row.get("grade_why")
        body = [*lines[1:], *([f"Why: {why}"] if isinstance(why, str) and why else [])]
        body += notify.plan_lines(row)
        ticket = notify.saxo_line(row, str(row.get("scan", "")))
        if ticket:
            body.append(ticket)
        items = "\n".join(f"- {b}" for b in body)
        st.markdown(f"**{row['ticker']}** · {lines[0]}\n{items}")


@st.cache_data(ttl=3600)
def fx_rate(folder: str, currency: str) -> float | None:
    """Units of the account currency per USD (`board_data.fx_rate`)."""
    return board_data.fx_rate(Path(folder), CFG, currency)


def setup_names() -> list[str]:
    """Live scans and the study-only setups, for tagging trades and plans."""
    return journal_view.setup_names(CFG)


@st.cache_data(ttl=600)
def recent_bars(folder: str, tickers: tuple[str, ...], sessions: int = 10) -> pd.DataFrame:
    """The newest daily bars of a few tickers, from the compact bars-2y file."""
    return positions_view.recent_bars(Path(folder), tickers, sessions)


def trade_bars(folder: str, trades: pd.DataFrame) -> pd.DataFrame:
    """Daily bars of the traded tickers over the trades' dates."""
    return journal_view.trade_bars(Path(folder), trades, lambda t: ticker_bars(folder, t))


@st.cache_data(ttl=600)
def latest_hits(folder: str) -> pd.DataFrame:
    """Planned hits (entry, stop) of the newest run, for starting a plan from a scan."""
    return journal_view.latest_hits(dashboard.list_runs(Path(folder)), read_parquet)


@st.cache_data(ttl=600)
def study_by_strategy(folder: str) -> dict[str, pd.DataFrame]:
    """History-study trades per strategy (`journal_view.study_by_strategy`)."""
    return journal_view.study_by_strategy(Path(folder))


def show_trade_chart(trade: dict, open_trade: bool = False) -> None:
    """Interactive daily chart around one trade: the entry and exit marked, the stop line."""
    bars = ticker_bars(str(data_dir), trade["ticker"])
    if bars.empty:
        st.caption("No daily bars for this ticker in the data repo.")
        return
    end = trade.get("exit_date") if not open_trade else None
    end = end if end is not None and end == end else bars["session_date"].max()
    before = bars[bars["session_date"] <= trade["entry_date"]].tail(60)
    window = bars[bars["session_date"] >= before["session_date"].min()]
    window = window[window["session_date"] <= end].tail(400)
    later = bars[bars["session_date"] > end].head(5)
    data = pd.concat([window, later])
    buy = "buy" if trade["direction"] == "long" else "sell"
    sell = "sell" if buy == "buy" else "buy"
    rows = [(trade["entry_date"], trade["entry_avg"], buy, trade.get("quantity", 0))]
    if not open_trade and trade.get("exit_avg") == trade.get("exit_avg"):
        rows.append((trade["exit_date"], trade["exit_avg"], sell, trade.get("quantity", 0)))
    fills = pd.DataFrame(rows, columns=["session_date", "price", "side", "quantity"])
    stop = pd.to_numeric(trade.get("order_stop"), errors="coerce")
    fig = ichart.daily_figure(
        data,
        title=f"{trade['ticker']} · {trade['direction']} {trade['entry_date']} → {end}",
        overlays=["MA10", "MA20", "MA50"],
        fills=fills,
        levels={"stop": float(stop)} if stop == stop else None,
        height=520,
    )
    key = f"trade-{trade['ticker']}-{trade['entry_date']}-{open_trade}"
    st.plotly_chart(fig, config=ichart.DRAW_CONFIG, key=key, width="stretch")


EP_FLAGS = research_view.EP_FLAGS
HISTORY_COLUMNS = research_view.HISTORY_COLUMNS
EP_COLUMNS = research_view.EP_COLUMNS


@st.cache_resource(ttl=3600)
def funds_cached(folder: str) -> frozenset:
    """ETFs, ETNs and funds (Massive's ticker types): left out of the study views."""
    from trading_os.regime_study import non_stocks

    return frozenset(non_stocks(Path(folder)))


@st.cache_resource(ttl=600)
def history_cached(folder: str, period: str = "2y") -> pd.DataFrame:
    """The strategy history with the EP study's EP-Days, stocks only (`research_view`)."""
    if period == "10y":
        from_github("history-10y", "*.parquet")
        return research_view.history_frame(Path(folder), period, skip=funds_cached(folder))
    built = sorted((Path(folder) / "data" / "ep_history").glob("ep_history_*.parquet"))
    ep = read_parquet(str(built[-1])) if built else pd.DataFrame()
    return research_view.history_frame(
        Path(folder), period, strategy_cached(folder), ep, funds_cached(folder)
    )


OVERLAYS = ["MA10", "MA20", "MA50", "MA200", "EMA9", "EMA21"]


@st.cache_data(ttl=600)
def bars_for(folder: str, ticker: str, period: str) -> pd.DataFrame:
    """Daily bars: 2 years (Massive, in git) or 10 years (Alpaca's yearly files)."""
    if period == "2y":
        return ticker_bars(folder, ticker)
    with st.spinner("Fetching bars-alpaca from GitHub…"):
        return chart_view.bars(Path(folder), ticker, period)


@st.cache_resource(ttl=600)
def all_hits(folder: str, period: str) -> pd.DataFrame:
    """Every scan hit (strategy, session_date, ticker, side), EP-Days included."""
    if period == "10y":
        with st.spinner("Fetching history-10y from GitHub…"):
            return chart_view.all_hits(Path(folder), period)
    return chart_view.all_hits(Path(folder), period, strategy_cached(folder))


def hits_for(folder: str, ticker: str, period: str) -> pd.DataFrame:
    return chart_view.hits_for(all_hits(folder, period), ticker)


@st.cache_resource(ttl=3600)
def minute_index(folder: str) -> pd.DataFrame:
    """Every stock-day with minute bars (`chart_view.minute_index`)."""
    return chart_view.minute_index(Path(folder))


def minute_days(folder: str, ticker: str) -> list:
    """Sessions that have minute bars for `ticker` (newest first)."""
    return chart_view.minute_days(minute_index(folder), ticker)


def minute_bars(folder: str, ticker: str, day) -> pd.DataFrame:
    """One stock-day's minute bars (`chart_view.minute_bars`)."""
    return chart_view.minute_bars(Path(folder), ticker, day)


@st.cache_data(ttl=60, show_spinner="Fetching minute bars from Alpaca…")
def live_minutes(ticker: str, day: dt.date) -> pd.DataFrame:
    """One session's minute bars from Alpaca's IEX feed (`chart_view.live_minutes`)."""
    return chart_view.live_minutes(ticker, day)


def live_intraday(ticker: str, levels: dict, daily: pd.DataFrame) -> None:
    """The Chart page's live intraday chart: a recent session's 1/5/15-minute candles with VWAP,
    the prior close, your plan levels and a line at 10:30, the EP entry time."""
    if not chart_view.has_alpaca():
        st.info(
            "Live minute bars need the Alpaca keys on this PC: run "
            "scripts\\set_local_secrets.ps1 (press Enter at the ntfy prompt to skip it), then "
            "restart the dashboard."
        )
        return
    recent = chart_view.live_sessions(CFG)
    a, b = st.columns(2)
    day = a.selectbox("Session", recent, key="ch_live_day")
    every = b.radio(
        "Candle",
        [1, 5, 15],
        index=1,
        horizontal=True,
        key="ch_live_every",
        format_func=lambda m: f"{m} min",
    )
    try:
        minutes = live_minutes(ticker, day)
    except Exception as exc:  # noqa: BLE001 - shown, not raised
        st.error(f"Alpaca didn't answer ({type(exc).__name__}).")
        return
    if minutes.empty:
        st.caption(f"No trades for {ticker} on {day} in Alpaca's IEX feed yet.")
        return
    fig = ichart.intraday_figure(
        minutes,
        title=f"{ticker} · {day} · live",
        prev_close=chart_view.prior_close(daily, day),
        levels=levels,
        every=every,
    )
    with contextlib.suppress(Exception):  # the 10:30 bar may not exist yet
        fig.add_vline(x="10:30", line_dash="dot", line_width=1, line_color="#9e9e9e")
    st.plotly_chart(fig, config=ichart.DRAW_CONFIG, key="ch_live", width="stretch")
    st.caption(
        "Alpaca's IEX feed: real-time prices, but its volume is a small part of the market's. "
        "Dotted line: 10:30, the EP entry time. Lines: the pivot, stops and plan entry for this "
        "stock. Refreshes every minute."
    )


@st.cache_data(ttl=600, show_spinner="Fetching indexes and sectors from TradingView…")
def sector_table(folder: str) -> tuple[pd.DataFrame, str]:
    """The ETFs of `sectors.py` now (`market_view.sector_table`, rotation columns included)."""
    return market_view.sector_table(Path(folder))


def market_overview() -> None:
    """Indexes, sectors and themes: returns over a chosen period, against SPY, the trend, the
    rotation quadrant and a rotation chart; then the industries' rank moves."""
    import plotly.express as px

    st.subheader("Indexes, sectors and themes")
    table, source = sector_table(str(data_dir))
    if table.empty:
        st.info("No sector data yet: it comes from TradingView, and with each EOD run.")
        return
    a, b = st.columns([3, 2])
    period = a.radio(
        "Return over", list(market_view.PERIODS), index=2, horizontal=True, key="sec_period"
    )
    groups = b.multiselect("Show", list(market_view.GROUPS), list(market_view.GROUPS),
                           key="sec_groups")  # fmt: skip
    shown = market_view.sector_view(table, period, groups)
    view = table[table["group"].isin(groups)]
    styled = shown.style.format(precision=1).background_gradient(
        cmap="RdYlGn", subset=[f"{period} %", "1M vs SPY", "1W vs SPY"]
    )
    st.dataframe(styled, hide_index=True, width="stretch")
    st.caption(market_view.SECTOR_CAPTION.format(source=source))
    fig = px.scatter(
        view, x="vs_spy_1m", y="vs_spy_1w", text="ticker", color="group",
        hover_name="name", labels={"vs_spy_1m": "1 month vs SPY (%)",
                                   "vs_spy_1w": "1 week vs SPY (%)"},
        height=480,
    )  # fmt: skip
    fig.update_traces(textposition="top center")
    fig.add_hline(y=0, line_width=1, line_color="#888")
    fig.add_vline(x=0, line_width=1, line_color="#888")
    for x, y, label in ((1, 1, "Leading"), (1, -1, "Weakening"), (-1, -1, "Lagging"),
                        (-1, 1, "Improving")):  # fmt: skip
        fig.add_annotation(xref="paper", yref="paper", x=(x + 1) / 2 * 0.96 + 0.02,
                           y=(y + 1) / 2 * 0.96 + 0.02, text=label, showarrow=False,
                           font={"color": "#888"})  # fmt: skip
    st.plotly_chart(fig, width="stretch", key="sec_rotation")

    if not market_view.industry_files(data_dir):
        return
    st.subheader("Industries: who leads and who is moving")
    back = st.radio("Rank move since", ["1 week", "1 month"], horizontal=True, key="ind_back")
    found = market_view.industries(data_dir, back)
    if found:
        a, b = st.columns(2)
        a.markdown("**Top 15 now**")
        a.dataframe(found["top"], hide_index=True)
        b.markdown(f"**Climbing most** ({back})")
        b.dataframe(found["climbing"], hide_index=True)
        st.caption(found["caption"])


def open_chart(ticker: str) -> None:
    """The search's button: the Chart page with this ticker."""
    go("Chart")
    st.session_state["ch_ticker"] = ticker
    st.session_state["search"] = ""


def search_view(query: str) -> None:
    """Search results in place of the page: a ticker everywhere, or words in notes and the
    guide (`search.py`)."""
    q = query.strip()
    st.header(f"🔎 {q}")
    if search.looks_like_ticker(q):
        ticker = q.lstrip("$").upper()
        st.button(f"Open {ticker} on the Chart page", on_click=open_chart, args=(ticker,))
        recent = [r for r in runs if r.kind == "scheduled"][:30]
        found = search.scan_hits(
            ((r.label, scan_frames(str(r.candidates))) for r in recent), ticker,
            report.SCAN_LABELS,
        )  # fmt: skip
        st.markdown(f"**Scan hits** (last {len(recent)} runs)")
        if found.empty:
            st.caption("None.")
        else:
            st.dataframe(found, hide_index=True, width="stretch")
        places = []
        mine = my_watchlists.current(my_watchlists.load(data_dir))
        places += [f"your list *{n}*" for n in mine.loc[mine["ticker"] == ticker, "list"]]
        scan_lists = dashboard.watchlist_state(data_dir)
        if len(scan_lists):
            on = scan_lists[(scan_lists["ticker"] == ticker) & (scan_lists["status"] == "active")]
            places += [
                {"bo_watch": "BO-Watch", "ep_watch": "EP-Watch"}.get(x, x) for x in on["list"]
            ]
        positions = dashboard.latest_positions(data_dir)
        if len(positions) and ticker in set(positions["ticker"]):
            places.append("an open position")
        own = alerts.current(data_dir)
        places += [
            f"price alert {r['direction']} {r['level']:.2f}"
            for r in own[own["ticker"] == ticker].to_dict("records")
        ]
        st.markdown("**On**: " + (", ".join(places) if places else "no list, position or alert"))
        notes = stock_notes.current(data_dir, ticker)
        tagged = daily_notes.current(data_dir, ticker)
        if len(notes) or len(tagged):
            st.markdown("**Notes**")
            for n in notes.to_dict("records"):
                st.markdown(f"- {n['note_date']} · stock note: {n['text']}")
            for n in tagged.to_dict("records"):
                st.markdown(f"- {n['note_date']} · daily note: {n['text']}")
        st.divider()
    # Words: your notes, daily notes, journal notes and the guide.
    shown = 0
    notes = search.text_hits(stock_notes.current(data_dir), ["text", "ticker"], q)
    for n in notes.to_dict("records"):
        st.markdown(f"- **{n['ticker']}** · {n['note_date']} · stock note: {n['text']}")
        shown += 1
    days = search.text_hits(daily_notes.current(data_dir), ["text", "tags"], q)
    for n in days.to_dict("records"):
        st.markdown(f"- {n['note_date']} · daily note: {n['text']}")
        shown += 1
    journal_notes = search.text_hits(dashboard.notes_state(data_dir), ["notes", "tags"], q)
    for n in journal_notes.to_dict("records"):
        st.markdown(f"- journal ({n['kind']} {n['ref_id']}): {n['notes']}")
        shown += 1
    guide = Path(__file__).resolve().parents[1] / "docs" / "GUIDE.md"
    lines = search.guide_hits(guide.read_text(encoding="utf-8"), q) if guide.exists() else []
    if lines:
        st.markdown("**In the guide**")
        for section, line in lines:
            st.markdown(f"- *{section}*: {line[:240]}")
            shown += 1
    if not shown and not search.looks_like_ticker(q):
        st.caption("Nothing found in your notes or the guide.")
    st.caption("Clear the search box to go back to the page.")


STRATEGY_RULES = research_view.STRATEGY_RULES


def strategy_rules_view() -> None:
    """Every strategy's definition: its own rules text (a live scan's function, or the study
    module that sets it up), its config numbers, and its study result per market heat."""
    labels = [label for label, *_ in STRATEGY_RULES]
    pick = st.selectbox("Strategy", labels, key="rules_pick")
    found = research_view.strategy_rules(CFG, data_dir, pick)
    st.markdown(f"**{found['heading']}**")
    st.markdown("**The rules**")
    st.markdown(found["rules"])
    if found["settings"]:
        st.markdown("**The numbers** (config/scans.yaml; change live scans on the Scans page)")
        st.dataframe(pd.DataFrame(found["settings"]), hide_index=True, width="stretch")
    if found["heat"]:
        st.markdown("**How it did, per market heat** (net R a trade after costs, its study plan)")
        st.dataframe(pd.DataFrame(found["heat"]).round(2), hide_index=True, width="stretch")
    elif found["heat_note"]:
        st.caption(found["heat_note"])


def levels_for(ticker: str) -> dict:
    """Pivot, order stop, your position's stop and open plans (`chart_view.levels_for`)."""
    return chart_view.levels_for(data_dir, runs, CFG, ticker, read_parquet)


def fills_for(ticker: str) -> pd.DataFrame:
    return chart_view.fills_for(data_dir, ticker)


to_weeks = chart_view.to_weeks


def stock_chart(
    ticker: str,
    *,
    period: str = "2y",
    timeframe: str = "Daily",
    overlays: list[str] | None = None,
    sessions: int | None = 250,
    show_hits: bool = True,
    show_fills: bool = True,
    show_levels: bool = True,
    anchors: dict | None = None,
    lines: list | None = None,
    drawable: bool = False,
    key: str = "chart",
) -> dict | None:
    """The interactive chart for one stock, drawn into the page. `lines`: saved trend lines,
    shown on the daily bars as shapes you can drag or erase. `drawable`: the chart reports the
    lines you draw, move or erase (returned; see chart_draw) so the page can save them."""
    bars = bars_for(str(data_dir), ticker, period)
    if bars.empty:
        st.caption(f"No daily bars for {ticker} in the data repo.")
        return
    hits = hits_for(str(data_dir), ticker, period) if show_hits else None
    fills = fills_for(ticker) if show_fills else None
    if fills is not None and len(fills):
        fills = fills.rename(columns={"trade_date": "session_date"})
    data = bars
    if timeframe == "Weekly":
        data = ichart.weekly(bars)
        hits, fills = to_weeks(hits, data), to_weeks(fills, data)
        sessions = sessions // 5 if sessions else None
    elif timeframe == "Monthly":  # Emil, 4 Nov 2026
        data = ichart.monthly(bars)
        hits, fills = to_weeks(hits, data, "M"), to_weeks(fills, data, "M")
        sessions = max(sessions // 21, 12) if sessions else None
    fig = ichart.daily_figure(
        data,
        title=f"{ticker} · {timeframe.lower()}",
        overlays=overlays or [],
        markers=hits,
        fills=fills,
        levels=levels_for(ticker) if show_levels else None,
        sessions=sessions,
    )
    shown = list(fig.data[0].x)
    if anchors and timeframe == "Daily":
        ichart.add_avwaps(fig, bars, anchors, shown)
    if timeframe == "Daily":
        for shape in ichart.line_shapes(bars["session_date"], shown, lines or []):
            fig.add_shape(shape)
    if drawable and timeframe == "Daily":
        # Keep your zoom and drawing tool when the figure comes back with a saved line; a
        # changed set of saved lines replaces whatever the pen left on the chart.
        fig.update_layout(
            uirevision=f"{ticker}|{period}|{sessions}",
            editrevision="|".join(sorted(str(m["mark_id"]) for m in lines or [])),
        )
        return chart_draw(fig, ticker=ticker, config=ichart.SAVE_CONFIG, key=key)
    st.plotly_chart(fig, config=ichart.DRAW_CONFIG, key=key, width="stretch")
    return None


@st.cache_resource(ttl=600, show_spinner=False)
def history_filtered(folder, period, picked, years, states, ep_args) -> pd.DataFrame:
    """The History page's rows for one set of filters (shared, computed once per set)."""
    return research_view.filter_history(history_cached(folder, period), picked, years, states,
                                        ep_args)  # fmt: skip


@st.cache_data(ttl=600, show_spinner=False)
def history_tables(folder: str, filters: tuple, group: str):
    """(summary, exits compared) for one set of filters and split (computed once per set)."""
    return research_view.history_tables(history_filtered(folder, *filters), CFG.exits, group)


def grade_form(kind: str, ref_id: str, title: str, key: str) -> None:
    """Grade + notes + screenshots for a trade or a signal (append-only)."""
    current = dashboard.notes_state(data_dir)
    match = current[(current["kind"] == kind) & (current["ref_id"] == ref_id)]
    prev = match.iloc[0].to_dict() if len(match) else {}
    with st.form(f"form-{key}"):
        st.markdown(f"**{title}**")
        grade_index = dashboard.GRADES.index(prev.get("grade", "")) if prev else 0
        grade = st.radio(
            "Grade (your call)",
            dashboard.GRADES,
            index=grade_index,
            horizontal=True,
            format_func=lambda g: g or "none",
        )
        notes = st.text_area("Notes", prev.get("notes", ""))
        tags = st.text_input("Tags (comma separated)", prev.get("tags", ""))
        shots = st.file_uploader(
            "Screenshots", type=["png", "jpg", "jpeg"], accept_multiple_files=True
        )
        if st.form_submit_button("Save"):
            saved = [a for a in str(prev.get("attachments", "")).split(";") if a]
            for shot in shots or []:
                saved.append(
                    dashboard.save_attachment(data_dir, ref_id, shot.name, shot.getvalue())
                )
            dashboard.save_note(data_dir, kind, ref_id, grade, notes, tags, saved)
            st.success("Saved locally. Use “Save & push” in the sidebar to send it to GitHub.")
    for rel in [a for a in str(prev.get("attachments", "")).split(";") if a]:
        if (data_dir / rel).exists():
            st.image(str(data_dir / rel), caption=rel.split("/")[-1])


def market_lines(run: dashboard.Run | None) -> None:
    if run is None or run.breadth is None:
        st.info("No breadth row for this run yet.")
        return
    row = read_parquet(str(run.breadth)).iloc[0].to_dict()
    for line in breadth.push_lines(row):
        st.markdown(f"- {line}")


# ---------------------------------------------------------------- pages

runs = runs_cached(str(data_dir), include_manual)

if query.strip():
    search_view(query)
    st.stop()

if page == "Research":
    st.header("Research")
    section = st.radio(
        "Section",
        list(RESEARCH),
        horizontal=True,
        key="research_section",
        label_visibility="collapsed",
    )
    page, what = RESEARCH[section]
    st.caption(what)
elif page == "Live results":
    st.header("Live results")
    section = st.radio(
        "Section", list(LIVE), horizontal=True, key="live_section", label_visibility="collapsed"
    )
    page = LIVE[section]
    st.caption("The live signals since launch, with what happened 5, 10, 20 and 60 sessions after.")
elif page == "System health":
    st.header("System health")
    section = st.radio(
        "Section", list(HEALTH), horizontal=True, key="health_section", label_visibility="collapsed"
    )
    page = HEALTH[section]


def focus_chart(
    ticker: str,
    row: dict | None = None,
    timeframe: str = "1D",
    picked: list[str] | None = None,
    height: int = 520,
) -> None:
    """The focus view's chart: the fast Lightweight Chart, daily or weekly, with the picked
    indicators (the anchored VWAP from the signal day, the RS line against QQQ) and the plan's
    levels. Drawing and the other tools are on the Chart page."""
    bars = bars_for(str(data_dir), ticker, "2y")
    if bars.empty:
        st.caption(f"No daily bars for {ticker} in the data repo.")
        return
    row = row or {}
    picked = lwchart.DEFAULT if picked is None else picked
    bench = bars_for(str(data_dir), "QQQ", "2y") if "RS vs QQQ" in picked else None
    if timeframe in ("1W", "1M"):
        to = lwchart.weekly if timeframe == "1W" else lwchart.monthly
        bars = to(bars)
        bench = to(bench) if bench is not None and len(bench) else bench
    levels = {"entry": row.get("plan_entry"), "stop": row.get("plan_stop") or row.get("grade_stop")}
    if row.get("pivot") == row.get("pivot") and row.get("pivot"):
        levels["pivot"] = row.get("pivot")
    exchange = row.get("exchange")
    where = f" · {exchange}" if isinstance(exchange, str) and exchange else ""
    anchor = row.get("avwap_anchor") or row.get("run_session")
    lwchart.show(
        bars,
        levels,
        height,
        title=f"{ticker} · {timeframe}{where}",
        picked=picked,
        anchor=anchor,
        bench=bench,
        show_bars={"1D": 130, "1W": 80}.get(timeframe, 24),
    )


if page == "Today":
    if not runs:
        st.header("Today")
        st.info("No runs yet. The first scheduled run writes here.")
        st.stop()
    board.controls(data_dir)
    latest_eod = next((r for r in runs if r.slot == "eod"), None)
    latest_pm = next((r for r in runs if r.slot == "pm"), None)
    # The market is the pill in the top bar now (Emil, 4 Nov 2026 redesign)
    board_account = sizing.load_account(data_dir)
    board_fragment(
        runs,
        board_account,
        fx_rate(str(data_dir), board_account.currency if board_account else "USD"),
    )
    st.divider()
    latest_am = next((r for r in runs if r.slot == "am"), None)
    latest_mid = next((r for r in runs if r.slot == "mid"), None)
    latest = [r for r in (latest_pm, latest_am, latest_mid, latest_eod) if r is not None]
    # A toggle, not only expanders: a collapsed expander's code runs too, and these tables cost
    # ~0.2 s on every click of the board (Emil, 28 Oct 2026).
    if st.toggle("All scans: every pushed scan's table", key="today_all_scans"):
        for run in sorted(latest, key=runs.index):  # newest first
            exp = st.expander(f"{run.label} · every pushed scan's table")
            with exp:
                tables = []
                for scan, hits in scan_frames(str(run.candidates)).items():
                    if scan not in CFG.scans or CFG.scans[scan].action != "push":
                        continue
                    alert_only = "push_tier" in CFG.scans[scan].params
                    shown = hits[hits["tier"] == "alert"] if alert_only else hits
                    ranks = shown["grade"].map(notify.GRADE_RANK) if "grade" in shown else None
                    best = ranks.min() if ranks is not None and ranks.notna().any() else 9
                    tables.append((best, scan, hits, shown))
                # The scan with the best grade first (A+ on top, C last; Emil, 26 Oct 2026)
                for _, scan, hits, shown in sorted(tables, key=lambda x: x[0]):
                    label = report.SCAN_LABELS.get(scan, scan)
                    st.markdown(f"**{label}** — {len(shown)} of {len(hits)} hits")
                    show_table(scan, shown, exchanges_of(str(run.universe)))
                    grade_blocks(shown)
                    facts = report.fact_lines(scan, shown)
                    if facts:
                        st.markdown("\n".join(facts))
                    charts = [
                        (t, dashboard.chart_for(run, scan, t)) for t in shown["ticker"].head(10)
                    ]
                    charts = [(t, p) for t, p in charts if p is not None]
                    if charts:
                        cols = st.columns(min(3, len(charts)))
                        for i, (ticker, path) in enumerate(charts):
                            cols[i % len(cols)].image(str(path), caption=ticker)

elif page == "Positions":
    # The positions cockpit (Emil, 26 Oct 2026): each open position with its price, open R, the
    # distance to its stop and what its plan says today. Live prices when the Alpaca keys are
    # set on this PC (scripts/set_local_secrets.ps1), else the newest close in the data repo.
    st.header("Positions")
    positions = dashboard.latest_positions(data_dir)
    if positions.empty:
        st.info("No open positions. Your fills come in through the Journal (import or log).")
        st.stop()
    account = sizing.load_account(data_dir)
    usd_rate = fx_rate(str(data_dir), account.currency if account else "USD")
    account_usd = account.size_usd(usd_rate) if account and usd_rate else None
    last = recent_bars(str(data_dir), tuple(sorted(positions["ticker"])))
    view = review.open_risk(positions, last, account_usd)
    prices, source = positions_view.live_prices(view["ticker"])
    a, b, c = st.columns(3)
    a.metric("Open positions", len(view))
    b.metric("Open P&L (at the close)", f"${view['open_pnl'].sum():,.0f}")
    c.metric("At risk to stops", f"${view['at_risk_usd'].sum():,.0f}")
    plan_check, _ = positions_view.plan_check(positions, runs, CFG, read_parquet)
    board.position_cards(view, plan_check, prices, source, open_chart)
    st.caption(positions_view.PLAN_CAPTION)

elif page == "Screener":
    # Your own screens, TradingView style (Emil, 29 Oct 2026; `trading_os/screens.py`)
    st.header("Screener")
    st.caption(
        "Filter every US stock in the universe (about 4,000), or one scan's hits, on the fields "
        "below, like TradingView's screener. A screen of all stocks is a list to look at, not a "
        "tested setup: no grade, no buy. Scan hits keep their study grade and your grading form."
    )
    eod_runs = [r for r in runs if r.slot == "eod" and r.universe.exists()]
    if not eod_runs:
        st.info("No EOD universe snapshot yet.")
        st.stop()
    snapshot = read_parquet(str(eod_runs[0].universe))
    saved = screens.load(data_dir)
    choices = ["＋ New screen", *saved, *(f"Example: {n}" for n in screens.EXAMPLES)]
    a, b = st.columns([3, 2])
    pick = a.selectbox("Screen", choices, key="sc_screen")
    # Where the stocks come from: the whole universe, or one run's scan hits (the old Screens
    # page, merged in on 29 Oct 2026 so one page lists, filters and grades)
    origin = b.segmented_control(
        "Stocks from",
        ["All stocks", "Scan hits"],
        default="All stocks",
        key="sc_from",
        help="All stocks: every US stock in the universe. Scan hits: one scan's hits from one "
        "run, with the study grade, the chart and your grading form.",
    )
    hit_scan, source = None, "Last close"
    if origin == "Scan hits":
        c1, c2, c3 = st.columns([3, 3, 2])
        run = c1.selectbox("Run", runs, format_func=lambda r: r.label, key="sc_run")
        frames = scan_frames(str(run.candidates))
        if not frames:
            st.info("This run saved no hits.")
            st.stop()
        hit_scan = c2.selectbox(
            "Scan", list(frames), format_func=lambda s: report.SCAN_LABELS.get(s, s), key="sc_scan"
        )
        tiers = c3.multiselect("Tier", ["alert", "log"], default=["alert", "log"], key="sc_tier")
        hits = frames[hit_scan][frames[hit_scan]["tier"].isin(tiers)]
    else:
        source = st.segmented_control(
            "Data",
            ["Last close", "Live now"],
            default="Last close",
            key="sc_source",
            help="Last close: the EOD snapshot, every field. Live now: one TradingView fetch for "
            "price, change, volume and pre/after-hours; history fields stay from the last close.",
        )
    # Load the picked screen into the editor when the pick changes
    if st.session_state.get("sc_loaded") != pick:
        if pick in saved:
            spec = saved[pick]
        elif pick.startswith("Example: "):
            spec = screens.EXAMPLES[pick.removeprefix("Example: ")]
        else:
            spec = {"filters": [], "sort": "rs_pct", "descending": True}
        # Each filter gets its own id, so its boxes keep their values when others change
        start = st.session_state.get("sc_next", 0)
        st.session_state["sc_filters"] = [
            {**f, "_id": start + k} for k, f in enumerate(spec["filters"])
        ]
        st.session_state["sc_next"] = start + len(spec["filters"])
        st.session_state["sc_sort"] = spec.get("sort") or "rs_pct"
        st.session_state["sc_desc"] = spec.get("descending", True)
        st.session_state["sc_loaded"] = pick
    filters = st.session_state["sc_filters"]
    fields = list(screens.FIELDS)
    groups = {f: screens.FIELDS[f][2] for f in fields}
    st.markdown("**Filters**")
    for i, f in enumerate(list(filters)):
        k = f["_id"]
        c1, c2, c3, c4 = st.columns([4, 2, 4, 1])
        field = c1.selectbox(
            "Field", fields, index=fields.index(f["field"]), key=f"sc_f{k}",
            format_func=lambda x: f"{groups[x]} · {screens.label(x)}",
            label_visibility="collapsed",
        )  # fmt: skip
        ops = screens.OPS[screens.kind(field)]
        op = c2.selectbox(
            "Op", ops, index=ops.index(f["op"]) if f["op"] in ops else 0, key=f"sc_o{k}",
            label_visibility="collapsed",
        )  # fmt: skip
        value = f.get("value")
        if op == "between":
            lo_hi = list(value) if isinstance(value, list | tuple) else [None, None]
            x, y = c3.columns(2)
            lo = x.number_input(
                "from", value=lo_hi[0], key=f"sc_lo{k}", label_visibility="collapsed"
            )
            hi = y.number_input("to", value=lo_hi[1], key=f"sc_hi{k}", label_visibility="collapsed")
            value = [lo, hi]
        elif op in ("is one of", "is not one of"):
            options = (
                sorted(snapshot[field].dropna().astype(str).unique()) if field in snapshot else []
            )
            value = c3.multiselect(
                "Values", options, default=[v for v in (value or []) if v in options],
                key=f"sc_m{k}", label_visibility="collapsed",
            )  # fmt: skip
        elif op in ("is yes", "is no"):
            value = None
            c3.write("")
        else:
            start = float(value) if isinstance(value, int | float) else 0.0
            value = c3.number_input(
                "Value", value=start, key=f"sc_v{k}", label_visibility="collapsed"
            )
        filters[i] = {"field": field, "op": op, "value": value, "_id": k}
        if c4.button("✕", key=f"sc_x{k}", help="Remove this filter"):
            filters.pop(i)
            st.rerun()
    c1, c2, c3 = st.columns([2, 3, 2])
    if c1.button("＋ Add filter", key="sc_add"):
        k = st.session_state.get("sc_next", 0)
        st.session_state["sc_next"] = k + 1
        filters.append({"field": "adr20_pct", "op": ">=", "value": 4.0, "_id": k})
        st.rerun()
    sort, descending = st.session_state["sc_sort"], st.session_state["sc_desc"]
    if hit_scan:  # scan hits keep the scan's order: best study grade first
        c2.caption("Sorted best study grade first, as in the push.")
    else:
        sort = c2.selectbox(
            "Sort by", fields, index=fields.index(sort),
            key=f"sc_sort_{st.session_state['sc_loaded']}",
            format_func=screens.label,
        )  # fmt: skip
        descending = c3.toggle(
            "Highest first", value=descending,
            key=f"sc_desc_{st.session_state['sc_loaded']}",
        )  # fmt: skip

    data = snapshot
    when = f"the {eod_runs[0].session:%d %b} close"
    if hit_scan:
        # The hits plus the universe's fields they lack, so every filter works on them
        snap = read_parquet(str(run.universe)) if run.universe.exists() else snapshot
        data = screens.with_universe(hits, snap)
        when = f"{report.SCAN_LABELS.get(hit_scan, hit_scan)} hits, {run.label}"
        if "exchange" not in data:
            data["exchange"] = data["ticker"].map(exchanges_of(str(eod_runs[0].universe)))
    elif source == "Live now":
        try:
            data = live_universe(str(eod_runs[0].universe))
            when = "live (TradingView, just now; history fields from the last close)"
        except Exception as exc:  # noqa: BLE001 - fall back to the snapshot
            st.warning(f"Live fetch failed ({type(exc).__name__}); showing the last close.")
    try:
        result = screens.run(data, filters, None if hit_scan else sort, descending)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    every = "every hit" if hit_scan else "every stock"
    summary = " · ".join(screens.describe(f) for f in filters) or f"no filters: {every}"
    st.markdown(f"**{len(result)} stocks** from {when}  \n{summary}")
    exchanges = dict(zip(data["ticker"], data.get("exchange", pd.Series(dtype=str)), strict=False))
    exchanges = {t: e for t, e in exchanges.items() if isinstance(e, str)}
    if hit_scan:  # the scan's own table: study grade, why, the scan's columns
        result = notify.best_first(result).reset_index(drop=True)
        show_table(hit_scan, result, exchanges)
    else:
        shown_cols = list(dict.fromkeys([*screens.SHOWN, *(f["field"] for f in filters), sort]))
        view = result[[c for c in shown_cols if c in result]].head(500).copy()
        view.insert(1, "chart", [tradingview_url(t, exchanges.get(t)) for t in view["ticker"]])
        formats = {"money": "compact", "pct": "%.1f", "num": "%.2f"}
        config = {"chart": st.column_config.LinkColumn("chart", display_text="TV ↗")}
        for col in view.columns:
            fmt = formats.get(screens.kind(col)) if col in screens.FIELDS else None
            if fmt:
                name = screens.label(col)
                fmt = "compact" if col in ("volume", "avg_volume_20d", "float_shares",
                                           "pm_volume", "ah_volume") else fmt  # fmt: skip
                config[name] = st.column_config.NumberColumn(name, format=fmt)
        st.dataframe(
            view.rename(columns=lambda c: screens.label(c) if c in screens.FIELDS else c),
            hide_index=True,
            width="stretch",
            column_config=config,
        )
        if len(result) > 500:
            st.caption(
                f"Showing the first 500 of {len(result)}; narrow the filters to see the rest."
            )

    def _flip(tickers: list[str], name: str) -> None:
        st.query_params.clear()
        st.query_params["screen"] = name
        st.query_params["t"] = ",".join(tickers)
        go("Today")
        st.session_state["board_i"] = 0
        st.session_state.pop("board_scope", None)

    a, b, c = st.columns(3)
    name_now = pick if pick in saved else ""
    a.button(
        f"📈 Flip through on Today ({min(len(result), 200)})",
        key="sc_flip",
        disabled=result.empty,
        on_click=_flip,
        args=(
            list(result["ticker"].head(200)),
            name_now or (report.SCAN_LABELS.get(hit_scan, hit_scan) if hit_scan else "unsaved"),
        ),
        width="stretch",
    )
    b.download_button(
        "TradingView list (.txt)",
        tradingview_list(result["ticker"].head(1000), exchanges),
        file_name=f"{run.session}_{hit_scan}.txt" if hit_scan else "screen.txt",
        help="TradingView: Watchlist menu → Import list",
        width="stretch",
    )
    with c.popover("💾 Save screen", width="stretch"):
        new_name = st.text_input("Name", value=name_now, key="sc_name")
        if st.button("Save", key="sc_save"):
            try:
                screens.save(data_dir, new_name, filters, sort, descending)
                st.session_state["sc_loaded"] = new_name.strip()
                st.toast(f"Saved '{new_name.strip()}'. Commit & push to keep it on GitHub.")
            except ValueError as exc:
                st.error(str(exc))
        if name_now and st.button(f"🗑 Delete '{name_now}'", key="sc_delete"):
            screens.delete(data_dir, name_now)
            st.session_state["sc_loaded"] = None
            st.toast(f"Deleted '{name_now}'")
            st.rerun()

    if hit_scan and len(result):
        # The A+/A/B blocks as the push shows them, then one hit's chart and your grading form
        grade_blocks(result)
        ticker = st.selectbox("Look at", result["ticker"].tolist(), key="sc_look")
        st.link_button("Open in TradingView", tradingview_url(ticker, exchanges.get(ticker)))
        row = result[result["ticker"] == ticker].iloc[0]
        stock_chart(ticker, sessions=126, key=f"scr-{hit_scan}-{ticker}")
        grade_form(
            "signal", row["signal_id"], f"Grade {ticker} · {hit_scan}", f"sig-{row['signal_id']}"
        )

elif page == "Runs":
    # Runs and scans in one place (Emil, 4 Nov 2026: "see all the push and scan runs and edit
    # them", "an overview of it"): the day's runs on top, a run's times and on/off, then the scans.
    st.header("Runs")
    st.caption(runs_view.CAPTION)
    try:
        run_jobs = timer.load()  # the file as it is now, edits included
    except timer.RunsError as exc:
        st.error(f"config/runs.yaml doesn't load: {exc}")
        st.stop()
    gh_runs = st.session_state.get("gh_runs")
    started = (
        timer.check(gh_runs, CFG.schedule.windows_et, dt.datetime.now(dt.UTC))
        if gh_runs is not None and not gh_runs.empty
        else None
    )
    st.dataframe(
        pd.DataFrame(runs_view.overview(CFG, run_jobs, started=started)).drop(columns="key"),
        hide_index=True,
        width="stretch",
        column_config={"on": st.column_config.CheckboxColumn("on")},
    )
    if st.button("Load how each run last started (GitHub)", key="rn_load"):
        st.session_state["gh_runs"] = health.run_list()
        st.rerun()

    st.subheader("Edit a run")
    run_keys = runs_view.keys(run_jobs)
    run_names = {r["key"]: r["run"] for r in runs_view.overview(CFG, run_jobs)}
    run_pick = st.selectbox("Run", run_keys, format_func=run_names.get, key="rn_pick")
    run_fields = runs_view.form(CFG, run_pick, run_jobs)
    with st.form(f"rn-edit-{run_pick}"):
        a, b, c = st.columns(3)
        run_new = {"enabled": a.toggle("On", value=run_fields["enabled"])}
        run_new["first"] = b.text_input(
            f"Starts ({run_fields['clock']}, HH:MM)", value=run_fields["first"]
        ).strip()
        if run_fields["second"] is not None:
            run_new["second"] = c.text_input(
                "Second start, in case the first failed", value=run_fields["second"]
            ).strip()
        if run_fields["window"]:
            st.caption(
                "Both starts must fall inside its New York window, "
                f"{run_fields['window'][0]}-{run_fields['window'][1]}, or the run does nothing."
            )
        st.caption(
            "Off: the timer stops starting it and GitHub's backup start exits at once. "
            "Started by hand on GitHub, it still runs."
        )
        run_saved = st.form_submit_button("Check and save")
    if run_saved:
        try:
            shown = runs_view.save(run_pick, run_new, CFG.schedule.windows_et)
            if not shown:
                st.info("Nothing changed.")
            else:
                st.session_state["rn_diff"] = (run_pick, shown)
                timer.JOBS = timer.load()  # the rest of the dashboard sees the new times
                st.rerun()
        except timer.RunsError as exc:
            st.error(f"Not saved: {exc}")
    if st.session_state.get("rn_diff"):
        key, shown = st.session_state["rn_diff"]
        st.success(
            f"Saved {run_names.get(key, key)} to config/runs.yaml on this PC. The timer and "
            "GitHub's jobs use it after Commit & push."
        )
        st.code(shown, language="diff")
    if st.button("Commit & push to GitHub", key="rn_push"):
        ok, out = runs_view.commit_and_push(run_pick)
        (st.success if ok else st.error)(out)
        if ok:
            st.session_state.pop("rn_diff", None)

    st.subheader("Scans")
    st.caption(scans_view.CAPTION)

    def scan_label(name: str) -> str:
        return scans_view.label(CFG, name)

    st.dataframe(
        pd.DataFrame(scans_view.table(CFG)),
        hide_index=True,
        width="stretch",
        column_config={"on": st.column_config.CheckboxColumn("on")},
    )

    st.subheader("Edit a scan")
    pick = st.selectbox(
        "Scan", list(CFG.scans), format_func=lambda n: f"{scan_label(n)} ({n})", key="sc_pick"
    )
    fields = scans_view.form(CFG, pick)
    with st.form(f"sc-edit-{pick}"):
        a, b = st.columns(2)
        new = {"enabled": a.toggle("On", value=fields["enabled"])}
        new["action"] = b.radio(
            "Hits",
            ["push", "log"],
            index=0 if fields["action"] == "push" else 1,
            horizontal=True,
            format_func={"push": "pushed", "log": "saved only"}.get,
        )
        if fields["push"] is not None:
            options = list(scans_view.PUSH_SLOTS)
            new["push"] = st.radio(
                "Pushed", options, index=options.index(fields["push"]), horizontal=True
            )
        cols = st.columns(3)
        for k, field in enumerate(fields["numbers"]):
            box, key = cols[k % 3], field["key"]
            if field["kind"] == "int":
                new[key] = box.number_input(
                    key, value=field["value"], step=1, key=f"sc-{pick}-{key}"
                )
            else:
                new[key] = box.number_input(
                    key, value=field["value"], format="%.4g", key=f"sc-{pick}-{key}"
                )
        for field in fields["flags"]:
            new[field["key"]] = st.checkbox(
                field["key"], value=field["value"], key=f"sc-{pick}-{field['key']}"
            )
        new["label"] = st.text_input(
            "Name in the push", value=fields["push_label"], placeholder=scan_label(pick)
        )
        new["note"] = st.text_area(
            "Note under its section in the push", value=fields["note"], height=80
        )
        submitted = st.form_submit_button("Check and save")
    if submitted:
        changes = scans_view.changes(CFG, pick, new)
        if not changes:
            st.info("Nothing changed.")
        else:
            try:
                shown = scan_editor.save(pick, changes)
                st.session_state["sc_diff"] = (pick, shown)
                st.cache_data.clear()
                st.rerun()
            except ConfigError as exc:
                st.error(f"Not saved: {exc}")
    if st.session_state.get("sc_diff"):
        name, shown = st.session_state["sc_diff"]
        st.success(
            f"Saved {scan_label(name)} to config/scans.yaml on this PC. GitHub's jobs use it "
            "after Commit & push."
        )
        st.code(shown, language="diff")
    if st.button("Commit & push to GitHub", key="sc_push"):
        ok, out = scan_editor.commit_and_push(pick)
        (st.success if ok else st.error)(out)
        if ok:
            st.session_state.pop("sc_diff", None)

elif page == "Chart":
    st.header("Chart")
    # Every alert-tier hit of the newest session's runs, pushed ones first (most hits are C:
    # counted in the push, not shown, so "pushed" alone was often empty), then your
    # watchlists and open positions.
    where = chart_view.picks(data_dir, runs, read_parquet)
    picks = list(where)
    a, b = st.columns([2, 2])
    quick = a.selectbox(
        "Today's hits (pushed first), watchlists, open positions",
        ["—", *picks],
        format_func=lambda t: t if t == "—" else f"{t}  ({where[t]})",
        key="ch_pick",
    )
    typed = b.text_input("…or type any ticker (wins over the list)", key="ch_ticker")
    ticker = (typed.strip() or ("" if quick == "—" else quick)).upper()
    if not ticker:
        st.info("Pick or type a ticker.")
        st.stop()
    a, b, c = st.columns(3)
    period = a.radio(
        "History",
        ["2y", "10y"],
        horizontal=True,
        key="ch_period",
        format_func=lambda p: "2 years" if p == "2y" else "10 years",
    )
    timeframe = b.radio("Bars", ["Daily", "Weekly", "Monthly"], horizontal=True, key="ch_tf")
    span = c.select_slider("Show", ["3M", "6M", "1Y", "2Y", "All"], value="1Y", key="ch_span")
    sessions = chart_view.SPANS[span]
    overlays = st.multiselect("Lines", OVERLAYS, default=["MA10", "MA20", "MA50"], key="ch_lines")
    a, b, c = st.columns(3)
    show_hits = a.toggle("Scan hits", value=True, key="ch_hits")
    show_fills = b.toggle("My trades", value=True, key="ch_fills")
    show_levels = c.toggle("Pivot and stops", value=True, key="ch_levels")

    bars = bars_for(str(data_dir), ticker, period)
    marks = chart_marks.current(data_dir, ticker)
    choices = chart_view.anchors_for(bars, hits_for(str(data_dir), ticker, period), marks)
    quick_anchor = choices["quick"]
    chosen = st.multiselect(
        "Anchored VWAP from", list(quick_anchor), default=[], key="ch_anchor_quick"
    )
    anchors = {name: quick_anchor[name] for name in chosen} | choices["saved"]
    lines = marks[marks["kind"] == "line"].to_dict("records")
    drawn = stock_chart(
        ticker,
        period=period,
        timeframe=timeframe,
        overlays=overlays,
        sessions=sessions,
        show_hits=show_hits,
        show_fills=show_fills,
        show_levels=show_levels,
        anchors=anchors,
        lines=lines,
        drawable=True,
        key="ch_main",
    )
    if drawn and drawn.get("seq") != st.session_state.get("ch_drawn_seq"):
        st.session_state["ch_drawn_seq"] = drawn["seq"]  # each report is saved once
        if any(chart_marks.apply_drawn(data_dir, ticker, drawn, marks).values()):
            st.rerun()
    st.caption(
        "Drag to pan, scroll or pinch to zoom, double-click to reset. On the daily bars, the "
        "line tool (top right) draws a trend line that is saved at once, for this stock; drag "
        "a line or its ends to move it, or click it and use the eraser to delete it. A line "
        "drawn past the last bar keeps extending each day. Triangles: amber = a scan's hit, "
        "green/red = your buys/sells."
    )
    exchanges = {}
    eod = [r for r in runs if r.slot == "eod" and r.universe.exists()]
    if eod:
        exchanges = exchanges_of(str(eod[0].universe))
    st.link_button("Open in TradingView", tradingview_url(ticker, exchanges.get(ticker)))

    st.subheader(f"Notes on {ticker}")
    with st.form("ch-note", clear_on_submit=True):
        a, b = st.columns([1, 4])
        note_day = a.date_input("Day", value=dt.date.today(), key="ch_note_day")
        text = b.text_area("New note", key="ch_note_text", height=90)
        if st.form_submit_button("Save note") and text.strip():
            stock_notes.add(data_dir, ticker, text, note_day)
            st.rerun()
    notes = stock_notes.current(data_dir, ticker)
    if not len(notes):
        st.caption("No notes on this stock yet.")
    for n in notes.to_dict("records"):
        edited = n["saved_ts"] != n["created_ts"]
        st.markdown(
            f"**{n['note_date']}** · written {n['created_ts']:%Y-%m-%d}"
            + (f" · edited {n['saved_ts']:%Y-%m-%d}" if edited else "")
        )
        st.text(n["text"])
        with st.popover("Edit or delete"), st.form(f"ch-note-{n['note_id']}"):
            new_day = st.date_input("Day", value=n["note_date"], key=f"nd-{n['note_id']}")
            new_text = st.text_area("Note", value=n["text"], key=f"nt-{n['note_id']}")
            a, b = st.columns(2)
            if a.form_submit_button("Save") and new_text.strip():
                stock_notes.edit(data_dir, n["note_id"], ticker, new_text, new_day)
                st.rerun()
            if b.form_submit_button("Delete"):
                stock_notes.remove(data_dir, n["note_id"])
                st.rerun()
    tagged = daily_notes.current(data_dir, ticker)
    if len(tagged):
        st.markdown(
            f"**From your daily notes** ({len(tagged)}; edit them in Journal → Daily notes)"
        )
        for n in tagged.to_dict("records"):
            others = [t for t in n["tag_list"] if t != ticker]
            also = f" · also {' · '.join(others)}" if others else ""
            st.markdown(f"**{n['note_date']}** · daily note{also}")
            st.text(n["text"])
    st.caption(
        "Notes are saved at once on this PC in the data repo (data/journal/stock_notes/) and "
        "kept for good: an edit or a delete adds a row and never erases the old text. Use "
        "“Save & push” to send them to GitHub."
    )

    with st.expander("Type in a trend line or an anchor"):
        recent = bars.tail(504) if len(bars) else bars
        dates = list(recent["session_date"])[::-1]
        with st.form("ch-line", clear_on_submit=True):
            st.markdown("**Trend line** through two points (it is extended to today)")
            a, b = st.columns(2)
            d0 = a.selectbox("First point: day", dates, key="ch_d0")
            p0 = b.number_input("First point: price", min_value=0.0, format="%.2f", key="ch_p0")
            a, b = st.columns(2)
            d1 = a.selectbox("Second point: day", dates, key="ch_d1")
            p1 = b.number_input("Second point: price", min_value=0.0, format="%.2f", key="ch_p1")
            a, b = st.columns(2)
            label = a.text_input("Name (optional)", key="ch_line_label")
            extend = b.checkbox("Extend to today", value=True, key="ch_extend")
            if st.form_submit_button("Save line") and p0 > 0 and p1 > 0 and d0 != d1:
                chart_marks.add_line(data_dir, ticker, d0, p0, d1, p1, label, extend)
                st.rerun()
        with st.form("ch-anchor", clear_on_submit=True):
            st.markdown("**Anchored VWAP** from a day (an earnings gap, a base high or low)")
            a, b = st.columns(2)
            day = a.selectbox("Anchor day", dates, key="ch_anchor_day")
            name = b.text_input("Name (optional)", key="ch_anchor_label")
            if st.form_submit_button("Save anchor"):
                chart_marks.add_anchor(data_dir, ticker, day, name)
                st.rerun()
        if len(marks):
            st.markdown("**Saved for this stock**")
            for m in marks.to_dict("records"):
                text = (
                    f"Line {m['x0']} {m['y0']:.2f} → {m['x1']} {m['y1']:.2f}"
                    if m["kind"] == "line"
                    else f"AVWAP from {m['anchor']}"
                )
                a, b = st.columns([5, 1])
                a.write(f"{text} {('· ' + m['label']) if m['label'] else ''}")
                if b.button("Remove", key=f"rm-{m['mark_id']}"):
                    chart_marks.remove(data_dir, m["mark_id"])
                    st.rerun()

    # A toggle, not an expander: Streamlit runs a collapsed expander's code too, and that
    # fetched a month of minute bars from GitHub for every stock you looked at.
    if st.toggle("Intraday (minute bars)", key="ch_intraday_on"):
        source = st.radio(
            "Minute bars", ["Live (Alpaca)", "Study days"], horizontal=True, key="ch_src"
        )
        days = [] if source.startswith("Live") else minute_days(str(data_dir), ticker)
        if source.startswith("Live"):
            live_intraday(ticker, levels_for(ticker), bars)
        elif not days:
            st.caption(
                "No minute bars for this stock on this PC. They exist for days a strategy could "
                "have traded it (the minute study's data)."
            )
        else:
            a, b = st.columns(2)
            day = a.selectbox("Day", days, key="ch_day")
            every = b.radio(
                "Candle",
                [1, 5, 15],
                horizontal=True,
                key="ch_every",
                format_func=lambda m: f"{m} min",
            )
            minutes = minute_bars(str(data_dir), ticker, day)
            prior = bars[bars["session_date"] < day]["close"]
            fig = ichart.intraday_figure(
                minutes,
                title=f"{ticker} · {day}",
                prev_close=float(prior.iloc[-1]) if len(prior) else None,
                every=every,
            )
            st.plotly_chart(fig, config=ichart.DRAW_CONFIG, key="ch_intraday", width="stretch")
            st.caption("VWAP from the 09:30 open; pre- and post-market shaded.")

elif page == "Watchlists":
    st.header("Watchlists")
    st.subheader("My watchlists")
    events = my_watchlists.load(data_dir)
    names = my_watchlists.lists(events)
    a, b = st.columns([2, 3])
    choice = a.selectbox("List", [*names, "＋ New list"], key="wl_choice")
    name = b.text_input("New list name") if choice == "＋ New list" else choice
    with st.form("wl-add", clear_on_submit=True):
        a, b = st.columns([3, 2])
        typed = a.text_input("Add tickers (comma or space separated)")
        note = b.text_input("Note (optional)")
        export = st.file_uploader("…or import a TradingView watchlist export (.txt)", type=["txt"])
        if st.form_submit_button("Add to list"):
            tickers = my_watchlists.parse_tickers(typed)
            if export is not None:
                text = export.getvalue().decode("utf-8", errors="replace")
                tickers += [t for t in my_watchlists.parse_tickers(text) if t not in tickers]
            try:
                known = my_watchlists.known_checker(runs, data_dir, read_parquet)
                done = my_watchlists.add_checked(data_dir, name, tickers, known, note)
                st.session_state["wl_msg"] = (done["kind"], "  \n".join(done["lines"]))
                st.cache_data.clear()
            except ValueError as exc:
                st.session_state["wl_msg"] = ("error", str(exc))
            st.rerun()
    if "wl_msg" in st.session_state:
        kind, text = st.session_state.pop("wl_msg")
        getattr(st, kind)(text)
        if kind == "success":
            st.toast("Watchlist updated")
    members = my_watchlists.current(my_watchlists.load(data_dir))
    members = members[members["list"] == name] if name else members.iloc[0:0]
    if members.empty:
        st.caption("No tickers in this list yet.")
    else:
        eod = [r for r in runs if r.slot == "eod" and r.universe.exists()]
        universe = read_parquet(str(eod[0].universe)) if eod else pd.DataFrame()
        hits = candidates_of(eod[0]) if eod else pd.DataFrame()
        view = my_watchlists.with_market(members, universe, hits)
        exchanges = exchanges_of(str(eod[0].universe)) if eod else {}
        view.insert(1, "chart", [tradingview_url(t, exchanges.get(t)) for t in view["ticker"]])
        if eod:
            st.caption(f"Market data from {eod[0].label}. in_scans = the scans it hit that run.")
        cols = ["ticker", "chart", "close", "chg_pct", "rvol50", "adr20_pct", "rs_pct"]
        cols += ["pct_from_52w_high", "ret_22", "ret_63", "above_ma50", "above_ma200"]
        cols += ["to_pivot_pct", "earnings_in_sessions", "in_scans", "industry", "note"]
        st.dataframe(
            view[[c for c in cols if c in view]].round(2),
            hide_index=True,
            width="stretch",
            column_config={"chart": st.column_config.LinkColumn("chart", display_text="TV ↗")},
        )
        st.download_button(
            "TradingView list (.txt)",
            tradingview_list(view["ticker"], exchanges),
            file_name=f"{name or 'watchlist'}.txt",
            help="TradingView: Watchlist menu → Import list",
            key="wl_tv",
        )
        a, b = st.columns([3, 1])
        gone = a.multiselect("Remove from the list", members["ticker"].tolist(), key="wl_rm")
        if b.button("Remove") and gone:
            my_watchlists.remove(data_dir, name, gone)
            st.cache_data.clear()
            st.rerun()
    st.caption("Saved in the data repo; use “Save & push” to send them to GitHub.")

    st.subheader("Price alerts")
    st.caption(
        "The alert watcher (scripts\\start_alerts.ps1) checks every minute of the New York "
        "session, 15:30–22:00 Copenhagen, and pushes once when a price is hit: your alerts "
        "below, last close's BO-Watch and MA-surf pivots, and your open positions' stops. "
        "Prices: Alpaca's real-time IEX feed. Your alerts end after they fire."
    )
    with st.form("alert-add", clear_on_submit=True):
        a, b, c, d = st.columns([2, 2, 2, 4])
        al_ticker = a.text_input("Ticker")
        al_level = b.number_input("Price", min_value=0.0, step=0.01, format="%.2f")
        al_dir = c.selectbox("When it trades", alerts.DIRECTIONS)
        al_note = d.text_input("Note (in the push)")
        if st.form_submit_button("Add alert"):
            try:
                alerts.add(data_dir, al_ticker, al_level, al_dir, al_note)
                st.success(f"Alert set: {al_ticker.upper()} {al_dir} {al_level:.2f}.")
            except ValueError as exc:
                st.error(str(exc))
    live_alerts = alerts.current(data_dir)
    if live_alerts.empty:
        st.caption("No alerts of your own yet.")
    else:
        st.dataframe(live_alerts.drop(columns="alert_id"), hide_index=True, width="stretch")
        labels = {
            r["alert_id"]: f"{r['ticker']} {r['direction']} {r['level']:.2f}"
            for r in live_alerts.to_dict("records")
        }
        a, b = st.columns([3, 1])
        drop = a.multiselect("Remove alerts", list(labels), format_func=labels.get, key="al_rm")
        if b.button("Remove", key="al_rm_btn") and drop:
            for alert_id in drop:
                alerts.end(data_dir, alert_id)
            st.rerun()
    ny_today = clock.ny_time(CFG.schedule, dt.datetime.now(dt.UTC)).date()
    today_fired = alerts.fired(data_dir, ny_today)
    if today_fired:
        st.markdown(f"**Fired today** ({len(today_fired)})")
        cols = ["fired_ts", "kind", "ticker", "level", "price", "note"]
        st.dataframe(pd.DataFrame(today_fired)[cols], hide_index=True, width="stretch")

    st.subheader("Scan watchlists")
    state = dashboard.watchlist_state(data_dir)
    if state.empty:
        st.info("EP-Watch and BO-Watch fill up as EP and breakout alerts come in.")
        st.stop()
    show_all = st.toggle("Include triggered / expired")
    for wl in ("bo_watch", "ep_watch"):
        rows = state[state["list"] == wl]
        if not show_all:
            rows = rows[rows["status"] == "active"]
        st.markdown(f"**{'BO-Watch' if wl == 'bo_watch' else 'EP-Watch'}** ({len(rows)})")
        st.dataframe(
            rows[["ticker", "status", "added_date", "status_date", "reason"]],
            hide_index=True,
            width="stretch",
        )

elif page == "Journal":
    st.header("Journal")
    st.caption(
        "Fills are the record: imported from the broker or logged here by hand (a broker fill "
        "later replaces the matching hand-logged one). Private: stays in the data repo; "
        "use “Save & push” to send it to GitHub."
    )
    with st.expander("Import broker fills (CSV)"):
        st.caption(journal_view.CSV_CAPTION)
        upload = st.file_uploader("Fills export", type=["csv"])
        if upload is not None and st.button("Import"):
            try:
                st.success(journal_view.import_csv(data_dir, upload.name, upload.getvalue()))
            except ValueError as exc:
                st.error(str(exc))

    account = sizing.load_account(data_dir)
    usd_rate = fx_rate(str(data_dir), account.currency if account else "USD")
    account_usd = account.size_usd(usd_rate) if account and usd_rate else None
    trades = dashboard.latest_journal(data_dir)
    positions = dashboard.latest_positions(data_dir)
    setups = setup_names()
    tab_open, tab_daily, tab_log, tab_plans, tab_closed, tab_real = st.tabs(
        ["Open positions", "Daily notes", "Log a trade", "Plans", "Closed trades", "Real vs study"]
    )

    with tab_daily:
        st.caption(
            "A note about the day. Tag the stocks it is about in the tag field, or write "
            "$TICKER in the text; each tagged stock's Chart page shows the note under its notes."
        )
        with st.form("daily-note", clear_on_submit=True):
            a, b = st.columns([1, 3])
            day = a.date_input("Day", value=dt.date.today(), key="dn_day")
            typed = b.text_input("Stocks (comma or space separated)", key="dn_tags")
            text = st.text_area("Note", key="dn_text", height=140)
            if st.form_submit_button("Save note") and text.strip():
                daily_notes.add(data_dir, text, day, typed)
                st.rerun()
        a, b = st.columns([2, 2])
        only = a.selectbox("Show", ["All notes", *daily_notes.all_tags(data_dir)], key="dn_only")
        days_back = b.select_slider(
            "From the last",
            [7, 30, 90, 365, 3650],
            value=30,
            key="dn_days",
            format_func=lambda d: "all" if d == 3650 else f"{d} days",
        )
        notes = journal_view.daily_notes_list(
            data_dir, None if only == "All notes" else only, days_back
        )
        if not len(notes):
            st.caption("No daily notes here yet.")
        for n in notes.to_dict("records"):
            tags = " · ".join(n["tag_list"])
            st.markdown(f"**{n['note_date']}**" + (f" · {tags}" if tags else ""))
            st.text(n["text"])
            with st.popover("Edit or delete"), st.form(f"dn-{n['note_id']}"):
                new_day = st.date_input("Day", value=n["note_date"], key=f"dnd-{n['note_id']}")
                new_tags = st.text_input(
                    "Stocks", value=", ".join(n["tag_list"]), key=f"dnt-{n['note_id']}"
                )
                new_text = st.text_area("Note", value=n["text"], key=f"dnx-{n['note_id']}")
                a, b = st.columns(2)
                if a.form_submit_button("Save") and new_text.strip():
                    daily_notes.edit(data_dir, n["note_id"], new_text, new_day, new_tags)
                    st.rerun()
                if b.form_submit_button("Delete"):
                    daily_notes.remove(data_dir, n["note_id"])
                    st.rerun()
        st.caption(
            "Saved at once in the data repo (data/journal/daily_notes/) and kept for good: an "
            "edit or delete adds a row. Use “Save & push” to send them to GitHub."
        )

    with tab_open:
        if positions.empty:
            st.info("No open positions. Log an entry under “Log a trade” or import fills.")
        else:
            last = recent_bars(str(data_dir), tuple(sorted(positions["ticker"])))
            view = review.open_risk(positions, last, account_usd)
            a, b, c = st.columns(3)
            a.metric("Open positions", len(view))
            b.metric("Open P&L", f"${view['open_pnl'].sum():,.0f}")
            heat = view.get("at_risk_pct")
            c.metric(
                "At risk to stops",
                f"${view['at_risk_usd'].sum():,.0f}"
                + (f" · {heat.sum():.1f}%" if heat is not None else ""),
            )
            cols = journal_view.OPEN_COLUMNS
            st.dataframe(
                view[[c for c in cols if c in view]].round(2), hide_index=True, width="stretch"
            )
            st.caption("Valued at the newest daily close in the data repo, not live prices.")
            plan_check, plan_day = positions_view.plan_check(positions, runs, CFG, read_parquet)
            if plan_day is not None:
                st.markdown(f"**What each plan says** (at the {plan_day} close)")
                cols = journal_view.PLAN_CHECK_COLUMNS
                st.dataframe(plan_check[cols].round(2), hide_index=True, width="stretch")
                st.caption(journal_view.PLAN_CHECK_CAPTION)
            pick = st.selectbox("Chart", ["—", *view["ticker"]], key="open_chart")
            if pick != "—":
                row = view[view["ticker"] == pick].iloc[0]
                show_trade_chart(row, open_trade=True)

    with tab_log, st.form("log-trade", clear_on_submit=True):
        st.markdown("**Log a fill** (an entry, an add, a partial sell or the exit)")
        a, b, c = st.columns(3)
        day = a.date_input("Date", dt.date.today())
        ticker = b.text_input("Ticker").strip().upper()
        side = c.radio("Side", ["buy", "sell"], horizontal=True)
        a, b, c = st.columns(3)
        qty = a.number_input("Shares", min_value=0.0, step=1.0)
        price = b.number_input("Price", min_value=0.0, step=0.01, format="%.4f")
        fees = c.number_input("Fees", min_value=0.0, step=0.5)
        a, b = st.columns(2)
        setup = a.selectbox("Setup", ["", *setups])
        stop = b.number_input("Initial stop (entries)", min_value=0.0, step=0.01, format="%.4f")
        if st.form_submit_button("Save fill"):
            try:
                fill = journal.manual_fill(day, ticker, side, qty, price, fees, setup or None)
                journal.log_manual(data_dir, CFG, fill, stop or None)
                st.success(f"Saved: {side} {qty:g} {ticker} @ {price:g}.")
                st.cache_data.clear()
            except ValueError as exc:
                st.error(str(exc))

    with tab_plans:
        today = journal_view.ny_today(CFG)
        current = journal_view.plan_table(data_dir, CFG, today)
        hits = latest_hits(str(data_dir))
        options = ["—"] + [journal_view.hit_label(r) for r in hits.to_dict("records")]
        prefill = st.selectbox("Start from a scan hit (latest run)", options, key="plan_from")
        base = hits.iloc[options.index(prefill) - 1].to_dict() if prefill != "—" else {}
        with st.form("new-plan", clear_on_submit=True):
            st.markdown("**New plan**")
            a, b, c = st.columns(3)
            pday = a.date_input("For session", today)
            pticker = b.text_input("Ticker", base.get("ticker", "")).strip().upper()
            direction = c.radio("Direction", ["long", "short"], horizontal=True)
            a, b, c = st.columns(3)
            entry = a.number_input(
                "Entry", min_value=0.0, value=float(base.get("plan_entry") or 0.0), format="%.4f"
            )
            pstop = b.number_input(
                "Stop", min_value=0.0, value=float(base.get("plan_stop") or 0.0), format="%.4f"
            )
            psetup = c.selectbox(
                "Setup",
                ["", *setups],
                index=([""] + setups).index(base["scan"]) if base.get("scan") in setups else 0,
            )
            suggestion = journal_view.suggest_shares(entry, pstop, account, usd_rate)
            shares = st.number_input(
                "Shares (suggested from your risk per trade)",
                min_value=0,
                value=int(suggestion["shares"]) if suggestion else 0,
                step=1,
            )
            note = st.text_input("Note")
            if st.form_submit_button("Save plan"):
                try:
                    plans.create(
                        data_dir, pday, pticker, direction, entry, pstop, shares, psetup, note
                    )
                    st.success("Plan saved.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if suggestion:
            st.caption(journal_view.suggestion_text(suggestion))
        if current.empty:
            st.info("No plans yet.")
        else:
            cols = journal_view.PLAN_COLUMNS
            st.dataframe(
                current[[c for c in cols if c in current]].round(3),
                hide_index=True,
                width="stretch",
            )
            open_ids = current.loc[current["status"] == "open", "plan_id"].tolist()
            if open_ids:
                a, b = st.columns([3, 1])
                gone = a.selectbox("Cancel an open plan", open_ids, key="plan_cancel")
                if b.button("Cancel plan"):
                    plans.cancel(data_dir, gone)
                    st.rerun()

    with tab_closed:
        if trades.empty:
            st.info("No closed trades yet.")
        else:
            trades = journal_view.closed_trades(data_dir, lambda t: ticker_bars(str(data_dir), t))
            summary = journal_view.closed_stats(trades)
            a, b, c, d = st.columns(4)
            a.metric("Closed trades", summary["trades"])
            b.metric("Win rate", f"{summary['win_rate']:.0f}%")
            c.metric("Avg R", f"{summary['avg_r']:.2f}" if summary["avg_r"] is not None else "n/a")
            d.metric("Total P&L", f"{summary['pnl']:,.0f}")
            curve = journal_view.r_curve(trades)
            if len(curve):
                st.line_chart(curve, height=200)
            cols = journal_view.CLOSED_COLUMNS
            st.dataframe(
                trades[[c for c in cols if c in trades]].round(2),
                hide_index=True,
                width="stretch",
            )
            st.caption(journal_view.MFE_CAPTION)
            pick = st.selectbox(
                "Review a trade",
                trades.to_dict("records"),
                format_func=journal_view.trade_label,
            )
            show_trade_chart(pick)
            grade_form(
                "trade", pick["trade_id"], f"{pick['ticker']} trade", f"tr-{pick['trade_id']}"
            )

    with tab_real:
        if trades.empty:
            st.info("Your real R per setup shows here once trades are closed.")
        else:
            with st.spinner("Fetching the minute study from GitHub…"):
                best = journal_view.minute_best(data_dir)
            table = review.real_vs_study(trades, study_by_strategy(str(data_dir)), best)
            st.dataframe(table.round(2), hide_index=True, width="stretch")
            st.caption(journal_view.REAL_CAPTION)

elif page == "Market regime":
    st.subheader("Market regime")
    with st.spinner("Fetching regime-10y from GitHub…"):
        folder = research_view.regime(data_dir)
    if folder is None:
        st.info("The regime study hasn't been published yet (the data repo's regime-10y release).")
        st.stop()
    st.caption(research_view.REGIME_CAPTION)
    st.subheader("Market Light per year (% of sessions)")
    st.dataframe(research_view.light_mix(folder), hide_index=True, width="stretch")
    source = st.radio(
        "Trades",
        ["minute", "daily"],
        horizontal=True,
        format_func=lambda s: (
            "Minute study (entries and stops)" if s == "minute" else "Daily histories"
        ),
        key="rg_source",
    )
    first = research_view.regime_view(folder, source, None, None)
    a, b = st.columns(2)
    strategy = a.selectbox("Strategy", first["strategies"], key="rg_strategy")
    exit_name = b.selectbox("Exit", first["exits"], index=0, key="rg_exit")
    entry = stop = None
    if source == "minute":
        picked = research_view.regime_view(folder, source, strategy, exit_name)
        a, b = st.columns(2)
        entry = a.selectbox("Entry", picked["entries"], key="rg_entry")
        stops = research_view.regime_view(folder, source, strategy, exit_name, entry)["stops"]
        stop = b.selectbox("Stop", stops, key="rg_stop")
    rv = research_view.regime_view(folder, source, strategy, exit_name, entry, stop)
    st.subheader("Each filter, all years")
    st.dataframe(rv["filters"], hide_index=True, width="stretch")
    st.subheader("Year by year (mean R)")
    st.dataframe(rv["by_year"], hide_index=True, width="stretch")

elif page == "Guide":
    st.header("Guide")
    guide = Path(__file__).resolve().parents[1] / "docs" / "GUIDE.md"
    text = guide.read_text(encoding="utf-8")
    body = text.splitlines()[1:]  # the file's own title is the page header
    st.markdown("\n".join(body))

elif page == "System health":
    now = dt.datetime.now(dt.UTC)
    st.caption(
        "From your local copy of the data repo: pull first (sidebar) to see the latest runs."
    )
    st.subheader("Runs per session")
    st.dataframe(health.run_grid(data_dir, CFG.schedule, now, 15), hide_index=True, width="stretch")
    st.caption(
        "✅ the scheduled run saved its output · 🟡 only a manual run · ❌ nothing · "
        "⏳ not due yet. pm 07:15-07:55, am 10:10-11:30, mid 11:55-13:30, eod 16:15-23:59 ET."
    )
    st.subheader("Data freshness")
    newest_bars = bars_date(str(data_dir))  # the bars live on GitHub; the file names say when
    extra = {"Daily bars (Massive)": newest_bars} if newest_bars else {}
    st.dataframe(
        health.freshness(data_dir, CFG.schedule, now, extra), hide_index=True, width="stretch"
    )
    st.subheader("Failures (newest first)")
    failures = health.errors(data_dir)
    if failures.empty:
        st.success("No failure logs.")
    else:
        st.dataframe(failures, hide_index=True, width="stretch")
    st.subheader("Data cache")
    used = remote_data.size() / 1024**3
    limit = remote_data.LIMIT_BYTES / 1024**3
    st.caption(
        f"The study data lives on GitHub; this PC keeps only what you opened, in "
        f"{remote_data.CACHE} ({used:.2f} of {limit:.0f} GB; least used files go first)."
    )
    if st.button("Empty the cache"):
        remote_data.clear()
        st.cache_resource.clear()
        st.success("Emptied. Pages fetch what they need again.")
    st.subheader("Timer and GitHub runs")
    if st.button("Load the latest runs from GitHub"):
        st.session_state["gh_runs"] = health.run_list()
    gh_runs = st.session_state.get("gh_runs")
    if gh_runs is not None:
        if gh_runs.empty:
            st.warning("No answer from GitHub (is the gh CLI installed and signed in?).")
        else:
            st.markdown("**Did each timed job start on time?**")
            st.dataframe(
                timer.check(gh_runs, CFG.schedule.windows_et, now),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "The cron-job.org timer starts each job at its New York time; GitHub's own "
                "schedule is the backup. Late: started after 10 minutes. Missed: no start "
                "before the job's window closed (2 hours for the jobs without one). If every "
                "job is missed, the timer stopped: check cron-job.org's email, or a GitHub "
                "token that expired (see the Guide)."
            )
            st.markdown("**Latest runs**")
            st.dataframe(health.github_runs(gh_runs), hide_index=True, width="stretch")
            st.caption(
                "minutes_late: how long after its cron GitHub started a scheduled run. A run "
                "that starts after its window closes exits without scanning."
            )

elif page == "Strategy rules":
    strategy_rules_view()

elif page == "How it was tested":
    st.subheader("The grade rules in config now")
    tested = research_view.how_tested(CFG, data_dir)
    if not tested["setups"]:
        st.caption("No quality grades in config.")
    else:
        for row in tested["setups"]:
            lines = [
                f"**{row['setup']}** · {row['grades']}",
                *(["- **Points:** " + " · ".join(row["points"])] if row["points"] else []),
                f"- **Buy:** {row['buy']}",
                f"- **Stop:** {row['stop']}",
                f"- **Exit:** {row['exit']}",
            ]
            st.markdown("\n".join(lines))
        st.caption(tested["caption"])
    if tested["write_up"]:
        st.markdown(tested["write_up"])
    else:
        st.info(
            "The write-up with the results lives in the private data repo "
            "(docs/research/how-we-test.md): Pull latest (sidebar) to get it."
        )

elif page == "Study notes":
    # Every write-up in the dashboard, not only on GitHub (Emil, 25 Oct 2026).
    notes = research_view.study_notes(data_dir)
    if not notes:
        st.info("The write-ups live in the private data repo (docs/research): Pull latest.")
    else:
        pick = st.selectbox("Study", notes, format_func=lambda p: p.stem, key="study_note")
        st.markdown(pick.read_text(encoding="utf-8"))

elif page == "Study grades":
    st.subheader("Study grades")
    st.caption(
        "Each hit of a scan with a scorecard gets the grade its setup earned in the 10-year "
        "grading study (rules confirmed by you on 20 Oct 2026, SPEC §11.17): predicted net R = "
        "the strategy's base + the points of each feature - trading costs in R, and the bands "
        "turn it into a grade. A grade is a fact from the study, never advice."
    )
    sg = research_view.study_grades(CFG, data_dir)
    if sg["period"] is not None or sg["source"]:
        st.caption(f"History: {sg['period'] or ''}. Report: data repo {sg['source']}.")
    else:
        st.info("The history behind the grades isn't in your data copy yet: Pull latest (sidebar).")
    st.dataframe(pd.DataFrame(sg["sizes"]), hide_index=True)
    st.caption(f"Every other scan: {sg['ungraded']}.")
    for rule in sg["strategies"]:
        st.subheader(rule["title"])
        st.markdown(
            f"- **Entry:** {rule['entry']}\n"
            f"- **Stop:** {rule['stop']} · **Exit:** {rule['exit']}\n"
            f"- **Grades** (predicted net R): {rule['bands']}; below that C. Base {rule['base']}"
        )
        if rule["history"]:
            st.dataframe(
                pd.DataFrame(rule["history"]),
                hide_index=True,
                column_config={
                    "Win %": st.column_config.NumberColumn(format="%.0f"),
                    "Mean R": st.column_config.NumberColumn(format="%+.2f"),
                    "Median R": st.column_config.NumberColumn(format="%+.2f"),
                    "Worst year R": st.column_config.NumberColumn(format="%+.2f"),
                    "Days held (median)": st.column_config.NumberColumn(format="%.0f"),
                },
            )
        with st.expander("Points per feature"):
            st.dataframe(pd.DataFrame(rule["features"]), hide_index=True, width="stretch")
    with st.expander("Trading costs in the score"):
        st.markdown("\n".join(f"- {line}" for line in sg["costs"]))
    if sg["report"]:
        with st.expander("The research report"):
            st.markdown(sg["report"])

elif page == "Live grades":
    st.subheader("Grades live vs study")
    lg = research_view.live_grades(data_dir, lambda t: bars_for(str(data_dir), t, "2y"))
    if lg["compare"] is None:
        st.info(
            "No live A+ / A / B signals yet. Each one shows here as it comes, with what its plan "
            "made, next to the history its grade carried."
        )
    else:
        st.dataframe(lg["compare"], hide_index=True, width="stretch")
        st.caption(research_view.LIVE_CAPTION.format(n=live_tracking.MIN_TRADES))
        st.markdown("**Your trades against the plan of the signal they came from**")
        if lg["gaps"].empty:
            st.caption(
                "None yet: a closed journal trade bought within two sessions of a live signal."
            )
        else:
            st.dataframe(lg["gaps"], hide_index=True, width="stretch")
        with st.expander("Every live signal"):
            st.dataframe(lg["signals"], hide_index=True, width="stretch")
    if lg["monthly"]:
        st.caption(f"Monthly reports: data repo docs/live-tracking/ (newest {lg['monthly']}).")

elif page == "Graded signals":
    st.subheader("Signals you graded")
    view = research_view.graded_signals(data_dir)
    if view.empty:
        st.info(
            "Grade signals on the Screener (Stocks from: Scan hits); they show up here with "
            "their outcomes."
        )
        st.stop()
    st.dataframe(view, hide_index=True, width="stretch")

elif page == "Market":
    st.header("Market")
    history = market_view.history_of(data_dir)
    if history.empty:
        st.info("Breadth rows start with the first scheduled EOD run.")
        st.stop()
    tile_list, _ = market_view.tiles(data_dir, history)
    cols = st.columns(3)
    for i, (label, value, delta) in enumerate(tile_list):
        cols[i % 3].metric(
            label, value, delta, delta_color="off" if label == "IBD market" else "normal"
        )
    with st.expander("The IBD market state (tracked, not a rule)", expanded=False):
        recent = market_view.ibd_recent(data_dir)
        if recent.empty:
            st.caption("Needs SPY's daily bars (data/market/spy_daily_seed.parquet).")
        else:
            st.dataframe(recent, hide_index=True, width="stretch")
        st.caption(market_view.IBD_CAPTION)
    hv = market_view.heat_view(data_dir, history)
    if hv:
        labels = {b["band"]: b["label"] for b in hv["bands"]}
        st.subheader(f"{hv['now'].capitalize()} market: scan count {hv['count']} "
                     f"({labels[hv['now']]})")  # fmt: skip
        pick = st.radio(
            "Setups at this heat",
            list(labels),
            index=list(labels).index(hv["now"]),
            horizontal=True,
            format_func=lambda b: f"{b} ({labels[b]})",
            key="heat_band",
        )
        hv = market_view.heat_view(data_dir, history, pick)
        st.dataframe(hv["table"], hide_index=True, width="stretch")
        st.caption(hv["caption"])
    market_overview()
    st.subheader("Breadth and the Market Light")
    st.dataframe(market_view.breadth(history), hide_index=True, width="stretch")
    st.line_chart(history.set_index("session_date")[["ratio_5d", "ratio_10d"]], height=220)

elif page == "Stats":
    st.subheader("Outcome statistics")
    minimum = st.slider("Minimum signals per group", 1, 50, CFG.stats["min_signals"])
    table, total = research_view.outcome_stats(data_dir, minimum)
    st.caption(f"{total} outcomes so far")
    if table.empty:
        st.info("Not enough outcomes yet.")
    else:
        st.dataframe(table, hide_index=True, width="stretch")

elif page == "History":
    st.subheader("History")
    period = st.radio(
        "Period",
        ["2y", "10y"],
        horizontal=True,
        format_func=lambda p: "2 years (Massive)" if p == "2y" else "10 years (Alpaca, since 2016)",
        index=1,
        key="hist_period",
    )
    if period == "10y":
        from_github("history-10y", "*.parquet")
    hist = history_cached(str(data_dir), period)
    if hist.empty:
        st.info(
            "No history here yet. 10 years: the files come from GitHub (is the `gh` CLI signed "
            "in, and is there a connection?). 2 years: build it with "
            "`scripts/strategy_history.py` and `scripts/ep_history.py`."
        )
        st.stop()
    st.caption(research_view.HISTORY_CAPTION)
    show_history_graded()
    names = sorted(hist["strategy"].unique())
    a, b, c = st.columns(3)
    picked = a.multiselect("Strategies", names, default=names, key="hist_strategies")
    years = sorted(hist["year"].dropna().unique().tolist())
    chosen_years = b.multiselect("Year", years, default=years, key="hist_years")
    states = c.multiselect("Breadth state that day", ["strong", "neutral", "weak"], key="hist_mkt")
    ep_on = "ep_day" in picked
    ep_args = None
    if ep_on:
        with st.expander("EP-Day filters", expanded=False):
            a, b, c = st.columns(3)
            gap_min = a.slider("Gap at least %", 0, 60, 10)
            rvol_min = b.slider("RVOL at least", 0.0, 20.0, 3.0, 0.5)
            months_min = c.slider("Months sideways at least", 0.0, 12.0, 0.0, 0.5)
            a, b = st.columns(2)
            earnings = a.selectbox("Earnings (inferred)", ["any", "yes", "no", "unknown"])
            must = b.multiselect("Criteria that must pass", EP_FLAGS)
        ep_args = (gap_min, rvol_min, months_min, earnings, tuple(must))
    filters = (period, tuple(picked), tuple(chosen_years), tuple(states), ep_args)
    view = history_filtered(str(data_dir), *filters)
    splits = research_view.HISTORY_SPLITS + (research_view.EP_SPLITS if ep_on else [])
    group = st.selectbox("Split by", splits, key="hist_split")
    st.subheader(f"{len(view):,} events")
    table, compared = history_tables(str(data_dir), filters, group)
    st.dataframe(table.round(2), hide_index=True, width="stretch")
    st.caption(research_view.SUMMARY_CAPTION)
    st.markdown("**Exits compared** (mean R with the stop; Qullamaggie and Stockbee management)")
    st.dataframe(compared.round(2), hide_index=True, width="stretch")
    one = st.selectbox("Events of", picked or names, key="hist_one")
    events = research_view.history_events(view, one)
    st.dataframe(events, hide_index=True, width="stretch", height=300)
    labels = [f"{r.session_date} · {r.ticker}" for r in events.head(500).itertuples()]
    pick = st.selectbox("Chart", ["—", *labels], key="hist_chart")
    if pick != "—":
        day_text, ticker = pick.split(" · ")
        row = events[
            (events["ticker"] == ticker) & (events["session_date"].astype(str) == day_text)
        ].iloc[0]
        bars = bars_for(str(data_dir), ticker, period)  # 10 years: Alpaca's bars
        if bars.empty or row["session_date"] < bars["session_date"].min():
            st.caption("No daily bars for that day on this PC (10 years: download them on Chart).")
            st.stop()
        side = "short" if row.get("side") == "short" else "long"
        marker = pd.DataFrame(
            [{"session_date": row["session_date"], "label_text": one, "side": side}]
        )
        stop = row["stop"] if row["stop"] == row["stop"] else None
        fig = ichart.daily_figure(
            research_view.event_window(bars, row["session_date"]),
            title=f"{ticker} · {one} {day_text} · then 63 sessions",
            overlays=["MA10", "MA20", "MA50"],
            markers=marker,
            levels={"stop": float(stop)} if stop is not None else None,
            height=520,
        )
        st.plotly_chart(fig, config=ichart.DRAW_CONFIG, key="hist-chart", width="stretch")

elif page == "Entries & exits":
    st.subheader("Entries & exits")
    ie_period = st.radio(
        "Period",
        ["2y", "10y"],
        horizontal=True,
        format_func=lambda p: "2 years (all trades)" if p == "2y" else "10 years (summaries)",
        index=1,
        key="ie_period",
    )
    if ie_period == "10y":
        with st.spinner("Fetching intraday-10y from GitHub…"):
            found_10y = research_view.entries_10y(data_dir)
        if found_10y is None:
            st.info("The 10-year minute study hasn't been published yet (release intraday-10y).")
            st.stop()
        overall, by_year = found_10y
        min_trades = st.slider("Minimum trades", 50, 2000, 200, step=50, key="ie10_min")
        st.subheader("Best entry, stop and exit per strategy, 10 years")
        st.dataframe(
            research_view.best(overall, min_trades).round(2), hide_index=True, width="stretch"
        )
        st.subheader("By year")
        exit_name = st.selectbox(
            "Exit",
            research_view.exits_of(overall),
            index=0,
            key="ie10_exit",
        )
        names = sorted(overall["strategy"].unique())
        one = st.selectbox("Strategy", names, key="ie10_strategy")
        table = research_view.by_year_table(by_year, one, exit_name)
        st.dataframe(table.round(2), hide_index=True, width="stretch")
        st.caption(
            f"Mean R per year for exit {exit_name} (groups of 20+ trades). A setup that only "
            "works in some years shows it here. Facts, not advice."
        )
        st.stop()
    with st.spinner("Fetching intraday-2y from GitHub…"):
        splits = research_view.entries_2y_splits(data_dir)
    if not splits:
        st.info("No minute study published yet (the data repo's intraday-2y release).")
        st.stop()
    st.caption(research_view.ENTRIES_CAPTION)
    group = st.selectbox("Split by", splits, key="ie_split")
    table = research_view.entries_2y(data_dir, group)
    names = sorted(table["strategy"].unique())
    picked = st.multiselect("Strategies", names, default=names, key="ie_strategies")
    table = table[table["strategy"].isin(picked)]
    min_trades = st.slider("Minimum trades", 10, 500, 50, step=10)
    st.subheader("Best entry, stop and exit per strategy")
    best_table = research_view.best(table, min_trades) if group == "none" else None
    if best_table is not None:
        st.dataframe(best_table.round(2), hide_index=True, width="stretch")
    else:
        st.caption("Shown for “none” (no split); the table below has every split.")
    exits_all = research_view.exits_of(table)
    default = [e for e in research_view.DEFAULT_EXITS if e in exits_all]
    shown = st.multiselect("Exits in the table", exits_all, default=default, key="ie_exits")
    st.subheader("Every entry and stop")
    st.dataframe(
        research_view.entries_table(table, group, shown, min_trades).round(2),
        hide_index=True,
        width="stretch",
    )
    one = st.selectbox("Trades of", ["—", *(picked or names)], key="ie_one")
    if one != "—":
        with st.spinner("Fetching the trades from GitHub…"):
            rows = research_view.strategy_trades(data_dir, one)
        st.dataframe(rows, hide_index=True, width="stretch")

elif page == "Validation":
    st.subheader("Validation against TradingView")
    if not runs:
        st.info("No runs yet.")
        st.stop()
    with_universe = [r for r in runs if r.universe.exists()]  # intraday runs keep no snapshot
    run = st.selectbox("Run", with_universe, format_func=lambda r: r.label)
    scan = st.selectbox("Scan", ["ep_day", "qm_gainers"], format_func=report.SCAN_LABELS.get)
    upload = st.file_uploader("TradingView screener export (CSV)", type=["csv"])
    if upload is not None:
        screen = validation.read_screen(io.BytesIO(upload.getvalue()))
        result = validation.compare(
            candidates_of(run), read_parquet(str(run.universe)), screen, CFG.scans[scan]
        )
        st.dataframe(result, hide_index=True, width="stretch")
        text = validation.to_markdown(result, f"{scan} vs TradingView · {run.label}")
        if st.button("Append to docs/validation.md"):
            target = data_dir / "docs" / "validation.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as fh:
                fh.write("\n" + text)
            st.success("Appended. Use “Save & push” to send it to GitHub.")

st.caption(
    f"{len(runs)} runs · {dt.date.today().isoformat()} · session "
    f"{clock.session_date(CFG.schedule, 'eod', dt.datetime.now(dt.UTC))}"
)
