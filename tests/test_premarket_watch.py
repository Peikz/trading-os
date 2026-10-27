"""The close's setups (Luk flush, EP9M AVWAP, MA-surf, the parabolics): found at the close,
pushed in the after-hours push with EP-AH and their after-hours move (Emil, 27 Oct 2026; they
came the next morning before). The other close scans are saved for the dashboard. Synthetic
data only."""

import datetime as dt
from pathlib import Path

import pandas as pd

from trading_os import job, notify
from trading_os.config import load_config
from trading_os.store import RunContext

A = "".join(["S", "R", "F"])
LATER = ("ma_surf", "parabolic_long", "parabolic_short", "luk_flush", "ep9m_avwap")
SAVED_ONLY = ("breakout_watch", "mb_up", "luk_pullback", "vcp", "ep_day", "ep9m",
              "breakout_trigger", "minervini_tt")  # fmt: skip


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
        run_ts=pd.Timestamp("2026-10-22T20:50:00Z"),
        run_kind="scheduled",
        forced=False,
    )


def test_the_close_setups_wait_for_the_after_hours_push():
    cfg = load_config()
    for name in LATER:
        scan = cfg.scans[name]
        assert scan.slot == "eod" and scan.params["push_slot"] == "ah"
        assert not notify.pushes_now(scan, "eod") and notify.pushes_now(scan, "ah")
        assert not notify.pushes_now(scan, "pm")
    for name in SAVED_ONLY:
        assert cfg.scans[name].action == "log"


def test_the_close_report_names_what_comes_after_hours():
    cfg = load_config()
    results = {"ma_surf": hit(), "breakout_watch": hit()}
    assert notify.select_for_push(results, cfg, "eod") == {}
    message = notify.build_message(ctx("eod"), results, {}, cfg)
    assert "In the after-hours push: MA-surf 1" in message.body
    assert "BO-Watch" not in message.body  # saved only
    assert "Study C, saved" not in message.body


def test_the_after_hours_block_shows_the_move_after_the_close():
    cfg = load_config()
    carried = {"ma_surf": hit(ah_price=10.4, ah_change_pct=4.0, carried_from="eod")}
    selected = notify.select_for_push(carried, cfg, "ah")
    message = notify.build_message(ctx("ah"), carried, selected, cfg)
    assert f"▸ {A}  MA10 12d  base 8d" in message.body
    assert "AH 10.40 +4.0%" in message.body and "PM" not in message.body
    assert notify.afterhours_line(hit(carried_from="eod").iloc[0].to_dict()) is None


def test_the_after_hours_run_carries_todays_close_hits(tmp_path: Path):
    cfg = load_config()
    today = dt.date(2026, 10, 22)
    folder = tmp_path / "data" / "candidates" / "2026"
    folder.mkdir(parents=True)
    pd.concat(
        [hit(scan="ma_surf"), hit(scan="ep9m"), hit(scan="parabolic_long", ah_price=1.0)]
    ).to_parquet(folder / f"{today}_eod.parquet")
    uni = pd.DataFrame({"ticker": [A], "ah_price": [10.3], "ah_change_pct": [3.0]})
    out = job._from_last_close(tmp_path, cfg, today, uni, "ah")
    assert set(out) == set(LATER)
    assert out["ma_surf"].iloc[0]["ah_price"] == 10.3  # this evening's, not the stored column
    assert out["parabolic_long"].iloc[0]["ah_price"] == 10.3
    assert out["luk_flush"].empty
    assert (out["ma_surf"]["carried_from"] == "eod").all()
    assert job._from_last_close(tmp_path, cfg, today, uni, "pm") == {}  # EP-PM only


def test_ep_ah_pushes_after_hours_only():
    cfg = load_config()
    scan = cfg.scans["ep_ah"]
    assert notify.pushes_now(scan, "ah") and not notify.pushes_now(scan, "pm")


def test_the_scans_read_their_live_flags():
    from trading_os.scans import REGISTRY

    cfg = load_config()
    uni = hit(
        tier="alert", dollar_volume=1e7, luk_pullback=True, vcp_watch=True, vcp_pivot=12.0,
        vcp_order_stop=11.4, vcp_risk_adr=1.0, vcp_base_len=30, minervini_tt=True, mm_rs=91.0,
    )  # fmt: skip
    vcp = REGISTRY["vcp"](uni, cfg.scans["vcp"]).iloc[0]
    assert (vcp["pivot"], vcp["order_stop"]) == (12.0, 11.4)
    assert len(REGISTRY["luk_pullback"](uni, cfg.scans["luk_pullback"])) == 1
    assert len(REGISTRY["minervini_tt"](uni, cfg.scans["minervini_tt"])) == 1
    empty = hit(tier="alert")
    assert REGISTRY["vcp"](empty, cfg.scans["vcp"]).empty
