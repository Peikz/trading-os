"""A second signal on a stock whose first plan is still open (Emil, 13 Nov 2026: "Ja, marker
push"). The study's account skipped a kept signal when it already held the stock. Buying it
too at half the grade's risk did better in both periods and beat a random top-up of a held
stock (the private data repo's docs/research/2026-11-13-capital-use.md). The test was not
blind and the recent period's gain is small, so this is a tag and a half-size plan: Emil
decides.

A first plan counts as open when it is

- a live A+ / A signal whose plan (`live_tracking.plan_results`) was still open at the last
  close; the close run saves those as `data/grading/open_plans.json`, or
- a graded signal with a same-day entry from a run after that close: last evening's
  after-hours run and this session's earlier intraday runs. The hit's own scan is left out
  there, so a repeat of the same signal is not a second one.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os import clock, store
from trading_os.live_tracking import NEXT_DAY_ENTRIES

STATE_FILE = Path("data") / "grading" / "open_plans.json"
SAME_DAY_SLOTS = ("am", "mid", "close")  # runs whose signals are bought in their own session
SLOT_ORDER = ("pm", "am", "mid", "close", "eod", "ah")


def open_plans(results: pd.DataFrame, grades: set[str]) -> dict[str, dict]:
    """{ticker: {since, scan}}: the newest still-open plan per stock in `plan_results`."""
    if results.empty or "status" not in results:
        return {}
    live = results[(results["status"] == "open") & results["grade"].isin(grades)]
    out: dict[str, dict] = {}
    for rec in live.sort_values("session_date").to_dict("records"):
        out[rec["ticker"]] = {"since": str(rec["session_date"]), "scan": rec.get("scan")}
    return out


def save(data_dir: Path, asof: dt.date, plans: Mapping[str, dict]) -> Path:
    path = Path(data_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"asof": asof.isoformat(), "plans": dict(sorted(plans.items()))}
    path.write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
    return path


def load(data_dir: Path, session: dt.date) -> dict | None:
    """The saved open plans if they are from before (or the close of) `session`, else None."""
    try:
        st = json.loads((Path(data_dir) / STATE_FILE).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    if dt.date.fromisoformat(st["asof"]) > session:
        return None
    return st


def update(data_dir: Path, today: dt.date, results: pd.DataFrame, grades: set[str]) -> int:
    """Save the plans open at `today`'s close; returns how many."""
    plans = open_plans(results, grades)
    save(data_dir, today, plans)
    return len(plans)


def _run_signals(data_dir: Path, session: dt.date, slot: str, grades: set[str]) -> list[dict]:
    """The graded same-day-entry signals the scheduled run of (session, slot) saved."""
    ctx = store.RunContext(session=session, slot=slot, run_ts=dt.datetime.now(dt.UTC), run_kind="")
    path = store.run_paths(data_dir, ctx)["candidates"]
    if not path.exists():
        return []
    cands = pd.read_parquet(path)
    if "grade" not in cands or "grade_entry_rule" not in cands:
        return []
    keep = cands[cands["grade"].isin(grades) & ~cands["grade_entry_rule"].isin(NEXT_DAY_ENTRIES)]
    return [
        {"ticker": t, "since": session.isoformat(), "scan": s}
        for t, s in zip(keep["ticker"], keep["scan"], strict=True)
    ]


def held(data_dir: Path, cfg, session: dt.date, slot: str) -> dict[str, list[dict]]:
    """{ticker: [{since, scan}, ...]}: the first plans open when the `slot` run of `session`
    grades its hits."""
    grades = set(cfg.grading["second_signal"]["grades"])
    out: dict[str, list[dict]] = {}
    st = load(data_dir, session)
    asof = dt.date.fromisoformat(st["asof"]) if st else None
    for ticker, plan in (st["plans"] if st else {}).items():
        out.setdefault(ticker, []).append(plan)
    later = []
    if asof is None or asof < session:  # last evening's after-hours run came after that close
        later += _run_signals(data_dir, clock.previous_session(cfg.schedule, session), "ah", grades)
    if slot in SLOT_ORDER:
        for earlier in SAME_DAY_SLOTS:
            if SLOT_ORDER.index(earlier) < SLOT_ORDER.index(slot):
                later += _run_signals(data_dir, session, earlier, grades)
    for sig in later:
        out.setdefault(sig["ticker"], []).append({"since": sig["since"], "scan": sig["scan"]})
    return out


def tag(first: Mapping[str, Any], mult: float, labels: Mapping[str, str]) -> str:
    """The push and card line for a second signal."""
    day = dt.date.fromisoformat(str(first["since"]))
    label = labels.get(first.get("scan"), first.get("scan") or "signal")
    size = "half size" if mult == 0.5 else f"x{mult:g} size"
    return f"➕ Second signal: {label} from {day:%d %b} still open · {size}"


def apply(
    hits: pd.DataFrame,
    scan: str,
    firsts: Mapping[str, list[dict]],
    conf: Mapping[str, Any],
    session: dt.date,
    labels: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """`second_tag`, `second_mult` and `grade_risk_mult` x `mult` on the `grades` hits whose
    stock has an open first plan. A first from this same session and scan is the same signal
    again, not a second one."""
    if hits.empty or "grade" not in hits or "grade_risk_mult" not in hits or not firsts:
        return hits
    mult, grades = float(conf["mult"]), set(conf["grades"])
    today = session.isoformat()
    tags, mults = [], []
    for rec in hits.to_dict("records"):
        mine = [
            f
            for f in firsts.get(rec["ticker"], [])
            if not (f.get("scan") == scan and str(f["since"]) == today)
        ]
        on = bool(mine) and rec.get("grade") in grades
        tags.append(tag(mine[-1], mult, labels or {}) if on else None)
        mults.append(mult if on else 1.0)
    if not any(tags):
        return hits
    out = hits.copy()
    out["second_tag"] = pd.Series(tags, index=out.index, dtype=object)
    out["second_mult"] = mults
    out["grade_risk_mult"] = pd.to_numeric(out["grade_risk_mult"]) * out["second_mult"]
    return out
