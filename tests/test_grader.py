"""Study grades: hand-computed scores against a small rule set and the real config."""

import math

import pytest

from trading_os import grader
from trading_os.config import load_config

COSTS = {
    "commission_pct": 0.08,
    "slip_by_dvol": [[50_000_000, 0.05], [10_000_000, 0.10], [2_000_000, 0.25], [0, 0.50]],
    "min_tick_usd": 0.01,
    "open_mult": 2.0,
    "offhours_mult": 3.0,
    "stop_slip_adr": 0.05,
}
RULES = {
    "enabled": False,
    "stats_file": "x",
    "risk_mult": {"A+": 2.0, "A": 1.5, "B": 1.0, "C": 0.0},
    "ungraded": "C: no edge",
    "costs": COSTS,
    "strategies": {
        "ep": {
            "live_scans": ["ep_day"],
            "entry": "close",
            "stop_adr": 1.0,
            "hold_sessions": 21,
            "base": 0.1,
            "bands": [[0.3, "A"], [0.1, "B"]],
            "features": {
                "mkt_scan_count": {"edges": [18, 44], "points": [0.5, 0.0, -0.2]},
                "mkt_light": {"points": {"GREEN": 0.1, "STOP": -0.3}},
                "mkt_spy_above_ma200": {"points": {"1": -0.05, "0": 0.05}},
                "d_rvol": {"edges": [3.0], "points": [0.0, -0.2], "na": 0.02},
            },
        }
    },
}


def test_buckets_use_the_edges_and_missing_values_score_na():
    spec = RULES["strategies"]["ep"]["features"]["mkt_scan_count"]
    assert grader.feature_points(spec, 17.9) == 0.5
    assert grader.feature_points(spec, 18) == 0.0  # at the edge: the next bucket up
    assert grader.feature_points(spec, 200) == -0.2
    na = RULES["strategies"]["ep"]["features"]["d_rvol"]
    assert grader.feature_points(na, None) == 0.02 and grader.feature_points(na, math.nan) == 0.02
    light = RULES["strategies"]["ep"]["features"]["mkt_light"]
    assert grader.feature_points(light, "YELLOW") == 0.0  # no points for that category


def test_a_live_scan_takes_its_strategys_scorecard():
    feats = {"mkt_scan_count": 10, "mkt_light": "GREEN", "mkt_spy_above_ma200": True, "d_rvol": 1.2}
    g = grader.grade("ep_day", feats, RULES)
    # 0.1 + 0.5 + 0.1 - 0.05 + 0 = 0.65, no cost given
    assert g.strategy == "ep" and g.score == pytest.approx(0.65) and g.grade == "A"
    assert g.risk_mult == 1.5 and g.plan["hold_sessions"] == 21
    assert g.reasons[0][0] == "mkt_scan_count"  # largest effect first


def test_cost_comes_off_the_score():
    feats = {"mkt_scan_count": 30, "mkt_light": "GREEN", "mkt_spy_above_ma200": 0.0, "d_rvol": 1.0}
    # 0.1 + 0 + 0.1 + 0.05 + 0 = 0.25 before costs
    g = grader.grade("ep_day", feats, RULES, price=50.0, stop=48.0, dvol20=60e6, adr_pct=4.0)
    # 2 x 0.08 + 0.05 + 0.05 + 0.5 x 0.05 x 4 = 0.36 % on a 4 % stop = 0.09R
    assert g.cost_r == pytest.approx(0.09) and g.score == pytest.approx(0.16)
    assert g.grade == "B"


def test_scans_without_a_scorecard_are_c_with_the_reason():
    g = grader.grade("breakout_trigger", {}, RULES)
    assert g.grade == "C" and g.strategy is None and g.note == "C: no edge"


def test_the_proposed_config_grades_every_rule_set():
    rules = load_config().grading
    for name, rule in rules["strategies"].items():
        g = grader.grade(name, {}, rules)
        assert g.grade in grader.GRADES and g.strategy == name
        assert len(rule["bands"]) >= 1


