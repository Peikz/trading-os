"""The Practice page (`trading_os.practice`): a past signal as the chart up to the entry and the
facts known then, four answers (Skip, 1, 2, 3), then the whole trade and your numbers.

Every number comes from `trading_os.practice`; nothing is computed here but the chart's
shape. Writes are the two Streamlit already makes, through the same functions and the same
files: an answer (`practice.save_answer`, one append-only file under `data/practice/answers/`)
and a note edit (`practice.save_note`). The bars after the entry session are never sent for an
unanswered signal. With "show stock and date" off the chart carries relative days ("day -3")
and prices with the entry at 100; on, the real dates and dollars rebuilt from the entry date,
the NYSE calendar and the entry price. Nothing here places an order.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from api.pages import Context
from api.serialize import records, scalar
from trading_os import chart_series, practice

POOL_LABELS = {"practice": "Practice 2016-21", "exam": "Exam 2022-26"}
LINES = ["MA10", "MA20", "MA50", "EMA9", "EMA21"]  # MA200 needs more than the 130 bars
NAMES = {"MA10": "MA 10", "MA20": "MA 20", "MA50": "MA 50", "EMA9": "EMA 9", "EMA21": "EMA 21"}
DEFAULT_LINES = "MA10,MA20,MA50"
VISIBLE_BEFORE = 90  # bars before the entry in view when the chart opens
VISIBLE_AFTER_REVEAL = 60
ENTRY_COLOUR, STOP_COLOUR, EXIT_COLOUR = "#2f81f7", "#ef5350", "#d1d4dc"
BLIND_BASE = "2000-01-03"  # the hidden chart's made-up dates: only the order of the bars shows


class AnswerIn(BaseModel):
    signal_id: str
    pool: Literal["practice", "exam"]
    choice: str
    note: str = ""
    shown: bool = False


class NoteIn(BaseModel):
    signal_id: str
    note: str


def day_label(rel: int) -> str:
    return "day 0" if rel == 0 else f"day {rel:+d}"


def chart_payload(
    row: pd.Series, bars: pd.DataFrame, *, answered: bool, shown: bool, lines: list[str]
) -> dict[str, Any]:
    """The signal's chart as the Chart page's payload (`DrawChart`): candles, lines, the entry
    and stop levels and the entry / exit markers. `labels` names the bars when the real dates
    are hidden."""
    b = practice.visible_bars(bars, answered)
    rels = b["rel_day"].astype(int).tolist()
    if shown:
        try:
            dates = practice.session_dates(row["entry_date"], rels)
            times = [d.strftime("%Y-%m-%d") for d in dates]
        except ValueError as exc:
            raise HTTPException(500, f"No dates for this signal: {exc}") from exc
        labels = None

        def to_price(v):
            return practice.real_price(v, row["price"])
    else:
        times = [str(d) for d in np.busday_offset(BLIND_BASE, [r + 400 for r in rels])]
        labels = {t: day_label(r) for t, r in zip(times, rels, strict=True)}

        def to_price(v):
            return v

    frame = pd.DataFrame({"time": times, "session_date": times})
    for col in ("open", "high", "low", "close"):
        frame[col] = to_price(b[col].astype(float)).to_numpy()
    frame["volume"] = b["volume"].fillna(0).astype(float).to_numpy()
    candles = [
        {"time": t, "open": float(o), "high": float(h), "low": float(lo), "close": float(c),
         "volume": float(v)}
        for t, o, h, lo, c, v in zip(frame["time"], frame["open"], frame["high"], frame["low"],
                                     frame["close"], frame["volume"], strict=True)
    ]  # fmt: skip
    picked = [NAMES[x] for x in lines if x in NAMES]
    at = dict(zip(rels, times, strict=True))
    markers = []
    if 0 in at:
        markers.append({"time": at[0], "position": "belowBar", "shape": "arrowUp",
                        "color": "#3fb950", "text": "entry"})  # fmt: skip
    hold = int(row["hold_days"])
    if answered and hold > 0 and hold in at:
        markers.append({"time": at[hold], "position": "aboveBar", "shape": "arrowDown",
                        "color": EXIT_COLOUR, "text": "exit"})  # fmt: skip
    levels = [
        {"name": "entry", "price": float(to_price(100.0)), "colour": ENTRY_COLOUR},
        {"name": "stop", "price": float(to_price(100.0 - float(row["stop_pct"]))),
         "colour": STOP_COLOUR},
    ]  # fmt: skip
    first = VISIBLE_AFTER_REVEAL if answered else VISIBLE_BEFORE
    start = next((t for r, t in zip(rels, times, strict=True) if r >= -first), times[0])
    return {
        "ticker": "",
        "period": "practice",
        "timeframe": "Daily",
        "candles": candles,
        "lines": chart_series.indicator_lines(frame, picked),
        "avwaps": [],
        "trend": [],
        "markers": markers,
        "levels": levels,
        "visible": {"from": start, "to": times[-1]},
        "labels": labels,
        "quick_anchors": {},
        "marks": [],
        "dates": [],
        "tradingview": "",
        "note": "",
    }


def register(app: FastAPI, ctx: Context) -> None:
    def signals() -> pd.DataFrame:
        if not practice.available(ctx.root()):
            raise HTTPException(404, "No practice data yet: it is exported to the data repo.")
        return ctx.table(practice.folder(ctx.root()) / "signals.parquet")

    def row_of(sid: str) -> pd.Series:
        found = signals()
        found = found[found["signal_id"] == sid]
        if found.empty:
            raise HTTPException(404, "No such signal.")
        return found.iloc[0]

    def result_of(row: pd.Series, answers: pd.DataFrame) -> dict | None:
        mine = answers[answers["signal_id"] == row["signal_id"]]
        if mine.empty:
            return None
        mine = mine.iloc[0]
        net_r = float(row["net_r"])
        notes = practice.current_notes(ctx.root(), answers)
        return {
            "choice": str(mine["choice"]),
            "pool": str(mine["pool"]),
            "net_r": net_r,
            "pick_r": net_r * practice.MULTIPLIER[str(mine["choice"])],
            "hold_days": int(row["hold_days"]),
            "entry_date": scalar(pd.Timestamp(row["entry_date"]).date()),
            "ticker": str(row["ticker"]),
            "setup": str(row["setup_name"]),
            "answered_at": scalar(mine["answered_at"]),
            "shown": bool(mine["shown"]),
            "note": notes.get(str(row["signal_id"]), ""),
        }

    @app.get("/api/practice")
    def practice_state() -> dict:
        """Whether the export is there, the pools and each pool's numbers."""
        if not practice.available(ctx.root()):
            return {"available": False, "pools": [], "stats": {}, "lines": LINES}
        sig, answers = signals(), practice.load_answers(ctx.root())
        return {
            "available": True,
            "pools": [{"id": p, "label": POOL_LABELS[p]} for p in practice.POOLS],
            "choices": list(practice.CHOICES),
            "multiplier": practice.MULTIPLIER,
            "stats": {p: scalar(practice.stats(sig, answers, p)) for p in practice.POOLS},
            "lines": LINES,
        }

    @app.get("/api/practice/next")
    def practice_next(pool: Literal["practice", "exam"] = "practice") -> dict:
        """A random signal of the pool you have not answered, or none when it is used up."""
        sid = practice.next_signal(signals(), practice.load_answers(ctx.root()), pool)
        return {"signal_id": sid}

    @app.get("/api/practice/signal/{sid}")
    def practice_signal(sid: str, shown: bool = False, lines: str = DEFAULT_LINES) -> dict:
        """The card and chart of one signal. Before the answer only the sessions before the
        entry are sent; the ticker and date only when 'shown' is on or the signal is answered."""
        row = row_of(sid)
        answers = practice.load_answers(ctx.root())
        result = result_of(row, answers)
        answered = result is not None
        bars = practice.load_bars(ctx.root(), sid)
        chart = chart_payload(
            row, bars, answered=answered, shown=shown, lines=[x for x in lines.split(",") if x]
        )
        reveal = shown or answered
        if reveal:
            chart["ticker"] = str(row["ticker"])
        return {
            "signal_id": sid,
            "pool": str(row["pool"]),
            "answered": answered,
            "shown": shown,
            "ticker": str(row["ticker"]) if reveal else None,
            "facts": [{"label": k, "value": v} for k, v in practice.card_facts(row)],
            "chart": chart,
            "result": result,
        }

    @app.post("/api/practice/answer")
    def practice_answer(a: AnswerIn) -> dict:
        """Save the answer (once per signal and pool: a double click keeps the first) and
        return the result."""
        sig = signals()
        try:
            practice.save_answer(ctx.root(), sig, a.signal_id, a.pool, a.choice, a.note, a.shown)
        except practice.AlreadyAnswered:
            pass  # the first answer stands
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"result": result_of(row_of(a.signal_id), practice.load_answers(ctx.root()))}

    @app.put("/api/practice/note")
    def practice_note(n: NoteIn) -> dict:
        row_of(n.signal_id)
        try:
            practice.save_note(ctx.root(), n.signal_id, n.note)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"saved": True}

    @app.get("/api/practice/answers")
    def practice_answers() -> list[dict]:
        """Your answered signals with their notes, newest first."""
        sig, answers = signals(), practice.load_answers(ctx.root())
        if answers.empty:
            return []
        notes = practice.current_notes(ctx.root(), answers)
        cols = ["signal_id", "ticker", "setup_name", "net_r", "entry_date", "hold_days"]
        joined = answers.merge(sig[cols], on="signal_id", how="inner")
        joined = joined.sort_values("answered_at", ascending=False).reset_index(drop=True)
        joined["note"] = joined["signal_id"].map(notes).fillna("")
        joined["entry_date"] = pd.to_datetime(joined["entry_date"]).dt.strftime("%Y-%m-%d")
        return records(joined.drop(columns=["answered_at"]).assign(
            answered=joined["answered_at"].dt.strftime("%Y-%m-%d")
        ))  # fmt: skip
