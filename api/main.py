"""Trading OS API: a read-only JSON view of the data repo for the React dashboard (`web/`).

    TRADING_OS_DATA=/path/to/trading-os-data uv run --group api uvicorn api.main:app

Every number comes from the `trading_os` package (runs from `dashboard`, the board from
`board_data`, chart lines from `chart_series`, screens from `screens`); nothing is computed
here. Writes: your own screens here, and in `api.pages` the same data-repo files Streamlit
writes (plans, fills, grades, notes, watchlists, alerts). No orders, no pushes, no AI.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from api import chart, pages, research
from api.serialize import records, scalar
from trading_os import board_data, chart_series, dashboard, notify, screens
from trading_os.config import DEFAULT_PATH as CONFIG_PATH
from trading_os.config import load_config

GRADED = ("A+", "A", "B")
SCOPES = {
    "graded": "A+ / A / B",
    "pushed": "Pushed, incl. C",
    "all": "Every scan hit",
    "watchlists": "My watchlists",
}
LIVE_EVERY_S = 300  # the Screener's live TradingView fetch: at most once per 5 minutes


def run_id(run: dashboard.Run) -> str:
    """`2026-10-21_eod`, or `2026-10-21_eod_142233` for a manual run."""
    base = f"{run.session.isoformat()}_{run.slot}"
    return f"{base}_{run.stamp}" if run.kind == "manual" else base


def _mtime(path: Path | None) -> int:
    try:
        return path.stat().st_mtime_ns if path is not None else 0
    except OSError:
        return 0


class _Cache:
    """Small in-process caches keyed by file version, so a new run file is read at once."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.frames: dict[tuple[str, int], dict[str, pd.DataFrame]] = {}
        self.tables: dict[tuple[str, int], pd.DataFrame] = {}
        self.live: tuple[float, pd.DataFrame] | None = None
        self.config: tuple[int, Any] | None = None

    def scan_frames(self, path: str) -> dict[str, pd.DataFrame]:
        key = (path, _mtime(Path(path)))
        with self.lock:
            if key not in self.frames:
                if len(self.frames) > 16:
                    self.frames.clear()
                self.frames[key] = board_data.scan_frames(path)
            return self.frames[key]

    def table(self, path: Path) -> pd.DataFrame:
        key = (str(path), _mtime(path))
        with self.lock:
            if key not in self.tables:
                if len(self.tables) > 16:
                    self.tables.clear()
                self.tables[key] = pd.read_parquet(path)
            return self.tables[key]


class ScreenSpec(BaseModel):
    filters: list[dict[str, Any]] = Field(default_factory=list)
    sort: str | None = "rs_pct"
    descending: bool = True


class ScreenRun(ScreenSpec):
    source: Literal["all", "hits"] = "all"
    data: Literal["close", "live"] = "close"
    run: str | None = None  # run id, for source "hits"
    scan: str | None = None
    tiers: list[str] = Field(default_factory=lambda: ["alert", "log"])
    limit: int = Field(500, ge=1, le=5000)


