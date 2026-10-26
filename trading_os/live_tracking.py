"""Live tracking (Emil, 21 Oct 2026): are the grades doing live what the grading study said,
and are Emil's own trades doing what the plan would have? Facts, not advice.

- Plan results: every live A+ / A / B signal played out by its study plan on daily bars: bought
  at the plan's entry price (`grade_entry`, else `plan_entry`), out at the stop, or at the
  close `grade_hold_sessions` sessions after the entry session. The stop is checked from the
  session after the entry (daily bars can't tell whether the entry day's low came before or
  after the fill, the trade review's convention); a session that opens below the stop exits
  at its open. Net R subtracts the trade's cost in R (`grade_cost_r`, else the study's median
  for that entry time).
- Compare: per strategy, entry time and grade, the closed live trades against the history
  each signal carried (`grade_stat_mean_r`, `grade_stat_win_pct`). "Below the study" needs
  enough trades and both the mean R and the win rate clearly under the study's.
- Execution: Emil's closed journal trades matched to the signal they came from (same ticker,
  bought within two sessions of the plan's entry session), his R next to the plan's.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

LIVE_GRADES = ("A+", "A", "B")  # B: the EP9M AVWAP re-entry (26 Oct 2026)
# The grading study's median cost in R per entry time (validated_trades_v3, quality plans).
STUDY_COST_R = {
    "t_1030": 0.10,
    "ah_1645": 0.13,
    "t_1015": 0.08,
    "t_1200": 0.08,
    "next_1030": 0.06,
    "close": 0.10,
}
NEXT_DAY_ENTRIES = ("next_1030", "next_open")
MIN_TRADES = 20


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v


def entry_session(signal_day, entry_rule: str, sessions: list) -> object | None:
    """The session the plan buys in: the signal's own, or the next one for next-day plans
    (after-hours buys happen the evening of the signal session)."""
    if signal_day not in sessions:
        later = [s for s in sessions if s > signal_day]
        return later[0] if later and entry_rule in NEXT_DAY_ENTRIES else None
    i = sessions.index(signal_day)
    if entry_rule in NEXT_DAY_ENTRIES:
        return sessions[i + 1] if i + 1 < len(sessions) else None
    return signal_day


def play_out(entry: float, stop: float, hold: int, path: pd.DataFrame) -> dict:
    """`path`: the sessions after the entry session (open, low, close), oldest first. Returns
    status (closed / open), the exit price and how many sessions it took."""
    if not (entry > 0) or not (stop < entry):
        return {"status": "invalid", "exit": math.nan, "sessions": 0}
    for k, (_, bar) in enumerate(path.iterrows(), start=1):
        if k > hold:
            break
        if bar["open"] <= stop:
            return {"status": "closed", "exit": float(bar["open"]), "sessions": k}
        if bar["low"] <= stop:
            return {"status": "closed", "exit": float(stop), "sessions": k}
        if k == hold:
            return {"status": "closed", "exit": float(bar["close"]), "sessions": k}
    last = float(path["close"].iloc[-1]) if len(path) else math.nan
    return {"status": "open", "exit": last, "sessions": min(len(path), hold)}


def plan_results(signals: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """One row per live A+ / A / B signal: its plan's result so far. `bars`: ticker, session_date,
    open, low, close (daily)."""
    cols = [
        "signal_id",
        "session_date",
        "scan",
        "ticker",
        "grade",
        "grade_strategy",
        "entry_rule",
        "entry",
        "stop",
        "status",
        "exit",
        "sessions",
        "r_gross",
        "r_net",
        "study_mean_r",
        "study_win_pct",
        "ibd_state",
    ]
    if signals.empty or "grade" not in signals:
        return pd.DataFrame(columns=cols)
    live = signals[signals["grade"].isin(LIVE_GRADES)].drop_duplicates("signal_id")
    if live.empty:
        return pd.DataFrame(columns=cols)
    bars = bars.copy()
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    sessions = sorted(bars["session_date"].unique())
    by_ticker = {
        t: g.sort_values("session_date").set_index("session_date")
        for t, g in bars.groupby("ticker")
    }
    rows = []
    for rec in live.to_dict("records"):
        rule = str(rec.get("grade_entry_rule") or "")
        entry = _num(rec.get("grade_entry"))
        if math.isnan(entry):
            entry = _num(rec.get("plan_entry"))
        stop = _num(rec.get("grade_stop"))
        hold_raw = _num(rec.get("grade_hold_sessions"))
        hold = 21 if math.isnan(hold_raw) else int(hold_raw)
        day = pd.Timestamp(rec["session_date"]).date()
        start = entry_session(day, rule, sessions)
        g = by_ticker.get(rec["ticker"])
        if start is None or g is None:
            out = {"status": "waiting", "exit": math.nan, "sessions": 0}
        else:
            out = play_out(entry, stop, hold, g[g.index > start])
        risk = entry - stop
        r = (out["exit"] - entry) / risk if risk > 0 and not math.isnan(out["exit"]) else math.nan
        cost = _num(rec.get("grade_cost_r"))
        cost = STUDY_COST_R.get(rule, 0.1) if math.isnan(cost) else cost
        rows.append(
            {
                "signal_id": rec["signal_id"],
                "session_date": day,
                "scan": rec.get("scan"),
                "ticker": rec["ticker"],
                "grade": rec["grade"],
                "grade_strategy": rec.get("grade_strategy"),
                "entry_rule": rule,
                "entry": entry,
                "stop": stop,
                "status": out["status"],
                "exit": out["exit"],
                "sessions": out["sessions"],
                "r_gross": r,
                "r_net": r - cost if r == r else r,
                "study_mean_r": _num(rec.get("grade_stat_mean_r")),
                "study_win_pct": _num(rec.get("grade_stat_win_pct")),
                "ibd_state": rec.get("ibd_state"),
            }
        )
    return pd.DataFrame(rows, columns=cols)


def by_market(results: pd.DataFrame) -> pd.DataFrame:
    """Closed live A+ / A / B trades per strategy and grade, split by the IBD market state at the
    signal (`ibd`; Emil, 25 Oct 2026: tracked, not a rule). Signals from before the state was
    stored count as "unknown"."""
    cols = ["grade_strategy", "grade", "ibd_state", "closed", "live_mean_r", "live_win_pct"]
    if results.empty:
        return pd.DataFrame(columns=cols)
    done = results[results["status"] == "closed"].copy()
    if done.empty:
        return pd.DataFrame(columns=cols)
    state = done["ibd_state"] if "ibd_state" in done else pd.Series(index=done.index, dtype=object)
    done["ibd_state"] = state.where(state.notna(), "unknown")
    rows = []
    keys = ["grade_strategy", "grade", "ibd_state"]
    for key, part in done.groupby(keys, dropna=False):
        r = part["r_net"].dropna()
        rows.append(
            dict(zip(keys, key, strict=True))
            | {
                "closed": len(part),
                "live_mean_r": r.mean() if len(r) else math.nan,
                "live_win_pct": (r > 0).mean() * 100 if len(r) else math.nan,
            }
        )
    return pd.DataFrame(rows, columns=cols)


def verdict(r: pd.Series, study_mean: float, study_win: float, min_trades: int = MIN_TRADES) -> str:
    """'too few trades yet' / 'on track' / 'below the study' / 'above the study'."""
    r = r.dropna()
    n = len(r)
    if n < min_trades or math.isnan(study_mean):
        return "too few trades yet"
    se = r.std(ddof=1) / math.sqrt(n) if n > 1 else math.inf
    z_mean = (r.mean() - study_mean) / se if se > 0 else 0.0
    p = (study_win / 100) if not math.isnan(study_win) else math.nan
    z_win = ((r > 0).mean() - p) / math.sqrt(p * (1 - p) / n) if 0 < p < 1 else 0.0
    if z_mean < -2 and z_win < -1.5:
        return "below the study"
    if z_mean > 2:
        return "above the study"
    return "on track"


def compare(results: pd.DataFrame, min_trades: int = MIN_TRADES) -> pd.DataFrame:
    """Per strategy, entry time and grade: closed live trades against the study."""
    cols = [
        "grade_strategy",
        "entry_rule",
        "grade",
        "closed",
        "open",
        "live_mean_r",
        "live_win_pct",
        "study_mean_r",
        "study_win_pct",
        "verdict",
    ]
    if results.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    keys = ["grade_strategy", "entry_rule", "grade"]
    for key, part in results.groupby(keys, dropna=False):
        done = part[part["status"] == "closed"]
        r = done["r_net"]
        study_mean = part["study_mean_r"].mean()
        study_win = part["study_win_pct"].mean()
        rows.append(
            dict(zip(keys, key, strict=True))
            | {
                "closed": len(done),
                "open": int((part["status"] == "open").sum()),
                "live_mean_r": r.mean() if len(r) else math.nan,
                "live_win_pct": (r > 0).mean() * 100 if len(r) else math.nan,
                "study_mean_r": study_mean,
                "study_win_pct": study_win,
                "verdict": verdict(r, study_mean, study_win, min_trades),
            }
        )
    return pd.DataFrame(rows, columns=cols)


def execution(results: pd.DataFrame, trades: pd.DataFrame, sessions: Iterable) -> pd.DataFrame:
    """Your closed trades next to the plan result of the signal they came from: same ticker,
    bought within two sessions of the plan's entry session."""
    cols = [
        "ticker",
        "signal_session",
        "grade",
        "entry_rule",
        "plan_r",
        "your_r",
        "your_entry_date",
        "gap_r",
    ]
    if results.empty or trades is None or trades.empty:
        return pd.DataFrame(columns=cols)
    sessions = sorted(pd.Timestamp(s).date() for s in sessions)
    idx = {s: i for i, s in enumerate(sessions)}
    rows = []
    for t in trades.to_dict("records"):
        bought = pd.Timestamp(t["entry_date"]).date()
        cands = results[(results["ticker"] == t["ticker"]) & (results["status"] == "closed")]
        best = None
        for c in cands.to_dict("records"):
            s0 = c["session_date"]
            near = s0 in idx and bought in idx and 0 <= idx[bought] - idx[s0] <= 2
            if near and (best is None or s0 > best["session_date"]):
                best = c
        if best is None:
            continue
        your = _num(t.get("r_multiple"))
        rows.append(
            {
                "ticker": t["ticker"],
                "signal_session": best["session_date"],
                "grade": best["grade"],
                "entry_rule": best["entry_rule"],
                "plan_r": best["r_net"],
                "your_r": your,
                "your_entry_date": bought,
                "gap_r": your - best["r_net"],
            }
        )
    return pd.DataFrame(rows, columns=cols)


def push_lines(table: pd.DataFrame, labels: Mapping[str, str] | None = None) -> list[str]:
    """`EP9M 10:15 A+ · 12 closed +0.41R (study +0.56R) · on track` per row."""
    out = []
    for row in table.to_dict("records"):
        name = (labels or {}).get(row["grade_strategy"], row["grade_strategy"])
        live = "" if np.isnan(row["live_mean_r"]) else f" {row['live_mean_r']:+.2f}R"
        study = "" if np.isnan(row["study_mean_r"]) else f" (study {row['study_mean_r']:+.2f}R)"
        out.append(
            f"{name} {row['entry_rule']} {row['grade']} · {row['closed']} closed{live}"
            f"{study} · {row['verdict']}"
        )
    return out
