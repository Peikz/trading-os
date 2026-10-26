import datetime as dt

import pandas as pd
import pytest

from trading_os import store

CTX = store.RunContext(
    session=dt.date(2026, 10, 19),
    slot="eod",
    run_ts=dt.datetime(2026, 10, 19, 20, 18, 5, tzinfo=dt.UTC),
    run_kind="scheduled",
)
FORCED = store.RunContext(
    session=dt.date(2026, 10, 16),
    slot="eod",
    run_ts=dt.datetime(2026, 10, 18, 20, 40, 1, tzinfo=dt.UTC),
    run_kind="manual",
    forced=True,
)


def hits():
    return pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "rank": [1, 2],
            "tier": ["alert", "log"],
            "gap_pct": [25.0, 12.0],
            "chg_pct": [20.0, 8.0],
            "rvol50": [6.0, 3.5],
            "rvol_basis": ["tv_avg60d_excl_today"] * 2,
            "rvol10_tv": [7.0, 4.0],
            "volume": [2_000_000, 400_000],
            "dollar_volume": [40_000_000.0, 4_000_000.0],
            "close": [20.0, 10.0],
            "market_cap": [900_000_000.0, 60_000_000.0],
            "avg_volume_20d": [600_000.0, 200_000.0],
            "earnings_flag": [True, False],
        }
    )


def test_signal_id_is_stable_and_distinct():
    a = store.signal_id(dt.date(2026, 10, 19), "eod", "ep_day", "AAA")
    assert a == store.signal_id(dt.date(2026, 10, 19), "eod", "ep_day", "AAA")
    assert a != store.signal_id(dt.date(2026, 10, 19), "eod", "ep_day", "AAB")
    assert len(a) == 16


def test_canonical_and_forced_paths(tmp_path):
    canonical = store.run_paths(tmp_path, CTX)
    assert canonical["universe"] == tmp_path / "data/universe/2026/2026-10-19_eod.parquet"
    assert canonical["candidates"] == tmp_path / "data/candidates/2026/2026-10-19_eod.parquet"
    assert canonical["export"] == tmp_path / "data/exports/2026-10-19_eod.xlsx"
    forced = store.run_paths(tmp_path, FORCED)
    assert forced["universe"] == tmp_path / "data/manual/2026-10-16_eod_204001/universe.parquet"


def test_candidates_layout_and_pushed_flag():
    out = store.build_candidates({"ep_day": hits()}, CTX, {"ep_day": {"AAA"}})
    assert list(out.columns[: len(store.SPEC_CANDIDATE_COLUMNS)]) == store.SPEC_CANDIDATE_COLUMNS
    assert out["pushed"].tolist() == [True, False]
    assert out["tier"].tolist() == ["alert", "log"]
    assert out["b1"].isna().all() and out["pivot"].isna().all()
    assert (out["run_kind"] == "scheduled").all()


def test_the_tags_are_saved():
    tagged = hits().assign(ibd_state="correction", ibd_dist=7, si_tag=["⚠️ shorted", None])
    out = store.build_candidates({"ep_day": tagged}, CTX, {})
    assert out["ibd_state"].tolist() == ["correction", "correction"]
    assert out["ibd_dist"].tolist() == [7, 7] and out["si_tag"].iloc[0] == "⚠️ shorted"
    assert out["heat_tag"].isna().all()


def test_empty_results_still_have_schema():
    out = store.build_candidates({"ep_day": hits().iloc[0:0]}, CTX, {})
    assert out.empty
    assert set(store.SPEC_CANDIDATE_COLUMNS) <= set(out.columns)


def test_write_run_round_trip_and_refuses_overwrite(tmp_path):
    universe = hits().drop(columns=["rank"])
    candidates = store.build_candidates({"ep_day": hits()}, CTX, {"ep_day": {"AAA"}})
    paths = store.write_run(tmp_path, CTX, universe, candidates)
    assert all(p.exists() for p in paths.values())
    assert not list(tmp_path.rglob("*.tmp"))
    back = pd.read_parquet(paths["candidates"])
    assert back["ticker"].tolist() == ["AAA", "BBB"]
    assert back["run_ts"].iloc[0] == pd.Timestamp(CTX.run_ts)
    uni = pd.read_parquet(paths["universe"])
    assert {"run_ts", "session_date", "slot", "run_kind", "data_source"} <= set(uni.columns)
    assert store.already_done(tmp_path, CTX.session, "eod")
    with pytest.raises(store.AlreadyWritten):
        store.write_run(tmp_path, CTX, universe, candidates)


def test_forced_run_does_not_mark_session_done(tmp_path):
    candidates = store.build_candidates({"ep_day": hits()}, FORCED, {})
    store.write_run(tmp_path, FORCED, hits(), candidates)
    assert not store.already_done(tmp_path, FORCED.session, "eod")
