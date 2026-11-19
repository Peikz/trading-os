"""UX round 4 (19 Nov 2026): the last Streamlit pages' features, so the React dashboard can stand
alone. Everything here reads what Streamlit reads, through the same `trading_os` functions:

* search by words and a ticker's detail (`search`, `my_watchlists`, `alerts`, the notes),
* "All scans" (every pushed scan's table with the grade blocks, the facts and the saved charts),
* a horizontal line at a price (`chart_marks.add_level`, the one write route, same validation),
* the data folder for the settings popover, and whether a ticker exists (`known_checker`).

Nothing here computes a number, changes a rule or places an order.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.pages import Context
from api.serialize import records, scalar
from trading_os import (
    alerts,
    board_data,
    chart_marks,
    daily_notes,
    dashboard,
    ibd,
    my_watchlists,
    notify,
    report,
    search,
    stock_notes,
)

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "GUIDE.md"
RECENT_RUNS = 30  # the scan-hit history a ticker search shows (Streamlit: the last 30 runs)
SAFE = re.compile(r"^[A-Za-z0-9_]{1,60}$")


class LevelIn(BaseModel):
    price: float
    start: str | None = None  # the first and last day of the span; default: the last year of bars
    end: str | None = None
    label: str = ""


def _col_fmt(fmt: str) -> str:
    """The report's number formats as the names the browser knows."""
    return {
        "int": "int", "text": "text", "link": "link", "flag": "flag", "money": "money",
        "shares": "shares", ".1f": "num1", ".2f": "num2", ".0f": "num0", "+.0f": "signed0",
        "+.1f": "signed1", "+.2f": "signed2",
    }.get(fmt, "text")  # fmt: skip


def table_columns(scan: str) -> list[tuple[str, str, str]]:
    """The columns of a scan's table, as Streamlit's `show_table` lists them: rank, ticker, the
    study grade, why, predicted R, short interest, IBD tag, volume build, the chart link, the
    tier, then the scan's own columns (`report.COLUMNS`)."""
    columns = [("Rank", "rank", "int"), ("Ticker", "ticker", "text")]
    columns += [("Study grade", "grade", "text"), ("Why", "grade_why", "text")]
    columns += [("Pred. R", "grade_score", "+.2f"), ("Short", "si_tag", "text")]
    columns += [("IBD", "ibd_tag", "text"), ("Vol build", "vol_build", ".1f")]
    columns += [("Chart", "tradingview", "link"), ("Tier", "tier", "text")]
    columns += report.COLUMNS.get(scan, [])
    return columns


def scan_table(
    scan: str, hits: pd.DataFrame, exchanges: dict[str, str] | None
) -> tuple[list[dict[str, str]], pd.DataFrame]:
    """One scan's table: the columns that exist in the hits and the rows, best first, with the
    TradingView link and (for a breakout scan) the five flags as text. The same selection and
    order as `show_table` in the Streamlit app."""
    columns = table_columns(scan)
    wanted = {c for _, c, _ in columns} | {"grade", "grade_score", "rank", "ticker"}
    wanted |= {f"b{i}" for i in range(1, 6)} | {"ibd_state", "ibd_dist"}
    hits = ibd.relabel(hits[[c for c in hits.columns if c in wanted]])
    view = notify.best_first(hits).copy()
    view["tradingview"] = [
        board_data.tradingview_url(t, (exchanges or {}).get(t)) for t in view["ticker"]
    ]
    if scan.startswith("breakout_"):
        flags = [c for c in (f"b{i}" for i in range(1, 6)) if c in view]
        view["b_flags"] = [report._b_flags(r) for r in view[flags].to_dict("records")]
    present = [(h, c, f) for h, c, f in columns if c in view.columns]
    cols = [{"header": h, "key": c, "fmt": _col_fmt(f)} for h, c, f in present]
    return cols, view[[c for _, c, _ in present]]


def grade_blocks(hits: pd.DataFrame) -> list[dict[str, Any]]:
    """The A+, A and B hits as their push shows them: the study grade, when to buy, the exit, the
    history behind the grade, why, and the plan (the C hits are saved, not shown)."""
    if "grade" not in hits:
        return []
    keep = hits["grade"].isin(["A+++", "A++", "A+", "A", "B"])
    if not keep.any():
        return []
    graded = hits[keep]
    graded = graded.assign(_order=graded["grade"].map(notify.GRADE_RANK)).sort_values("_order")
    out = []
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
        out.append({"ticker": str(row["ticker"]), "title": lines[0], "lines": body})
    return out


