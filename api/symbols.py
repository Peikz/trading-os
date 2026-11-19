"""The stock universe's tickers and company names (UX round 3, 18 Nov 2026), for the search that
filters as you type and for the company name beside a ticker. Read-only: the tickers are the
newest EOD snapshot's, the names the data repo's own ticker table
(`data/ep_enrich/tickers.parquet`).
No fetching.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Response

from api.pages import Context

NAMES = Path("data") / "ep_enrich" / "tickers.parquet"


def register(app: FastAPI, ctx: Context) -> None:
    def names() -> dict[str, str]:
        path = ctx.root() / NAMES
        if not path.exists():
            return {}
        try:
            table = ctx.table(path)
        except Exception:  # noqa: BLE001 - a table that cannot be read: tickers without names
            return {}
        if not {"ticker", "name"} <= set(table.columns):
            return {}
        if "active" in table:  # a live listing wins over a delisted one with the same symbol
            table = table.sort_values("active", ascending=False, kind="stable")
        table = table.dropna(subset=["name"]).drop_duplicates("ticker")
        return dict(zip(table["ticker"].astype(str), table["name"].astype(str), strict=True))

    @app.get("/api/symbols")
    def symbols(response: Response) -> dict:
        """Every ticker in the newest EOD snapshot with its company name: `[[ticker, name], ...]`
        (a name is empty when the data repo has none). Small and cacheable."""
        eod = next((r for r in ctx.runs() if r.slot == "eod" and r.universe.exists()), None)
        if eod is None:
            return {"asof": None, "symbols": []}
        universe = ctx.table(eod.universe)
        found = names()
        tickers = sorted(set(universe["ticker"].astype(str))) if "ticker" in universe else []
        response.headers["Cache-Control"] = "private, max-age=300"
        return {
            "asof": eod.session.isoformat(),
            "symbols": [[t, found.get(t, "")] for t in tickers],
        }
