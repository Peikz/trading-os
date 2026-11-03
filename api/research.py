"""Phase 2b routes: Research (strategy rules, how it was tested, grades, History, entries &
exits, market regime, study notes), Live results, System health (jobs and data, validation
against TradingView), the Scans editor, and Pull latest / Save & push.

Every table comes from the package (`research_view`, `scans_view`, `health`, `timer`,
`validation`); nothing is computed here. Writes: `config/scans.yaml` through `scan_editor`
(checked like the jobs check config; only Emil edits, on the Scans page), an appended
`docs/validation.md` in the data repo, and git pull / commit / push of the data repo
(`dashboard.pull`, `dashboard.save_and_push`) and of the scans config (`scan_editor`).
"""

from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from api.pages import Context
from api.serialize import records, scalar
from trading_os import (
    chart_view,
    dashboard,
    health,
    live_tracking,
    remote_data,
    research_view,
    scan_editor,
    scans_view,
    timer,
    validation,
)
from trading_os.config import ConfigError

MAX_ROWS = 2000
VALIDATION_SCANS = ("ep_day", "qm_gainers")


def table(frame: pd.DataFrame | None, limit: int = MAX_ROWS, digits: int | None = None) -> dict:
    """A frame as {columns, rows, total} (its index kept when it is named)."""
    if frame is None or frame.empty:
        return {"columns": [], "rows": [], "total": 0}
    out = frame
    if out.index.name is not None:
        out = out.reset_index()
    if digits is not None:
        out = out.round(digits)
    out = out.rename(columns=str)
    return {
        "columns": list(out.columns),
        "rows": records(out.head(limit)),
        "total": int(len(frame)),
    }


class EpFilters(BaseModel):
    gap_min: float = 10
    rvol_min: float = 3.0
    months_min: float = 0.0
    earnings: str = Field("any", pattern="^(any|yes|no|unknown)$")
    must: list[str] = Field(default_factory=list)


class HistoryQuery(BaseModel):
    period: str = Field("10y", pattern="^(2y|10y)$")
    strategies: list[str] | None = None  # None: every strategy
    years: list[int] | None = None  # None: every year
    states: list[str] = Field(default_factory=list)
    ep: EpFilters | None = None
    split: str = "none"
    one: str | None = None  # the strategy whose events to list


class ValidationIn(BaseModel):
    run: str
    scan: str
    csv_text: str


class ScanEdit(BaseModel):
    values: dict[str, Any]


