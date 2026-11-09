"""Live tracking (Emil, 21 Oct 2026): are the grades doing live what the grading study said,
and are Emil's own trades doing what the plan would have? Facts, not advice.

- Plan results: every live A+ / A / B signal played out by its study plan on daily bars: bought
  at the plan's entry price (`grade_entry`, else `plan_entry`), out at the stop, or at the
  close `grade_hold_sessions` sessions after the entry session. The stop is checked from the
  session after the entry (daily bars can't tell whether the entry day's low came before or
  after the fill, the trade review's convention); a session that opens below the stop exits
  at its open. Net R subtracts the trade's cost in R (`grade_cost_r`, else the study's median
  for that entry time).
- A setup on its own plan plays out the study's way (Emil, 4 Nov 2026). MA-surf
  (`pivot_1000`) is a buy-stop at the pivot the session after the signal: a session whose
  high stays under the pivot leaves it "not filled", no trade, as in the study; one that
  opens over it is bought at the open (daily bars have no 10:00 price). `trail_ma20` exits
  at the stop or at the first close under the 20-day MA, `TRAIL_SESSIONS` at the longest.
- Compare: per strategy, entry time and grade, the closed live trades against the history
  each signal carried (`grade_stat_mean_r`, `grade_stat_win_pct`). "Below the study" needs
  enough trades and both the mean R and the win rate clearly under the study's.
- Execution: Emil's closed journal trades matched to the signal they came from (same ticker,
  bought within two sessions of the plan's entry session), his R next to the plan's.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

LIVE_GRADES = ("A++", "A+", "A", "B")  # B: the EP9M AVWAP re-entry (26 Oct 2026)
# The grading study's median cost in R per entry time (validated_trades_v3, quality plans).
STUDY_COST_R = {
    "t_1030": 0.10,
    "ah_1645": 0.13,
    "t_1015": 0.08,
    "t_1200": 0.08,
    "next_1030": 0.06,
    "close": 0.10,
}
ORDER_ENTRIES = ("pivot_1000",)  # a buy-stop at the pivot the session after the signal
NEXT_DAY_ENTRIES = ("next_1030", "next_open", *ORDER_ENTRIES)
TRAIL_SESSIONS = 126  # the grading study's longest exit (config intraday_study.exit_sessions)
MA_SESSIONS = 20  # the trail's average; bars must reach this far before the first signal
MIN_TRADES = 20


def exit_rules(grading: Mapping) -> dict[str, str]:
    """Each graded strategy's exit (config `grading:` quality and scorecards): `trail_ma20`
    for MA-surf, the holding period for the rest."""
    out: dict[str, str] = {}
    for part in ("strategies", "quality"):
        for name, rule in (grading.get(part) or {}).items():
            out[name] = rule.get("exit", "hold")
    return out


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


def play_out(entry: float, stop: float, hold: int, path: pd.DataFrame, trail: bool = False) -> dict:
    """`path`: the sessions after the entry session (open, low, close; `ma20` to trail),
    oldest first. Returns status (closed / open), the exit price and how many sessions it
    took. `trail`: also out at the first close under the 20-day MA."""
    if not (entry > 0) or not (stop < entry):
        return {"status": "invalid", "exit": math.nan, "sessions": 0}
    for k, (_, bar) in enumerate(path.iterrows(), start=1):
        if k > hold:
            break
        if bar["open"] <= stop:
            return {"status": "closed", "exit": float(bar["open"]), "sessions": k}
        if bar["low"] <= stop:
            return {"status": "closed", "exit": float(stop), "sessions": k}
        if trail and bar["close"] < bar["ma20"]:  # a NaN average never exits
            return {"status": "closed", "exit": float(bar["close"]), "sessions": k}
        if k == hold:
            return {"status": "closed", "exit": float(bar["close"]), "sessions": k}
    last = float(path["close"].iloc[-1]) if len(path) else math.nan
    return {"status": "open", "exit": last, "sessions": min(len(path), hold)}


def plan_results(
    signals: pd.DataFrame, bars: pd.DataFrame, exits: Mapping[str, str] | None = None
) -> pd.DataFrame:
    """One row per live A+ / A / B signal: its plan's result so far. `bars`: ticker, session_date,
    open, high, low, close (daily), from `MA_SESSIONS` before the first signal for the trail.
    `exits`: each strategy's exit (`exit_rules`); without one a plan holds its sessions."""
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
    by_ticker = {}
    for t, g in bars.groupby("ticker"):
        g = g.sort_values("session_date").set_index("session_date")
        by_ticker[t] = g.assign(ma20=g["close"].rolling(MA_SESSIONS).mean())
    exits = exits or {}
    rows = []
    for rec in live.to_dict("records"):
        rule = str(rec.get("grade_entry_rule") or "")
        rule = "" if rule == "nan" else rule
        entry = _num(rec.get("grade_entry"))
        if math.isnan(entry):
            entry = _num(rec.get("plan_entry"))
        stop = _num(rec.get("grade_stop"))
        trail = exits.get(rec.get("grade_strategy")) == "trail_ma20"
        hold_raw = _num(rec.get("grade_hold_sessions"))
        hold = TRAIL_SESSIONS if trail else 21 if math.isnan(hold_raw) else int(hold_raw)
        day = pd.Timestamp(rec["session_date"]).date()
        start = entry_session(day, rule, sessions)
        g = by_ticker.get(rec["ticker"])
        order = rule in ORDER_ENTRIES
        high = _num(g.loc[start].get("high")) if order and g is not None and start in g.index else 0
        if start is None or g is None or math.isnan(high) or (order and start not in g.index):
            out = {"status": "waiting", "exit": math.nan, "sessions": 0}
        elif order and high < entry:
            out = {"status": "not filled", "exit": math.nan, "sessions": 0}
        else:
            if order:  # opened over the pivot: bought at the open
                entry = max(entry, _num(g.loc[start, "open"]))
            out = play_out(entry, stop, hold, g[g.index > start], trail)
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
        "not_filled",
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
                "not_filled": int((part["status"] == "not filled").sum()),
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


