"""Outcomes against hand-computed windows."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import history, outcomes, store

DAYS = [dt.date(2026, 10, d) for d in (5, 6, 7, 8, 9, 12, 13)]  # D0 = 5 Oct, then 6 sessions
TS = pd.Timestamp("2026-10-13 22:00", tz="UTC")


def bars():
    #            D0    D1    D2    D3    D4    D5    D6
    opens = [10.2, 10.0, 11.0, 10.4, 12.0, 12.0, 12.0]
    highs = [10.5, 11.0, 12.0, 10.5, 13.0, 12.0, 12.5]
    lows = [9.8, 9.5, 10.0, 9.0, 11.0, 11.5, 11.0]
    closes = [10.0, 10.5, 11.0, 10.0, 12.0, 12.0, 11.5]
    return pd.DataFrame(
        {
            "ticker": "AAA",
            "session_date": DAYS,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "source": "tradingview",
        }
    )


def window(signal, slot, n):
    after = [d for d in DAYS if d > signal]
    days = [signal, *after][:n] if slot == "pm" else after[:n]
    return days


def candidate(signal_id="s1", slot="eod", order_stop=None):
    return {
        "signal_id": signal_id,
        "scan": "ep_day",
        "ticker": "AAA",
        "session_date": DAYS[0],
        "slot": slot,
        "order_stop": order_stop,
    }


def run(cands, horizons=(5,), done=frozenset(), bar_frame=None):
    return outcomes.compute_outcomes(
        pd.DataFrame(cands),
        bars() if bar_frame is None else bar_frame,
        horizons,
        window,
        set(done),
        TS,
    )


def test_eod_signal_five_sessions():
    [row] = run([candidate()]).to_dict("records")
    # Entry: D0 close 10. Window D1..D5: max high 13, min low 9, last close 12.
    assert row["entry_price"] == 10.0 and row["entry_basis"] == "close"
    assert row["max_gain_pct"] == pytest.approx(30.0)
    assert row["max_drawdown_pct"] == pytest.approx(-10.0)
    assert row["close_ret_pct"] == pytest.approx(20.0)
    assert pd.isna(row["hit_order_stop"]) and pd.isna(row["r_hypothetical"])


def test_breakout_stop_and_r():
    [row] = run([candidate(order_stop=9.2)]).to_dict("records")
    assert bool(row["hit_order_stop"])  # D3 low 9.0 <= 9.2
    assert row["r_hypothetical"] == pytest.approx((12.0 - 10.0) / (10.0 - 9.2))


def test_premarket_signal_enters_at_the_open_and_counts_the_session():
    [row] = run([candidate(slot="pm")]).to_dict("records")
    # Entry: D0 open 10.2. Window D0..D4: max high 13, min low 9, last close 12.
    assert row["entry_basis"] == "open"
    assert row["max_gain_pct"] == pytest.approx((13 / 10.2 - 1) * 100)
    assert row["close_ret_pct"] == pytest.approx((12 / 10.2 - 1) * 100)


def test_intraday_signal_enters_at_the_price_the_run_saw():
    [row] = run([candidate(slot="am") | {"close": 10.4}]).to_dict("records")
    # Entry 10.40 during D0. Window D1..D5 like EOD: max high 13, last close 12.
    assert row["entry_basis"] == "signal" and row["entry_price"] == 10.4
    assert row["max_gain_pct"] == pytest.approx((13 / 10.4 - 1) * 100)


def test_unmatured_done_and_incomplete_are_skipped():
    assert run([candidate()], horizons=(10,)).empty  # only 6 sessions after D0
    assert run([candidate()], done={("s1", 5)}).empty
    gappy = bars().drop(index=3)  # D3 missing
    assert run([candidate()], bar_frame=gappy).empty


def test_write_once(tmp_path):
    out = run([candidate()])
    outcomes.write_outcomes(tmp_path, DAYS[-1], out)
    assert outcomes.done_pairs(tmp_path) == {("s1", 5)}
    with pytest.raises(outcomes.AlreadyWritten):
        outcomes.write_outcomes(tmp_path, DAYS[-1], out)


def test_job_end_to_end_from_eod_snapshots(tmp_path, capsys):
    signal = dt.date(2026, 10, 5)
    days = [dt.date(2026, 10, d) for d in (5, 6, 7, 8, 9, 12)]
    for i, day in enumerate(days):
        snap = pd.DataFrame(
            {
                "run_ts": [pd.Timestamp(f"{day} 20:17", tz="UTC")],
                "session_date": [pd.Timestamp(day)],
                "ticker": ["AAA"],
                "open": [10.0 + i],
                "high": [10.5 + i],
                "low": [9.5 + i],
                "close": [10.0 + i],
                "volume": [1000],
            }
        )
        path = history.universe_snapshot_path(tmp_path, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        snap.to_parquet(path, index=False)
    ctx = store.RunContext(signal, "eod", pd.Timestamp(f"{signal} 20:17", tz="UTC"), "scheduled")
    hits = pd.DataFrame({"ticker": ["AAA"], "rank": [1], "tier": ["alert"]})
    candidates = store.build_candidates({"ep_day": hits}, ctx, {})
    path = store.run_paths(tmp_path, ctx)["candidates"]
    path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_parquet(path, index=False)

    assert outcomes.main(["--data-dir", str(tmp_path), "--force"]) == 0
    assert "Outcomes: 1 written (5d: 1)" in capsys.readouterr().out
    [written] = (tmp_path / "data" / "outcomes").glob("*/*.parquet")
    row = pd.read_parquet(written).iloc[0]
    # Entry 10 (5 Oct close); window 6-12 Oct: max high 15.5, last close 15.
    assert row["max_gain_pct"] == pytest.approx(55.0)
    assert row["close_ret_pct"] == pytest.approx(50.0)
    assert row["bars_source"] == "tradingview"
