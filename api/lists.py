"""The Chart workspace's list panel: one read-only shape for every list you can step through
(today's hits, each watchlist, open positions, a scan's hits at the last close). Every row is
a ticker with the grade chip, last price, % change, relative volume and the setup's name, the
numbers from the newest EOD snapshot. Nothing is computed here and nothing is written.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException

from api.pages import Context
from api.serialize import scalar
from trading_os import board_data, dashboard, my_watchlists, notify

GRADED = ("A+++", "A++", "A+", "A", "B")
RANK = {g: i for i, g in enumerate(("A+++", "A++", "A+", "A", "B", "C"))}


def register(app: FastAPI, ctx: Context) -> None:
    def eod():
        return next((r for r in ctx.runs() if r.slot == "eod" and r.universe.exists()), None)

    def numbers() -> pd.DataFrame:
        run = eod()
        if run is None:
            return pd.DataFrame(columns=["close", "chg_pct", "rvol50"])
        uni = ctx.table(run.universe)
        keep = [c for c in ("ticker", "close", "chg_pct", "rvol50") if c in uni]
        return uni[keep].drop_duplicates("ticker").set_index("ticker")

    def today_hits() -> dict[str, tuple[str, str]]:
        """Ticker -> (best grade, setup label) over the board's alert-tier hits."""
        hits = board_data.collect(ctx.runs(), ctx.cfg(), ctx.scan_frames, ctx.exchanges)
        out: dict[str, tuple[str, str]] = {}
        if hits.empty:
            return out
        for r in notify.best_first(hits).to_dict("records"):
            t = str(r["ticker"])
            if t not in out:
                out[t] = (str(r.get("grade") or "C"), notify.SCAN_LABELS.get(r["scan"], r["scan"]))
        return out

    def rows_for(
        tickers: list[str],
        setup: dict[str, tuple[str, str]],
        fallback: str = "",
        signals: dict[str, str] | None = None,
    ) -> list:
        nums = numbers()
        out: list[dict[str, Any]] = []
        for t in dict.fromkeys(tickers):
            n = nums.loc[t] if t in nums.index else None

            def pick(col: str, n=n):
                return scalar(n[col]) if n is not None and col in n else None

            grade, label = setup.get(t, ("", fallback))
            out.append(
                {
                    "ticker": t,
                    "grade": grade,
                    "setup": label,
                    "last": pick("close"),
                    "chg_pct": pick("chg_pct"),
                    "rvol": pick("rvol50"),
                    "signal_id": (signals or {}).get(t),
                }
            )
        return out

    def scan_hits(name: str) -> tuple[list[str], dict[str, tuple[str, str]], dict[str, str]]:
        run = eod()
        if run is None:
            raise HTTPException(404, "No EOD run yet.")
        frames = ctx.scan_frames(str(run.candidates))
        if name not in frames:
            raise HTTPException(404, "That scan has no hits in the last close.")
        frame = notify.best_first(frames[name]).reset_index(drop=True)
        label = notify.SCAN_LABELS.get(name, name)
        grades = frame["grade"] if "grade" in frame else pd.Series([""] * len(frame))
        setup = {
            str(t): (str(g) if isinstance(g, str) else "", label)
            for t, g in zip(frame["ticker"], grades, strict=True)
        }
        ids = (
            {str(t): str(i) for t, i in zip(frame["ticker"], frame["signal_id"], strict=True)}
            if "signal_id" in frame
            else {}
        )
        return [str(t) for t in frame["ticker"]], setup, ids

    def members(name: str) -> list[str]:
        cur = my_watchlists.current(my_watchlists.load(ctx.root()))
        return [str(t) for t in cur[cur["list"] == name]["ticker"]]

    def held() -> list[str]:
        pos = dashboard.latest_positions(ctx.root())
        return [str(t) for t in pos["ticker"]] if "ticker" in pos else []

    def graded_hits(hits: dict[str, tuple[str, str]]) -> list[str]:
        ranked = sorted(hits, key=lambda t: RANK.get(hits[t][0], 9))
        return [t for t in ranked if hits[t][0] in GRADED]

    @app.get("/api/chart-lists")
    def chart_lists() -> dict:
        """The lists to pick from: id, label, group and size."""
        hits = today_hits()
        out: list[dict[str, Any]] = [
            {
                "id": "hits",
                "label": "Today's hits",
                "group": "Today",
                "count": len(graded_hits(hits)),
            }
        ]
        loaded = my_watchlists.load(ctx.root())
        cur = my_watchlists.current(loaded)
        for name in my_watchlists.lists(loaded):
            count = int((cur["list"] == name).sum())
            out.append({"id": f"wl:{name}", "label": name, "group": "My lists", "count": count})
        out.append(
            {"id": "pos", "label": "Open positions", "group": "My lists", "count": len(held())}
        )
        run = eod()
        if run is not None:
            for name, frame in ctx.scan_frames(str(run.candidates)).items():
                out.append(
                    {
                        "id": f"scan:{name}",
                        "label": notify.SCAN_LABELS.get(name, name),
                        "group": "Scan hits · last close",
                        "count": len(frame),
                    }
                )
        return {"lists": out}

    @app.get("/api/chart-lists/{list_id:path}")
    def chart_list(list_id: str) -> dict:
        """One list's rows: ticker, grade, setup, last, % change, relative volume (a scan's hits
        also carry the hit's signal id, for its grading form)."""
        kind, _, name = list_id.partition(":")
        if list_id == "hits":
            hits = today_hits()
            return {
                "id": list_id,
                "label": "Today's hits",
                "rows": rows_for(graded_hits(hits), hits),
            }
        if kind == "wl" and name:
            return {"id": list_id, "label": name, "rows": rows_for(members(name), today_hits())}
        if list_id == "pos":
            rows = rows_for(held(), today_hits(), "open position")
            return {"id": list_id, "label": "Open positions", "rows": rows}
        if kind == "scan" and name:
            tickers, setup, ids = scan_hits(name)
            label = notify.SCAN_LABELS.get(name, name)
            return {"id": list_id, "label": label, "rows": rows_for(tickers, setup, "", ids)}
        raise HTTPException(404, "No such list.")
