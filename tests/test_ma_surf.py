"""MA-surf live: the scan maps the surf levels to the plan's names, and the push shows its C
hits in full with the study plan."""

import pandas as pd

from trading_os import notify, sizing
from trading_os.config import load_config
from trading_os.scans import REGISTRY

A = "".join(["S", "R", "F"])


def universe(**kw):
    row = {
        "ticker": A,
        "tier": "alert",
        "close": 10.0,
        "dollar_volume": 5e7,
        "adr20_usd": 0.6,
        "ma_surf": True,
        "surf_pivot": 10.4,
        "surf_order_stop": 9.8,
        "surf_risk_adr": 1.0,
        "surf_ma": 10.0,
        "surf_days": 14.0,
        "surf_base_len": 9.0,
        "surf_day_in_setup": 1.0,
        "surf_prior_move_pct": 45.0,
        "surf_ma_stacked": True,
        "pivot": 99.0,  # a breakout scan's own pivot on the same row stays its own
    }
    return pd.DataFrame([row | kw])


def test_the_scan_takes_the_surf_levels_and_is_empty_without_a_setup():
    cfg = load_config()
    hits = REGISTRY["ma_surf"](universe(), cfg.scans["ma_surf"])
    assert len(hits) == 1
    assert (hits.iloc[0]["pivot"], hits.iloc[0]["order_stop"]) == (10.4, 9.8)
    plain = universe().drop(columns=[c for c in universe() if c.startswith("surf_")])
    assert REGISTRY["ma_surf"](plain.assign(ma_surf=False), cfg.scans["ma_surf"]).empty


def test_c_hits_are_pushed_in_full_with_the_study_plan():
    cfg = load_config()
    hits = REGISTRY["ma_surf"](universe(), cfg.scans["ma_surf"]).assign(grade="C")
    chosen = notify.select_for_push({"ma_surf": hits}, cfg)["ma_surf"]
    assert len(chosen) == 1 and not chosen.iloc[0]["push_partial"]
    assert notify.c_counts({"ma_surf": hits}, cfg) == []  # not counted as saved-only
    text = [line.text for line in notify._block(chosen.iloc[0].to_dict(), "ma_surf", "eod")]
    assert text[0] == f"▸ {A}  MA10 14d  base 9d"
    assert any("buy-stop at the pivot" in t for t in text)
    assert any("close under the 20-day MA" in t for t in text)


def test_the_plan_buys_at_the_pivot_with_the_order_stop():
    row = REGISTRY["ma_surf"](universe(), load_config().scans["ma_surf"]).iloc[0].to_dict()
    entry, stop, basis = sizing.plan(row, "ma_surf", {})
    assert (entry, stop) == (10.4, 9.8) and "buy-stop at pivot" in basis