def register(app: FastAPI, ctx: Context, find_run, run_id, guide: Path = GUIDE) -> None:
    def read(path: str) -> pd.DataFrame:
        return ctx.table(Path(path))

    # --- settings

    @app.get("/api/settings")
    def settings() -> dict:
        """What the settings popover shows and cannot change: the data folder (the server's)."""
        return {"data_folder": str(ctx.root())}

    @app.get("/api/known/{ticker}")
    def known(ticker: str) -> dict:
        """Whether the ticker exists: in the newest universe, else in the daily bars."""
        t = ticker.strip().lstrip("$").upper()
        if not search.looks_like_ticker(t):
            return {"ticker": t, "known": False}
        check = my_watchlists.known_checker(ctx.runs(), ctx.root(), read)
        return {"ticker": t, "known": bool(check(t))}

    # --- search

    @app.get("/api/search/ticker/{ticker}")
    def search_ticker(ticker: str) -> dict:
        """A ticker everywhere: its scan hits in the last runs, the lists, position and alerts it
        is on, and its notes (Streamlit's search page)."""
        t = ticker.strip().lstrip("$").upper()
        if not search.looks_like_ticker(t):
            raise HTTPException(400, "Not a ticker.")
        root = ctx.root()
        recent = [r for r in ctx.runs() if r.kind == "scheduled"][:RECENT_RUNS]
        found = search.scan_hits(
            ((r.label, ctx.scan_frames(str(r.candidates))) for r in recent), t, notify.SCAN_LABELS
        )
        places: list[str] = []
        mine = my_watchlists.current(my_watchlists.load(root))
        places += [f"your list {n}" for n in mine.loc[mine["ticker"] == t, "list"]]
        scan_lists = dashboard.watchlist_state(root)
        if len(scan_lists):
            on = scan_lists[(scan_lists["ticker"] == t) & (scan_lists["status"] == "active")]
            places += [
                {"bo_watch": "BO-Watch", "ep_watch": "EP-Watch"}.get(x, x) for x in on["list"]
            ]
        positions = dashboard.latest_positions(root)
        if len(positions) and t in set(positions["ticker"]):
            places.append("an open position")
        own = alerts.current(root)
        places += [
            f"price alert {r['direction']} {r['level']:.2f}"
            for r in own[own["ticker"] == t].to_dict("records")
        ]
        notes = stock_notes.current(root, t)
        tagged = daily_notes.current(root, t)
        return {
            "ticker": t,
            "runs_searched": len(recent),
            "hits": records(found),
            "places": places,
            "notes": [
                {"date": scalar(n["note_date"]), "kind": "stock note", "text": n["text"]}
                for n in notes.to_dict("records")
            ]
            + [
                {"date": scalar(n["note_date"]), "kind": "daily note", "text": n["text"]}
                for n in tagged.to_dict("records")
            ],
        }

    @app.get("/api/search/words")
    def search_words(q: str = Query("", max_length=200)) -> dict:
        """Words in your stock notes, daily notes, journal notes and the guide's lines."""
        root = ctx.root()
        text = q.strip()
        if not text:
            return {"q": "", "stock": [], "daily": [], "journal": [], "guide": []}
        stock = search.text_hits(stock_notes.current(root), ["text", "ticker"], text)
        days = search.text_hits(daily_notes.current(root), ["text", "tags"], text)
        journal = search.text_hits(dashboard.notes_state(root), ["notes", "tags"], text)
        lines = search.guide_hits(guide.read_text(encoding="utf-8"), text) if guide.exists() else []
        return {
            "q": text,
            "stock": [
                {"ticker": n["ticker"], "date": scalar(n["note_date"]), "text": n["text"]}
                for n in stock.to_dict("records")
            ],
            "daily": [
                {"date": scalar(n["note_date"]), "text": n["text"]} for n in days.to_dict("records")
            ],
            "journal": [
                {"kind": scalar(n["kind"]), "ref_id": scalar(n["ref_id"]), "text": n["notes"]}
                for n in journal.to_dict("records")
            ],
            "guide": [{"section": s, "line": line[:240]} for s, line in lines],
        }

    # --- All scans: every pushed scan's table, one run

    @app.get("/api/scan-tables")
    def scan_tables(run: str = Query(...), scan: str | None = Query(None)) -> dict:
        """Every pushed scan's table of one run, the scan with the best grade first: its hits in
        the report's columns, the A+/A/B blocks as the push shows them, the facts behind the
        names, and which stocks have a saved chart image. With `scan`: that one scan only, pushed
        or not, every tier (the Screener's scan hits page)."""
        r = find_run(run)
        only = scan if scan and SAFE.match(scan) else None
        eod = next((x for x in ctx.runs() if x.slot == "eod" and x.universe.exists()), None)
        listing = ctx.exchanges(str(r.universe)) or (
            ctx.exchanges(str(eod.universe)) if eod else {}
        )
        tables = []
        for scan, hits in ctx.scan_frames(str(r.candidates)).items():
            setting = ctx.cfg().scans.get(scan)
            if only is not None:
                if scan != only:
                    continue
            elif setting is None or setting.action != "push":
                continue
            alert_only = only is None and "push_tier" in setting.params
            shown = hits[hits["tier"] == "alert"] if alert_only and "tier" in hits else hits
            ranks = shown["grade"].map(notify.GRADE_RANK) if "grade" in shown else None
            best = ranks.min() if ranks is not None and ranks.notna().any() else 9
            tables.append((best, scan, hits, shown))
        out = []
        for _, scan, hits, shown in sorted(tables, key=lambda x: x[0]):
            cols, view = scan_table(scan, shown, listing)
            charts = [
                t
                for t in shown["ticker"].head(10)
                if dashboard.chart_for(r, scan, str(t)) is not None
            ]
            out.append(
                {
                    "scan": scan,
                    "label": notify.SCAN_LABELS.get(scan, scan),
                    "shown": len(shown),
                    "total": len(hits),
                    "columns": cols,
                    "rows": records(view),
                    "blocks": grade_blocks(shown),
                    "facts": report.fact_lines(scan, shown),
                    "charts": [str(t) for t in charts],
                }
            )
        return {"run": run_id(r), "label": r.label, "scans": out}

    @app.get("/api/run-chart/{rid}/{scan}/{ticker}")
    def run_chart(rid: str, scan: str, ticker: str):
        """A scan's saved chart image of one stock in one run (the push's picture)."""
        if not SAFE.match(scan) or not re.match(r"^[A-Za-z0-9.\-/]{1,12}$", ticker):
            raise HTTPException(400, "Bad name.")
        path = dashboard.chart_for(find_run(rid), scan, ticker)
        if path is None:
            raise HTTPException(404, "No chart image for this stock in this run.")
        return FileResponse(path, media_type="image/png")

    # --- a horizontal line at a price

    @app.post("/api/chart/{ticker}/levels")
    def add_level(ticker: str, body: LevelIn) -> dict:
        """Save a horizontal line at a price (a flat trend line extended to today), the same
        validation as Streamlit's "＋ Horizontal line"."""
        t = my_watchlists.parse_tickers(ticker)
        if not t:
            raise HTTPException(400, "Not a ticker.")
        start, end = body.start, body.end
        if not (start and end):
            bars = board_data.daily_bars(ctx.root(), t[0])
            if len(bars) < 2:
                raise HTTPException(400, "No daily bars for this stock to place a line on.")
            days = list(bars.sort_values("session_date")["session_date"])[-252:]
            start, end = days[0], days[-1]
        try:
            mark_id = chart_marks.add_level(ctx.root(), t[0], body.price, start, end, body.label)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"mark_id": mark_id}

    @app.get("/api/chart/{ticker}/saved")
    def saved_marks(ticker: str) -> list[dict]:
        """The saved lines, levels and anchors of a stock, each described in one line."""
        t = my_watchlists.parse_tickers(ticker)
        if not t:
            raise HTTPException(400, "Not a ticker.")
        marks = chart_marks.current(ctx.root(), t[0])
        return [
            {"mark_id": str(m["mark_id"]), "kind": m["kind"], "text": chart_marks.describe(m)}
            for m in marks.to_dict("records")
        ]
