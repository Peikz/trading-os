"""Trading OS dashboard: a private web app over the local clone of the data repo.

    uv run --group app streamlit run app/streamlit_app.py

Reads runs, charts, breadth, watchlists, outcomes and the journal; writes your grades, notes
and screenshots back to the data repo (append-only) and can pull / push it. Never deploy this
from the public repo with data in it: the data stays in the private repo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd
import streamlit as st

from trading_os import (
    breadth,
    charts,
    clock,
    dashboard,
    exits,
    health,
    history,
    intraday_study,
    journal,
    long_history,
    luk,
    minervini,
    my_watchlists,
    outcomes,
    plans,
    report,
    review,
    sizing,
    stats,
    strategy_history,
    tv,
    validation,
)
from trading_os.config import load_config

st.set_page_config(page_title="Trading OS", page_icon="📈", layout="wide")
CFG = load_config()
_cli = argparse.ArgumentParser()
_cli.add_argument("--data-dir", default=None)  # streamlit run app/streamlit_app.py -- --data-dir X
_args, _ = _cli.parse_known_args(sys.argv[1:])
DEFAULT_DATA = Path(
    _args.data_dir
    or os.environ.get("TRADING_OS_DATA", Path(__file__).resolve().parents[2] / "trading-os-data")
)
PAGES = [
    "Today",
    "Screens",
    "Watchlists",
    "Journal",
    "Graded signals",
    "Market",
    "Stats",
    "History",
    "Entries & exits",
    "Market regime",
    "System health",
    "Validation",
    "Guide",
]


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.title("Trading OS")
    page = st.radio("Page", PAGES, label_visibility="collapsed")
    data_dir = Path(st.text_input("Data repo folder", str(DEFAULT_DATA)))
    include_manual = st.toggle("Show manual test runs", value=True)
    left, right = st.columns(2)
    if left.button("Pull latest", width="stretch"):
        ok, out = dashboard.pull(data_dir)
        (st.success if ok else st.error)(out or "up to date")
        st.cache_data.clear()
    if right.button("Save & push", width="stretch"):
        ok, out = dashboard.save_and_push(data_dir)
        (st.success if ok else st.error)(out or "saved")

if not (data_dir / "data").exists():
    st.error(f"No data folder at {data_dir}. Clone trading-os-data there or fix the path.")
    st.stop()


# ---------------------------------------------------------------- cached loaders


@st.cache_data(ttl=60)
def runs_cached(folder: str, manual: bool) -> list[dashboard.Run]:
    return dashboard.list_runs(Path(folder), include_manual=manual)


@st.cache_data(ttl=60)
def read_parquet(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


CHART_CACHE = Path(os.environ.get("TEMP", "/tmp")) / "trading-os-charts"


@st.cache_data(ttl=600)
def strategy_cached(folder: str) -> pd.DataFrame:
    return strategy_history.load(folder)


@st.cache_data(ttl=600)
def intraday_cached(folder: str) -> pd.DataFrame:
    return intraday_study.load_results(folder)


@st.cache_data(ttl=600)
def ticker_bars(folder: str, ticker: str) -> pd.DataFrame:
    """One stock's daily bars from the Massive files (for the EP history charts)."""
    import pyarrow.dataset as ds

    root = Path(folder) / "data" / "bars"
    if not root.exists():
        return pd.DataFrame(columns=["session_date", "open", "high", "low", "close", "volume"])
    table = ds.dataset(root, format="parquet").to_table(filter=ds.field("ticker") == ticker)
    bars = table.to_pandas()
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    return bars.drop_duplicates("session_date").sort_values("session_date")


def candidates_of(run: dashboard.Run) -> pd.DataFrame:
    return read_parquet(str(run.candidates))


FORMATS = {"money": "compact", "shares": "compact", "int": "%d"}


def tradingview_url(ticker: str, exchange: str | None = None) -> str:
    """The stock's TradingView chart (exchange-qualified when known)."""
    symbol = f"{exchange}:{ticker}" if exchange else str(ticker)
    return f"https://www.tradingview.com/chart/?symbol={symbol.replace(':', '%3A')}"


@st.cache_data(ttl=600)
def exchanges_of(universe_path: str) -> dict[str, str]:
    """Ticker -> exchange from a run's universe snapshot (intraday runs have none)."""
    path = Path(universe_path)
    if not path.exists():
        return {}
    uni = pd.read_parquet(path)
    if "exchange" not in uni:
        return {}
    return dict(zip(uni["ticker"], uni["exchange"], strict=True))


def show_table(scan: str, hits: pd.DataFrame, exchanges: dict | None = None) -> None:
    """The same columns and number formats as the Markdown report, plus a TradingView link."""
    columns = [("Rank", "rank", "int"), ("Ticker", "ticker", "text")]
    columns += [("Chart", "tradingview", "link"), ("Tier", "tier", "text")]
    columns += report.COLUMNS.get(scan, [])
    view = hits.copy()
    view["tradingview"] = [tradingview_url(t, (exchanges or {}).get(t)) for t in view["ticker"]]
    if scan.startswith("breakout_"):
        view["b_flags"] = [report._b_flags(r) for r in view.to_dict("records")]
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


