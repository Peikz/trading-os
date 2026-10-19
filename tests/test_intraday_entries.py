"""Entry rules and exits of the minute-bar study on hand-built bars (synthetic data only)."""

import numpy as np
import pytest

from trading_os import intraday_entries as ie
from trading_os import intraday_exits
from trading_os.config import load_config
from trading_os.intraday_study import params

P = params(load_config())
RULES = load_config().exits


def bars(points):
    """[(minute, price, volume), ...] -> Bars with a 0.05 range around each price."""
    m = np.array([x[0] for x in points])
    c = np.array([x[1] for x in points], dtype=float)
    v = np.array([x[2] for x in points], dtype=float)
    return ie.Bars(m, c.copy(), c + 0.05, c - 0.05, c, v, c)


def names(rows, rule=None):
    return sorted({r["entry"] for r in rows if rule is None or r["stop_rule"] == rule})


def test_ep_entries_use_only_what_was_known_by_then():
    pts = [(-470, 11.0, 60_000), (-400, 11.0, 1_000)]  # +10 % after hours, 61K shares
    pts += [(300, 11.4, 30_000), (470, 11.5, 30_000), (550, 11.6, 10_000)]  # pre-market
    pts += [(570 + k, 11.2 + 0.01 * k, 100_000) for k in range(390)]  # opens +12 %, drifts up
    rows = ie.gap(bars(pts), {"prev_close": 10.0, "adr_usd": 0.5}, P)
    got = names(rows)
    assert {"ah_1800", "pm_0800", "pm_0915", "open", "orh_5m", "t_1030", "close"} <= set(got)
    pm = next(r for r in rows if r["entry"] == "pm_0800" and r["stop_rule"] == "lod")
    assert pm["price"] == 11.5 and pm["start"] == 4  # the 07:50 bar, checked from the next one
    orh = next(r for r in rows if r["entry"] == "orh_5m" and r["stop_rule"] == "adr")
    assert orh["price"] == pytest.approx(11.2 + 0.04 + 0.05)  # the 5-minute high
    # An opening gap under 10 % gets no session entries, whatever the pre-market did.
    low_gap = [(p[0], p[1] - 0.4 if p[0] >= 570 else p[1], p[2]) for p in pts]
    later = names(ie.gap(bars(low_gap), {"prev_close": 10.0, "adr_usd": 0.5}, P))
    assert "open" not in later and "pm_0800" in later


def test_ep9m_counts_the_pace_at_the_check_time():
    pts = [(570 + k, 10.5, 50_000) for k in range(390)]  # +5 %, 2.25M by 10:15
    rows = ie.ep9m(bars(pts), {"prev_close": 10.0, "adr_usd": 0.5}, P)
    first = next(r for r in rows if r["entry"] == "t_1015")
    assert first["proj_volume"] == pytest.approx(45 * 50_000 / P["pace_fraction"]["10:15"])
    quiet = [(m, p, 10_000) for m, p, _ in pts]
    assert names(ie.ep9m(bars(quiet), {"prev_close": 10.0, "adr_usd": 0.5}, P)) == []


def test_breakout_buys_the_pivot_cross_and_waits_until_ten_in_the_variant():
    pts = [(570 + k, 9.6 + 0.01 * k, 10_000) for k in range(60)]  # crosses 10.0 at ~10:10
    pts += [(630 + k, 10.3, 10_000) for k in range(330)]
    row = {"prev_close": 9.6, "adr_usd": 0.5, "pivot": 10.0, "order_stop": 9.4, "b1": True}
    rows = ie.pivot(bars(pts), row, P)
    cross = next(r for r in rows if r["entry"] == "pivot_cross" and r["stop_rule"] == "order")
    assert cross["price"] == 10.0 and cross["stop"] == 9.4 and cross["b_count"] == 1
    wait = next(r for r in rows if r["entry"] == "pivot_1000")
    assert wait["price"] == 10.0  # not crossed by 10:00, so the buy stop waits at the pivot
    assert "pivot_close" in names(rows)