def quality_rules():
    rules = dict(RULES)
    rules["quality_enabled"] = True
    rules["conditions"] = {
        "earnings": {"feature": "is_earnings_reaction_day", "equals": True},
        "sideways_1_2m": {"feature": "d_neglect_months", "min": 1, "max": 2},
        "market_cool": {"feature": "mkt_scan_count", "below": 45},
        "revenue_accel": {"feature": "revenue_growth_accel", "above": 0},
    }
    rules["quality"] = {
        "ep": {
            "parts": ["earnings", "sideways_1_2m", "market_cool", "revenue_accel"],
            "grades": [[4, "A+"], [3, "B"]],
            "live_scans": ["ep_pm", "ep_close"],
            "entries": {"ep_pm": "pm_0915", "ep_close": "close"},
            "stop_adr": 1.0,
            "hold_sessions": 21,
        }
    }
    return rules


def test_conditions_are_inclusive_ranges_strict_bounds_and_equality():
    assert grader.condition_met({"feature": "x", "min": 1, "max": 2}, 2)
    assert not grader.condition_met({"feature": "x", "min": 1, "max": 2}, 3)
    assert not grader.condition_met({"feature": "x", "below": 45}, 45)
    assert grader.condition_met({"feature": "x", "equals": True}, True)
    assert not grader.condition_met({"feature": "x", "above": 0}, None)  # missing = no


def test_a_quality_count_grades_by_points_and_carries_the_scan_entry():
    rules = quality_rules()
    feats = {
        "is_earnings_reaction_day": True,
        "d_neglect_months": 1,
        "mkt_scan_count": 30,
        "revenue_growth_accel": 5.0,
    }
    g = grader.grade("ep_pm", feats, rules)
    assert g.grade == "A+" and g.score == 4 and g.plan["entry"] == "pm_0915"
    assert g.note == "4 of 4 quality points" and g.risk_mult == 2.0
    g3 = grader.grade("ep_close", feats | {"mkt_scan_count": 80}, rules)
    assert g3.grade == "B" and g3.plan["entry"] == "close"
    assert grader.grade("ep_close", {}, rules).grade == "C"
    off = rules | {"quality_enabled": False}
    assert grader.grade("ep_pm", feats, off).grade == "C"  # the scorecards don't cover ep_pm


def test_the_quality_counts_grade_every_live_setup():
    rules = load_config().grading
    assert rules["quality_enabled"] is True  # Emil, 21 Oct 2026
    for name, rule in rules["quality"].items():
        assert set(rule["parts"]) <= set(rules["conditions"]), name
    assert grader.grade("ep_am", {}, rules).plan["entry"] == "t_1030"
    four = {
        "is_earnings_reaction_day": True,
        "d_neglect_months": 1,
        "mkt_scan_count": 30,
        "revenue_growth_accel": 2.0,
    }
    assert grader.grade("ep_am", four, rules).grade == "C"  # 4 points: C (Emil, 21 Oct 2026)
    assert grader.grade("ep_am", four | {"eps_yoy_pct": 5.0}, rules).grade == "A+"
    assert grader.grade("ep_ah", {}, rules).plan["entry"] == "ah_1645"
    assert grader.quality_for("ep9m_pace", rules) == "ep9m"
    ep9m_four = four | {"sessions_since_earnings": 3}
    ep9m_four.pop("is_earnings_reaction_day")
    assert grader.grade("ep9m_pace", ep9m_four, rules).grade == "C"  # 4 points: C (21 Oct 2026)
    assert grader.grade("ep9m_pace", ep9m_four | {"eps_yoy_pct": 5.0}, rules).grade == "A+"
    assert grader.quality_for("luk_flush", rules) == "luk_avwap_flush"
    only_ep = rules | {"quality_enabled": ["ep"]}
    assert grader.quality_for("ep9m_pace", only_ep) is None  # a list switches some on
