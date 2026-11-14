"""Pressing when it works (Emil, 5 Nov 2026: "Skrue op", the rule "mean of the last 20 > +1R
-> x2"; data repo docs/research/2026-11-05-qullamaggie-his-way.md). Qullamaggie sized up after
strong runs. In the 2016-26 study, doubling the risk on new A+ / A trades while the package's
last 20 closed trades averaged more than +1R raised the account from 18.1 to 20.9 %/yr
(2022-26) and 32.2 to 38.1 % (2016-21) with the same drawdown, and beat the same extra risk at
random times in both periods.

Live, the "package's closed trades" are the live A+ / A signals played out by their own plans
(`live_tracking.plan_results`, as in the monthly live check), taken or not. The close run
updates `data/grading/press_state.json` after it saves; every run reads the newest state from
before its own entries. Under `window` closed trades it stays off. Facts, not advice: the plan
sizes, Emil decides.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

STATE_FILE = Path("data") / "grading" / "press_state.json"


def state(results: pd.DataFrame, sessions: list, conf: Mapping[str, Any], asof: dt.date) -> dict:
    """{asof, closed, window, mean_r, active, mult}: the last `window` closed `grades` trades in
    exit order. `results`: `live_tracking.plan_results`; `sessions`: its bars' sessions."""
    from trading_os import live_tracking as lt

    window, grades = int(conf["window"]), set(conf["grades"])
    done = results[(results["status"] == "closed") & results["grade"].isin(grades)]
    pos = {s: i for i, s in enumerate(sessions)}
    exits = []
    for rec in done.to_dict("records"):
        start = lt.entry_session(rec["session_date"], str(rec.get("entry_rule") or ""), sessions)
        if start is None or start not in pos or math.isnan(rec["r_net"]):
            continue
        exits.append((pos[start] + int(rec["sessions"]), rec["r_net"]))
    exits.sort(key=lambda x: x[0])
    last = [r for _, r in exits[-window:]]
    mean_r = sum(last) / len(last) if last else None
    active = bool(conf["enabled"]) and len(last) == window and mean_r > float(conf["mean_r_above"])
    return {
        "asof": asof.isoformat(),
        "closed": len(exits),
        "window": window,
        "mean_r": None if mean_r is None else round(mean_r, 3),
        "active": active,
        "mult": float(conf["mult"]) if active else 1.0,
    }


def save(data_dir: Path, st: Mapping[str, Any]) -> Path:
    path = Path(data_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(st), indent=1) + "\n", encoding="utf-8")
    return path


def load(data_dir: Path, session: dt.date) -> dict | None:
    """The saved state if it is from before (or the close of) `session`, else None."""
    path = Path(data_dir) / STATE_FILE
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    if dt.date.fromisoformat(st["asof"]) > session:
        return None
    return st


def apply(
    hits: pd.DataFrame, st: Mapping[str, Any] | None, conf: Mapping[str, Any]
) -> pd.DataFrame:
    """`grade_risk_mult` x the press multiple on the `grades` hits, with `press_mult` stored."""
    if hits.empty or "grade" not in hits or "grade_risk_mult" not in hits:
        return hits
    on = (
        bool(conf.get("enabled", True)) and bool(st) and bool(st.get("active"))
    )  # off: no old state
    mult = float(st["mult"]) if on else 1.0
    out = hits.copy()
    on = out["grade"].isin(set(conf["grades"]))
    out["press_mult"] = pd.Series(1.0, index=out.index).where(~on, mult)
    out.loc[on, "grade_risk_mult"] = pd.to_numeric(out.loc[on, "grade_risk_mult"]) * mult
    return out


def line(st: Mapping[str, Any] | None) -> list[str]:
    """One push / report line while pressing is on."""
    if not st or not st.get("active"):
        return []
    return [
        f"🔥 Pressing: the last {st['window']} closed A+/A averaged {st['mean_r']:+.2f}R, "
        f"risk x{st['mult']:g} on A+/A today"
    ]


def live_results(
    data_dir: Path, cfg, today: dt.date, grades, lookback: int = 400
) -> tuple[pd.DataFrame, list]:
    """The scheduled live `grades` signals played out by their plans up to `today`, and the
    sessions their bars cover."""
    from trading_os import clock, history, outcomes
    from trading_os import live_tracking as lt

    cands = outcomes.load_candidates(data_dir)
    live = cands[cands["grade"].isin(set(grades))] if "grade" in cands else cands.iloc[0:0]
    if "run_kind" in live:
        live = live[live["run_kind"] == "scheduled"]
    if live.empty:
        return pd.DataFrame(columns=["status", "grade"]), []
    back = clock.sessions_back(cfg.schedule, today, lookback)
    first = next((i for i, s in enumerate(back) if s >= min(live["session_date"])), len(back))
    sessions = back[max(0, first - lt.MA_SESSIONS) :]
    bars = history.load_bars(data_dir, sessions)
    bars = bars[bars["ticker"].isin(set(live["ticker"]))]
    res = lt.plan_results(live, bars, lt.exit_rules(cfg.grading))
    have = sorted(pd.to_datetime(bars["session_date"]).dt.date.unique()) if len(bars) else []
    return res, have


def update(data_dir: Path, cfg, today: dt.date, lookback: int = 400, results=None) -> dict:
    """Play out the live A+ / A signals and save the state as of `today`'s close. `results`:
    `live_results` when the caller already has them."""
    conf = cfg.grading["press"]
    res, have = results or live_results(data_dir, cfg, today, conf["grades"], lookback)
    st = state(res, have, conf, today)
    save(data_dir, st)
    return st
