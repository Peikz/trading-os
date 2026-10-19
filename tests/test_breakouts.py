"""Breakout criteria B1-B5 (SPEC §6.4) on hand-built price paths."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import breakouts as bo
from trading_os.config import load_config
from trading_os.scans.history_scans import breakout_trigger, breakout_watch
from trading_os.store import RunContext, build_candidates


@pytest.fixture(scope="module")
def params():
    return load_config().breakout


def test_zigzag_hand_example():
    high = np.array([10, 9.5, 9.0, 9.6, 9.8, 9.3, 9.1, 9.5])
    low = high - 0.2
    depths, lows = bo.zigzag_pullbacks(high, low, threshold=0.5)
    # 10 → 8.8 (−12 %), back up to 9.8, then → 8.9 (−9.18 %), back up again.
    assert depths == pytest.approx([12.0, 0.9 / 9.8 * 100])
    assert lows == pytest.approx([8.8, 8.9])


def textbook():
    """Lead-in, +50 % advance, a 3-contraction base, tight quiet right side, breakout bar."""
    closes = list(np.linspace(9.0, 10.0, 45))
    closes += list(np.linspace(10.0, 15.0, 30))
    closes += [14.6, 14.1, 13.6, 13.2, 13.0]
    closes += [13.4, 13.9, 14.3, 14.6, 14.8]
    closes += [14.6, 14.3, 14.0, 13.9]
    closes += [14.1, 14.4, 14.6, 14.7]
    closes += [14.55, 14.45, 14.4, 14.5, 14.55, 14.6, 14.55, 14.6]
    closes += [15.6]
    c = np.array(closes)
    h, lo = c * 1.008, c * 0.992
    h[-1], lo[-1] = 15.8, 14.6
    v = np.full(len(c), 1_000_000.0)
    v[45:75] = 1_500_000
    v[75:-1] = 600_000
    v[-9:-1] = 400_000
    v[-1] = 2_500_000
    return h, lo, c, v


def analyze(params, end_offset, mutate=None):
    h, lo, c, v = textbook()
    if mutate is not None:
        h, lo, c, v = mutate(h, lo, c, v)
    grids = {"high": h[:, None], "low": lo[:, None], "close": c[:, None], "volume": v[:, None]}
    ind = {k: a[:, 0] for k, a in bo.indicators(**grids).items()}
    return bo.analyze_base(len(c) - 1 - end_offset, h, lo, c, v, ind, params)


def test_textbook_base_passes_b1_to_b4(params):
    base = analyze(params, end_offset=1)  # the base as of the day before the breakout
    assert (base.b1, base.b2, base.b3, base.b4) == (True, True, True, True)
    h, _, _, _ = textbook()
    assert base.pivot == pytest.approx(h[:-1].max())  # highest high in the base
    assert base.base_len == 27
    depths = base.contraction_depths
    assert all(b <= 0.85 * a for a, b in zip(depths, depths[1:], strict=False))
    # Order stop rule: max(last contraction low, pivot − 1 × ADR $); risk in ADR <= 1.
    assert base.order_stop == pytest.approx(
        max(base.last_contraction_low, base.pivot - base.adr_usd)
    )
    assert base.risk_adr <= 1.0 + 1e-9


def test_breakout_day_has_no_base_yet(params):
    # On the breakout day itself the pivot is today's high: base length 1, B2 fails.
    base = analyze(params, end_offset=0)
    assert base.base_len == 1 and base.b2 is False


def test_small_prior_move_fails_b1(params):
    def shallow_advance(h, lo, c, v):
        # The lead-in and advance start at 13.0 instead of 9.0: about +17 % into the pivot.
        c = c.copy()
        c[:45] = np.linspace(13.0, 13.5, 45)
        c[45:75] = np.linspace(13.5, 15.0, 30)
        h, lo = h.copy(), lo.copy()
        h[:75], lo[:75] = c[:75] * 1.008, c[:75] * 0.992
        return h, lo, c, v

    base = analyze(params, end_offset=1, mutate=shallow_advance)
    assert base.prior_move_pct < 30 and base.b1 is False


def test_loud_right_side_fails_b4(params):
    def loud(h, lo, c, v):
        v = v.copy()
        v[-6:-1] = 3_000_000
        return h, lo, c, v

    assert analyze(params, end_offset=1, mutate=loud).b4 is False


def test_detect_finds_watch_and_trigger(params):
    h, lo, c, v = textbook()
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(len(c))]
    grids = {"high": h[:, None], "low": lo[:, None], "close": c[:, None], "volume": v[:, None]}
    out = bo.detect(grids, pd.Index(["AAA"]), days, params)
    row = out.iloc[0]
    assert bool(row["trig_b5"]) and bool(row["trig_b1"]) and bool(row["trig_b4"])
    assert row["trig_range_adr"] > 1 and row["trig_rvol"] == pytest.approx(2.5)
    assert row["bo_base_len"] == 1  # today's base is only the breakout bar

    df = out.assign(chg_pct=6.8, tier="alert")
    hits = breakout_trigger(df, load_config().scans["breakout_trigger"])
    assert hits["ticker"].tolist() == ["AAA"] and bool(hits.loc[0, "b5"])
    assert breakout_watch(df, load_config().scans["breakout_watch"]).empty

    ctx = RunContext(days[-1], "eod", pd.Timestamp("2026-04-12 20:17", tz="UTC"), "scheduled")
    cands = build_candidates({"breakout_trigger": hits}, ctx, {})
    stored = cands.iloc[0]
    assert stored["pivot"] == pytest.approx(row["trig_pivot"])
    assert stored["order_stop"] == pytest.approx(row["trig_order_stop"])
    assert bool(stored["b5"]) and stored["contraction_depths"] == row["trig_contraction_depths"]


def test_not_enough_history_is_none(params):
    h, lo, c, v = (x[-60:] for x in textbook())
    grids = {"high": h[:, None], "low": lo[:, None], "close": c[:, None], "volume": v[:, None]}
    ind = {k: a[:, 0] for k, a in bo.indicators(**grids).items()}
    assert bo.analyze_base(len(c) - 1, h, lo, c, v, ind, params) is None
