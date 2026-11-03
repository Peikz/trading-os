"""Phase 3 routes: the Market page (`trading_os.market_view`) and the Guide (docs/GUIDE.md).

Read-only. The Market page's indexes, sectors and themes come live from TradingView (one
request, at most every 10 minutes), else from the last EOD's saved rows.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import FastAPI, Query

from api.pages import Context
from api.research import table
from api.serialize import scalar
from trading_os import market_view

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "GUIDE.md"
SECTORS_EVERY_S = 600


def register(app: FastAPI, ctx: Context, guide: Path = GUIDE) -> None:
    lock = threading.Lock()
    sectors: dict[str, tuple[float, object]] = {}

    def sector_table():
        now = time.time()
        with lock:
            hit = sectors.get("table")
            if hit is None or now - hit[0] > SECTORS_EVERY_S:
                hit = (now, market_view.sector_table(ctx.root()))
                sectors["table"] = hit
        return hit[1]

    @app.get("/api/market/page")
    def market_page(
        band: str | None = None,
        period: str = Query("1 month"),
        groups: str = ",".join(market_view.GROUPS),
        back: str = Query("1 week", pattern="^(1 week|1 month)$"),
    ) -> dict:
        """The Market page: tiles, the IBD state's last 30 sessions, the setups at a heat, the
        indexes / sectors / themes with their rotation, the industries, the breadth history."""
        history = market_view.history_of(ctx.root())
        if history.empty:
            return {"empty": True}
        tiles, _ = market_view.tiles(ctx.root(), history)
        heat = market_view.heat_view(ctx.root(), history, band)
        picked = [g for g in groups.split(",") if g in market_view.GROUPS]
        period = period if period in market_view.PERIODS else "1 month"
        sector, source = sector_table()
        industries = market_view.industries(ctx.root(), back)
        return scalar(
            {
                "empty": False,
                "tiles": [{"label": k, "value": v, "delta": d} for k, v, d in tiles],
                "ibd": table(market_view.ibd_recent(ctx.root())),
                "ibd_caption": market_view.IBD_CAPTION,
                "heat": None
                if heat is None
                else {k: (table(v) if k == "table" else v) for k, v in heat.items()},
                "periods": list(market_view.PERIODS),
                "period": period,
                "groups": list(market_view.GROUPS),
                "picked": picked,
                "sectors": table(market_view.sector_view(sector, period, picked), digits=1)
                if len(sector)
                else None,
                "sector_caption": market_view.SECTOR_CAPTION.format(source=source),
                "rotation": market_view.rotation_points(sector, picked) if len(sector) else [],
                "back": back,
                "industries": None
                if industries is None
                else {
                    "top": table(industries["top"]),
                    "climbing": table(industries["climbing"]),
                    "caption": industries["caption"],
                },
                "breadth": table(market_view.breadth(history), limit=500),
                "ratios": market_view.ratio_curve(history),
            }
        )

    @app.get("/api/guide")
    def guide_text() -> dict:
        """The guide (docs/GUIDE.md), without its own title (the page has one)."""
        if not guide.is_file():
            return {"text": None}
        body = guide.read_text(encoding="utf-8").splitlines()[1:]
        return {"text": "\n".join(body)}
