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
    ep_history,
    journal,
    outcomes,
    report,
    stats,
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
    "EP history",
    "Validation",
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
def ticker_bars(folder: str, ticker: str) -> pd.DataFrame:
    """One stock's daily bars from the Massive files (for the EP history charts)."""
    import pyarrow.dataset as ds

    table = ds.dataset(Path(folder) / "data" / "bars", format="parquet").to_table(
        filter=ds.field("ticker") == ticker
    )
    bars = table.to_pandas()
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    return bars.drop_duplicates("session_date").sort_values("session_date")


def candidates_of(run: dashboard.Run) -> pd.DataFrame:
    return read_parquet(str(run.candidates))


FORMATS = {"money": "compact", "shares": "compact", "int": "%d"}


def show_table(scan: str, hits: pd.DataFrame) -> None:
    """The same columns and number formats as the Markdown report."""
    columns = [("Rank", "rank", "int"), ("Ticker", "ticker", "text"), ("Tier", "tier", "text")]
    columns += report.COLUMNS.get(scan, [])
    view = hits.copy()
    if scan.startswith("breakout_"):
        view["b_flags"] = [report._b_flags(r) for r in view.to_dict("records")]
    present = [(h, c, f) for h, c, f in columns if c in view.columns]
    config = {}
    for header, _, fmt in present:
        if fmt == "flag":
            config[header] = st.column_config.CheckboxColumn(header)
        elif fmt != "text":
            config[header] = st.column_config.NumberColumn(
                header, format=FORMATS.get(fmt, f"%{fmt}")
            )
    view = view[[c for _, c, _ in present]].rename(columns={c: h for h, c, _ in present})
    st.dataframe(view, hide_index=True, width="stretch", column_config=config)


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
            show_table(scan, shown)
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
    show_table(scan, hits)
    if len(hits):
        ticker = st.selectbox("Look at", hits["ticker"].tolist())
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
    state = dashboard.watchlist_state(data_dir)
    if state.empty:
        st.info("Watchlists are empty until EP or breakout alerts come in.")
        st.stop()
    show_all = st.toggle("Include triggered / expired")
    for name in ("bo_watch", "ep_watch"):
        rows = state[state["list"] == name]
        if not show_all:
            rows = rows[rows["status"] == "active"]
        st.subheader(f"{'BO-Watch' if name == 'bo_watch' else 'EP-Watch'} ({len(rows)})")
        st.dataframe(
            rows[["ticker", "status", "added_date", "status_date", "reason"]],
            hide_index=True,
            width="stretch",
        )

elif page == "Journal":
    st.header("Journal")
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
    trades = dashboard.latest_journal(data_dir)
    if trades.empty:
        st.info("No trades yet. Import a fills export above.")
        st.stop()
    notes = dashboard.notes_state(data_dir)
    graded = notes[notes["kind"] == "trade"].set_index("ref_id")["grade"].to_dict()
    trades = trades.assign(grade=trades["trade_id"].map(graded).fillna(""))
    with_r = trades["r_multiple"].dropna()
    a, b, c, d = st.columns(4)
    a.metric("Closed trades", len(trades))
    b.metric("Win rate", f"{(trades['pnl'] > 0).mean() * 100:.0f}%")
    c.metric("Avg R", f"{with_r.mean():.2f}" if len(with_r) else "n/a")
    d.metric("Total P&L", f"{trades['pnl'].sum():,.0f}")
    if len(with_r):
        curve = trades.dropna(subset=["r_multiple"]).sort_values("exit_date")
        st.line_chart(curve.set_index("exit_date")["r_multiple"].cumsum(), height=200)
    cols = [
        "ticker",
        "direction",
        "entry_date",
        "exit_date",
        "entry_avg",
        "exit_avg",
        "quantity",
        "pnl",
        "r_multiple",
        "signal_scan",
        "grade",
    ]
    st.dataframe(trades[[c for c in cols if c in trades]], hide_index=True, width="stretch")
    pick = st.selectbox(
        "Journal a trade",
        trades.to_dict("records"),
        format_func=lambda t: (
            f"{t['ticker']} {t['entry_date']} → {t['exit_date']} ({t['pnl']:,.0f})"
        ),
    )
    grade_form("trade", pick["trade_id"], f"{pick['ticker']} trade", f"tr-{pick['trade_id']}")

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

