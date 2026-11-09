"""Backtest step 4: the trade engine, on hand-made bars."""

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os.backtest import engine as en
from trading_os.backtest.config import ExitConfig, load_config
from trading_os.backtest.setups import ROW_COLUMNS

CFG = load_config()
E0 = CFG.engine.exits["E0"]
E1 = CFG.engine.exits["E1"]
E2 = CFG.engine.exits["E2"]
NEVER = np.full(20, -np.inf)  # a trail that never fires


def bars(rows):
    """rows: (open, high, low, close) per day, day 0 first."""
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def play(rows, ex=E2, trail=None, **kw):
    o, h, low, c = bars(rows)
    tr = NEVER[: len(c)] if trail is None else np.asarray(trail, float)
    args = dict(f=0, entry=10.0, stop0=9.0, ex=ex, raise_stop=False, max_hold=252)
    args.update(kw)
    return en.play(o, h, low, c, tr, **args)


def test_gap_through_stop_exits_at_the_open():
    p = play([(10, 10, 10, 10), (8.5, 8.8, 8.2, 8.6)])
    assert (p.reason, p.exit_price, p.exit_k) == ("gap_stop", 8.5, 1)
    assert p.r_gross == pytest.approx(-1.5)


def test_intraday_stop_exits_at_the_stop():
    p = play([(10, 10, 10, 10), (9.8, 10.2, 8.9, 9.5)])
    assert (p.reason, p.exit_price) == ("stop", 9.0)
    assert p.r_gross == pytest.approx(-1.0)


def test_fail_sold_exits_at_the_fill_day_close():
    p = play([(10, 10.5, 9.8, 9.9), (11, 12, 11, 12)], fail_at_close=True)
    assert (p.reason, p.exit_k, p.exit_price) == ("fail_sold", 0, 9.9)
    assert p.r_gross == pytest.approx(-0.1)


def test_r_partial_then_breakeven_and_r_no_partial():
    rows = [
        (10, 10, 10, 10),
        (10.5, 13.3, 10.4, 13.1),  # close >= +3R (13): sell 15 % at 13.1, stop to 10
        (12.0, 12.1, 9.9, 10.5),  # back through the entry: out at break-even
        (10.0, 10.2, 8.5, 9.0),  # without the partial, this takes out the 9 stop
    ]
    p = play(rows, ex=E1)
    assert p.reason == "breakeven" and p.exit_k == 2 and p.partial_k == 1
    assert p.r_gross == pytest.approx(0.15 * 3.1 + 0.85 * 0.0)
    q = play(rows, ex=E1, partial=False)
    assert q.reason == "stop" and q.exit_k == 3
    assert q.r_gross == pytest.approx(-1.0)


def test_e0_sells_a_third_on_day_3_to_5_above_the_entry():
    rows = [(10, 10, 10, 10), (10, 10.2, 9.8, 9.9), (10, 10.3, 9.9, 10.2), (10.2, 10.8, 10.1, 10.6)]
    rows += [(10.6, 10.7, 9.95, 10.1)]  # day 4: through the new break-even stop
    p = play(rows, ex=E0)
    assert p.partial_k == 3  # not day 2, though it closed above the entry
    assert p.reason == "breakeven"
    assert p.r_gross == pytest.approx(0.3333 * 0.6 + (1 - 0.3333) * 0.0)


def test_trail_exits_on_a_close_under_the_ma():
    rows = [(10, 10, 10, 10), (10, 11, 9.9, 10.8), (10.8, 11, 10.3, 10.4)]
    p = play(rows, trail=[0, 10.5, 10.5])
    assert (p.reason, p.exit_k, p.exit_price) == ("trail", 2, 10.4)


def test_k1_raises_the_stop_to_the_entry_day_low():
    rows = [(10, 10.2, 9.5, 10), (9.9, 10.1, 9.4, 9.8), (9.8, 9.9, 8.0, 8.1)]
    k1 = play(rows, raise_stop=True)
    assert (k1.reason, k1.exit_k, k1.exit_price) == ("stop", 1, 9.5)
    k0 = play(rows, raise_stop=False)
    assert (k0.reason, k0.exit_k) == ("stop", 2)


def test_time_and_end_exits():
    rows = [(10, 10, 10, 10)] + [(10, 10.1, 9.9, 10.05)] * 5
    assert play(rows, max_hold=3).reason == "time"
    delisted = rows[:3] + [(np.nan,) * 4] * 3
    p = play(delisted)
    assert (p.reason, p.exit_k) == ("end", 2)