@st.cache_data(ttl=3600)
def fx_rate(folder: str, currency: str) -> float | None:
    """Units of the account currency per USD: live from TradingView, else the rate stored with
    the newest planned alerts, else None (then sizes are not suggested)."""
    if currency == "USD":
        return 1.0
    try:
        return tv.fetch_fx(CFG.sizing["fx_symbol"].format(currency=currency))
    except Exception:  # offline or TradingView down: fall back to the stored rate
        for run in dashboard.list_runs(Path(folder))[:10]:
            cands = read_parquet(str(run.candidates))
            if "plan_fx_rate" in cands and cands["plan_fx_rate"].notna().any():
                return float(cands["plan_fx_rate"].dropna().iloc[0])
    return None


def setup_names() -> list[str]:
    """Live scans and the study-only setups, for tagging trades and plans."""
    return sorted({*CFG.scans, *luk.STRATEGIES, *minervini.STRATEGIES} - {"breadth"})


@st.cache_data(ttl=600)
def recent_bars(folder: str, tickers: tuple[str, ...], sessions: int = 10) -> pd.DataFrame:
    """The newest daily bars of a few tickers (Massive, else EOD snapshots)."""
    days = clock.sessions_back(CFG.schedule, dt.date.today(), sessions)
    try:
        bars = history.load_bars(Path(folder), days)
    except (KeyError, ValueError, OSError):  # a snapshot without the bar columns: no marks
        return pd.DataFrame(columns=["ticker", "session_date", "close"])
    return bars[bars["ticker"].isin(tickers)]


