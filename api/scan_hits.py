"""The Screener's "Scan hits" page (UX round 3, 18 Nov 2026): every hit of one run of today, or of
all of them, one row per stock and scan, best study grade first. Read-only: the rows are the run
files' own hits with the newest snapshot's sector and exchange; nothing is graded or computed
here beyond the plan's price lines the cards already draw.
"""

from __future__ import annotations

import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from api import today_runs
from api.pages import Context
from api.serialize import scalar
from trading_os import board_data, notify

LIMIT = 3000
RANK = {g: i for i, g in enumerate(("A+++", "A++", "A+", "A", "B", "C"))}
KEEP = (
    "ticker", "scan", "grade", "grade_score", "tier", "close", "chg_pct", "rvol50", "adr20_pct",
    "rs_pct", "pct_from_52w_high", "ret_22", "ret_63", "dist_ma10_adr", "above_ma50", "above_ma200",
    "market_cap", "vol_build", "earnings_in_sessions", "plan_entry", "plan_stop", "plan_risk_usd",
    "pivot", "grade_why", "grade_stat_mean_r", "grade_stat_win_pct", "si_tag", "ibd_tag",
    "heat_tag", "industry_rank", "signal_id",
)  # fmt: skip
INFO = ("sector", "industry", "exchange")


def register(app: FastAPI, ctx: Context) -> None:
    def newest_universe() -> pd.DataFrame:
        run = next((r for r in ctx.runs() if r.universe.exists()), None)
        if run is None:
            return pd.DataFrame()
        want = ["ticker", *INFO]
        uni = ctx.table(run.universe)
        return uni[[c for c in want if c in uni]].drop_duplicates("ticker").set_index("ticker")

    @app.get("/api/scan-hits")
    def scan_hits(run: str = Query(today_runs.ALL)) -> dict:
        """Every scan's hits of one run of today (`run`: its id from `/api/today-runs`, or any
        scheduled run's id) or of all of today's runs, de-duplicated per stock and scan, each
        tagged with the run slots it came from."""
        found = ctx.runs()
        today = today_runs.todays_runs(found)
        if run == today_runs.ALL:
            picked, label = today, "All today"
        else:
            picked = [r for r in found if r.kind == "scheduled" and today_runs.run_key(r) == run]
            if not picked:
                raise HTTPException(404, "No such run.")
            label = picked[0].label
        parts = []
        for r in picked:
            for scan, hits in ctx.scan_frames(str(r.candidates)).items():
                parts.append(hits.assign(scan=scan, _slot=r.slot))
        if not parts:
            return {"run": run, "label": label, "count": 0, "scans": [], "rows": []}
        both = pd.concat(parts, ignore_index=True)
        if "grade" not in both:
            both["grade"] = None
        score = both["grade_score"] if "grade_score" in both else pd.Series(index=both.index)
        both["_g"] = both["grade"].map(RANK).fillna(9)
        both["_s"] = pd.to_numeric(score, errors="coerce").fillna(-1e9)
        seen = both.groupby(["ticker", "scan"], sort=False)["_slot"].agg(
            lambda s: list(dict.fromkeys(s))
        )
        both = both.sort_values(["_g", "_s"], ascending=[True, False], kind="stable")
        both = both.drop_duplicates(["ticker", "scan"], keep="first")
        info = newest_universe()
        for col in INFO:
            if col in info and col not in both:
                both[col] = both["ticker"].map(info[col])
        rows = []
        for rec in both.head(LIMIT).to_dict("records"):
            levels = board_data.levels(rec)
            out = {k: scalar(rec.get(k)) for k in (*KEEP, *INFO)}
            out["grade"] = out["grade"] or ""
            out["scan_label"] = notify.SCAN_LABELS.get(rec["scan"], rec["scan"])
            out["runs"] = seen[(rec["ticker"], rec["scan"])]
            out["levels"] = levels
            out["tv"] = board_data.tradingview_url(str(rec["ticker"]), out.get("exchange"))
            rows.append(out)
        counts = both.groupby("scan", sort=False).size()
        scans = [
            {"id": s, "label": notify.SCAN_LABELS.get(s, s), "count": int(n)}
            for s, n in counts.items()
        ]
        return {"run": run, "label": label, "count": len(both), "scans": scans, "rows": rows}
