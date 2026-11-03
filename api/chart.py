"""Phase 2b routes: the Chart page (`trading_os.chart_view`): any stock's daily or weekly bars
with MA/EMA lines, the scans' past hits, your fills, pivot / stops / plan entry, anchored VWAPs,
your trend lines (draw, move, delete, or type one in), the stock's notes, and minute bars (the
minute study's days, or Alpaca's live feed when its keys are set on the server).

Writes go through the package: drawings to `data/chart_marks/` (`chart_marks`), notes to
`data/journal/stock_notes/` (`stock_notes`); both are append-only event logs.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from api.pages import Context, _frame
from api.serialize import scalar
from trading_os import board_data, chart_marks, chart_view, daily_notes, my_watchlists, stock_notes

CHART_NOTE = (
    "Drag to pan, scroll or pinch to zoom. On the daily bars the ✏️ line tool draws a trend line "
    "with two clicks; it is saved at once, for this stock. ✋ drags a line's ends to move it; "
    "🧽 deletes the line you click. A line drawn past the last bar keeps extending each day. "
    "Triangles: amber = a scan's hit, green/red = your buys/sells."
)


class LineIn(BaseModel):
    x0: dt.date
    y0: float
    x1: dt.date
    y1: float
    label: str = ""
    extend: bool = True


class AnchorIn(BaseModel):
    day: dt.date
    label: str = ""


class NoteIn(BaseModel):
    text: str
    day: dt.date | None = None


def _ticker(raw: str) -> str:
    t = my_watchlists.parse_tickers(raw)
    if not t:
        raise HTTPException(400, "Not a ticker.")
    return t[0]


def register(app: FastAPI, ctx: Context) -> None:
    def read(path: str) -> pd.DataFrame:
        return ctx.table(Path(path))

    @app.get("/api/chart/picks")
    def chart_picks() -> list[dict]:
        """Today's alert-tier hits (pushed first), your watchlists and open positions."""
        where = chart_view.picks(ctx.root(), ctx.runs(), read)
        return [{"ticker": t, "where": w} for t, w in where.items()]

    @app.get("/api/chart/{ticker}")
    def chart(
        ticker: str,
        period: str = Query("2y", pattern="^(2y|10y)$"),
        timeframe: str = Query("Daily", pattern="^(Daily|Weekly)$"),
        span: str = Query("1Y", pattern="^(3M|6M|1Y|2Y|All)$"),
        lines: str = "MA10,MA20,MA50",
        hits: bool = True,
        fills: bool = True,
        levels: bool = True,
        anchors: str = "",
    ) -> dict:
        """One stock's chart (`chart_view.payload`), the anchors to choose from, the notes."""
        t = _ticker(ticker)
        daily = chart_view.bars(ctx.root(), t, period)
        marks = chart_marks.current(ctx.root(), t)
        past = chart_view.hits_for(chart_view.all_hits(ctx.root(), period), t)
        choices = chart_view.anchors_for(daily, past, marks)
        picked = {k: v for k, v in choices["quick"].items() if k in anchors.split(",")}
        line_marks = marks[marks["kind"] == "line"].to_dict("records") if len(marks) else []
        body = chart_view.payload(
            daily,
            timeframe=timeframe,
            lines=[x for x in lines.split(",") if x],
            sessions=chart_view.SPANS[span],
            hits=past if hits else None,
            fills=chart_view.fills_for(ctx.root(), t) if fills else None,
            levels=chart_view.levels_for(ctx.root(), ctx.runs(), ctx.cfg(), t, read)
            if levels
            else None,
            anchors=picked | choices["saved"],
            marks=line_marks,
        )
        eod = next((r for r in ctx.runs() if r.slot == "eod" and r.universe.exists()), None)
        exchange = ctx.exchanges(str(eod.universe)).get(t) if eod else None
        saved = marks.to_dict("records") if len(marks) else []
        # scalar(): saved marks and bars come from parquet (numpy numbers)
        return scalar(
            body
            | {
                "ticker": t,
                "period": period,
                "timeframe": timeframe,
                "quick_anchors": {k: scalar(v) for k, v in choices["quick"].items()},
                "marks": [
                    {
                        k: scalar(m.get(k))
                        for k in (
                            "mark_id",
                            "kind",
                            "label",
                            "x0",
                            "y0",
                            "x1",
                            "y1",
                            "extend",
                            "anchor",
                        )
                    }
                    for m in saved
                ],  # fmt: skip
                "dates": [c["time"] for c in body["candles"]][-504:][::-1],
                "tradingview": board_data.tradingview_url(t, exchange),
                "note": CHART_NOTE,
            }
        )

    @app.post("/api/chart/{ticker}/lines")
    def add_line(ticker: str, line: LineIn) -> dict:
        if line.x0 == line.x1 or not (line.y0 > 0 and line.y1 > 0):
            raise HTTPException(400, "A line needs two different days and prices above 0.")
        mark_id = chart_marks.add_line(
            ctx.root(), _ticker(ticker), line.x0, line.y0, line.x1, line.y1, line.label,
            line.extend,
        )  # fmt: skip
        return {"mark_id": mark_id}

    def mark_of(t: str, mark_id: str) -> dict:
        marks = chart_marks.current(ctx.root(), t)
        found = marks[marks["mark_id"] == mark_id] if len(marks) else marks
        if not len(found):
            raise HTTPException(404, "No such drawing on this stock.")
        return found.iloc[0].to_dict()

    @app.put("/api/chart/{ticker}/lines/{mark_id}")
    def move_line(ticker: str, mark_id: str, line: LineIn) -> dict:
        """Move a line's ends (it keeps its name and extension)."""
        t = _ticker(ticker)
        old = mark_of(t, mark_id)
        if old.get("kind") != "line" or line.x0 == line.x1:
            raise HTTPException(400, "Not a line, or both ends on one day.")
        points = line.model_dump()
        return {"mark_id": chart_marks.move(ctx.root(), t, mark_id, points, old, False)}

    @app.post("/api/chart/{ticker}/anchors")
    def add_anchor(ticker: str, anchor: AnchorIn) -> dict:
        return {"mark_id": chart_marks.add_anchor(ctx.root(), _ticker(ticker), anchor.day,
                                                  anchor.label)}  # fmt: skip

    @app.delete("/api/chart/{ticker}/marks/{mark_id}")
    def remove_mark(ticker: str, mark_id: str) -> dict:
        mark_of(_ticker(ticker), mark_id)
        chart_marks.remove(ctx.root(), mark_id)
        return {"removed": mark_id}

    # --- the stock's notes (all of them, with edit and delete) and tagged daily notes

    @app.get("/api/chart/{ticker}/notes")
    def chart_notes(ticker: str) -> dict:
        t = _ticker(ticker)
        notes = stock_notes.current(ctx.root(), t)
        rows = []
        for n in notes.to_dict("records") if len(notes) else []:
            created, saved = n.get("created_ts"), n.get("saved_ts")
            rows.append(
                {
                    "note_id": n["note_id"],
                    "note_date": scalar(n["note_date"]),
                    "text": n["text"],
                    "written": scalar(pd.Timestamp(created).date())
                    if created is not None
                    else None,
                    "edited": scalar(pd.Timestamp(saved).date())
                    if saved is not None and created is not None and saved != created
                    else None,
                }
            )
        tagged = daily_notes.current(ctx.root(), t)
        days = [
            {
                "note_date": scalar(n["note_date"]),
                "text": n["text"],
                "also": [x for x in n["tag_list"] if x != t],
            }
            for n in (tagged.to_dict("records") if len(tagged) else [])
        ]
        return {"notes": rows, "daily": days}

    @app.post("/api/chart/{ticker}/notes")
    def chart_note_add(ticker: str, body: NoteIn) -> dict:
        if not body.text.strip():
            raise HTTPException(400, "The note is empty.")
        stock_notes.add(ctx.root(), _ticker(ticker), body.text, body.day)
        return chart_notes(ticker)

    def note_known(t: str, note_id: str) -> None:
        notes = stock_notes.current(ctx.root(), t)
        if not len(notes) or note_id not in set(notes["note_id"]):
            raise HTTPException(404, "No such note on this stock.")

    @app.put("/api/chart/{ticker}/notes/{note_id}")
    def chart_note_edit(ticker: str, note_id: str, body: NoteIn) -> dict:
        t = _ticker(ticker)
        note_known(t, note_id)
        if not body.text.strip():
            raise HTTPException(400, "The note is empty.")
        stock_notes.edit(ctx.root(), note_id, t, body.text, body.day or dt.date.today())
        return chart_notes(ticker)

    @app.delete("/api/chart/{ticker}/notes/{note_id}")
    def chart_note_remove(ticker: str, note_id: str) -> dict:
        t = _ticker(ticker)
        note_known(t, note_id)
        stock_notes.remove(ctx.root(), note_id)
        return chart_notes(ticker)

    # --- minute bars

    @app.get("/api/chart/{ticker}/intraday-days")
    def intraday_days(ticker: str) -> dict:
        """The minute study's days for this stock, and the recent sessions for the live feed."""
        t = _ticker(ticker)
        days = chart_view.minute_days(chart_view.minute_index(ctx.root()), t)
        return {
            "study_days": [scalar(d) for d in days],
            "live": chart_view.has_alpaca(),
            "live_sessions": [scalar(d) for d in chart_view.live_sessions(ctx.cfg())],
            "no_keys": chart_view.NO_KEYS,
        }

    @app.get("/api/chart/{ticker}/intraday")
    def intraday(
        ticker: str,
        day: dt.date,
        every: int = Query(1, ge=1, le=15),
        source: str = Query("study", pattern="^(study|live)$"),
    ) -> dict[str, Any]:
        """One day's 1/5/15-minute candles with VWAP from the open, the prior close and (live)
        your levels. Live needs the Alpaca keys on the server."""
        t = _ticker(ticker)
        daily = chart_view.bars(ctx.root(), t, "2y")
        levels = None
        if source == "live":
            if not chart_view.has_alpaca():
                raise HTTPException(400, chart_view.NO_KEYS)
            try:
                minutes = chart_view.live_minutes(t, day)
            except Exception as exc:  # noqa: BLE001 - shown, not raised
                raise HTTPException(502, f"Alpaca didn't answer ({type(exc).__name__}).") from exc
            levels = chart_view.levels_for(ctx.root(), ctx.runs(), ctx.cfg(), t, read)
        else:
            minutes = chart_view.minute_bars(ctx.root(), t, day)
        marks = chart_view.LIVE_MARKS if source == "live" else None
        out = chart_view.intraday_payload(
            minutes, every, chart_view.prior_close(daily, day), levels, marks
        )
        return out | {"ticker": t, "day": day.isoformat(), "every": every, "source": source}

    @app.get("/api/daily-notes")
    def daily_notes_list(ticker: str | None = None) -> list[dict]:
        notes = daily_notes.current(ctx.root(), ticker)
        return _frame(notes, ["note_id", "note_date", "text", "tags"]) if len(notes) else []
