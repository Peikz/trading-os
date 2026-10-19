"""EP-Watch / BO-Watch event log (SPEC §7): add, refresh, move, trigger, expire."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import watchlists as wl
from trading_os.config import load_config
from trading_os.scans.ep import watchlist_gappers

D = dt.date(2026, 10, 19)


@pytest.fixture(scope="module")
def rules():
    return load_config().watchlists


def hits(*tickers, tier="alert"):
    return pd.DataFrame({"ticker": list(tickers), "tier": tier})


def state_of(*events):
    df = pd.DataFrame([e | {"run_ts": pd.Timestamp("2026-10-01", tz="UTC")} for e in events])
    return wl.current(df)


def event(ticker, list_name, status, status_date, added=None, source="s0"):
    return {
        "ticker": ticker,
        "list": list_name,
        "status": status,
        "status_date": status_date,
        "added_date": added or status_date,
        "source_signal_id": source,
        "reason": "",
    }


def since(days):
    return lambda day: days


def test_ep_hit_enters_ep_watch_once(rules):
    new = wl.update(wl.current(pd.DataFrame()), {"ep_day": hits("GAP")}, D, "eod", since(0), rules)
    assert new[["ticker", "list", "status"]].values.tolist() == [["GAP", "ep_watch", "active"]]
    state = state_of(event("GAP", "ep_watch", "active", dt.date(2026, 10, 15)))
    again = wl.update(state, {"ep_day": hits("GAP")}, D, "eod", since(2), rules)
    assert again.empty  # already active: no duplicate


def test_log_tier_hits_do_not_enter(rules):
    new = wl.update(
        wl.current(pd.DataFrame()), {"ep_day": hits("LOW", tier="log")}, D, "eod", since(0), rules
    )
    assert new.empty


def test_qualifying_ep_name_moves_to_bo_watch(rules):
    state = state_of(event("GAP", "ep_watch", "active", dt.date(2026, 10, 1)))
    new = wl.update(state, {"breakout_watch": hits("GAP")}, D, "eod", since(12), rules)
    rows = {(r["list"], r["status"], r["reason"]) for r in new.to_dict("records")}
    assert rows == {
        ("bo_watch", "active", "B1-B4 pass"),
        ("ep_watch", "expired", "moved to bo_watch"),
    }


def test_bo_watch_refresh_trigger_and_staleness(rules):
    added = dt.date(2026, 10, 5)
    state = state_of(event("BASE", "bo_watch", "active", dt.date(2026, 10, 16), added=added))
    refresh = wl.update(state, {"breakout_watch": hits("BASE")}, D, "eod", since(1), rules)
    assert refresh.iloc[0]["reason"] == "refresh" and refresh.iloc[0]["added_date"] == added
    fired = wl.update(state, {"breakout_trigger": hits("BASE")}, D, "eod", since(1), rules)
    assert fired.iloc[0]["status"] == "triggered"
    quiet = wl.update(state, {}, D, "eod", since(10), rules)
    assert quiet.empty  # 10 sessions is still within bo_watch_stale_sessions
    stale = wl.update(state, {}, D, "eod", since(11), rules)
    assert stale.iloc[0]["status"] == "expired" and stale.iloc[0]["reason"] == "stale"


def test_ep_watch_max_age(rules):
    state = state_of(event("OLD", "ep_watch", "active", dt.date(2026, 7, 1)))
    assert wl.update(state, {}, D, "eod", since(63), rules).empty
    expired = wl.update(state, {}, D, "eod", since(64), rules)
    assert expired.iloc[0]["reason"] == "max age"


def test_current_takes_the_latest_event():
    events = pd.DataFrame(
        [
            event("A", "bo_watch", "active", dt.date(2026, 10, 1))
            | {"run_ts": pd.Timestamp("2026-10-01", tz="UTC")},
            event("A", "bo_watch", "triggered", dt.date(2026, 10, 2))
            | {"run_ts": pd.Timestamp("2026-10-02", tz="UTC")},
        ]
    )
    state = wl.current(events)
    assert state["status"].tolist() == ["triggered"] and wl.active(state, "bo_watch") == set()


def test_watchlist_gappers_need_list_membership_and_gap():
    scan = load_config().scans["watchlist_gappers"]
    df = pd.DataFrame(
        {
            "ticker": ["ON", "OFF", "SMALL"],
            "on_bo_watch": [True, False, True],
            "on_ep_watch": [False, False, False],
            "pm_change_pct": [3.0, 9.0, 1.99],
            "pm_gap_pct": [0.0, 0.0, 0.0],
        }
    )
    assert watchlist_gappers(df, scan)["ticker"].tolist() == ["ON"]