# The A+ basket, tracked on paper next to the plans (Emil, 6 Nov 2026: "Yes"; data repo
# docs/research/2026-11-05-hold-longer-and-basket.md). Every EP / EP9M A+ and Luk flush A gets
# the same share of the account, no price stop. Each session after the entry, in this order:
# - at the close of session 10, 21 or 42, sold if that close is under the entry price;
# - sold at the first close under the entry session's low (CUT, Emil 6 Nov 2026: "Switch");
# - at session 21, a close 19 %+ over the entry lets it run (RUN): from then on it is only sold
#   at the close of session 63, 84 or 105 when that close is under the session-21 close, else at
#   session 126.
# Otherwise out at the close of session 63. Not confirmed on 2010-15: a paper plan, never a buy.
BASKET_STRATEGIES = {
    "ep": ("A++", "A+"),
    "ep9m": ("A+",),
    "luk_avwap_flush": ("A", "A+"),
}  # Luk A+: A under the 40-week MA
BASKET_REVIEWS = (10, 21, 42)
BASKET_HOLD = 63
BASKET_RUN_GAIN, BASKET_RUN_AT, BASKET_RUN_CHECKS, BASKET_RUN_HOLD = 0.19, 21, (63, 84, 105), 126
BASKET_SIZE_PCT = 5.0
BASKET_EXTRA_COST_PCT = 0.10  # the later exit, as in the study
# Study, 2022-26 (1,076 trades, net of costs, these rules): mean +8.1 %, win rate 27.7 %
BASKET_STUDY_MEAN_PCT, BASKET_STUDY_WIN_PCT = 8.1, 27.7


def basket_exit(entry: float, path: pd.DataFrame, entry_low: float = math.nan) -> dict:
    """`path`: closes of the sessions after the entry session, oldest first; `entry_low`: the
    entry session's low (no CUT when unknown)."""
    closes = path["close"].to_numpy(dtype=float)

    def closed(k: int) -> dict:
        return {"status": "closed", "exit": float(closes[k - 1]), "sessions": k}

    for k in range(1, min(len(closes), BASKET_HOLD) + 1):
        c = closes[k - 1]
        if k in BASKET_REVIEWS and c < entry:
            return closed(k)
        if c < entry_low:
            return closed(k)
        if k == BASKET_RUN_AT and c >= entry * (1 + BASKET_RUN_GAIN):
            for m in BASKET_RUN_CHECKS:
                if len(closes) < m:
                    break
                if closes[m - 1] < c:
                    return closed(m)
            if len(closes) >= BASKET_RUN_HOLD:
                return closed(BASKET_RUN_HOLD)
            return {"status": "open", "exit": float(closes[-1]), "sessions": len(closes)}
    if len(closes) >= BASKET_HOLD:
        return closed(BASKET_HOLD)
    last = float(closes[-1]) if len(closes) else math.nan
    return {"status": "open", "exit": last, "sessions": len(closes)}