def create_app(data_dir: Path | str | None = None, config_path: Path | str | None = None):
    """The app over `data_dir` (default: env TRADING_OS_DATA)."""
    folder = data_dir or os.environ.get("TRADING_OS_DATA")
    cfg_path = Path(config_path or CONFIG_PATH)
    cache = _Cache()
    app = FastAPI(title="Trading OS", docs_url="/api/docs", openapi_url="/api/openapi.json")

    def root() -> Path:
        if not folder or not (Path(folder) / "data").exists():
            raise HTTPException(503, "No data folder: set TRADING_OS_DATA to a data repo clone.")
        return Path(folder)

    def cfg():
        version = _mtime(cfg_path)
        if cache.config is None or cache.config[0] != version:
            cache.config = (version, load_config(cfg_path))
        return cache.config[1]

    def runs(manual: bool = False) -> list[dashboard.Run]:
        return dashboard.list_runs(root(), include_manual=manual)

    def find_run(rid: str) -> dashboard.Run:
        for r in runs(manual=True):
            if run_id(r) == rid:
                return r
        raise HTTPException(404, "No such run.")

    def exchanges(path: str) -> dict[str, str]:
        p = Path(path)
        if not p.exists():
            return {}
        uni = cache.table(p)
        return dict(zip(uni["ticker"], uni["exchange"], strict=True)) if "exchange" in uni else {}

    def board_row(row: dict) -> dict:
        """A board row as the card shows it: the row's own fields plus the card's facts, the key
        stats and the chart's price lines (computed on the raw row, then made JSON-safe)."""
        try:
            facts = board_data.card_facts(row)
        except (KeyError, TypeError, ValueError):  # a row saved without every plan field
            facts = []
        out = {str(k): scalar(v) for k, v in row.items() if not str(k).startswith("_")}
        out["scan_label"] = notify.SCAN_LABELS.get(row["scan"], row["scan"])
        out["facts"] = facts
        out["stats"] = [{"label": k, "value": v} for k, v in board_data.key_stats(row)]
        out["levels"] = board_data.levels(row)
        out["alert_default"] = board_data.alert_default(row)
        return out

    @app.get("/api/health")
    def health() -> dict:
        found = runs(manual=False)
        return {"ok": True, "runs": len(found), "latest": run_id(found[0]) if found else None}

    @app.get("/api/runs")
    def list_runs(manual: bool = False) -> list[dict]:
        return [
            {
                "id": run_id(r),
                "label": r.label,
                "session": r.session.isoformat(),
                "slot": r.slot,
                "kind": r.kind,
                "has_universe": r.universe.exists(),
                "has_breadth": r.breadth is not None,
            }
            for r in runs(manual)
        ]

    @app.get("/api/runs/{rid}/scans")
    def run_scans(rid: str) -> dict:
        """Every scan's hits in one run, best study grade first, with the scan's push setting."""
        run = find_run(rid)
        out = {}
        for scan, hits in cache.scan_frames(str(run.candidates)).items():
            setting = cfg().scans.get(scan)
            ordered = notify.best_first(hits) if "grade" in hits else hits
            out[scan] = {
                "label": notify.SCAN_LABELS.get(scan, scan),
                "pushed": bool(setting is not None and setting.action == "push"),
                "count": len(hits),
                "hits": records(ordered),
            }
        return {"run": rid, "label": run.label, "scans": out}

    @app.get("/api/today")
    def today(
        scope: Literal["graded", "pushed", "all", "watchlists"] = "graded",
        t: str | None = None,
        screen: str | None = None,
    ) -> dict:
        """The board's queue: the newest runs' A+ / A / B first (C with scope pushed / all).
        `t`: a push link's stocks (`?t=A,B`), in the push's order, from every scan's hits.
        `screen` with `t`: a screen's results to flip through (no grade). Scope `watchlists`:
        your own lists' stocks."""
        found = runs(manual=False)
        wanted = [x for x in (t or "").split(",") if x]
        if (screen and wanted) or scope == "watchlists":
            if scope == "watchlists" and not (screen and wanted):
                rows_ = board_data.watchlist_rows(found, root())
            else:
                rows_ = board_data.ticker_rows(found, wanted, f"screen: {screen}")
                scope = "screen"
            if len(rows_) and "exchange" not in rows_:
                with_uni = next((r for r in found if r.universe.exists()), None)
                listing = exchanges(str(with_uni.universe)) if with_uni else {}
                rows_["exchange"] = rows_["ticker"].map(listing)
            rows = [board_row(r) for r in rows_.to_dict("records")]
            return {"scope": scope, "rows": rows, "hidden_c": 0, "total": len(rows)}
        every = scope == "all" or bool(wanted)
        hits = board_data.collect(found, cfg(), cache.scan_frames, exchanges, everything=every)
        if wanted and len(hits):
            order = {x: i for i, x in enumerate(wanted)}
            hits = hits[hits["ticker"].isin(order)]
            hits = hits.assign(_o=hits["ticker"].map(order)).sort_values("_o")
            scope = "all"
        if hits.empty:
            return {"scope": scope, "rows": [], "hidden_c": 0, "total": 0}
        graded = hits[hits["grade"].isin(GRADED)]
        shown = graded if scope == "graded" else hits
        rows = [board_row(r) for r in shown.to_dict("records")]
        return {
            "scope": scope,
            "rows": rows,
            "hidden_c": int(len(hits) - len(graded)) if scope == "graded" else 0,
            "total": int(len(hits)),
        }

    @app.get("/api/market")
    def market() -> dict:
        """The market tiles: QQQ light, heat, IBD state, SPY, QQQ, VIX; and the full lines."""
        row, ibd_info, heat_text = board_data.market_inputs(root(), runs(manual=False))
        if not row:
            return {"tiles": [], "details": []}
        tiles = board_data.tiles(row, ibd_info, heat_text)
        return {
            "tiles": [{"label": k, "value": v, "delta": d} for k, v, d in tiles],
            "details": board_data.market_details(row),
            "session": scalar(row.get("session_date")),
        }

    @app.get("/api/bars/{ticker}")
    def bars(
        ticker: str,
        tf: Literal["1D", "1W"] = "1D",
        indicators: str = Query(",".join(chart_series.DEFAULT)),
        anchor: str | None = None,
    ) -> dict:
        """Daily (or weekly) bars for one stock with the picked indicator lines."""
        ticker = ticker.strip().upper()
        if not ticker or len(ticker) > 12:
            raise HTTPException(400, "Bad ticker.")
        picked = [p for p in indicators.split(",") if p in chart_series.INDICATORS]
        b = board_data.daily_bars(root(), ticker)
        if b.empty:
            return {"ticker": ticker, "tf": tf, "candles": [], "lines": []}
        bench = board_data.daily_bars(root(), "QQQ") if "RS vs QQQ" in picked else None
        if tf == "1W":
            b = chart_series.weekly(b)
            bench = chart_series.weekly(bench) if bench is not None and len(bench) else bench
        b = b.sort_values("session_date").reset_index(drop=True)
        b["time"] = pd.to_datetime(b["session_date"]).dt.strftime("%Y-%m-%d")
        cols = zip(b.time, b.open, b.high, b.low, b.close, b.volume, strict=True)
        candles = [
            {"time": t, "open": o, "high": h, "low": lo, "close": c, "volume": v}
            for t, o, h, lo, c, v in ((t, *map(float, rest)) for t, *rest in cols)
        ]
        lines = chart_series.indicator_lines(b, picked, anchor, bench)
        return {"ticker": ticker, "tf": tf, "candles": candles, "lines": lines}

    # --- Screener

    def snapshot() -> tuple[dashboard.Run, pd.DataFrame]:
        eod = [r for r in runs(manual=False) if r.slot == "eod" and r.universe.exists()]
        if not eod:
            raise HTTPException(404, "No EOD universe snapshot yet.")
        return eod[0], cache.table(eod[0].universe)

    @app.get("/api/screener/meta")
    def screener_meta() -> dict:
        return {
            "fields": {
                f: {"label": lab, "kind": k, "group": g}
                for f, (lab, k, g) in screens.FIELDS.items()
            },
            "ops": screens.OPS,
            "shown": screens.SHOWN,
            "examples": screens.EXAMPLES,
            "saved": screens.load(root()),
            "labels": notify.SCAN_LABELS,
        }

    @app.get("/api/screener/options/{field}")
    def screener_options(field: str) -> list[str]:
        """The values a text field takes in the last close's snapshot (sector, industry...)."""
        if screens.kind(field) != "text":
            raise HTTPException(400, "Not a text field.")
        _, snap = snapshot()
        return sorted(snap[field].dropna().astype(str).unique()) if field in snap else []

    @app.post("/api/screener/run")
    def screener_run(req: ScreenRun) -> dict:
        eod, snap = snapshot()
        data, when, scan = snap, f"the {eod.session:%d %b} close", None
        if req.source == "hits":
            if not req.run or not req.scan:
                raise HTTPException(400, "Pick a run and a scan.")
            run = find_run(req.run)
            frames = cache.scan_frames(str(run.candidates))
            if req.scan not in frames:
                raise HTTPException(404, "That run has no hits for this scan.")
            hits = frames[req.scan]
            if "tier" in hits:
                hits = hits[hits["tier"].isin(req.tiers)]
            uni = cache.table(run.universe) if run.universe.exists() else snap
            data = screens.with_universe(hits, uni)
            if "exchange" not in data:
                data["exchange"] = data["ticker"].map(exchanges(str(eod.universe)))
            scan = req.scan
            when = f"{notify.SCAN_LABELS.get(scan, scan)} hits, {run.label}"
        elif req.data == "live":
            now = time.time()
            failed = None
            if cache.live is None or now - cache.live[0] > LIVE_EVERY_S:
                try:
                    cache.live = (now, screens.live_data(cfg(), snap))
                except Exception as exc:  # noqa: BLE001 - fall back to the snapshot
                    failed = type(exc).__name__
            if failed:
                when += f" (live fetch failed: {failed})"
            elif cache.live is not None:
                data = cache.live[1]
                when = "live (TradingView; history fields from the last close)"
        try:
            result = screens.run(data, req.filters, None if scan else req.sort, req.descending)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if scan and "grade" in result:
            result = notify.best_first(result).reset_index(drop=True)
        fields = [f.get("field") for f in req.filters]
        lead = ["grade", "grade_score", "tier"] if scan else []
        cols = list(dict.fromkeys([*lead, *screens.SHOWN, *fields, req.sort, "exchange"]))
        cols = [c for c in cols if c and c in result]
        summary = " · ".join(screens.describe(f) for f in screens.check(req.filters))
        return {
            "count": int(len(result)),
            "when": when,
            "summary": summary or ("no filters: every hit" if scan else "no filters: every stock"),
            "columns": cols,
            "rows": records(result[cols].head(req.limit)),
            "tickers": [str(x) for x in result["ticker"].head(200)],
            # A scan hit's id per ticker, for its grading form
            "signal_ids": (
                {str(t): str(i) for t, i in zip(result["ticker"], result["signal_id"], strict=True)}
                if scan and "signal_id" in result
                else {}
            ),
            "tv_list": board_data.tradingview_list(
                result["ticker"].head(1000),
                dict(zip(result["ticker"], result["exchange"], strict=False))
                if "exchange" in result
                else None,
            ),
        }

    @app.get("/api/screens")
    def saved_screens() -> dict:
        return screens.load(root())

    @app.put("/api/screens/{name}")
    def save_screen(name: str, spec: ScreenSpec) -> dict:
        try:
            screens.save(root(), name, spec.filters, spec.sort, spec.descending)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return screens.load(root())

    @app.delete("/api/screens/{name}")
    def delete_screen(name: str) -> dict:
        screens.delete(root(), name)
        return screens.load(root())

    ctx = pages.Context(root=root, cfg=cfg, runs=runs, table=cache.table, exchanges=exchanges)
    pages.register(app, ctx)
    chart.register(app, ctx)
    research.register(app, ctx, find_run, run_id, cfg_path)
    return app


app = create_app()
