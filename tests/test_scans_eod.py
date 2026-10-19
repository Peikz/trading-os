"""EP9M, Momentum Burst and EP-AH: each threshold on its edge, then one step past it."""

import pandas as pd
import pytest

from trading_os.config import load_config
from trading_os.scans.ep import ep9m, ep9m_early, ep9m_pace, ep_ah, ep_pm
from trading_os.scans.momentum import mb_down, mb_up


@pytest.fixture(scope="module")
def scans():
    return load_config().scans


def run(fn, scan, *rows):
    return fn(pd.DataFrame(list(rows)), scan)["ticker"].tolist()


def ep9m_row(ticker, **kw):
    return {"ticker": ticker, "volume": 9_000_000, "chg_pct": 4.0} | kw


def test_ep9m(scans):
    s = scans["ep9m"]
    assert run(ep9m, s, ep9m_row("EDGE")) == ["EDGE"]
    assert run(ep9m, s, ep9m_row("LOWV", volume=8_999_999)) == []
    assert run(ep9m, s, ep9m_row("SLOW", chg_pct=3.99)) == []
    # Ranked by volume, largest first; MA position plays no part.
    ranked = run(ep9m, s, ep9m_row("A", volume=10_000_000), ep9m_row("B", volume=30_000_000))
    assert ranked == ["B", "A"]


def pace_row(ticker, **kw):
    # 2M traded so far; normally 1M a day; 4.5x the usual volume by this time -> 4.5M pace.
    base = {"ticker": ticker, "chg_pct": 4.0, "volume": 2_000_000, "rvol_base_volume": 1e6}
    return base | {"rvol_at_time_tv": 4.5} | kw


def test_ep9m_pace(scans):
    s = scans["ep9m_pace"]
    assert s.slots == ("am", "mid") and s.runs_in("mid") and not s.runs_in("eod")
    assert run(ep9m_pace, s, pace_row("SLOW")) == []  # on pace for 4.5M
    assert run(ep9m_pace, s, pace_row("EDGE", rvol_at_time_tv=9.0)) == ["EDGE"]  # exactly 9M
    assert run(ep9m_pace, s, pace_row("JUST", rvol_at_time_tv=8.99)) == []
    assert run(ep9m_pace, s, pace_row("FLAT", rvol_at_time_tv=12.0, chg_pct=3.99)) == []
    # Already 9M traded counts even when the pace field is missing.
    done = pace_row("DONE", volume=9_000_000, rvol_at_time_tv=float("nan"))
    assert run(ep9m_pace, s, done) == ["DONE"]
    hits = ep9m_pace(
        pd.DataFrame([pace_row("A", rvol_at_time_tv=10.0), pace_row("B", rvol_at_time_tv=30.0)]),
        s,
    )
    assert hits["ticker"].tolist() == ["B", "A"]
    assert hits["proj_volume"].tolist() == [30e6, 10e6]


def mb_row(ticker, **kw):
    base = {"ticker": ticker, "chg_pct": 4.0, "volume": 100_000, "prev_volume": 99_999}
    return base | {"close_loc": 0.70} | kw


def test_mb_up(scans):
    s = scans["mb_up"]
    assert run(mb_up, s, mb_row("EDGE")) == ["EDGE"]
    assert run(mb_up, s, mb_row("SLOW", chg_pct=3.99)) == []
    assert run(mb_up, s, mb_row("THIN", volume=99_999, prev_volume=50_000)) == []
    assert run(mb_up, s, mb_row("FLAT", prev_volume=100_000)) == []  # volume must beat prior day
    assert run(mb_up, s, mb_row("WEAK", close_loc=0.69)) == []
    assert run(mb_up, s, mb_row("NOPV", prev_volume=float("nan"))) == []


def test_mb_down(scans):
    s = scans["mb_down"]
    down = {"chg_pct": -4.0, "close_loc": 0.0}
    assert run(mb_down, s, mb_row("EDGE", **down)) == ["EDGE"]
    assert run(mb_down, s, mb_row("SOFT", **(down | {"chg_pct": -3.99}))) == []
    assert run(mb_down, s, mb_row("FLAT", **down, prev_volume=100_000)) == []
    # No close-location rule on the way down; biggest drop ranks first.
    ranked = run(
        mb_down,
        s,
        mb_row("A", chg_pct=-5.0, close_loc=0.9),
        mb_row("B", chg_pct=-12.0, close_loc=0.9),
    )
    assert ranked == ["B", "A"]


def ah_row(ticker, **kw):
    base = {"ticker": ticker, "ah_change_pct": 8.0, "close": 1.0, "market_cap": 50_000_000}
    return base | {"ah_volume": 50_000} | kw


def test_ep_ah(scans):
    s = scans["ep_ah"]
    assert s.enabled is False
    assert run(ep_ah, s, ah_row("EDGE")) == ["EDGE"]
    assert run(ep_ah, s, ah_row("SMALL", ah_change_pct=7.99)) == []
    assert run(ep_ah, s, ah_row("THIN", ah_volume=49_999)) == []
    assert run(ep_ah, s, ah_row("SUB1", close=0.99)) == []
    assert run(ep_ah, s, ah_row("TINY", market_cap=49_999_999)) == []


def pm_row(ticker, **kw):
    base = {"ticker": ticker, "pm_change_pct": 10.0, "close": 1.0, "pm_volume": 50_000}
    return base | {"market_cap": 50_000_000} | kw


def test_ep_pm(scans):
    s = scans["ep_pm"]
    assert s.slot == "pm"
    assert run(ep_pm, s, pm_row("EDGE")) == ["EDGE"]
    assert run(ep_pm, s, pm_row("SMALL", pm_change_pct=9.99)) == []
    assert run(ep_pm, s, pm_row("THIN", pm_volume=49_999)) == []
    assert run(ep_pm, s, pm_row("SUB1", close=0.99)) == []
    assert run(ep_pm, s, pm_row("TINY", market_cap=49_999_999)) == []
    assert run(ep_pm, s, pm_row("NOPM", pm_change_pct=float("nan"))) == []


def test_ep9m_early_uses_the_configured_gap(scans):
    s = scans["ep9m_early"]
    assert s["pm_gap_basis"] == "premarket_change"
    row = {"ticker": "EDGE", "pm_volume": 500_000, "pm_change_pct": 4.0, "pm_gap_pct": 1.0}
    hits = ep9m_early(pd.DataFrame([row]), s)
    assert hits["ticker"].tolist() == ["EDGE"] and hits["pm_gap_used"].tolist() == [4.0]
    assert run(ep9m_early, s, row | {"pm_volume": 499_999}) == []
    assert run(ep9m_early, s, row | {"pm_change_pct": 3.99}) == []