def test_luk_pullback_turns_green_after_touching_yesterdays_ema():
    pts = [(570 + k, 19.8 - 0.03 * k, 10_000) for k in range(20)]  # dips to ~19.2
    pts += [(590 + k, 19.2 + 0.02 * k, 10_000) for k in range(370)]  # then rallies past 20
    row = {
        "prev_close": 20.0,
        "adr_usd": 1.0,
        "ema_fast": 19.0,
        "ema_mid": 18.0,
        "avwap": 15.0,
        "lead": True,
        "mid_rising": True,
        "base_days": 10,
    }
    rows = ie.luk(bars(pts), row, P)
    green = next(r for r in rows if r["entry"] == "turn_green" and r["stop_rule"] == "lod")
    assert green["strategy"] == "luk_pullback" and green["touched"] == "ema9"
    assert green["price"] == 20.0 and green["stop"] == pytest.approx(19.2 - 0.05, abs=0.02)
    assert not [r for r in rows if r["strategy"] == "luk_avwap_flush"]  # base too short


def test_next_day_short_sells_the_break_of_the_signal_low():
    pts = [(570 + 5 * k, 9.9 - 0.01 * k, 10_000) for k in range(78)]
    row = {"strategy": "mb_down", "adr_usd": 0.5, "signal_high": 10.5, "signal_low": 9.8}
    rows = ie.next_day(bars(pts), row, P)
    brk = next(r for r in rows if r["entry"] == "next_prior_break" and r["stop_rule"] == "signal")
    assert brk["side"] == -1 and brk["price"] == 9.8 and brk["stop"] == 10.5


def test_entry_day_stop_fills_at_the_stop_or_a_worse_open():
    b = bars([(570, 10.0, 1), (571, 9.0, 1), (572, 9.5, 1)])
    stopped, price = ie.entry_day_exit(b, {"start": 1, "stop": 9.5, "side": 1})
    assert stopped and price == 9.0  # the 09:31 bar opened under the stop
    stopped, price = ie.entry_day_exit(b, {"start": 1, "stop": 8.0, "side": 1})
    assert not stopped and price == 9.5


def grid(closes):
    c = np.array(closes, dtype=float)[:, None]
    return {"open": c.copy(), "high": c + 0.2, "low": c - 0.2, "close": c}


def test_exits_long_hold_stop_and_trail():
    g = grid([10, 10.5, 11, 9.0, 9.5, 10, 10, 10] + [10] * 30)
    lines = {"ma10": np.full_like(g["close"], 10.6), "ma20": np.full_like(g["close"], 5.0)}
    lines |= {"ema9": lines["ma10"], "ema21": lines["ma20"]}
    out = intraday_exits.run(
        g,
        lines,
        np.array([0]),
        np.array([0]),
        np.array([10.0]),
        np.array([9.5]),
        np.array([1]),
        (np.array([False]), np.array([10.0])),
        RULES,
    )
    assert out["r_hold_1d"][0] == pytest.approx(1.0)  # 10.5 close, 0.5 risk
    assert out["r_hold_5d"][0] == pytest.approx(-2.0)  # day 3 opens at 9.0, under the 9.5 stop
    assert out["r_trail_ma10"][0] == pytest.approx(1.0)  # first close under 10.6: day 1
    assert out["days_trail_ma10"][0] == 1


def test_exits_mirror_a_short_and_the_entry_day_stop_wins():
    g = grid([10, 9.5, 9.0, 8.5] + [8.5] * 30)
    lines = {k: np.full_like(g["close"], np.nan) for k in ("ma10", "ma20", "ema9", "ema21")}
    out = intraday_exits.run(
        g,
        lines,
        np.array([0, 0]),
        np.array([0, 0]),
        np.array([10.0, 10.0]),
        np.array([10.5, 10.5]),
        np.array([-1, -1]),
        (np.array([False, True]), np.array([10.0, 10.5])),
        RULES,
    )
    assert out["r_hold_1d"][0] == pytest.approx(1.0) and out["pnl_hold_1d"][0] == pytest.approx(5)
    assert out["r_hold_21d"][1] == pytest.approx(-1.0) and out["r_trail_ma20"][1] == -1.0


def test_breakout_rows_without_a_setup_are_named_breakout():
    pts = [(570 + k, 9.6 + 0.01 * k, 10_000) for k in range(60)]
    base = {"prev_close": 9.6, "adr_usd": 0.5, "pivot": 10.0, "order_stop": 9.4}
    for setup in (float("nan"), None):
        rows = ie.pivot(bars(pts), base | {"setup": setup}, P)
        assert rows and {r["strategy"] for r in rows} == {"breakout"}
