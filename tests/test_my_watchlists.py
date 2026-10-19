"""Own watchlists: parsing, add/remove history, market facts (synthetic data only)."""

import pandas as pd

from trading_os import my_watchlists as wl

A, B, C = ("".join(["W", "L", x]) for x in "ABC")


def test_parse_reads_typed_lists_and_tradingview_exports():
    assert wl.parse_tickers(f"{A}, {B} {A};{C}") == [A, B, C]
    export = f"###Leaders,NASDAQ:{A},NYSE:{B}\n###Other,AMEX:{C}"
    assert wl.parse_tickers(export) == [A, B, C]
    assert wl.parse_tickers("") == []


def test_members_follow_the_latest_add_or_remove(tmp_path):
    wl.add(tmp_path, "Leaders", [A, B], note="base")
    wl.add(tmp_path, "Earnings", [C])
    wl.remove(tmp_path, "Leaders", [A])
    events = wl.load(tmp_path)
    now = wl.current(events)
    assert wl.lists(events) == ["Earnings", "Leaders"]
    assert now[now["list"] == "Leaders"]["ticker"].tolist() == [B]
    wl.add(tmp_path, "Leaders", [A])  # back again
    assert sorted(wl.current(wl.load(tmp_path)).query("list == 'Leaders'")["ticker"]) == [A, B]


def test_an_empty_name_is_refused(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        wl.add(tmp_path, "  ", [A])


def test_market_facts_and_todays_scans_join_the_members():
    members = pd.DataFrame(
        {"list": ["L", "L"], "ticker": [A, B], "note": ["", ""], "added": [0, 0]}
    )
    universe = pd.DataFrame({"ticker": [A], "close": [10.0], "bo_pivot": [11.0], "rvol50": [2.0]})
    hits = pd.DataFrame({"ticker": [A, A], "scan": ["ep_day", "mb_up"]})
    out = wl.with_market(members, universe, hits).set_index("ticker")
    assert round(out.loc[A, "to_pivot_pct"], 6) == 10.0
    assert out.loc[A, "in_scans"] == "ep_day, mb_up"
    assert out.loc[B, "in_scans"] == "" and pd.isna(out.loc[B, "close"])
