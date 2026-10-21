"""BO-Watch, MA-surf and the parabolics: found at the close, pushed the next morning with the
pre-market move (Emil, 21 Oct 2026). Synthetic data only."""

import datetime as dt
from pathlib import Path

import pandas as pd

from trading_os import job, notify
from trading_os.config import load_config
from trading_os.store import RunContext

A = "".join(["S", "R", "F"])
LATER = ("breakout_watch", "ma_surf", "parabolic_long", "parabolic_short")
CARRIED = (*LATER, "luk_flush")  # Luk flush: pushed at EOD and again pre-market


def hit(**kw):
    row = {
        "ticker": A,
        "tier": "alert",
        "rank": 1,
        "grade": "C",
        "close": 10.0,
        "adr20_usd": 0.5,
        "pivot": 10.2,
        "order_stop": 9.7,
        "chg_pct": 3.0,
        "rvol50": 1.5,
        "dollar_volume": 4e7,
        "surf_ma": 10.0,
        "surf_days": 12.0,
        "surf_base_len": 8.0,
    }
    return pd.DataFrame([row | kw])


def ctx(slot):
    return RunContext(
        session=dt.date(2026, 10, 22),
        slot=slot,
        run_ts=pd.Timestamp("2026-10-22T11:17:00Z"),
        run_kind="scheduled",
        forced=False,
    )


def test_the_four_scans_wait_for_the_premarket_push():
    cfg = load_config()
    for name in LATER:
        scan = cfg.scans[name]
        assert scan.slot == "eod" and scan.params["push_slot"] == "pm"
        assert not notify.pushes_now(scan, "eod") and notify.pushes_now(scan, "pm")
    luk = cfg.scans["luk_flush"]
    assert notify.pushes_now(luk, "eod") and notify.pushes_now(luk, "pm")
    for name in ("ep_day", "ep9m", "breakout_trigger"):  # saved only since 21 Oct 2026
        assert not notify.pushes_now(cfg.scans[name], "eod")


def test_the_evening_push_names_what_comes_in_the_morning():
    cfg = load_config()
    results = {"ma_surf": hit(), "breakout_watch": hit()}
    assert notify.select_for_push(results, cfg, "eod") == {}
    message = notify.build_message(ctx("eod"), results, {}, cfg)
    assert "In the pre-market push: MA-surf 1 · BO-Watch 1" in message.body
    assert "Study C, saved" not in message.body


def test_the_premarket_block_shows_the_move_against_the_pivot():
    cfg = load_config()
    carried = {"ma_surf": hit(pm_price=10.71, pm_change_pct=7.1, carried_from="eod")}
    selected = notify.select_for_push(carried, cfg, "pm")
    message = notify.build_message(ctx("pm"), carried, selected, cfg)
    assert f"▸ {A}  MA10 12d  base 8d" in message.body
    assert "PM 10.71 +7.1% · +5.0% vs pivot · ⚠️ up > 1 ADR" in message.body
    quiet = notify.premarket_line(hit(carried_from="eod").iloc[0].to_dict())
    assert quiet == "PM: no trade yet"


def test_the_premarket_run_carries_last_closes_hits(tmp_path: Path):
    cfg = load_config()
    last = dt.date(2026, 10, 21)
    folder = tmp_path / "data" / "candidates" / "2026"
    folder.mkdir(parents=True)
    pd.concat(
        [hit(scan="ma_surf"), hit(scan="ep9m"), hit(scan="parabolic_long", pm_price=1.0)]
    ).to_parquet(folder / f"{last}_eod.parquet")
    uni = pd.DataFrame({"ticker": [A], "pm_price": [10.3], "pm_change_pct": [3.0]})
    out = job._from_last_close(tmp_path, cfg, dt.date(2026, 10, 22), uni)
    assert set(out) == set(CARRIED)
    assert out["ma_surf"].iloc[0]["pm_price"] == 10.3  # today's, not the stored column
    assert out["parabolic_long"].iloc[0]["pm_price"] == 10.3
    assert out["breakout_watch"].empty
    assert (out["ma_surf"]["carried_from"] == "eod").all()