elif page == "EP history":
    st.header("EP history")
    built = sorted((data_dir / "data" / "ep_history").glob("ep_history_*.parquet"))
    if not built:
        st.info("No EP history yet. Build it with `scripts/ep_history.py` after the backfill.")
        st.stop()
    hist = read_parquet(str(built[-1]))
    hist["session_date"] = pd.to_datetime(hist["session_date"]).dt.date
    st.caption(
        f"Bars up to {built[-1].stem[len('ep_history_') :]} · {len(hist):,} events. Facts only: "
        "the criteria are yes/no and the grade is yours. Entry at the gap-day close, stop at the "
        "low of day within the live ADR bounds. Earnings and growth are inferred from the "
        "quarterly rhythm and exist only for stocks still listed; float is today's."
    )
    a, b, c = st.columns(3)
    variants = a.multiselect("Variant", ["ep_day", "ep9m"], default=["ep_day"])
    tiers = b.multiselect("Tier", ["alert", "log"], default=["alert"])
    years = sorted({d.year for d in hist["session_date"]})
    chosen_years = c.multiselect("Year", years, default=years)
    a, b, c = st.columns(3)
    gap_min = a.slider("Gap at least %", 0, 60, 10)
    rvol_min = b.slider("RVOL at least", 0.0, 20.0, 3.0, 0.5)
    months_min = c.slider("Months sideways at least", 0.0, 12.0, 0.0, 0.5)
    a, b, c = st.columns(3)
    earnings = a.selectbox("Earnings (inferred)", ["any", "yes", "no", "unknown"])
    must = b.multiselect(
        "Criteria that must pass", ["c1_gap", "c2_volume", "c3_growth", "c4_neglect", "c5_stop"]
    )
    states = c.multiselect("Breadth state that day", ["strong", "neutral", "weak"])

    keep = (hist["is_ep_day"] & ("ep_day" in variants)) | (hist["is_ep9m"] & ("ep9m" in variants))
    keep &= hist["tier"].isin(tiers) & hist["session_date"].map(lambda d: d.year).isin(chosen_years)
    keep &= (hist["gap_pct"] >= gap_min) & (hist["rvol50"] >= rvol_min)
    keep &= hist["months_sideways"] >= months_min
    known = hist["earnings_inferred"] if "earnings_inferred" in hist else pd.Series(None)
    if earnings == "yes":
        keep &= known.eq(True)
    elif earnings == "no":
        keep &= known.eq(False)
    elif earnings == "unknown":
        keep &= known.isna()
    for flag in must:
        keep &= hist[flag].fillna(False).astype(bool)
    if states:
        keep &= hist["mkt_breadth_state"].isin(states)
    view = hist[keep].copy()
    flags = ["c1_gap", "c2_volume", "c3_growth", "c4_neglect", "c5_stop"]
    view["criteria_met"] = view[flags].fillna(False).astype(bool).sum(axis=1)
    view["gap_bucket"] = pd.cut(
        view["gap_pct"], [0, 15, 25, 50, 1e9], labels=["<15", "15-25", "25-50", "50+"]
    )
    view["rvol_bucket"] = pd.cut(
        view["rvol50"], [0, 5, 10, 20, 1e9], labels=["<5", "5-10", "10-20", "20+"]
    )
    view["year"] = view["session_date"].map(lambda d: d.year)
    st.subheader(f"{len(view):,} events")
    group = st.selectbox(
        "Group by",
        [
            "none",
            "earnings_inferred",
            "criteria_met",
            "mkt_breadth_state",
            "mkt_qqq_trend",
            "gap_bucket",
            "rvol_bucket",
            "c4_neglect",
            "above_ma200",
            "year",
        ],
    )
    table = ep_history.summary(view, None if group == "none" else group)
    st.dataframe(
        table.pivot_table(
            index="group",
            columns="horizon_d",
            values=["n", "win_rate_pct", "median_ret_pct", "mean_r"],
            observed=True,
        ).round(2),
        width="stretch",
    )
    trail = (
        view.groupby(group if group != "none" else lambda _: "all", observed=True)[
            ["r_trail_ma10", "r_trail_ma20", "days_trail_ma10", "days_trail_ma20"]
        ]
        .mean()
        .round(2)
    )
    st.caption("Trailing exit at the first close under the 10-day / 20-day MA (mean R, mean days)")
    st.dataframe(trail, width="stretch")
    columns = [
        "session_date",
        "ticker",
        "variant",
        "gap_pct",
        "rvol50",
        "months_sideways",
        "eps_growth_yoy",
        "sales_growth_yoy",
        "earnings_inferred",
        "criteria_met",
        "ret_5d",
        "ret_21d",
        "ret_63d",
        "r_21d",
        "r_trail_ma10",
    ]
    shown = view[[col for col in columns if col in view]].sort_values(
        "session_date", ascending=False
    )
    st.dataframe(shown, hide_index=True, width="stretch", height=320)
    labels = [f"{r.session_date} · {r.ticker}" for r in shown.head(500).itertuples()]
    pick = st.selectbox("Chart", ["—", *labels])
    if pick != "—":
        day_text, ticker = pick.split(" · ")
        event = view[(view["ticker"] == ticker) & (view["session_date"].astype(str) == day_text)]
        row = event.iloc[0]
        bars = ticker_bars(str(data_dir), ticker)
        path = Path(CHART_CACHE) / f"ep_{ticker}_{day_text}.png"
        drawn = charts.before_shot(
            bars,
            path,
            title=f"{ticker} · EP {day_text} · then 63 sessions",
            signal_session=row["session_date"],
            sessions=120,
            order_stop=row["plan_stop"],
            after=63,
        )
        if drawn:
            st.image(str(drawn))

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
