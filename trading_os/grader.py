"""Study grades (Emil, 20 Oct 2026; SPEC §1.4): A+/A/B/C for a setup from the 10-year grading
study of his own scan rules. Deterministic: the same features give the same grade, no AI.

A grade is a historical fact, not advice: how setups like this one did, net of costs, when
the rules were fitted on earlier years only (data repo docs/research/). The trade decision
and the journal grade stay Emil's.

    predicted net R = base + the points of the setup's feature buckets - its cost in R
    grade           = the first band of the strategy whose floor the prediction reaches, else C

Rules live in config `grading:` (all proposed until Emil confirms them):

- `features`: per feature, either `edges` (a value at or above an edge moves up one bucket,
  `points` has one more value than `edges`; `na` for a missing value) or category `points`
  (`"1"`/`"0"` for yes/no features);
- feature names: `d_*` are daily facts at the last close before the entry (`d_rvol`: that
  day's volume over its 50-day average; `d_tight5_adr`: the 5-day high-low range in ADR;
  `d_vol_dry`: 10-day over 50-day average volume; `d_dist_ma10_adr`: close minus the 10-day
  MA in ADR; `d_ret_5` / `d_ret_63`: % return over 5 / 63 sessions; `d_ma50_slope`: % change
  of the 50-day MA over 5 sessions; `d_ma_stack`: MA10 > MA20 > MA50; `d_surf20`: share of
  the last 40 closes at or above the 20-day MA); `mkt_*` are the market regime of that
  session (Market Light, breadth state, the Sunday scan count, SPY over its 200-day MA,
  QQQ over its 50-day MA); `sig_base_days`: the AVWAP flush's base length;
  `revenue_growth_accel`: revenue growth change in % points vs the quarter before (SEC);
- `costs`: Saxo's commission and the slippage model; cost in R = cost % / stop distance %.

Quality counts (variable search, 21 Oct 2026; on with `quality_enabled`): a strategy listed
under `quality` is graded by how many of its yes/no `conditions` hold (equal weights, nothing
fitted), e.g. EP: an earnings release, 1-2 months sideways, a market that isn't hot, revenue
growth accelerating, EPS up, near the 52-week high; `grades` maps points to A+/A/B. A missing
value counts as a no. Its plan (entry per live scan, stop, hold) comes with it.

Scans without a scorecard grade C with `ungraded` as the reason.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

GRADES = ("A+", "A", "B", "C")
OPEN_ENTRIES = {"open", "orh_5m", "next_open", "next_orb_5m"}
OFFHOURS_ENTRIES = {"ah_1645", "ah_1800", "pm_0705", "pm_0800", "pm_0915"}


@dataclass(frozen=True)
class Grade:
    scan: str
    strategy: str | None  # the study strategy whose rules graded it (None = ungraded)
    grade: str
    score: float | None  # predicted net R
    cost_r: float | None
    reasons: tuple = ()  # (feature, value, points), largest effect first
    plan: Mapping[str, Any] = field(default_factory=dict)
    risk_mult: float = 0.0
    note: str = ""


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _category(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return "1" if value == 1 else "0" if value == 0 else str(value)
    return str(value)


def feature_points(spec: Mapping[str, Any], value) -> float:
    """Points of one feature value (0 when its bucket or category has none)."""
    if _missing(value):
        return float(spec.get("na", 0.0))
    edges = spec.get("edges")
    if edges is not None:
        bucket = sum(1 for e in edges if float(value) >= float(e))
        return float(spec["points"][bucket])
    return float(spec["points"].get(_category(value), 0.0))


def slippage_pct(dvol20, price, costs: Mapping[str, Any]) -> float:
    """Per-side slippage in % from the 20-day average dollar volume, at least one tick."""
    dvol = 0.0 if _missing(dvol20) else float(dvol20)
    pct = costs["slip_by_dvol"][-1][1]
    for floor, value in costs["slip_by_dvol"]:
        if dvol >= floor:
            pct = value
            break
    tick = costs["min_tick_usd"] / price * 100 if price and price > 0 else 0.0
    return max(float(pct), tick)


def cost_r(
    price: float, stop: float, dvol20, adr_pct, entry: str, costs: Mapping[str, Any]
) -> float | None:
    """Expected round-trip cost in R: commission on both orders, the entry's and a market
    exit's slippage, and half a stop's extra slip (about half the trades end at the stop)."""
    if not (price and stop) or price <= 0 or price == stop:
        return None
    stop_pct = abs(price - stop) / price * 100
    base = slippage_pct(dvol20, price, costs)
    mult = (
        costs["offhours_mult"]
        if entry in OFFHOURS_ENTRIES
        else costs["open_mult"]
        if entry in OPEN_ENTRIES
        else 1.0
    )
    adr = 0.0 if _missing(adr_pct) else float(adr_pct)
    total = 2 * costs["commission_pct"] + base * mult + base + 0.5 * costs["stop_slip_adr"] * adr
    return total / stop_pct


def condition_met(spec: Mapping[str, Any], value) -> bool:
    """One yes/no condition: `equals`, `min`/`max` (inclusive), `above`/`below` (strict). A
    missing value is a no."""
    if _missing(value):
        return False
    if "equals" in spec:
        want = spec["equals"]
        if isinstance(want, bool):
            return bool(value) == want
        return _category(value) == _category(want)
    v = float(value)
    return (
        ("min" not in spec or v >= float(spec["min"]))
        and ("max" not in spec or v <= float(spec["max"]))
        and ("above" not in spec or v > float(spec["above"]))
        and ("below" not in spec or v < float(spec["below"]))
    )


def quality_for(scan: str, grading: Mapping[str, Any]) -> str | None:
    """The quality-count strategy that grades a live scan, when its count is on
    (`quality_enabled`: true for all, or a list of strategies)."""
    enabled = grading.get("quality_enabled")
    if not enabled:
        return None
    for name, rule in grading.get("quality", {}).items():
        if enabled is not True and name not in enabled:
            continue
        if scan == name or scan in rule.get("live_scans", ()):
            return name
    return None


def quality_grade(scan: str, features: Mapping[str, Any], grading: Mapping[str, Any]) -> Grade:
    """Grade by the number of the strategy's conditions that hold."""
    name = quality_for(scan, grading)
    rule = grading["quality"][name]
    conditions = grading["conditions"]
    reasons = []
    for part in rule["parts"]:
        spec = conditions[part]
        met = condition_met(spec, features.get(spec["feature"]))
        reasons.append((part, features.get(spec["feature"]), 1.0 if met else 0.0))
    points = sum(r[2] for r in reasons)
    label = "C"
    for floor, grade_label in rule["grades"]:
        if points >= float(floor):
            label = grade_label
            break
    entries = rule.get("entries", {})
    plan = {  # a setup on its own plan has `stop` / `exit` instead (MA-surf)
        "entry": entries.get(scan, rule.get("entry")),
        "stop_adr": rule.get("stop_adr"),
        "hold_sessions": rule.get("hold_sessions"),
        "stop": rule.get("stop", "adr"),
        "exit": rule.get("exit", "hold"),
    }
    return Grade(
        scan,
        name,
        label,
        float(points),
        None,
        tuple(sorted(reasons, key=lambda r: -r[2])),
        plan,
        float(grading["risk_mult"].get(label, 0.0)),
        note=f"{int(points)} of {len(rule['parts'])} quality points",
    )


