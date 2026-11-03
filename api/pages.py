"""Phase 2a routes: the focus view's ticket and Notes & alerts, the grading form, the Journal,
Positions and Watchlists pages.

Every number comes from the `trading_os` package (`board_data`, `journal_view`,
`positions_view`, `my_watchlists`, ...); nothing is computed here. Writes go through the same
package functions Streamlit calls, so they land in the same data-repo files: plans, fills and
stops (`data/journal/`), grades and screenshots (`data/journal/notes/`, `.../attachments/`),
stock notes, your watchlists (`data/my_watchlists/`) and price alerts (`data/my_alerts/`).
Nothing places an order, nothing pushes, no AI.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.serialize import records, scalar
from trading_os import (
    alerts,
    board_data,
    daily_notes,
    dashboard,
    journal,
    journal_view,
    my_watchlists,
    plans,
    positions_view,
    sizing,
    stock_notes,
    ticket,
)

# The fields the ticket reads from a board row (`ticket`, `board_data.make_ticket`)
TICKET_FIELDS = (
    "ticker", "scan", "grade", "grade_risk_mult", "grade_entry_rule", "plan_entry",
    "grade_entry", "close", "pivot", "plan_stop", "grade_stop", "run_session", "run_slot",
)  # fmt: skip
FX_EVERY_S = 3600  # the account currency's USD rate: one TradingView fetch an hour at most
MAX_SHOT_BYTES = 10 * 1024 * 1024
WATCH_COLUMNS = [
    "ticker", "close", "chg_pct", "rvol50", "adr20_pct", "rs_pct", "pct_from_52w_high",
    "ret_22", "ret_63", "above_ma50", "above_ma200", "to_pivot_pct", "earnings_in_sessions",
    "in_scans", "industry", "note",
]  # fmt: skip


@dataclass
class Context:
    """What the routes share with `api.main`: the data folder, config, runs and caches."""

    root: Callable[[], Path]
    cfg: Callable[[], Any]
    runs: Callable[..., list]
    table: Callable[[Path], pd.DataFrame]
    exchanges: Callable[[str], dict[str, str]]


class TicketRequest(BaseModel):
    row: dict[str, Any]
    kind: str | None = None  # an order type in ticket.ORDER_TYPES; None: the plan's
    price: float | None = None  # your own price; None or 0: the plan's


class Flag(BaseModel):
    ticker: str
    name: str = board_data.FLAGS["🟩"]


class NoteText(BaseModel):
    text: str


class AlertIn(BaseModel):
    ticker: str
    level: float
    direction: Literal["above", "below"] = "above"
    note: str = ""


class Shot(BaseModel):
    name: str
    data: str  # base64


class GradeIn(BaseModel):
    grade: str = ""
    notes: str = ""
    tags: str = ""
    screenshots: list[Shot] = Field(default_factory=list)


class FillIn(BaseModel):
    date: dt.date
    ticker: str
    side: Literal["buy", "sell"]
    shares: float
    price: float
    fees: float = 0.0
    setup: str | None = None
    stop: float | None = None


class CsvIn(BaseModel):
    name: str
    content: str  # the export's text


class DailyIn(BaseModel):
    text: str
    day: dt.date | None = None
    tags: str = ""  # typed stocks, comma or space separated ($TICKER in the text counts too)


class PlanIn(BaseModel):
    session: dt.date
    ticker: str
    direction: Literal["long", "short"] = "long"
    entry: float
    stop: float
    shares: int
    setup: str | None = None
    note: str = ""


class WatchAdd(BaseModel):
    text: str = ""  # typed tickers
    export_text: str = ""  # a TradingView watchlist export's contents
    note: str = ""


class WatchRemove(BaseModel):
    tickers: list[str]


def _frame(frame: pd.DataFrame, columns: list[str], digits: int | None = None) -> list[dict]:
    keep = frame[[c for c in columns if c in frame]]
    return records(keep.round(digits) if digits is not None else keep)


def register(app: FastAPI, ctx: Context) -> None:
    lock = threading.Lock()
    fx: dict[str, tuple[float, float | None]] = {}

    def account() -> tuple[Any, float | None]:
        acct = sizing.load_account(ctx.root())
        currency = acct.currency if acct else "USD"
        now = time.time()
        with lock:
            hit = fx.get(currency)
            if hit is None or now - hit[0] > FX_EVERY_S:
                rate = board_data.fx_rate(ctx.root(), ctx.cfg(), currency, ctx.runs())
                fx[currency] = hit = (now, rate)
        return acct, hit[1]

    def read(path: str) -> pd.DataFrame:
        return ctx.table(Path(path))

    # --- the Saxo ticket

    def ticket_for(req: TicketRequest):
        row = {k: req.row.get(k) for k in TICKET_FIELDS}
        if not row["ticker"]:
            raise HTTPException(400, "The row needs a ticker.")
        default = ticket.default_type(row)
        kind = req.kind or default
        if kind not in ticket.ORDER_TYPES:
            raise HTTPException(400, "Unknown order type.")
        return row, default, kind

    @app.post("/api/ticket")
    def ticket_view(req: TicketRequest) -> dict:
        """The ticket for a board row: the plan's order type by default, any other on request,
        shares at the grade's risk; the values to type into Saxo, in its order."""
        row, default, kind = ticket_for(req)
        plan_price = ticket.plan_price(row, kind)
        out: dict[str, Any] = {
            "kinds": ticket.ORDER_TYPES,
            "default": default,
            "kind": kind,
            "price_label": board_data.PRICE_LABELS.get(kind, "Price"),
            "plan_price": round(plan_price, 2) if plan_price else None,
            "note": None,
            "error": None,
            "ticket": None,
        }
        acct, usd_rate = account()
        if acct is None or not usd_rate:
            return out | {"note": board_data.NO_ACCOUNT}
        if not board_data.risk_mult(row, ctx.cfg())[1]:
            out["note"] = board_data.UNGRADED_NOTE
        t = board_data.make_ticket(row, kind, ctx.cfg(), acct, usd_rate, req.price or None)
        if t is None:
            return out | {"error": board_data.NO_TICKET}
        out["ticket"] = asdict(t) | {
            "lines": [{"label": k, "value": v} for k, v in t.lines()],
            "caption": board_data.ticket_caption(t, usd_rate, acct.currency),
        }
        return out

    @app.post("/api/ticket/place")
    def ticket_place(req: TicketRequest) -> dict:
        """'Placed in Saxo': saves the ticket as a plan (`plans.create`). Nothing goes to Saxo."""
        row, _, kind = ticket_for(req)
        acct, usd_rate = account()
        if acct is None or not usd_rate:
            raise HTTPException(400, board_data.NO_ACCOUNT)
        t = board_data.make_ticket(row, kind, ctx.cfg(), acct, usd_rate, req.price or None)
        if t is None:
            raise HTTPException(400, board_data.NO_TICKET)
        try:
            plan_id = board_data.place_plan(ctx.root(), row, ctx.cfg(), t, kind)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        saved = "Saved as a plan. Your fill will match it in the Journal."
        return {"plan_id": plan_id, "message": saved}

    # --- Notes & alerts on the focus view

    @app.post("/api/flags")
    def flag(f: Flag) -> dict:
        """🟥 🟨 🟩: the stock onto the matching watchlist."""
        if f.name not in board_data.FLAGS.values():
            raise HTTPException(400, "Not a flag list.")
        tickers = my_watchlists.parse_tickers(f.ticker)
        if not tickers:
            raise HTTPException(400, "Not a ticker.")
        my_watchlists.add(ctx.root(), f.name, tickers[:1])
        return {"message": f"{tickers[0]} → {f.name}"}

    @app.get("/api/stock-notes/{ticker}")
    def notes_of(ticker: str, last: int = 3) -> list[dict]:
        mine = stock_notes.latest(ctx.root(), ticker.strip().upper(), last)
        return _frame(mine, ["note_id", "note_date", "text"]) if len(mine) else []

    @app.post("/api/stock-notes/{ticker}")
    def add_note(ticker: str, body: NoteText) -> list[dict]:
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "The note is empty.")
        stock_notes.add(ctx.root(), ticker.strip().upper(), text)
        return notes_of(ticker)

    @app.get("/api/alerts")
    def alert_list() -> dict:
        """Your price alerts that are on, and what fired today (New York's session)."""
        on = alerts.current(ctx.root())
        today = journal_view.ny_today(ctx.cfg())
        fired = alerts.fired(ctx.root(), today)
        cols = ["fired_ts", "kind", "ticker", "level", "price", "note"]
        return {
            "directions": list(alerts.DIRECTIONS),
            "alerts": records(on),
            "fired": [{k: scalar(f.get(k)) for k in cols} for f in fired],
        }

    @app.post("/api/alerts")
    def alert_add(a: AlertIn) -> dict:
        try:
            alerts.add(ctx.root(), a.ticker, a.level, a.direction, a.note)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return alert_list() | {
            "message": f"Alert set: {a.ticker.strip().upper()} {a.direction} {a.level:.2f}."
        }

    @app.delete("/api/alerts/{alert_id}")
    def alert_remove(alert_id: str) -> dict:
        if alert_id not in set(alerts.current(ctx.root())["alert_id"]):
            raise HTTPException(404, "No such alert.")
        alerts.end(ctx.root(), alert_id)
        return alert_list()

    # --- the grading form (a scan hit or a closed trade)

    def note_of(kind: str, ref_id: str) -> dict:
        current = dashboard.notes_state(ctx.root())
        match = current[(current["kind"] == kind) & (current["ref_id"] == ref_id)]
        prev = match.iloc[0].to_dict() if len(match) else {}
        shots = [a for a in str(prev.get("attachments") or "").split(";") if a]
        return {
            "kind": kind,
            "ref_id": ref_id,
            "grades": list(dashboard.GRADES),
            "grade": prev.get("grade") or "",
            "notes": prev.get("notes") or "",
            "tags": prev.get("tags") or "",
            "attachments": shots,
        }

    @app.get("/api/grades/{kind}/{ref_id}")
    def grade_get(kind: Literal["signal", "trade"], ref_id: str) -> dict:
        return note_of(kind, ref_id)

    @app.put("/api/grades/{kind}/{ref_id}")
    def grade_put(kind: Literal["signal", "trade"], ref_id: str, g: GradeIn) -> dict:
        """Your grade, notes, tags and screenshots (append-only; earlier events are kept)."""
        if g.grade not in dashboard.GRADES:
            raise HTTPException(400, f"The grade is one of {dashboard.GRADES}.")
        saved = note_of(kind, ref_id)["attachments"]
        blobs = []
        for shot in g.screenshots:
            if not shot.name.lower().endswith((".png", ".jpg", ".jpeg")):
                raise HTTPException(400, "Screenshots are .png or .jpg.")
            try:
                blob = base64.b64decode(shot.data.split(",")[-1], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(400, "A screenshot didn't decode.") from exc
            if len(blob) > MAX_SHOT_BYTES:
                raise HTTPException(400, "A screenshot is over 10 MB.")
            blobs.append((shot.name, blob))
        for name, blob in blobs:
            saved.append(dashboard.save_attachment(ctx.root(), ref_id, name, blob))
        dashboard.save_note(ctx.root(), kind, ref_id, g.grade, g.notes, g.tags, saved)
        return note_of(kind, ref_id) | {"message": "Saved. Save & push sends it to GitHub."}

    @app.get("/api/attachments/{path:path}")
    def attachment(path: str) -> FileResponse:
        """A saved screenshot; only files under data/journal/attachments/."""
        base = (ctx.root() / "data" / "journal" / "attachments").resolve()
        target = (ctx.root() / path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise HTTPException(404, "No such screenshot.")
        return FileResponse(target)

    # --- Journal

    def positions_now() -> tuple[pd.DataFrame, pd.DataFrame, Any, float | None]:
        positions = dashboard.latest_positions(ctx.root())
        acct, usd_rate = account()
        account_usd = acct.size_usd(usd_rate) if acct and usd_rate else None
        view = positions_view.open_view(ctx.root(), positions, account_usd)
        return positions, view, acct, usd_rate

    @app.get("/api/journal/open")
    def journal_open() -> dict:
        """Open positions at the newest close and what each plan says."""
        positions, view, _, _ = positions_now()
        if view.empty:
            return {"totals": positions_view.totals(view), "rows": [], "plan": [], "plan_day": None}
        check, day = positions_view.plan_check(positions, ctx.runs(), ctx.cfg(), read)
        return {
            "totals": positions_view.totals(view),
            "rows": _frame(view, journal_view.OPEN_COLUMNS, 2),
            "plan": _frame(check, journal_view.PLAN_CHECK_COLUMNS, 2) if len(check) else [],
            "plan_day": scalar(day),
            "plan_caption": journal_view.PLAN_CHECK_CAPTION,
        }

    @app.post("/api/journal/fills")
    def journal_fill(f: FillIn) -> dict:
        """Log a fill by hand (`journal.log_manual`: the fill, the entry's stop, a rebuild)."""
        try:
            fill = journal.manual_fill(
                f.date, f.ticker, f.side, f.shares, f.price, f.fees, f.setup or None
            )
            journal.log_manual(ctx.root(), ctx.cfg(), fill, f.stop or None)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        ticker = fill.iloc[0]["ticker"]
        return {"message": f"Saved: {f.side} {f.shares:g} {ticker} @ {f.price:g}."}

    @app.get("/api/journal/setups")
    def journal_setups() -> list[str]:
        return journal_view.setup_names(ctx.cfg())

    @app.get("/api/journal/plans")
    def journal_plans() -> dict:
        """Every plan with its status, and the newest run's planned hits to start one from."""
        today = journal_view.ny_today(ctx.cfg())
        table = journal_view.plan_table(ctx.root(), ctx.cfg(), today)
        hits = journal_view.latest_hits(ctx.runs(), read)
        return {
            "today": today.isoformat(),
            "plans": _frame(table, journal_view.PLAN_COLUMNS, 3) if len(table) else [],
            "hits": [r | {"label": journal_view.hit_label(r)} for r in records(hits)],
            "setups": journal_view.setup_names(ctx.cfg()),
        }

    @app.get("/api/journal/plans/suggest")
    def plan_suggest(entry: float, stop: float) -> dict:
        acct, usd_rate = account()
        s = journal_view.suggest_shares(entry, stop, acct, usd_rate)
        return {"suggestion": s, "text": journal_view.suggestion_text(s) if s else None}

    @app.post("/api/journal/plans")
    def plan_create(p: PlanIn) -> dict:
        try:
            plan_id = plans.create(
                ctx.root(), p.session, p.ticker, p.direction, p.entry, p.stop, p.shares,
                p.setup or None, p.note,
            )  # fmt: skip
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return journal_plans() | {"plan_id": plan_id, "message": "Plan saved."}

    @app.post("/api/journal/plans/{plan_id}/cancel")
    def plan_cancel(plan_id: str) -> dict:
        table = journal_view.plan_table(ctx.root(), ctx.cfg())
        open_ids = set(table.loc[table["status"] == "open", "plan_id"]) if len(table) else set()
        if plan_id not in open_ids:
            raise HTTPException(404, "No open plan with that id.")
        plans.cancel(ctx.root(), plan_id)
        return journal_plans()

    @app.get("/api/journal/closed")
    def journal_closed() -> dict:
        """Closed trades with your grade and MFE/MAE, the stats and the R curve."""
        trades = journal_view.closed_trades(ctx.root())
        curve = journal_view.r_curve(trades)
        rows = _frame(trades, ["trade_id", *journal_view.CLOSED_COLUMNS], 2) if len(trades) else []
        for r, t in zip(rows, trades.to_dict("records"), strict=False):
            r["label"] = journal_view.trade_label(t)
        return {
            "stats": journal_view.closed_stats(trades),
            "curve": [{"time": scalar(k), "value": float(v)} for k, v in curve.items()],
            "trades": rows,
            "caption": journal_view.MFE_CAPTION,
        }

    @app.get("/api/journal/real-vs-study")
    def journal_real() -> dict:
        trades = dashboard.latest_journal(ctx.root())
        table = journal_view.real_vs_study(ctx.root(), trades)
        return {
            "columns": [str(c) for c in table.columns],
            "rows": records(table.round(2)),
            "caption": journal_view.REAL_CAPTION,
        }

    @app.post("/api/journal/import")
    def journal_import(f: CsvIn) -> dict:
        """Import a broker's fills export (`journal.main --csv`; columns mapped in config)."""
        data = f.content.encode("utf-8")
        if len(data) > MAX_SHOT_BYTES:
            raise HTTPException(400, "The file is over 10 MB.")
        try:
            out = journal_view.import_csv(ctx.root(), f.name, data)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, f"Not imported: {exc}") from exc
        return {"message": out}

    @app.get("/api/journal/daily-notes")
    def daily_list(tag: str | None = None, days: int = 30) -> dict:
        notes = journal_view.daily_notes_list(ctx.root(), tag, days)
        rows = []
        for n in notes.to_dict("records") if len(notes) else []:
            rows.append(
                {"note_id": n["note_id"], "note_date": scalar(n["note_date"]),
                 "text": n["text"], "tags": list(n["tag_list"])}
            )  # fmt: skip
        return {
            "notes": rows,
            "tags": daily_notes.all_tags(ctx.root()),
            "days": list(journal_view.DAYS_BACK),
            "caption": journal_view.DAILY_CAPTION,
            "kept": journal_view.DAILY_KEPT,
        }

    @app.post("/api/journal/daily-notes")
    def daily_add(n: DailyIn) -> dict:
        if not n.text.strip():
            raise HTTPException(400, "The note is empty.")
        note_id = daily_notes.add(ctx.root(), n.text, n.day, n.tags)
        return {"note_id": note_id}

    def daily_known(note_id: str) -> None:
        live = daily_notes.current(ctx.root())
        if not len(live) or note_id not in set(live["note_id"]):
            raise HTTPException(404, "No such daily note.")

    @app.put("/api/journal/daily-notes/{note_id}")
    def daily_edit(note_id: str, n: DailyIn) -> dict:
        daily_known(note_id)
        if not n.text.strip():
            raise HTTPException(400, "The note is empty.")
        daily_notes.edit(ctx.root(), note_id, n.text, n.day or dt.date.today(), n.tags)
        return {"note_id": note_id}

    @app.delete("/api/journal/daily-notes/{note_id}")
    def daily_remove(note_id: str) -> dict:
        daily_known(note_id)
        daily_notes.remove(ctx.root(), note_id)
        return {"removed": note_id}

    # --- Positions

    @app.get("/api/positions")
    def positions() -> dict:
        """A card per open position: price (live from Alpaca only when its keys are set on the
        server, else the last close), open R and P&L, distance to the stop, the plan today."""
        positions, view, _, _ = positions_now()
        if view.empty:
            return {"source": None, "totals": positions_view.totals(view), "cards": []}
        prices, source = positions_view.live_prices(view["ticker"])
        check, _ = positions_view.plan_check(positions, ctx.runs(), ctx.cfg(), read)
        cards = positions_view.cards(view, check, prices)
        return {
            "source": source,
            "totals": positions_view.totals(view),
            "cards": [{k: scalar(v) for k, v in c.items()} for c in cards],
            "caption": positions_view.PLAN_CAPTION,
        }

    # --- Watchlists

    def eod_run():
        return next((r for r in ctx.runs() if r.slot == "eod" and r.universe.exists()), None)

    @app.get("/api/watchlists")
    def watch_lists() -> dict:
        return {
            "lists": my_watchlists.lists(my_watchlists.load(ctx.root())),
            "flags": list(board_data.FLAGS.values()),
        }

    @app.get("/api/watchlists/{name}")
    def watch_list(name: str) -> dict:
        """A list's stocks with the newest EOD snapshot's numbers and the scans they hit."""
        members = my_watchlists.current(my_watchlists.load(ctx.root()))
        members = members[members["list"] == name]
        eod = eod_run()
        if members.empty:
            return {"name": name, "rows": [], "columns": [], "label": None, "tv_list": ""}
        universe = ctx.table(eod.universe) if eod else pd.DataFrame()
        hits = ctx.table(eod.candidates) if eod else pd.DataFrame()
        view = my_watchlists.with_market(members, universe, hits)
        listing = ctx.exchanges(str(eod.universe)) if eod else {}
        view = view.assign(exchange=view["ticker"].map(listing))
        cols = [c for c in [*WATCH_COLUMNS, "exchange"] if c in view]
        return {
            "name": name,
            "label": eod.label if eod else None,
            "columns": cols,
            "rows": records(view[cols].round(2)),
            "tv_list": board_data.tradingview_list(view["ticker"], listing),
        }

    @app.post("/api/watchlists/{name}/add")
    def watch_add(name: str, body: WatchAdd) -> dict:
        """Add typed tickers and/or a TradingView export's, each checked against the newest
        universe and the daily bars; the answer says what was added, already there, not found."""
        tickers = my_watchlists.parse_tickers(body.text)
        tickers += [t for t in my_watchlists.parse_tickers(body.export_text) if t not in tickers]
        known = my_watchlists.known_checker(ctx.runs(), ctx.root(), read)
        try:
            return my_watchlists.add_checked(ctx.root(), name, tickers, known, body.note)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/watchlists/{name}/remove")
    def watch_remove(name: str, body: WatchRemove) -> dict:
        my_watchlists.remove(ctx.root(), name, body.tickers)
        return watch_list(name)

    @app.get("/api/scan-watchlists")
    def scan_watchlists(include_ended: bool = False) -> dict:
        """EP-Watch and BO-Watch (the jobs' lists), active only unless `include_ended`."""
        state = dashboard.watchlist_state(ctx.root())
        out = {}
        for wl, label in (("bo_watch", "BO-Watch"), ("ep_watch", "EP-Watch")):
            rows = state[state["list"] == wl] if len(state) else state
            if len(rows) and not include_ended:
                rows = rows[rows["status"] == "active"]
            cols = ["ticker", "status", "added_date", "status_date", "reason"]
            out[wl] = {"label": label, "rows": _frame(rows, cols) if len(rows) else []}
        return out
