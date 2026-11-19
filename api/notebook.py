"""The Journal notebook (Emil, 18 Nov 2026): one read of every note the sidebar lists (daily notes,
trades, stocks with notes, free pages, tags with counts), the free pages' own routes, and a
pasted image's upload. Daily, stock and trade notes keep their own routes and files; nothing about
them changes. The only new store is the free pages (`trading_os/pages.py`:
`data/journal/pages/<slug>.md`), written by the owner only. No orders, no AI.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import re
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from api import today_runs
from api.pages import MAX_SHOT_BYTES, Context
from api.serialize import scalar
from trading_os import daily_notes, dashboard, notify, pages, stock_notes

IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


class PageIn(BaseModel):
    title: str | None = None
    text: str | None = None
    tags: list[str] | None = None


class ImageIn(BaseModel):
    ref: str  # what the image belongs to (a trade id, a ticker, a page): the attachment folder
    name: str
    data: str  # base64, a data: URL is fine


def open_id(ticker: str, entry_date: str) -> str:
    """A trade that is still open has no id yet: its notes are kept under this one."""
    return f"open-{ticker}-{entry_date}"


def register(app: FastAPI, ctx: Context) -> None:
    def trades() -> list[dict[str, Any]]:
        """Open positions and closed trades with the grade, conviction, notes and tags you
        saved on each (`dashboard.notes_state`, the grading form's file)."""
        noted = dashboard.notes_state(ctx.root())
        mine = noted[noted["kind"] == "trade"].set_index("ref_id") if len(noted) else None

        def note_of(ref: str) -> dict[str, Any]:
            if mine is None or ref not in mine.index:
                return {"grade": "", "conviction": None, "notes": "", "typed": ""}
            n = mine.loc[ref]
            sure = n.get("conviction")
            return {
                "grade": str(n.get("grade") or ""),
                "conviction": None if pd.isna(sure) else int(sure),
                "notes": str(n.get("notes") or ""),
                "typed": str(n.get("tags") or ""),
            }

        def sure_of(t: dict) -> int | None:
            v = t.get("conviction")
            return None if pd.isna(v) else int(v)

        out: list[dict[str, Any]] = []
        closed = dashboard.latest_journal(ctx.root())
        for t in closed.to_dict("records") if len(closed) else []:
            n = note_of(str(t["trade_id"]))
            out.append(
                {
                    "id": str(t["trade_id"]), "status": "closed", "ticker": str(t["ticker"]),
                    "direction": str(t.get("direction") or ""),
                    "entry_date": scalar(t.get("entry_date")),
                    "exit_date": scalar(t.get("exit_date")),
                    "setup": str(t.get("setup") or ""),
                    "r": scalar(t.get("r_multiple")), "pnl": scalar(t.get("pnl")),
                    "entry": scalar(t.get("entry_avg")), "exit": scalar(t.get("exit_avg")),
                    "stop": scalar(t.get("order_stop")),
                    "grade": n["grade"], "conviction": n["conviction"] or sure_of(t),
                    "text": n["notes"], "tags": pages.all_tags(n["typed"], n["notes"]),
                    "typed_tags": pages.split_tags(n["typed"]),
                }
            )  # fmt: skip
        held = dashboard.latest_positions(ctx.root())
        for p in held.to_dict("records") if len(held) else []:
            entry = str(scalar(p.get("entry_date")) or "")[:10]
            ref = open_id(str(p["ticker"]), entry)
            n = note_of(ref)
            out.append(
                {
                    "id": ref, "status": "open", "ticker": str(p["ticker"]),
                    "direction": str(p.get("direction") or ""), "entry_date": entry,
                    "exit_date": None, "setup": str(p.get("setup") or ""), "r": None, "pnl": None,
                    "entry": scalar(p.get("entry_avg")), "exit": None,
                    "stop": scalar(p.get("order_stop")),
                    "grade": n["grade"], "conviction": n["conviction"], "text": n["notes"],
                    "tags": pages.all_tags(n["typed"], n["notes"]),
                    "typed_tags": pages.split_tags(n["typed"]),
                }
            )  # fmt: skip
        return out

    @app.get("/api/notebook")
    def notebook() -> dict:
        """Everything the notebook's sidebar lists, with the text of every note (search and the
        linked mentions are computed from it in the browser)."""
        today = dt.date.today().isoformat()
        daily = []
        live = daily_notes.current(ctx.root())
        for n in live.to_dict("records") if len(live) else []:
            text = str(n["text"] or "")
            daily.append(
                {
                    "id": n["note_id"], "date": scalar(n["note_date"]), "text": text,
                    "stocks": list(n["tag_list"]), "tags": pages.hashtags(text),
                }
            )  # fmt: skip
        by_stock: dict[str, list[dict]] = {}
        mine = stock_notes.current(ctx.root())
        for n in mine.to_dict("records") if len(mine) else []:
            text = str(n["text"] or "")
            by_stock.setdefault(str(n["ticker"]), []).append(
                {"note_id": n["note_id"], "date": scalar(n["note_date"]), "text": text,
                 "tags": pages.hashtags(text)}
            )  # fmt: skip
        stocks = [
            {
                "ticker": t,
                "notes": notes,
                "tags": list(dict.fromkeys(x for n in notes for x in n["tags"])),
            }
            for t, notes in sorted(by_stock.items())
        ]
        free = [p.as_dict() | {"tags": p.as_dict()["all_tags"], "typed_tags": p.tags}
                for p in pages.list_pages(ctx.root())]  # fmt: skip
        owned = trades()
        counts: dict[str, int] = {}
        for tags in (
            *[d["tags"] for d in daily], *[s["tags"] for s in stocks],
            *[p["tags"] for p in free], *[t["tags"] for t in owned],
        ):  # fmt: skip
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
        tickers = sorted(
            {*by_stock, *[t["ticker"] for t in owned], *[s for d in daily for s in d["stocks"]]}
        )
        return {
            "today": today,
            "daily": daily,
            "trades": owned,
            "stocks": stocks,
            "pages": free,
            "tags": [{"tag": k, "count": v} for k, v in sorted(counts.items())],
            "tickers": tickers,
        }

    # --- free pages

    def page_or_404(slug: str) -> pages.Page:
        try:
            found = pages.load(ctx.root(), slug)
        except ValueError as exc:
            raise HTTPException(404, "No such page.") from exc
        if found is None:
            raise HTTPException(404, "No such page.")
        return found

    def shown(p: pages.Page) -> dict:
        return p.as_dict() | {"tags": p.as_dict()["all_tags"], "typed_tags": p.tags}

    @app.post("/api/notebook/pages")
    def page_create(body: PageIn) -> dict:
        made = pages.create(ctx.root(), body.title or "Untitled", body.text or "", body.tags)
        return shown(made)

    @app.get("/api/notebook/pages/{slug}")
    def page_get(slug: str) -> dict:
        return shown(page_or_404(slug))

    @app.put("/api/notebook/pages/{slug}")
    def page_save(slug: str, body: PageIn) -> dict:
        page_or_404(slug)
        return shown(pages.save(ctx.root(), slug, body.title, body.text, body.tags))

    @app.delete("/api/notebook/pages/{slug}")
    def page_delete(slug: str) -> dict:
        page_or_404(slug)
        pages.delete(ctx.root(), slug)
        return {"removed": slug}

    # --- a pasted or picked image (the grading form's attachment store)

    @app.post("/api/notebook/images")
    def image_add(img: ImageIn) -> dict:
        if not img.name.lower().endswith(IMAGE_TYPES):
            raise HTTPException(400, "Images are .png, .jpg, .gif or .webp.")
        try:
            blob = base64.b64decode(img.data.split(",")[-1], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(400, "The image didn't decode.") from exc
        if len(blob) > MAX_SHOT_BYTES:
            raise HTTPException(400, "The image is over 10 MB.")
        ref = re.sub(r"[^A-Za-z0-9._-]+", "_", img.ref)[:80] or "notebook"
        path = dashboard.save_attachment(ctx.root(), ref, img.name, blob)
        return {"path": path, "url": f"/api/attachments/{path}"}

    # --- the hover card of a $TICKER: last, % change and today's grade (read-only)

    @app.get("/api/notebook/cards")
    def cards(t: str) -> dict:
        wanted = [x.strip().upper() for x in t.split(",") if x.strip()][:20]
        run = next((r for r in ctx.runs() if r.slot == "eod" and r.universe.exists()), None)
        nums = pd.DataFrame()
        if run is not None:
            uni = ctx.table(run.universe)
            keep = [c for c in ("ticker", "close", "chg_pct") if c in uni]
            nums = uni[keep].drop_duplicates("ticker").set_index("ticker")
        grades: dict[str, str] = {}
        hits = today_runs.hits(
            today_runs.ALL, ctx.runs(), ctx.cfg(), ctx.scan_frames, ctx.exchanges,
            everything=False,
        )  # fmt: skip
        if hits is not None and not hits.empty:
            for r in notify.best_first(hits).to_dict("records"):
                grades.setdefault(str(r["ticker"]), str(r.get("grade") or ""))
        out = {}
        for ticker in wanted:
            row = nums.loc[ticker] if ticker in nums.index else None
            out[ticker] = {
                "last": scalar(row["close"]) if row is not None and "close" in row else None,
                "chg_pct": scalar(row["chg_pct"]) if row is not None and "chg_pct" in row else None,
                "grade": grades.get(ticker, ""),
            }
        return out
