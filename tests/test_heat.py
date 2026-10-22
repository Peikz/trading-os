"""Market heat: the band of a scan count, which setups held there, and the push lines."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from trading_os import heat

BANDS = [[18, "cool"], [45, "mild"], [81, "warm"], [None, "hot"]]


def row(setup, band, period, mean_r, day_r, trades):
    return {
        "setup": setup,
        "heat": band,
        "period": period,
        "trades": trades,
        "signal_days": trades // 2,
        "mean_r": mean_r,
        "day_mean_r": day_r,
        "win_pct": 30.0,
        "years_up": 2,
        "years": 3,
    }


def stats():
    setups = [
        ("ep_a", "EP A+ 10:30", "EP A+", "A"),
        ("luk_a", "Luk flush A", "Luk A", "A"),
        ("surf", "MA-surf", "MA-surf", "C"),
        ("bo", "Breakouts", "Breakouts", "C"),
        ("pp", "Pocket pivot", "Pocket pivot", "C"),
    ]
    rows = [
        row("ep_a", "warm", "2016-21", -0.40, -0.3, 10),
        row("ep_a", "warm", "2022-26", -0.80, -0.7, 20),
        row("surf", "warm", "2016-21", 0.25, 0.30, 40),
        row("surf", "warm", "2022-26", 0.75, 0.60, 50),
        row("bo", "warm", "2016-21", 0.10, 0.10, 500),
        row("bo", "warm", "2022-26", -0.50, -0.50, 900),
        row("pp", "warm", "2016-21", 0.40, -0.20, 200),  # per trade up, per day down
        row("pp", "warm", "2022-26", 0.10, 0.05, 300),
    ]
    return {
        "built": "2026-10-21",
        "bands": BANDS,
        "band_labels": {"cool": "under 18", "mild": "18-44", "warm": "45-80", "hot": "over 80"},
        "periods": list(heat.PERIODS),
        "min_trades": 30,
        "setups": [
            {"key": k, "label": label, "short": short, "kind": kind, "side": "long", "plan": "x"}
            for k, label, short, kind in setups
        ],
        "rows": rows,
    }


@pytest.mark.parametrize(
    ("count", "band"),
    [(0, "cool"), (17, "cool"), (18, "mild"), (44, "mild"), (45, "warm"), (80, "warm"),
     (81, "hot"), (None, None), (float("nan"), None)],
)  # fmt: skip
def test_band_edges_match_the_research(count, band):
    assert heat.band(count, BANDS) == band


def test_verdicts():
    t = heat.table(stats(), "warm").set_index("setup")["verdict"]
    assert t["MA-surf"] == "held"
    assert t["Breakouts"] == "mixed"  # up then down
    assert t["Pocket pivot"] == "mixed"  # per trade up, per signal day down
    assert t["EP A+ 10:30"] == "lost"  # lost in both, few trades: still shown as lost
    assert t["Luk flush A"] == "too few trades"  # never fires at this heat


def test_push_lines_name_the_band_the_graded_setups_and_what_held():
    lines = heat.push_lines(stats(), 60)
    assert lines[0].startswith("🌡 Warm market (count 60, 45-80)")
    assert lines[1] == "A: EP A+ -0.40/-0.80 (n 10/20) · Luk A none"
    assert lines[2] == "Held here too (C): MA-surf +0.25/+0.75"
    assert heat.push_lines(stats(), 10)[-1] == "No other setup held in both periods at this heat."
    assert heat.push_lines(None, 54) == [] and heat.push_lines(stats(), None) == []


def test_build_scores_each_setup_per_band_and_period(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "heat_stats", Path(__file__).resolve().parents[1] / "scripts" / "heat_stats.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    days = pd.to_datetime(["2019-03-01", "2019-03-04", "2023-05-01"]).date
    trades = pd.DataFrame(
        {
            "strategy": ["qm_surf"] * 4,
            "entry": ["pivot_1000"] * 4,
            "stop_rule": ["order"] * 4,
            "exit": ["trail_ma20"] * 4,
            "side": [1] * 4,
            "session_date": [days[0], days[0], days[1], days[2]],
            "year": [2019, 2019, 2019, 2023],
            "quality": [0] * 4,
            "luk_market_tight": [0] * 4,
            "net_capped": [1.0, -1.0, 2.0, 0.5],
        }
    )
    counts = pd.DataFrame({"session_date": days, "mkt_scan_count": [50, 50, 10]})
    out = script.build(trades, counts)
    json.dumps(out)  # what the file holds
    got = {(r["setup"], r["heat"], r["period"]): r for r in out["rows"]}
    warm = got[("qm_surf", "warm", "2016-21")]
    assert warm["trades"] == 3 and warm["mean_r"] == pytest.approx(2 / 3, abs=1e-3)
    assert warm["day_mean_r"] == pytest.approx(1.0)  # day 1 averages to 0, day 2 is 2
    assert got[("qm_surf", "cool", "2022-26")]["trades"] == 1
    surf = next(s for s in out["setups"] if s["key"] == "qm_surf")
    assert surf["plan"] == "10:00 over the pivot; the setup's own stop; trail the 20-day MA"


def test_the_heat_tag_per_scan():
    s = stats()
    s["setups"].append({"key": "qm_surf", "label": "MA-surf live", "short": "MA-surf",
                        "kind": "C", "side": "long", "plan": "x"})  # fmt: skip
    s["rows"] += [row("qm_surf", "warm", "2016-21", 0.25, 0.30, 40),
                  row("qm_surf", "warm", "2022-26", 0.75, 0.60, 50)]  # fmt: skip
    assert heat.tag(s, 60, "ma_surf") == "🌡 warm: held · +0.25/+0.75R (n 40/50)"
    assert heat.tag(s, 60, "qm_gainers") is None and heat.tag(None, 60, "ma_surf") is None