def register(app: FastAPI, ctx: Context, find_run, run_id, config_path: Path) -> None:
    root, cfg = ctx.root, ctx.cfg
    config_path = Path(config_path)

    # --- Research

    @app.get("/api/research/strategy-rules")
    def rules(label: str | None = None) -> dict:
        labels = [x[0] for x in research_view.STRATEGY_RULES]
        pick = label if label in labels else labels[0]
        found = research_view.strategy_rules(cfg(), root(), pick)
        # scalar(): the rules carry numpy numbers from the stats files (a 500 on real data)
        return scalar({"labels": labels, "label": pick, **found})

    @app.get("/api/research/how-tested")
    def how_tested() -> dict:
        return scalar(research_view.how_tested(cfg(), root()))

    @app.get("/api/research/grades")
    def grades() -> dict:
        return scalar(research_view.study_grades(cfg(), root()))

    @app.get("/api/research/notes")
    def notes(name: str | None = None) -> dict:
        found = research_view.study_notes(root())
        names = [p.stem for p in found]
        pick = name if name in names else (names[0] if names else None)
        text = next((p for p in found if p.stem == pick), None)
        return {
            "names": names,
            "name": pick,
            "text": text.read_text(encoding="utf-8") if text else None,
        }

    def history(period: str) -> pd.DataFrame:
        if period == "10y":
            research_view.release(root(), "history-10y", "*.parquet")
        return research_view.history_frame(root(), period)

    @app.post("/api/research/history")
    def history_view(q: HistoryQuery) -> dict:
        """The History page: the graded section, then every event with the filters, the summary
        per split, the exits compared and one strategy's events."""
        hist = history(q.period)
        summary, by_grade = research_view.history_graded(root())
        graded = {
            "summary": table(summary.rename(columns=research_view.GRADED_RENAME), digits=3),
            "by_grade": table(by_grade, digits=3),
            "caption": research_view.GRADED_CAPTION,
        }
        if hist.empty:
            return {"empty": True, "graded": graded}
        names = sorted(hist["strategy"].unique())
        years = sorted(int(y) for y in hist["year"].dropna().unique())
        picked = names if q.strategies is None else [s for s in q.strategies if s in names]
        chosen = years if q.years is None else q.years
        ep_on = "ep_day" in picked
        ep_args = None
        if ep_on and q.ep is not None:
            e = q.ep
            ep_args = (e.gap_min, e.rvol_min, e.months_min, e.earnings, tuple(e.must))
        elif ep_on:
            ep_args = (10, 3.0, 0.0, "any", ())
        view = research_view.filter_history(hist, picked, chosen, q.states, ep_args)
        splits = research_view.HISTORY_SPLITS + (research_view.EP_SPLITS if ep_on else [])
        split = q.split if q.split in splits else "none"
        summary_t, compared = research_view.history_tables(view, cfg().exits, split)
        one = q.one if q.one in (picked or names) else (picked or names)[0]
        events = research_view.history_events(view, one)
        return scalar(
            {
                "empty": False,
                "graded": graded,
                "caption": research_view.HISTORY_CAPTION,
                "strategies": names,
                "years": years,
                "picked": picked,
                "chosen_years": chosen,
                "ep_flags": research_view.EP_FLAGS,
                "splits": splits,
                "split": split,
                "count": int(len(view)),
                "summary": table(summary_t, digits=2),
                "summary_caption": research_view.SUMMARY_CAPTION,
                "compared": table(compared, digits=2),
                "one": one,
                "events": table(events, limit=500),
            }
        )

    @app.get("/api/research/history/event")
    def history_event(
        ticker: str, day: dt.date, strategy: str, period: str = "10y", stop: float | None = None,
        side: str = "long",
    ) -> dict:  # fmt: skip
        """An event's chart: 120 sessions up to it and 63 after, the hit marked, the stop."""
        bars = chart_view.bars(root(), ticker.upper(), period)
        if bars.empty or day < bars["session_date"].min():
            return {"candles": []}
        window = research_view.event_window(bars, day)
        hit = pd.DataFrame([{"session_date": day, "label_text": strategy, "side": side}])
        return chart_view.payload(
            window,
            lines=["MA10", "MA20", "MA50"],
            sessions=None,
            hits=hit,
            levels={"stop": stop} if stop else None,
        )

    @app.get("/api/research/entries")
    def entries(
        period: str = Query("10y", pattern="^(2y|10y)$"),
        min_trades: int = 200,
        exit: str | None = None,
        strategy: str | None = None,
        split: str = "none",
        strategies: str | None = None,
        exits: str | None = None,
    ) -> dict:
        """The minute study: 10 years (best per strategy and a by-year table) or 2 years (every
        entry and stop with any exit, per split)."""
        if period == "10y":
            found = research_view.entries_10y(root())
            if found is None:
                return {"published": False}
            overall, by_year = found
            names = sorted(overall["strategy"].unique())
            exit_names = research_view.exits_of(overall)
            ex = exit if exit in exit_names else exit_names[0]
            one = strategy if strategy in names else names[0]
            return scalar(
                {
                    "published": True,
                    "best": table(research_view.best(overall, min_trades), digits=2),
                    "exits": exit_names,
                    "exit": ex,
                    "strategies": names,
                    "strategy": one,
                    "by_year": table(research_view.by_year_table(by_year, one, ex), digits=2),
                }
            )
        splits = research_view.entries_2y_splits(root())
        if not splits:
            return {"published": False}
        group = split if split in splits else "none"
        full = research_view.entries_2y(root(), group)
        names = sorted(full["strategy"].unique())
        picked = names if strategies is None else [s for s in strategies.split(",") if s in names]
        part = full[full["strategy"].isin(picked)]
        exit_names = research_view.exits_of(full)
        shown = (
            [e for e in research_view.DEFAULT_EXITS if e in exit_names]
            if exits is None
            else [e for e in exits.split(",") if e in exit_names]
        )
        return scalar(
            {
                "published": True,
                "caption": research_view.ENTRIES_CAPTION,
                "splits": splits,
                "split": group,
                "strategies": names,
                "picked": picked,
                "exits": exit_names,
                "shown": shown,
                "best": table(research_view.best(part, min_trades), digits=2)
                if group == "none"
                else None,
                "table": table(
                    research_view.entries_table(part, group, shown, min_trades), digits=2
                ),
            }
        )

    @app.get("/api/research/entries/trades/{strategy}")
    def entry_trades(strategy: str) -> dict:
        if not re.fullmatch(r"[a-z0-9_]+", strategy):
            raise HTTPException(400, "Not a strategy name.")
        return table(research_view.strategy_trades(root(), strategy))

    @app.get("/api/research/regime")
    def regime(
        source: str = Query("minute", pattern="^(minute|daily)$"),
        strategy: str | None = None,
        exit: str | None = None,
        entry: str | None = None,
        stop: str | None = None,
    ) -> dict:
        folder = research_view.regime(root())
        if folder is None:
            return {"published": False}
        v = research_view.regime_view(folder, source, strategy, exit, entry, stop)
        return scalar({
            "published": True,
            "caption": research_view.REGIME_CAPTION,
            "mix": table(research_view.light_mix(folder)),
            **{k: v[k] for k in ("strategies", "strategy", "exits", "exit", "entries", "entry",
                                 "stops", "stop")},
            "filters": table(v["filters"]),
            "by_year": table(v["by_year"]),
        })  # fmt: skip

    # --- Live results

    @app.get("/api/live/grades")
    def live_grades() -> dict:
        found = research_view.live_grades(root(), lambda t: chart_view.bars(root(), t, "2y"))
        return {
            "compare": table(found["compare"]) if found["compare"] is not None else None,
            "gaps": table(found["gaps"]) if found["gaps"] is not None else None,
            "signals": table(found["signals"]) if found["signals"] is not None else None,
            "monthly": found["monthly"],
            "caption": research_view.LIVE_CAPTION.format(n=live_tracking.MIN_TRADES),
        }

    @app.get("/api/live/stats")
    def live_stats(minimum: int | None = None) -> dict:
        n = minimum if minimum is not None else int(cfg().stats["min_signals"])
        found, total = research_view.outcome_stats(root(), n)
        return {"minimum": n, "total": total, "table": table(found)}

    @app.get("/api/live/graded")
    def live_graded() -> dict:
        return table(research_view.graded_signals(root()))

    # --- System health

    @app.get("/api/system/jobs")
    def jobs() -> dict:
        now = dt.datetime.now(dt.UTC)
        extra = {}
        try:
            found = remote_data.names(remote_data.repo_of(root()), "bars-2y", "bars_2y_*.parquet")
            if found:
                extra["Daily bars (Massive)"] = dt.date.fromisoformat(found[-1].split("_")[2])
        except Exception:  # noqa: BLE001 - offline: the local datasets only
            pass
        return {
            "grid": table(health.run_grid(root(), cfg().schedule, now, 15)),
            "freshness": table(health.freshness(root(), cfg().schedule, now, extra)),
            "failures": table(health.errors(root())),
            "cache": {
                "used_gb": round(remote_data.size() / 1024**3, 2),
                "limit_gb": round(remote_data.LIMIT_BYTES / 1024**3),
            },
        }

    @app.post("/api/system/cache/clear")
    def cache_clear() -> dict:
        remote_data.clear()
        return {"message": "Emptied. Pages fetch what they need again."}

    @app.get("/api/system/github")
    def github() -> dict:
        """Did each timed job start on time, and the latest runs (the gh CLI on the server)."""
        runs = health.run_list()
        if runs.empty:
            return {"answered": False}
        now = dt.datetime.now(dt.UTC)
        return {
            "answered": True,
            "timer": table(timer.check(runs, cfg().schedule.windows_et, now)),
            "runs": table(health.github_runs(runs)),
        }

    def validation_result(v: ValidationIn):
        if v.scan not in VALIDATION_SCANS:
            raise HTTPException(400, f"Scan is one of {VALIDATION_SCANS}.")
        run = find_run(v.run)
        if not run.universe.exists():
            raise HTTPException(400, "That run has no universe snapshot.")
        try:
            screen = validation.read_screen(io.StringIO(v.csv_text))
        except Exception as exc:  # noqa: BLE001 - a bad file is the user's to fix
            raise HTTPException(
                400, f"Not a TradingView CSV export ({type(exc).__name__})."
            ) from exc
        result = validation.compare(
            ctx.table(run.candidates), ctx.table(run.universe), screen, cfg().scans[v.scan]
        )
        return run, result

    @app.get("/api/system/validation/runs")
    def validation_runs() -> dict:
        found = [r for r in ctx.runs(manual=True) if r.universe.exists()]
        return {
            "runs": [{"id": run_id(r), "label": r.label} for r in found],
            "scans": [{"id": s, "label": research_view.report.SCAN_LABELS.get(s, s)}
                      for s in VALIDATION_SCANS],
        }  # fmt: skip

    @app.post("/api/system/validation")
    def validation_compare(v: ValidationIn) -> dict:
        _, result = validation_result(v)
        return table(result)

    @app.post("/api/system/validation/append")
    def validation_append(v: ValidationIn) -> dict:
        """Append the comparison to docs/validation.md in the data repo."""
        run, result = validation_result(v)
        text = validation.to_markdown(result, f"{v.scan} vs TradingView · {run.label}")
        target = root() / "docs" / "validation.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
        return {"message": "Appended. Save & push sends it to GitHub."}

    # --- Scans

    @app.get("/api/scans")
    def scans() -> dict:
        names = [{"key": n, "label": scans_view.label(cfg(), n)} for n in cfg().scans]
        writable, checkout = scans_view.editable(config_path)
        return {
            "caption": scans_view.CAPTION,
            "rows": scans_view.table(cfg()),
            "names": names,
            "writable": writable,
            "checkout": checkout,
            "note": None
            if writable and checkout
            else scans_view.NOT_WRITABLE
            if not writable
            else scans_view.NOT_A_CHECKOUT,
        }

    def scan_of(name: str):
        if name not in cfg().scans:
            raise HTTPException(404, "No such scan.")
        return name

    @app.get("/api/scans/{name}/form")
    def scan_form(name: str) -> dict:
        return scans_view.form(cfg(), scan_of(name)) | {"push_slots": scans_view.PUSH_SLOTS}

    @app.post("/api/scans/{name}")
    def scan_save(name: str, edit: ScanEdit) -> dict:
        """Check and save: only what changed, validated like the jobs validate config."""
        changes = scans_view.changes(cfg(), scan_of(name), edit.values)
        if not changes:
            return {"saved": False, "message": "Nothing changed.", "diff": ""}
        if not scans_view.editable(config_path)[0]:
            raise HTTPException(409, scans_view.NOT_WRITABLE)
        try:
            shown = scan_editor.save(name, changes, config_path)
        except ConfigError as exc:
            raise HTTPException(400, f"Not saved: {exc}") from exc
        except OSError as exc:
            raise HTTPException(409, f"{scans_view.NOT_WRITABLE} ({type(exc).__name__})") from exc
        return {
            "saved": True,
            "message": f"Saved {scans_view.label(cfg(), name)} to config/scans.yaml where the "
            "dashboard runs. GitHub's jobs use it after Commit & push.",
            "diff": shown,
        }

    @app.post("/api/scans/{name}/commit")
    def scan_commit(name: str) -> dict:
        scan_of(name)
        if not scans_view.editable(config_path)[1]:
            return {"ok": False, "message": scans_view.NOT_A_CHECKOUT}
        ok, out = scan_editor.commit_and_push(name, config_path)
        return {"ok": ok, "message": out}

    # --- Pull latest / Save & push (the data repo)

    @app.post("/api/sync/pull")
    def pull() -> dict:
        ok, out = dashboard.pull(root())
        return {"ok": ok, "message": out or "up to date"}

    @app.post("/api/sync/push")
    def push() -> dict:
        ok, out = dashboard.save_and_push(root())
        return {"ok": ok, "message": out or "saved"}