def basket_signals(signals: pd.DataFrame) -> pd.DataFrame:
    """The live A+ / A / B signals plus the A+ / A that the short-interest rule turned into C
    (`grade_before_si`), back at their own grade. The paper basket takes them (Emil, 6 Nov 2026):
    in the basket the heavily shorted ones did better than skipping them, 45.8 / 45.4 % a year
    against 37.7 / 35.2 % (2022-26 / 2016-21), while the 1-ADR plans keep them as C."""
    if signals.empty or "grade" not in signals:
        return signals.iloc[0:0]
    live = signals[signals["grade"].isin(LIVE_GRADES)]
    if "grade_before_si" not in signals:
        return live
    back = signals[(signals["grade"] == "C") & signals["grade_before_si"].isin(["A++", "A+", "A"])]
    return pd.concat([live, back.assign(grade=back["grade_before_si"])], ignore_index=True)


def basket_results(results: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """The basket's paper trades from `plan_results` rows: the first qualifying signal per stock
    while it is held (a later one on a held stock is skipped), net % of the money put in."""
    cols = ["session_date", "ticker", "grade_strategy", "entry", "status", "sessions", "net_pct"]
    if results.empty:
        return pd.DataFrame(columns=cols)
    want = results["grade_strategy"].map(BASKET_STRATEGIES)
    match = [
        g in w if isinstance(w, tuple) else False
        for g, w in zip(results["grade"], want, strict=True)
    ]
    picked = results[pd.Series(match, index=results.index) & results["entry"].gt(0)]
    picked = picked[picked["status"].isin(["closed", "open"])]
    bars = bars.copy()
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    by_ticker = {t: g.sort_values("session_date") for t, g in bars.groupby("ticker")}
    rows, held_until = [], {}
    for rec in picked.sort_values(["session_date", "ticker"]).to_dict("records"):
        g = by_ticker.get(rec["ticker"])
        if g is None:
            continue
        rule = str(rec.get("entry_rule") or "")
        start = entry_session(rec["session_date"], rule, list(g["session_date"]))
        if start is None or held_until.get(rec["ticker"], start) > start:
            continue
        day = g[g["session_date"] == start]
        low = float(day["low"].iloc[0]) if "low" in day and len(day) else math.nan
        out = basket_exit(rec["entry"], g[g["session_date"] > start], low)
        risk_pct = (
            (rec["entry"] - rec["stop"]) / rec["entry"] * 100 if rec["stop"] == rec["stop"] else 0
        )
        cost_r = rec["r_gross"] - rec["r_net"] if rec["r_gross"] == rec["r_gross"] else 0.1
        cost = cost_r * risk_pct + BASKET_EXTRA_COST_PCT
        net = (
            (out["exit"] / rec["entry"] - 1) * 100 - cost
            if out["exit"] == out["exit"]
            else math.nan
        )
        ahead = g[g["session_date"] > start]["session_date"].tolist()
        if out["status"] == "open":  # still held: every later signal on it is skipped
            held_until[rec["ticker"]] = dt.date.max
        else:
            held_until[rec["ticker"]] = ahead[out["sessions"] - 1]
        rows.append(
            {
                "session_date": rec["session_date"],
                "ticker": rec["ticker"],
                "grade_strategy": rec["grade_strategy"],
                "entry": rec["entry"],
                "status": out["status"],
                "sessions": out["sessions"],
                "net_pct": net,
            }
        )
    return pd.DataFrame(rows, columns=cols)


def basket_summary(basket: pd.DataFrame, results: pd.DataFrame) -> dict:
    """Closed basket trades against the study, and both plans in % of the account on the same
    signals: the basket at `BASKET_SIZE_PCT` a stock, today's plans at 1 % (A+) / 0.75 % (A) risk
    per trade (closed trades only, before any position cap)."""
    done = basket[basket["status"] == "closed"]["net_pct"].dropna()
    plans = results[(results["status"] == "closed") & results["grade"].isin(["A++", "A+", "A"])]
    risk = plans["grade"].map({"A++": 1.0, "A+": 1.0, "A": 0.75})
    luk_plus = (plans["grade"] == "A+") & (plans.get("grade_strategy") == "luk_avwap_flush")
    risk = risk.where(~luk_plus, 1.5)  # Luk flush A+ = A under its 40-week MA at 2x (9 Nov 2026)
    return {
        "closed": len(done),
        "open": int((basket["status"] == "open").sum()),
        "mean_pct": done.mean() if len(done) else math.nan,
        "win_pct": (done > 0).mean() * 100 if len(done) else math.nan,
        "account_pct": done.sum() * BASKET_SIZE_PCT / 100,
        "plans_account_pct": float((plans["r_net"] * risk).sum()),
        "verdict": verdict(done, BASKET_STUDY_MEAN_PCT, BASKET_STUDY_WIN_PCT),
    }