def frames(rows, ticker="XYZ"):
    o, h, low, c = bars(rows)
    idx = [dt.date(2021, 3, 1) + dt.timedelta(days=i) for i in range(len(c))]
    w = {
        k: pd.DataFrame({ticker: v}, index=idx)
        for k, v in {"open": o, "high": h, "low": low, "close": c}.items()
    }
    flat = pd.DataFrame({ticker: np.full(len(c), np.nan)}, index=idx)
    ind = {k: flat for k in ("sma10", "ema9", "ema21")}
    ind["regime"] = pd.Series("up", index=idx)
    ind["breadth"] = pd.DataFrame({"tag": "strong"}, index=idx)
    return w, ind, idx


def signal(idx, setup="L2", side=1, entry=10.0, stop=9.0, close_ok=True, day=0):
    row = dict.fromkeys(ROW_COLUMNS, np.nan)
    row.update(
        setup=setup,
        session_date=idx[day],
        ticker="XYZ",
        side=side,
        entry=entry,
        stop=stop,
        skip=False,
        close_ok=close_ok,
    )
    return pd.DataFrame([row])


def test_run_short_is_mirrored():
    rows = [(20, 20.2, 19.8, 20), (20.5, 21.6, 20.4, 21.5), (21.5, 22, 21, 21.8)]
    w, ind, idx = frames(rows)
    out = en.run(signal(idx, "S1", -1, 20.0, 21.0), w, ind, CFG, exits=["E2"], stops=["K0"])
    r = out.iloc[0]
    # a short with a 21 stop: day 1 trades up through it -> out at 21, -1R
    assert (r.exit_reason, r.exit_price) == ("stop", 21.0)
    assert r.r_gross == pytest.approx(-1.0)
    rows[1] = (21.5, 22, 21.4, 21.8)  # gaps over the stop: out at the open
    w, ind, idx = frames(rows)
    r = en.run(signal(idx, "S1", -1, 20.0, 21.0), w, ind, CFG, exits=["E2"], stops=["K0"]).iloc[0]
    assert (r.exit_reason, r.exit_price) == ("gap_stop", 21.5)
    assert r.r_gross == pytest.approx(-1.5)


def test_run_costs_variants_and_tags():
    rows = [(10, 10, 9.5, 10)] + [(9.98, 10.1, 9.9, 9.95)] * 4  # never stopped, no partial
    w, ind, idx = frames(rows)
    out = en.run(signal(idx), w, ind, CFG)
    assert len(out) == len(CFG.engine.exits) * len(CFG.engine.stops)
    cost = 2 * (0.10 + 0.08) / 100 / 0.10  # risk = 10 % of the entry
    assert out["cost_r"].iloc[0] == pytest.approx(cost)
    assert (out["r"] == out["r_gross"] - out["cost_r"]).all()
    assert out["regime"].iloc[0] == "up" and out["breadth"].iloc[0] == "strong"
    assert set(out["exit_reason"]) == {"end"}


def test_run_b0_fail_sold():
    rows = [(10, 10.5, 9.8, 9.9), (10, 10.2, 9.9, 10.1)]
    w, ind, idx = frames(rows)
    out = en.run(signal(idx, "B0", close_ok=False), w, ind, CFG, exits=["E2"], stops=["K0"])
    assert out["exit_reason"].iloc[0] == "fail_sold" and out["hold_days"].iloc[0] == 0


def test_run_next_open_fill():
    cfg = dataclasses.replace(CFG, engine=dataclasses.replace(CFG.engine, fill="next_open"))
    rows = [(10, 10, 10, 10), (10.3, 10.5, 10.2, 10.4), (10.4, 10.5, 8.0, 8.5)]
    w, ind, idx = frames(rows)
    r = en.run(signal(idx), w, ind, cfg, exits=["E2"], stops=["K0"]).iloc[0]
    assert r.entry == 10.3 and r.entry_date == idx[1]
    assert r.r_gross == pytest.approx((9.0 - 10.3) / 1.3)
    # a next open at or under the stop is no trade
    rows[1] = (8.9, 9.0, 8.5, 8.8)
    w, ind, idx = frames(rows)
    assert en.run(signal(idx), w, ind, cfg, exits=["E2"], stops=["K0"]).empty


def test_shakeout_flag():
    rows = [(10, 10, 10, 10), (9.5, 9.6, 8.8, 9.2), (9.3, 10.4, 9.2, 10.3)]
    w, ind, idx = frames(rows)
    r = en.run(signal(idx), w, ind, CFG, exits=["E2"], stops=["K0"]).iloc[0]
    assert r.exit_reason == "stop" and bool(r.day1_stop) and bool(r.shakeout)


def test_exit_config_must_match_its_partial_kind():
    from trading_os.backtest.config import _exit

    with pytest.raises(ValueError, match="missing"):
        _exit("X", {"partial": "day", "trail": "sma10"})
    with pytest.raises(ValueError, match="trail"):
        _exit("X", {"partial": "none", "trail": "sma7"})
    assert isinstance(_exit("X", {"partial": "none", "trail": "ema9"}), ExitConfig)
