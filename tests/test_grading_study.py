"""Grading study: point-in-time features, new exits, funds left out (synthetic data only)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from trading_os import clock, intraday_exits
from trading_os import grading_study as gs
from trading_os.config import load_config

CFG = load_config()
RULES = CFG.exits
A, F = "".join(["A", "A", "Q"]), "".join(["F", "N", "D"])


def grid(closes, highs=None, lows=None, opens=None, volume=1_000_000.0):
    c = np.array(closes, dtype=float)[:, None]
    h = np.array(highs, dtype=float)[:, None] if highs is not None else c * 1.02
    lo = np.array(lows, dtype=float)[:, None] if lows is not None else c * 0.98
    o = np.array(opens, dtype=float)[:, None] if opens is not None else c.copy()
    return {"open": o, "high": h, "low": lo, "close": c, "volume": np.full(c.shape, volume)}


def test_daily_features_use_nothing_after_their_row():
    rng = np.random.default_rng(1)
    closes = 10 * np.cumprod(1 + rng.normal(0, 0.02, 300))
    g = grid(closes)
    before = gs.daily_features(g)
    later = {k: v.copy() for k, v in g.items()}
    for k in ("open", "high", "low", "close", "volume"):
        later[k][250:] *= 3.0  # rewrite the future
    after = gs.daily_features(later)
    for name in before:
        assert np.allclose(before[name][:250], after[name][:250], equal_nan=True), name


def test_daily_features_hand_computed():
    closes = [10.0] * 60 + [11.0]
    g = grid(closes)
    f = gs.daily_features(g)
    assert f["chg_pct"][-1, 0] == pytest.approx(10.0)
    assert f["ret_5"][-1, 0] == pytest.approx(10.0)
    assert f["adr_pct"][-1, 0] == pytest.approx((1.02 / 0.98 - 1) * 100)
    assert f["dvol20"][-1, 0] == pytest.approx((19 * 10.0 + 11.0) / 20 * 1_000_000)
    assert f["up_days"][-1, 0] == 1
    assert f["surf10"][-1, 0] == pytest.approx(1.0)  # every close at or above its MA10


def test_neglect_counts_whole_months_inside_the_band():
    closes = np.array([10.0] * 100 + [10.5] * 10)
    months = gs.neglect_months(closes[:, None])
    assert months[-1, 0] == 5  # 109 sessions of history: 5 full months, all within ±25 %
    jumped = closes.copy()
    jumped[60] = 20.0  # one close 2x, 49 sessions back
    assert gs.neglect_months(jumped[:, None])[-1, 0] == 2


def test_gather_leaves_rows_before_the_first_session_empty():
    a = {"x": np.arange(6, dtype=float).reshape(3, 2)}
    out = gs.gather(a, np.array([-1, 2]), np.array([0, 1]))
    assert np.isnan(out["x"][0]) and out["x"][1] == 5


def run_exits(closes, entry, stop, side=1, extra=None, highs=None, lows=None, opens=None, k=30):
    g = grid(closes, highs, lows, opens)
    c = g["close"]
    lines = {
        "ma10": np.full_like(c, np.nan),
        "ma20": np.full_like(c, np.nan),
        "ema9": np.full_like(c, np.nan),
        "ema21": np.full_like(c, np.nan),
    }
    return (
        g,
        lines,
        intraday_exits.run(
            g,
            lines,
            np.array([0]),
            np.array([0]),
            np.array([entry]),
            np.array([stop]),
            np.array([side]),
            (np.array([False]), np.array([entry])),
            RULES,
            extra,
            k,
        ),
    )


def test_hold_days_and_r_targets():
    closes = [10, 10.5, 11.2, 12.5, 12.0] + [12.0] * 20
    highs = [10.1, 10.6, 11.4, 12.6, 12.1] + [12.1] * 20
    opens = [10, 10, 10.5, 11.2, 12.5] + [12.0] * 20  # each day opens at the prior close
    extra = {"mrev_mas": [], "r_targets": [1, 2], "r_target_days": 10}
    _, _, out = run_exits(closes, 10.0, 9.0, extra=extra, highs=highs, opens=opens)
    assert out["days_hold_5d"][0] == 5 and out["days_hold_1d"][0] == 1
    assert out["r_tgt1R_10d"][0] == pytest.approx(1.0) and out["days_tgt1R_10d"][0] == 2
    assert out["r_tgt2R_10d"][0] == pytest.approx(2.0) and out["days_tgt2R_10d"][0] == 3


def test_mean_reversion_exit_sells_at_yesterdays_ma():
    closes = [7.0, 7.5, 8.2, 8.9, 9.5] + [9.5] * 20
    highs = [7.1, 7.6, 8.4, 9.1, 9.6] + [9.6] * 20
    g = grid(closes, highs=highs)
    c = g["close"]
    ma10 = np.full_like(c, 9.0)  # a flat MA at 9: day 3's high (9.1) reaches it
    lines = {"ma10": ma10, "ma20": np.full_like(c, 20.0), "ema9": ma10, "ema21": ma10}
    out = intraday_exits.run(
        g,
        lines,
        np.array([0]),
        np.array([0]),
        np.array([7.0]),
        np.array([6.0]),
        np.array([1]),
        (np.array([False]), np.array([7.0])),
        RULES,
        {"mrev_mas": [10, 20], "r_targets": [], "r_target_days": 10},
        30,
    )
    assert out["r_mrev_ma10"][0] == pytest.approx(2.0) and out["days_mrev_ma10"][0] == 3
    # The 20-day MA (20.0) is never reached: out at the newest close inside the window.
    assert out["r_mrev_ma20"][0] == pytest.approx(2.5)


def test_partial_legs_add_up_to_the_blended_exit():
    closes = [10, 11, 12, 13, 14, 15, 13.5] + [13.5] * 20
    g = grid(closes)
    c = g["close"]
    ma = np.full_like(c, np.nan)
    ma[3:7, 0] = [12, 13, 14, 14.0]  # day 6 closes under it
    lines = {"ma10": ma, "ma20": ma, "ema9": ma, "ema21": ma}
    out = intraday_exits.run(
        g,
        lines,
        np.array([0]),
        np.array([0]),
        np.array([10.0]),
        np.array([9.0]),
        np.array([1]),
        (np.array([False]), np.array([10.0])),
        RULES,
        None,
        30,
    )
    frac = RULES["partial_fraction"]
    blended = frac * out["r_part3"][0] + (1 - frac) * out["r_rest3_ma10"][0]
    assert out["r_q3_ma10"][0] == pytest.approx(blended)
    assert out["r_part3"][0] == pytest.approx(3.0) and out["days_q3_ma10"][0] == 6


def test_regime_is_the_one_known_the_session_before():
    days = [dt.date(2024, 1, d) for d in (2, 3, 4, 5)]
    regime = pd.DataFrame(
        {
            "session_date": days,
            "light": ["GREEN", "RED", "STOP", "YELLOW"],
            "qqq_trend": "up",
            "breadth_state": "neutral",
            "scan_count": 20.0,
            "mkt_ratio_10d": 1.0,
        }
    )
    trades = pd.DataFrame({"session_date": [days[2], days[0]], "ticker": [A, A]})
    out = gs.add_regime(trades, regime, days)
    assert out["mkt_light"].tolist()[0] == "RED" and pd.isna(out["mkt_light"].iloc[1])


def year_inputs(tmp_path):
    days = clock.sessions_after(CFG.schedule, dt.date(2018, 6, 1), 420, dt.date(2019, 12, 31))
    frames = []
    for ticker in (A, F):
        frames.append(
            pd.DataFrame(
                {
                    "session_date": days,
                    "ticker": ticker,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10.0,
                    "volume": 2_000_000.0,
                }
            )
        )
    bars = pd.concat(frames, ignore_index=True)
    gap_day = dt.date(2019, 3, 15)
    on_gap = bars["session_date"] == gap_day
    bars.loc[on_gap, ["open", "high", "low", "close"]] = [11.5, 12.4, 11.3, 12.2]
    after = bars["session_date"] > gap_day
    bars.loc[after, ["open", "high", "low", "close"]] = [12.2, 12.5, 12.0, 12.3]
    bars["vwap"], bars["source"] = bars["close"], "alpaca"
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    for year in (2018, 2019):
        bars[pd.to_datetime(bars["session_date"]).dt.year == year].to_parquet(
            bars_dir / f"{year}.parquet"
        )
    minutes = tmp_path / "minutes"
    minutes.mkdir()
    rows = []
    for ticker in (A, F):
        start = pd.Timestamp(f"{gap_day} 09:30", tz="America/New_York")
        for m in range(390):
            price = 11.5 + 0.7 * m / 389
            rows.append(
                {
                    "ticker": ticker,
                    "ts": (start + pd.Timedelta(minutes=m)).tz_convert("UTC"),
                    "open": price,
                    "high": price + 0.02,
                    "low": price - 0.02,
                    "close": price,
                    "volume": 20_000,
                    "vwap": price,
                    "session_date": gap_day,
                    "kind": "evening",
                }
            )
    pd.DataFrame(rows).to_parquet(minutes / "2019-03_20260101000000.parquet")
    return bars_dir, minutes, gap_day


def test_a_year_keeps_stock_trades_with_features_and_drops_funds(tmp_path):
    bars_dir, minutes, gap_day = year_inputs(tmp_path)
    trades = gs.run_year(CFG, 2019, bars_dir, None, minutes, None, funds={F})
    assert len(trades) and set(trades["ticker"]) == {A}
    ep = trades[trades["strategy"] == "ep"]  # the flat days also reach their base's high
    assert set(ep["session_date"]) == {gap_day}
    row = ep[(ep["entry"] == "open") & (ep["stop_rule"] == "adr")].iloc[0]
    assert row["d_chg_pct"] == pytest.approx(0.0)  # the day before the gap, not the gap day
    assert row["open_gap_pct"] == pytest.approx(15.0)
    assert row["entry_minute"] == 570
    assert {"days_hold_5d", "r_part3", "r_mrev_ma10", "r_tgt2R_10d"} <= set(trades.columns)
    stops = trades["price"] - trades["stop"]
    assert (stops >= trades["price"] * CFG.intraday_study["min_stop_pct"] / 100 - 1e-6).all()


def test_setup_candidates_fetch_the_trigger_day_when_it_reaches_the_pivot(monkeypatch):
    from trading_os import intraday_study, patterns, qm_setups

    days = clock.sessions_after(CFG.schedule, dt.date(2024, 1, 2), 60, dt.date(2024, 12, 31))
    bars = pd.DataFrame(
        {
            "session_date": days,
            "ticker": A,
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.0,
            "volume": 2_000_000.0,
        }
    )
    g, tickers = intraday_study.daily(bars, days)
    hit = days[40]

    def qm(sub, part, sessions, conf):
        return pd.DataFrame(
            {
                "strategy": ["qm_surf", "qm_surf"],
                "session_date": [hit, days[45]],
                "ticker": [A, A],
                "pivot": [10.1, 11.0],  # the next day's high (10.2) reaches only the first
                "order_stop": [9.5, 10.0],
                "surf_ma": [10, 10],
            }
        )

    pp = pd.DataFrame({"strategy": ["pocket_pivot"], "session_date": [days[50]], "ticker": [A]})
    monkeypatch.setattr(qm_setups, "find", qm)
    monkeypatch.setattr(patterns, "find", lambda *a: pp)
    facts = intraday_study.prior_facts(g, CFG.universe["alert"])
    rows, pockets = intraday_study.setup_candidates(g, tickers, days, CFG, facts)
    assert rows["session_date"].tolist() == [days[41]] and rows["group"].tolist() == ["qm_surf"]
    assert rows["signal_date"].tolist() == [hit] and rows["surf_ma"].tolist() == [10]
    assert pockets["strategy"].tolist() == ["pocket_pivot"]


def test_ep_entries_inside_saxos_extended_hours():
    from trading_os import intraday_entries as ie
    from trading_os.intraday_study import params

    p = params(CFG)
    m = np.array([-460, -440, 400, 430, 570, 571])  # 16:20, 16:40 the evening before; 06:40, 07:10
    c = np.array([11.0, 11.2, 11.5, 11.6, 11.8, 11.9])
    v = np.array([40_000, 20_000, 60_000, 30_000, 100_000, 100_000], dtype=float)
    b = ie.Bars(m, c.copy(), c + 0.05, c - 0.05, c, v, c)
    rows = ie.gap(b, {"prev_close": 10.0, "adr_usd": 0.5}, p)
    ah = next(r for r in rows if r["entry"] == "ah_1645")
    assert ah["price"] == pytest.approx(11.2)  # +12 % on 60K shares by 16:45
    pm = next(r for r in rows if r["entry"] == "pm_0705" and r["stop_rule"] == "lod")
    assert pm["price"] == pytest.approx(11.5)  # the 06:40 bar: +15 %, 60K pre-market shares