def strategy_for(scan: str, grading: Mapping[str, Any]) -> str | None:
    """The study strategy whose scorecard grades a live scan (config `live_scans`), or the
    scan itself when it has one."""
    rules = grading["strategies"]
    if scan in rules:
        return scan
    for name, rule in rules.items():
        if scan in rule.get("live_scans", ()):
            return name
    return None


def grade(
    scan: str,
    features: Mapping[str, Any],
    grading: Mapping[str, Any],
    *,
    price: float | None = None,
    stop: float | None = None,
    dvol20: float | None = None,
    adr_pct: float | None = None,
) -> Grade:
    """The study grade of one setup. `features`: the scorecard's feature values (missing ones
    score their `na` points); `price` / `stop`: the planned entry and stop, for the cost."""
    risk = grading["risk_mult"]
    if quality_for(scan, grading) is not None:
        return quality_grade(scan, features, grading)
    name = strategy_for(scan, grading)
    if name is None:
        return Grade(
            scan,
            None,
            "C",
            None,
            None,
            risk_mult=float(risk.get("C", 0.0)),
            note=str(grading["ungraded"]),
        )
    rule = grading["strategies"][name]
    reasons = []
    total = float(rule["base"])
    for feature, spec in rule["features"].items():
        pts = feature_points(spec, features.get(feature))
        total += pts
        reasons.append((feature, features.get(feature), round(pts, 3)))
    cost = None
    if price is not None and stop is not None:
        cost = cost_r(price, stop, dvol20, adr_pct, rule["entry"], grading["costs"])
    score = total - (cost or 0.0)
    label = "C"
    for floor, band in rule["bands"]:
        if score >= float(floor):
            label = band
            break
    plan = {
        "entry": rule["entry"],
        "stop_adr": rule["stop_adr"],
        "hold_sessions": rule["hold_sessions"],
    }
    reasons.sort(key=lambda r: -abs(r[2]))
    return Grade(
        scan,
        name,
        label,
        round(score, 3),
        None if cost is None else round(cost, 3),
        tuple(reasons),
        plan,
        float(risk.get(label, 0.0)),
    )
