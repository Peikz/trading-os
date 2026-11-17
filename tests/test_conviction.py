"""Conviction 1-3 on plans, fills and notes, and the closed-trades table by conviction
(synthetic data only)."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import conviction, dashboard, journal, journal_view, plans
from trading_os.config import load_config

CFG = load_config()
T1, T2, T3 = ("".join([c, "Z", "Q", c]) for c in "ABC")
MON, TUE, WED = dt.date(2026, 10, 19), dt.date(2026, 10, 20), dt.date(2026, 10, 21)


def test_normalize_accepts_levels_and_empty_only():
    assert [conviction.normalize(v) for v in (None, "", "none", float("nan"), pd.NA)] == [None] * 5
    assert [conviction.normalize(v) for v in (1, "2", 3.0)] == [1, 2, 3]
    for bad in (0, 4, "high", 2.5):
        with pytest.raises(ValueError):
            conviction.normalize(bad)


def test_by_conviction_counts_win_rate_and_r_by_hand():
    trades = pd.DataFrame(
        {
            "conviction": [3, 3, 3, 1, 1, None],
            "pnl": [300.0, 100.0, -100.0, -50.0, -20.0, 999.0],
            "r_multiple": [3.0, 1.0, -1.0, -0.5, None, 9.0],
        }
    )
    table = conviction.by_conviction(trades).set_index("conviction")
    assert list(table.index) == [1, 3]  # 2 has no trades, the untagged trade is left out
    three, one = table.loc[3], table.loc[1]
    assert three["trades"] == 3 and three["win_pct"] == pytest.approx(200 / 3)
    assert three["mean_r"] == pytest.approx(1.0) and three["total_r"] == pytest.approx(3.0)
    assert one["trades"] == 2 and one["win_pct"] == 0.0
    assert one["mean_r"] == pytest.approx(-0.5) and one["total_r"] == pytest.approx(-0.5)


def test_by_conviction_is_empty_without_the_column_or_trades():
    assert conviction.by_conviction(pd.DataFrame()).empty
    assert conviction.by_conviction(pd.DataFrame({"pnl": [1.0]})).empty
    untagged = pd.DataFrame({"conviction": [None], "pnl": [1.0], "r_multiple": [1.0]})
    assert conviction.by_conviction(untagged.astype({"conviction": "Int64"})).empty


def test_notes_keep_conviction_and_old_notes_have_none(tmp_path):
    t1 = dt.datetime(2026, 11, 2, 21, tzinfo=dt.UTC)
    t2 = dt.datetime(2026, 11, 3, 21, tzinfo=dt.UTC)
    # a note saved before the field existed: the old column set, written straight to parquet
    old = pd.DataFrame(
        [{"kind": "trade", "ref_id": "old", "grade": "A", "notes": "", "tags": "",
          "attachments": "", "saved_ts": pd.Timestamp(t1)}]
    )  # fmt: skip
    folder = tmp_path / "data" / "journal" / "notes" / "2026"
    folder.mkdir(parents=True)
    old.to_parquet(folder / "20261102T210000000000_trade_old.parquet")
    dashboard.save_note(tmp_path, "trade", "tr1", "B", "x", "", [], now=t1, conviction=2)
    dashboard.save_note(tmp_path, "trade", "tr1", "B", "x", "", [], now=t2, conviction=3)
    dashboard.save_note(tmp_path, "signal", "s1", "", "", "", [], now=t2)
    state = dashboard.notes_state(tmp_path).set_index(["kind", "ref_id"])
    assert state.loc[("trade", "tr1"), "conviction"] == 3  # the latest event wins
    assert pd.isna(state.loc[("trade", "old"), "conviction"])
    assert pd.isna(state.loc[("signal", "s1"), "conviction"])
    assert len(list(folder.glob("*.parquet"))) == 4  # append-only: nothing was rewritten
    with pytest.raises(ValueError):
        dashboard.save_note(tmp_path, "trade", "x", "A", "", "", [], conviction=7)


def test_manual_fill_conviction_reaches_trades_open_and_closed(tmp_path):
    buy = journal.manual_fill(MON, T1, "buy", 100, 10.0, conviction=3)
    _, open_ = journal.log_manual(tmp_path, CFG, buy, stop=9.5)
    assert open_["conviction"].iloc[0] == 3
    trades, _ = journal.log_manual(tmp_path, CFG, journal.manual_fill(WED, T1, "sell", 100, 11.0))
    assert trades["conviction"].iloc[0] == 3
    # a fill without one stays empty, and loads fine next to fills that have one
    journal.log_manual(tmp_path, CFG, journal.manual_fill(MON, T2, "buy", 10, 5.0))
    fills = journal.load_fills(tmp_path)
    assert fills[fills["ticker"] == T1]["conviction"].iloc[0] == 3
    assert fills[fills["ticker"] == T2]["conviction"].isna().all()


def test_a_filled_plan_hands_its_conviction_to_the_trade(tmp_path):
    plans.create(tmp_path, MON, T1, "long", 10.0, 9.5, 100, conviction=2)
    plans.create(tmp_path, MON, T2, "long", 10.0, 9.5, 100)
    journal.log_manual(tmp_path, CFG, journal.manual_fill(TUE, T1, "buy", 100, 10.0), stop=9.5)
    _, open_ = journal.log_manual(tmp_path, CFG, journal.manual_fill(TUE, T2, "buy", 100, 10.0))
    by_ticker = open_.set_index("ticker")["conviction"]
    assert by_ticker[T1] == 2 and pd.isna(by_ticker[T2])
    table = plans.load(tmp_path)
    assert sorted(table["conviction"].dropna()) == [2]


def test_plans_saved_before_the_field_still_load(tmp_path):
    folder = plans.folder(tmp_path)
    folder.mkdir(parents=True)
    old = pd.DataFrame(
        [{"plan_id": "p1", "action": "create", "saved_ts": pd.Timestamp("2026-10-19"),
          "session_date": MON, "ticker": T1, "direction": "long", "setup": None,
          "entry": 10.0, "stop": 9.0, "shares": 5, "risk_usd": 5.0, "position_usd": 50.0,
          "note": ""}]
    )  # fmt: skip
    old.to_parquet(folder / "20261019T000000000000_create.parquet")
    plans.create(tmp_path, MON, T2, "long", 10.0, 9.0, 5, conviction=1)
    loaded = plans.load(tmp_path).set_index("ticker")
    assert pd.isna(loaded.loc[T1, "conviction"]) and loaded.loc[T2, "conviction"] == 1


def test_closed_trades_take_the_note_over_the_fill(tmp_path):
    buy = journal.manual_fill(MON, T1, "buy", 100, 10.0, conviction=1)
    journal.log_manual(tmp_path, CFG, buy, stop=9.5)
    journal.log_manual(tmp_path, CFG, journal.manual_fill(WED, T1, "sell", 100, 11.0))
    journal.log_manual(tmp_path, CFG, journal.manual_fill(MON, T3, "buy", 100, 10.0), stop=9.5)
    journal.log_manual(tmp_path, CFG, journal.manual_fill(WED, T3, "sell", 100, 9.0))
    trades = dashboard.latest_journal(tmp_path)
    first = trades[trades["ticker"] == T1]["trade_id"].iloc[0]
    quiet = trades[trades["ticker"] == T3]["trade_id"].iloc[0]
    assert journal_view.with_conviction(trades, {}).dropna().tolist() == [1]  # from the fill
    noted = journal_view.with_conviction(trades, {first: 3, quiet: 2}).tolist()
    assert sorted(noted) == [2, 3]  # the notes win and fill the empty one
    table = journal_view.conviction_table(trades.assign(conviction=[3, 2]))
    assert table["trades"].sum() == 2