def trade_bars(folder: str, trades: pd.DataFrame) -> pd.DataFrame:
    """Daily bars of the traded tickers over the trades' dates."""
    if trades.empty:
        return pd.DataFrame()
    frames = [ticker_bars(folder, t) for t in sorted(set(trades["ticker"]))]
    frames = [
        f.assign(ticker=t) for f, t in zip(frames, sorted(set(trades["ticker"])), strict=True)
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@st.cache_data(ttl=600)
def latest_hits(folder: str) -> pd.DataFrame:
    """Planned hits (entry, stop) of the newest run, for starting a plan from a scan."""
    runs = dashboard.list_runs(Path(folder))
    if not runs:
        return pd.DataFrame()
    cands = read_parquet(str(runs[0].candidates))
    if "plan_entry" not in cands:
        return pd.DataFrame()
    keep = cands.dropna(subset=["plan_entry", "plan_stop"])
    return keep.sort_values(["scan", "rank"])[["ticker", "scan", "plan_entry", "plan_stop"]]


@st.cache_data(ttl=600)
def study_by_strategy(folder: str) -> dict[str, pd.DataFrame]:
    """History-study trades per strategy (EP-Day from the EP study, alert tier)."""
    hist = strategy_cached(folder)
    out = {k: v for k, v in hist.groupby("strategy")} if len(hist) else {}
    built = sorted((Path(folder) / "data" / "ep_history").glob("ep_history_*.parquet"))
    if built:
        ep = pd.read_parquet(built[-1], columns=["is_ep_day", "tier", "r_21d", "r_trail_ma20"])
        out["ep_day"] = ep[ep["is_ep_day"] & (ep["tier"] == "alert")]
    return out


def show_trade_chart(trade: dict, open_trade: bool = False) -> None:
    """Daily chart around one trade with the fills marked and the stop line."""
    bars = ticker_bars(str(data_dir), trade["ticker"])
    if bars.empty:
        st.caption("No daily bars for this ticker in the data repo.")
        return
    end = trade.get("exit_date") if not open_trade else None
    end = end if end is not None and end == end else bars["session_date"].max()
    held = (bars["session_date"] > trade["entry_date"]) & (bars["session_date"] <= end)
    after = int(held.sum()) + 5
    buy = "buy" if trade["direction"] == "long" else "sell"
    sell = "sell" if buy == "buy" else "buy"
    marks = [(trade["entry_date"], trade["entry_avg"], buy)]
    if not open_trade and trade.get("exit_avg") == trade.get("exit_avg"):
        marks.append((trade["exit_date"], trade["exit_avg"], sell))
    stop = pd.to_numeric(trade.get("order_stop"), errors="coerce")
    tag = f"{trade['ticker']}_{trade['entry_date']}_{end}_{len(marks)}"
    drawn = charts.before_shot(
        bars,
        Path(CHART_CACHE) / f"trade_{tag}.png",
        title=f"{trade['ticker']} · {trade['direction']} {trade['entry_date']} → {end}",
        signal_session=trade["entry_date"],
        sessions=60,
        order_stop=stop if stop == stop else None,
        after=after,
        marks=marks,
    )
    if drawn:
        st.image(str(drawn))


EP_FLAGS = ["c1_gap", "c2_volume", "c3_growth", "c4_neglect", "c5_stop"]


LONG_HISTORY = ("data", "history_10y")  # the history-10y release, downloaded
MINUTE_10Y = ("data", "intraday_10y")
REGIME_10Y = (
    "data",
    "regime_10y",
)  # the regime-10y release, downloaded  # the intraday-10y release's summaries, downloaded
HISTORY_COLUMNS = [
    "strategy",
    "side",
    "session_date",
    "ticker",
    "entry",
    "stop",
    "stop_adr",
    "close",
    "chg_pct",
    "gap_pct",
    "rvol50",
    "mkt_breadth_state",
    "mkt_qqq_trend",
    "above_ma200",
    "pnl_1d",
    "pnl_5d",
    "pnl_21d",
    "pnl_63d",
    "r_5d",
    "r_21d",
    "r_63d",
    "stop_hit_5d",
    "r_trail_ma10",
    "r_trail_ma20",
    "r_trail_ema9",
    "r_trail_ema21",
    "r_q3_ma10",
    "r_q3_ma20",
    "r_q5_ma10",
    "r_q5_ma20",
    "r_time3d",
    "r_time5d",
    "r_target8_5d",
]
EP_COLUMNS = [
    "is_ep_day",
    "tier",
    "plan_entry",
    "plan_stop",
    "months_sideways",
    "earnings_inferred",
    "eps_growth_yoy",
    "sales_growth_yoy",
    "ret_1d",
    "ret_5d",
    "ret_21d",
    "ret_63d",
]


@st.cache_data(ttl=600)
def history_cached(folder: str, period: str = "2y") -> pd.DataFrame:
    """The strategy history plus the EP study's alert-tier EP-Days as strategy `ep_day`, in
    one shape: the EP study's returns become `pnl_*`, its planned entry and stop `entry` and
    `stop`; its criteria and fundamentals columns come along for the EP filters. `10y`:
    the yearly files of the history-10y release (only the columns the page uses)."""
    if period == "10y":
        long_dir = Path(folder).joinpath(*LONG_HISTORY)
        hist = long_history.load(long_dir, "strategy", HISTORY_COLUMNS)
        ep = long_history.load(long_dir, "ep", [*HISTORY_COLUMNS, *EP_COLUMNS, *EP_FLAGS])
    else:
        hist = strategy_cached(folder)
        built = sorted((Path(folder) / "data" / "ep_history").glob("ep_history_*.parquet"))
        ep = read_parquet(str(built[-1])) if built else pd.DataFrame()
    if ep.empty:
        return hist
    ep = ep[ep["is_ep_day"] & (ep["tier"] == "alert")].copy()
    ep["session_date"] = pd.to_datetime(ep["session_date"]).dt.date
    outcome = re.compile(r"^ret_\d+d$")  # outcomes only; ret_22 etc. are features
    ep = ep.rename(columns={c: "pnl_" + c[4:] for c in ep.columns if outcome.match(c)})
    ep = ep.assign(strategy="ep_day", side="long", entry=ep["plan_entry"], stop=ep["plan_stop"])
    ep["criteria_met"] = ep[EP_FLAGS].fillna(False).astype(bool).sum(axis=1)
    extra = ("gap_pct", "rvol50", "months_sideways", "earnings_inferred", "criteria_met")
    extra += ("eps_growth_yoy", "sales_growth_yoy", *EP_FLAGS)
    for column in extra:
        if column not in hist:
            hist = hist.assign(**{column: None})
    return pd.concat([hist, ep[[c for c in ep.columns if c in hist]]], ignore_index=True)


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

if page == "Today":
    st.header("Today")
    if not runs:
        st.info("No runs yet. The first scheduled run writes here.")
        st.stop()
    latest_eod = next((r for r in runs if r.slot == "eod"), None)
    latest_pm = next((r for r in runs if r.slot == "pm"), None)
    st.subheader("Market")
    if (
        latest_pm is not None
        and latest_pm.breadth_pm is not None
        and (latest_eod is None or latest_pm.session > latest_eod.session)
    ):
        pm_row = read_parquet(str(latest_pm.breadth_pm)).iloc[0].to_dict()
        last = breadth.latest_eod_row(data_dir, latest_pm.session)
        for line in breadth.premarket_lines(pm_row, last):
            st.markdown(f"- {line}")
    else:
        market_lines(latest_eod)
    latest_am = next((r for r in runs if r.slot == "am"), None)
    latest_mid = next((r for r in runs if r.slot == "mid"), None)
    latest = [r for r in (latest_pm, latest_am, latest_mid, latest_eod) if r is not None]
    for run in sorted(latest, key=runs.index):  # newest first
        st.subheader(run.label)
        cands = candidates_of(run)
        for scan, hits in cands.groupby("scan", sort=False):
            if CFG.scans[scan].action != "push":
                continue
            shown = hits[hits["tier"] == "alert"] if "push_tier" in CFG.scans[scan].params else hits
            label = report.SCAN_LABELS.get(scan, scan)
            st.markdown(f"**{label}** — {len(shown)} of {len(hits)} hits")
            show_table(scan, shown, exchanges_of(str(run.universe)))
            facts = report.fact_lines(scan, shown)
            if facts:
                st.markdown("\n".join(facts))
            charts = [(t, dashboard.chart_for(run, scan, t)) for t in shown["ticker"].head(10)]
            charts = [(t, p) for t, p in charts if p is not None]
            if charts:
                cols = st.columns(min(3, len(charts)))
                for i, (ticker, path) in enumerate(charts):
                    cols[i % len(cols)].image(str(path), caption=ticker)

elif page == "Screens":
    st.header("Screens")
    if not runs:
        st.info("No runs yet.")
        st.stop()
    run = st.selectbox("Run", runs, format_func=lambda r: r.label)
    cands = candidates_of(run)
    scans = list(dict.fromkeys(cands["scan"]))
    scan = st.selectbox("Scan", scans, format_func=lambda s: report.SCAN_LABELS.get(s, s))
    hits = cands[cands["scan"] == scan]
    tiers = st.multiselect("Tier", ["alert", "log"], default=["alert", "log"])
    hits = hits[hits["tier"].isin(tiers)]
    st.caption(f"{len(hits)} hits")
    exchanges = exchanges_of(str(run.universe))
    show_table(scan, hits, exchanges)
    if len(hits):
        ticker = st.selectbox("Look at", hits["ticker"].tolist())
        st.link_button("Open in TradingView", tradingview_url(ticker, exchanges.get(ticker)))
        row = hits[hits["ticker"] == ticker].iloc[0]
        chart = dashboard.chart_for(run, scan, ticker)
        if chart:
            st.image(str(chart))
        else:
            st.caption("No chart for this one (charts are drawn for pushed candidates).")
        grade_form(
            "signal", row["signal_id"], f"Grade {ticker} · {scan}", f"sig-{row['signal_id']}"
        )

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
                added = my_watchlists.add(data_dir, name or "", tickers, note)
                if added:
                    st.success(f"Added {added} to {name}.")
                else:
                    st.warning("No tickers to add.")
                st.cache_data.clear()
            except ValueError as exc:
                st.error(str(exc))
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
        a, b = st.columns([3, 1])
        gone = a.multiselect("Remove from the list", members["ticker"].tolist(), key="wl_rm")
        if b.button("Remove") and gone:
            my_watchlists.remove(data_dir, name, gone)
            st.cache_data.clear()
            st.rerun()
    st.caption("Saved in the data repo; use “Save & push” to send them to GitHub.")

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
        st.caption("Column names are mapped in config/scans.yaml → journal.csv_columns.")
        upload = st.file_uploader("Fills export", type=["csv"])
        if upload is not None and st.button("Import"):
            tmp = data_dir / "data" / "journal" / f"_upload_{upload.name}"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(upload.getvalue())
            buffer = io.StringIO()
            try:
                with redirect_stdout(buffer):
                    journal.main(["--csv", str(tmp), "--data-dir", str(data_dir)])
                st.success(buffer.getvalue() or "Imported.")
            except ValueError as exc:
                st.error(str(exc))
            finally:
                tmp.unlink(missing_ok=True)

    account = sizing.load_account(data_dir)
    usd_rate = fx_rate(str(data_dir), account.currency if account else "USD")
    account_usd = account.size_usd(usd_rate) if account and usd_rate else None
    trades = dashboard.latest_journal(data_dir)
    positions = dashboard.latest_positions(data_dir)
    setups = setup_names()
    tab_open, tab_log, tab_plans, tab_closed, tab_real = st.tabs(
        ["Open positions", "Log a trade", "Plans", "Closed trades", "Real vs study"]
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
            cols = ["ticker", "direction", "entry_date", "entry_avg", "open_quantity"]
            cols += ["order_stop", "last_close", "last_date", "open_pnl", "open_r"]
            cols += ["at_risk_usd", "at_risk_pct", "setup"]
            st.dataframe(
                view[[c for c in cols if c in view]].round(2), hide_index=True, width="stretch"
            )
            st.caption("Valued at the newest daily close in the data repo, not live prices.")
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
        plan_events = plans.load(data_dir)
        fills = journal.reconcile(journal.load_fills(data_dir))
        today = clock.ny_time(CFG.schedule, dt.datetime.now(dt.UTC)).date()
        current = plans.status(
            plan_events, fills, CFG.schedule, CFG.journal["plan_valid_sessions"], today
        )
        hits = latest_hits(str(data_dir))
        options = ["—"] + [
            f"{r['ticker']} · {r['scan']} · buy {r['plan_entry']:.2f} stop {r['plan_stop']:.2f}"
            for r in hits.to_dict("records")
        ]
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
            suggestion = None
            if account and usd_rate and entry and pstop:
                suggestion = plans.shares_for(
                    entry,
                    pstop,
                    account.risk_usd(usd_rate),
                    account.size_usd(usd_rate),
                    account.max_position_pct,
                )
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
            st.caption(
                f"Suggested: {suggestion['shares']:,} shares · ${suggestion['position_usd']:,.0f}"
                f" · risk ${suggestion['risk_usd']:,.0f}"
                + (" (capped by max position)" if suggestion["capped"] else "")
            )
        if current.empty:
            st.info("No plans yet.")
        else:
            cols = ["status", "session_date", "ticker", "direction", "setup", "entry", "stop"]
            cols += ["shares", "risk_usd", "fill_date", "fill_price", "slippage_pct"]
            cols += ["slippage_r", "note", "plan_id"]
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
            notes = dashboard.notes_state(data_dir)
            graded = notes[notes["kind"] == "trade"].set_index("ref_id")["grade"].to_dict()
            trades = trades.assign(grade=trades["trade_id"].map(graded).fillna(""))
            bars = trade_bars(str(data_dir), trades)
            trades = review.excursions(trades, bars)
            with_r = trades["r_multiple"].dropna()
            a, b, c, d = st.columns(4)
            a.metric("Closed trades", len(trades))
            b.metric("Win rate", f"{(trades['pnl'] > 0).mean() * 100:.0f}%")
            c.metric("Avg R", f"{with_r.mean():.2f}" if len(with_r) else "n/a")
            d.metric("Total P&L", f"{trades['pnl'].sum():,.0f}")
            if len(with_r):
                curve = trades.dropna(subset=["r_multiple"]).sort_values("exit_date")
                st.line_chart(curve.set_index("exit_date")["r_multiple"].cumsum(), height=200)
            cols = ["ticker", "direction", "setup", "entry_date", "exit_date", "entry_avg"]
            cols += ["exit_avg", "quantity", "pnl", "r_multiple", "mfe_r", "mae_r"]
            cols += ["exit_efficiency", "sessions_held", "signal_scan", "grade"]
            st.dataframe(
                trades[[c for c in cols if c in trades]].round(2),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "MFE/MAE: best and worst price from the session after entry to the exit, in R. "
                "Exit efficiency: the R you took as a share of the MFE."
            )
            pick = st.selectbox(
                "Review a trade",
                trades.to_dict("records"),
                format_func=lambda t: (
                    f"{t['ticker']} {t['entry_date']} → {t['exit_date']} ({t['pnl']:,.0f})"
                ),
            )
            show_trade_chart(pick)
            grade_form(
                "trade", pick["trade_id"], f"{pick['ticker']} trade", f"tr-{pick['trade_id']}"
            )

    with tab_real:
        if trades.empty:
            st.info("Your real R per setup shows here once trades are closed.")
        else:
            daily = study_by_strategy(str(data_dir))
            minute = intraday_cached(str(data_dir))
            best = intraday_study.best(intraday_study.summary(minute), 50) if len(minute) else None
            table = review.real_vs_study(trades, daily, best)
            st.dataframe(table.round(2), hide_index=True, width="stretch")
            st.caption(
                "Study = the history replay of the same strategy (entry at the signal, its stop): "
                "21-session hold and 20-day MA trail; minute best = the minute study's best "
                "entry, stop and exit. The gap between your R and the study's is execution "
                "(entries, exits, selection). Facts, not advice."
            )

elif page == "Market regime":
    st.header("Market regime")
    folder = data_dir.joinpath(*REGIME_10Y)
    needed = ["regime_daily", "regime_minute", "regime_minute_by_year"]
    needed += ["regime_daily_study", "regime_daily_study_by_year"]
    if not all((folder / f"{n}.parquet").exists() for n in needed):
        st.info("The regime study isn't on this PC yet (the data repo's regime-10y release).")
        if st.button("Download it"):
            ok, out = dashboard.download_release(data_dir, "regime-10y", folder)
            if ok:
                st.success("Downloaded.")
            else:
                st.error(out)
            st.rerun()
        st.stop()
    st.caption(
        "Would skipping trades in a bad market have helped? Each trade gets the regime known "
        "before it was entered (the prior close; for entries at a signal's close, that close) "
        "and each filter keeps or skips it. Market Light = your rules (QQQ trend, breadth, the "
        "Sunday scan count) rebuilt from 10 years of daily bars; ETFs and funds left out. "
        "Mean R capped at 20 per trade. Facts, not advice."
    )
    daily = read_parquet(str(folder / "regime_daily.parquet"))
    daily["year"] = pd.to_datetime(daily["session_date"]).dt.year
    mix = pd.crosstab(daily["year"], daily["light"].fillna("n/a"), normalize="index") * 100
    st.subheader("Market Light per year (% of sessions)")
    st.dataframe(mix.round(0), width="stretch")
    source = st.radio(
        "Trades",
        ["minute", "daily"],
        horizontal=True,
        format_func=lambda s: (
            "Minute study (entries and stops)" if s == "minute" else "Daily histories"
        ),
        key="rg_source",
    )
    name = "regime_minute" if source == "minute" else "regime_daily_study"
    table = read_parquet(str(folder / f"{name}.parquet"))
    by_year = read_parquet(str(folder / f"{name}_by_year.parquet"))
    exits = [c[2:] for c in table.columns if c.startswith("R_")]
    a, b = st.columns(2)
    strategy = a.selectbox("Strategy", sorted(table["strategy"].unique()), key="rg_strategy")
    exit_name = b.selectbox("Exit", exits, index=0, key="rg_exit")
    part = table[table["strategy"] == strategy]
    year_part = by_year[by_year["strategy"] == strategy]
    if source == "minute":
        a, b = st.columns(2)
        entry = a.selectbox("Entry", sorted(part["entry"].unique()), key="rg_entry")
        stops = sorted(part.loc[part["entry"] == entry, "stop_rule"].unique())
        stop = b.selectbox("Stop", stops, key="rg_stop")
        part = part[(part["entry"] == entry) & (part["stop_rule"] == stop)]
        year_part = year_part[(year_part["entry"] == entry) & (year_part["stop_rule"] == stop)]
    base = part.loc[part["filter"] == "all", "trades"]
    view = part[["filter", "trades", f"R_{exit_name}", f"win_{exit_name}%"]].copy()
    if len(base):
        view.insert(2, "kept_%", view["trades"] / base.iloc[0] * 100)
    st.subheader("Each filter, all years")
    st.dataframe(
        view.sort_values(f"R_{exit_name}", ascending=False).round(2),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Year by year (mean R)")
    pivot = year_part.pivot_table(index="year", columns="filter", values=f"R_{exit_name}")
    st.dataframe(pivot.round(2), width="stretch")

elif page == "Guide":
    st.header("Guide")
    guide = Path(__file__).resolve().parents[1] / "docs" / "GUIDE.md"
    text = guide.read_text(encoding="utf-8")
    body = text.splitlines()[1:]  # the file's own title is the page header
    st.markdown("\n".join(body))

elif page == "System health":
    st.header("System health")
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
    st.dataframe(health.freshness(data_dir, CFG.schedule, now), hide_index=True, width="stretch")
    st.subheader("Failures (newest first)")
    failures = health.errors(data_dir)
    if failures.empty:
        st.success("No failure logs.")
    else:
        st.dataframe(failures, hide_index=True, width="stretch")
    st.subheader("GitHub runs")
    if st.button("Load the latest runs from GitHub"):
        st.session_state["gh_runs"] = health.github_runs()
    gh_runs = st.session_state.get("gh_runs")
    if gh_runs is not None:
        if gh_runs.empty:
            st.warning("No answer from GitHub (is the gh CLI installed and signed in?).")
        else:
            st.dataframe(gh_runs, hide_index=True, width="stretch")
            st.caption(
                "minutes_late: how long after its cron GitHub started a scheduled run. A run "
                "that starts after its window closes exits without scanning."
            )

elif page == "Graded signals":
    st.header("Graded signals")
    notes = dashboard.notes_state(data_dir)
    graded = notes[notes["kind"] == "signal"]
    if graded.empty:
        st.info("Grade signals on the Screens page; they show up here with their outcomes.")
        st.stop()
    cands = outcomes.load_candidates(data_dir)
    found = stats.load_outcomes(data_dir)
    view = graded.merge(
        cands[["signal_id", "session_date", "scan", "ticker", "tier"]].drop_duplicates("signal_id"),
        left_on="ref_id",
        right_on="signal_id",
        how="left",
    )
    if not found.empty:
        wide = found.pivot_table(index="signal_id", columns="horizon", values="close_ret_pct")
        wide.columns = [f"ret_{h}d" for h in wide.columns]
        view = view.merge(wide, left_on="ref_id", right_index=True, how="left")
    st.dataframe(view.drop(columns=["kind", "signal_id"]), hide_index=True, width="stretch")

elif page == "Market":
    st.header("Market")
    history = dashboard.breadth_history(data_dir)
    if history.empty:
        st.info("Breadth rows start with the first scheduled EOD run.")
        st.stop()
    st.dataframe(
        history[
            [
                "session_date",
                "light",
                "qqq_trend",
                "breadth_state",
                "scan_count",
                "up4",
                "down4",
                "ratio_5d",
                "ratio_10d",
                "up25q",
                "down25q",
            ]
        ].iloc[::-1],
        hide_index=True,
        width="stretch",
    )
    st.line_chart(history.set_index("session_date")[["ratio_5d", "ratio_10d"]], height=220)

elif page == "Stats":
    st.header("Outcome statistics")
    found = stats.load_outcomes(data_dir)
    minimum = st.slider("Minimum signals per group", 1, 50, CFG.stats["min_signals"])
    table = stats.summarize(outcomes.load_candidates(data_dir), found, minimum)
    st.caption(f"{len(found)} outcomes so far")
    if table.empty:
        st.info("Not enough outcomes yet.")
    else:
        st.dataframe(table, hide_index=True, width="stretch")

elif page == "History":
    st.header("History")
    period = st.radio(
        "Period",
        ["2y", "10y"],
        horizontal=True,
        format_func=lambda p: "2 years (Massive)" if p == "2y" else "10 years (Alpaca, since 2016)",
        key="hist_period",
    )
    long_dir = data_dir.joinpath(*LONG_HISTORY)
    if period == "10y" and not list(long_dir.glob("strategy_*.parquet")):
        st.info("The 10-year history isn't on this PC yet (the data repo's history-10y release).")
        if st.button("Download it"):
            ok, out = dashboard.download_release(data_dir, "history-10y", long_dir)
            if ok:
                st.success("Downloaded.")
            else:
                st.error(out)
            st.cache_data.clear()
            st.rerun()
        st.stop()
    hist = history_cached(str(data_dir), period)
    if hist.empty:
        st.info(
            "No history yet. Build it with `scripts/strategy_history.py` and "
            "`scripts/ep_history.py`."
        )
        st.stop()
    st.caption(
        "Every alert-tier hit of each scan over the Massive bars (EP-Day from the EP study, "
        "with its criteria), the market that day and what happened after. P&L is in the strategy's "
        "direction (shorts profit when it falls). Entries at the signal close (EP-Day: the gap-day "
        "close, stop at the day low within the live ADR bounds); other stops as in "
        "`strategy_history.py`. Facts, not advice; the grade is yours."
    )
    names = sorted(hist["strategy"].unique())
    a, b, c = st.columns(3)
    picked = a.multiselect("Strategies", names, default=names, key="hist_strategies")
    years = sorted({d.year for d in hist["session_date"]})
    chosen_years = b.multiselect("Year", years, default=years, key="hist_years")
    states = c.multiselect("Breadth state that day", ["strong", "neutral", "weak"], key="hist_mkt")
    keep = hist["strategy"].isin(picked) & hist["session_date"].map(lambda d: d.year).isin(
        chosen_years
    )
    if states:
        keep &= hist["mkt_breadth_state"].isin(states)
    ep_on = "ep_day" in picked
    if ep_on:
        with st.expander("EP-Day filters", expanded=False):
            a, b, c = st.columns(3)
            gap_min = a.slider("Gap at least %", 0, 60, 10)
            rvol_min = b.slider("RVOL at least", 0.0, 20.0, 3.0, 0.5)
            months_min = c.slider("Months sideways at least", 0.0, 12.0, 0.0, 0.5)
            a, b = st.columns(2)
            earnings = a.selectbox("Earnings (inferred)", ["any", "yes", "no", "unknown"])
            must = b.multiselect("Criteria that must pass", EP_FLAGS)
        ep = hist["strategy"] == "ep_day"
        ok = (hist["gap_pct"] >= gap_min) & (hist["rvol50"] >= rvol_min)
        ok &= hist["months_sideways"].fillna(0) >= months_min
        known = hist["earnings_inferred"]
        if earnings == "yes":
            ok &= known.eq(True)
        elif earnings == "no":
            ok &= known.eq(False)
        elif earnings == "unknown":
            ok &= known.isna()
        for flag in must:
            ok &= hist[flag].fillna(False).astype(bool)
        keep &= ~ep | ok
    view = hist[keep].copy()
    view["year"] = view["session_date"].map(lambda d: d.year)
    view["price_bucket"] = pd.cut(
        view["close"], [0, 5, 10, 50, 1e9], labels=["<5", "5-10", "10-50", "50+"]
    )
    splits = ["none", "year", "mkt_breadth_state", "mkt_qqq_trend", "price_bucket", "above_ma200"]
    if ep_on:
        view["gap_bucket"] = pd.cut(
            view["gap_pct"], [0, 15, 25, 50, 1e9], labels=["<15", "15-25", "25-50", "50+"]
        )
        view["rvol_bucket"] = pd.cut(
            view["rvol50"], [0, 5, 10, 20, 1e9], labels=["<5", "5-10", "10-20", "20+"]
        )
        splits += ["earnings_inferred", "criteria_met", "gap_bucket", "rvol_bucket", "c4_neglect"]
    group = st.selectbox("Split by", splits, key="hist_split")
    by = None if group == "none" else [group]
    st.subheader(f"{len(view):,} events")
    table = strategy_history.summary(view, by)
    st.dataframe(table.round(2), hide_index=True, width="stretch")
    st.caption(
        "win/med = share up and median % move after 1, 5, 21 and 63 sessions; R = mean R with the "
        "stop (capped at 20); trails = out at the first close under the 10/20-day MA or EMA 9/21."
    )
    st.markdown("**Exits compared** (mean R with the stop; Qullamaggie and Stockbee management)")
    compared = exits.compare(view[view["entry"].notna()], CFG.exits, ["strategy", *(by or [])])
    st.dataframe(compared.round(2), hide_index=True, width="stretch")
    one = st.selectbox("Events of", picked or names, key="hist_one")
    events = view[view["strategy"] == one].sort_values("session_date", ascending=False)
    columns = ["session_date", "ticker", "side", "entry", "stop", "stop_adr", "chg_pct"]
    if one == "ep_day":
        columns += ["gap_pct", "rvol50", "months_sideways", "eps_growth_yoy", "sales_growth_yoy"]
        columns += ["earnings_inferred", "criteria_met"]
    columns += ["pnl_5d", "pnl_21d", "pnl_63d", "r_21d", "r_trail_ma20", "mkt_breadth_state"]
    st.dataframe(
        events[[c for c in columns if c in events]], hide_index=True, width="stretch", height=300
    )
    labels = [f"{r.session_date} · {r.ticker}" for r in events.head(500).itertuples()]
    pick = st.selectbox("Chart", ["—", *labels], key="hist_chart")
    if pick != "—":
        day_text, ticker = pick.split(" · ")
        row = events[
            (events["ticker"] == ticker) & (events["session_date"].astype(str) == day_text)
        ].iloc[0]
        path = Path(CHART_CACHE) / f"{one}_{ticker}_{day_text}.png"
        drawn = charts.before_shot(
            ticker_bars(str(data_dir), ticker),
            path,
            title=f"{ticker} · {one} {day_text} · then 63 sessions",
            signal_session=row["session_date"],
            sessions=120,
            order_stop=row["stop"] if row["stop"] == row["stop"] else None,
            after=63,
        )
        if drawn:
            st.image(str(drawn))

elif page == "Entries & exits":
    st.header("Entries & exits")
    ie_period = st.radio(
        "Period",
        ["2y", "10y"],
        horizontal=True,
        format_func=lambda p: "2 years (all trades)" if p == "2y" else "10 years (summaries)",
        key="ie_period",
    )
    if ie_period == "10y":
        ten = data_dir.joinpath(*MINUTE_10Y)
        files = [ten / "intraday_summary_10y.parquet", ten / "intraday_summary_10y_by_year.parquet"]
        if not all(f.exists() for f in files):
            st.info("The 10-year minute study isn't on this PC yet (release intraday-10y).")
            if st.button("Download the summaries"):
                ok, out = dashboard.download_release(
                    data_dir, "intraday-10y", ten, ["intraday_summary_10y*.parquet"]
                )
                if ok:
                    st.success("Downloaded.")
                else:
                    st.error(out)
                st.rerun()
            st.stop()
        overall, by_year = (read_parquet(str(f)) for f in files)
        min_trades = st.slider("Minimum trades", 50, 2000, 200, step=50, key="ie10_min")
        st.subheader("Best entry, stop and exit per strategy, 10 years")
        st.dataframe(
            intraday_study.best(overall, min_trades).round(2), hide_index=True, width="stretch"
        )
        st.subheader("By year")
        exit_name = st.selectbox(
            "Exit",
            [c[2:] for c in overall.columns if c.startswith("R_")],
            index=0,
            key="ie10_exit",
        )
        names = sorted(overall["strategy"].unique())
        one = st.selectbox("Strategy", names, key="ie10_strategy")
        part = by_year[(by_year["strategy"] == one) & (by_year["trades"] >= 20)]
        table = part.pivot_table(
            index=["entry", "stop_rule"], columns="year", values=f"R_{exit_name}"
        )
        st.dataframe(table.round(2), width="stretch")
        st.caption(
            f"Mean R per year for exit {exit_name} (groups of 20+ trades). A setup that only "
            "works in some years shows it here. Facts, not advice."
        )
        st.stop()
    trades = intraday_cached(str(data_dir))
    if trades.empty:
        st.info(
            "No minute-bar study yet. It needs the minute files from the data repo's "
            "`intraday-minutes` release: `python -m trading_os.intraday_cli --data-dir ... "
            "--run <folder>`."
        )
        st.stop()
    st.caption(
        "Every strategy bought (or shorted) at different times on minute bars, each entry "
        "picked only with what was known at that minute, then run with every exit. R is per "
        "unit of the starting risk (capped at 20 per trade in the means). Stops: lod = the low "
        "so far (high for shorts), adr = 1 ADR, order = the setup's own stop, signal = the "
        "signal day's low/high. Facts, not advice."
    )
    names = sorted(trades["strategy"].unique())
    picked = st.multiselect("Strategies", names, default=names, key="ie_strategies")
    view = trades[trades["strategy"].isin(picked)].copy()
    view["year"] = view["session_date"].map(lambda d: d.year)
    view["price_bucket"] = pd.cut(
        view["prev_close"], [0, 5, 10, 50, 1e9], labels=["<5", "5-10", "10-50", "50+"]
    )
    splits = ["none", "year", "price_bucket"]
    splits += [c for c in ("above_vwap", "b_count", "touched", "contractions") if c in view]
    group = st.selectbox("Split by", splits, key="ie_split")
    min_trades = st.slider("Minimum trades", 10, 500, 50, step=10)
    table = intraday_study.summary(view, None if group == "none" else [group])
    st.subheader("Best entry, stop and exit per strategy")
    st.dataframe(intraday_study.best(table, min_trades).round(2), hide_index=True, width="stretch")
    exits_all = [c[2:] for c in intraday_study.exit_columns(view)]
    default = [
        e for e in ("hold_1d", "hold_5d", "hold_21d", "trail_ema9", "q3_ma20") if e in exits_all
    ]
    shown = st.multiselect("Exits in the table", exits_all, default=default, key="ie_exits")
    columns = ["strategy", "entry", "stop_rule", *([] if group == "none" else [group])]
    columns += ["trades", "stopped_same_day%"]
    for e in shown:
        columns += [f"win_{e}%", f"R_{e}"]
    table = table[table["trades"] >= min_trades]
    st.subheader("Every entry and stop")
    st.dataframe(
        table[[c for c in columns if c in table]].round(2), hide_index=True, width="stretch"
    )
    one = st.selectbox("Trades of", picked or names, key="ie_one")
    rows = view[view["strategy"] == one].sort_values("session_date", ascending=False)
    keep = ["session_date", "ticker", "entry", "stop_rule", "side", "price", "stop", "risk_adr"]
    keep += ["r_0d", "r_hold_5d", "r_hold_21d", "r_trail_ema9", "pnl_hold_5d", "pnl_hold_21d"]
    st.dataframe(rows[[c for c in keep if c in rows]].head(2000), hide_index=True, width="stretch")

elif page == "Validation":
    st.header("Validation against TradingView")
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

st.sidebar.caption(
    f"{len(runs)} runs · {dt.date.today().isoformat()} · session "
    f"{clock.session_date(CFG.schedule, 'eod', dt.datetime.now(dt.UTC))}"
)
