"""The Chart page's stock lists (synthetic data only)."""

import pandas as pd

from trading_os import chart_lists as cl


def test_where_is_prefers_given_list():
    lists = {
        "A": pd.DataFrame({"ticker": ["X1", "X2"]}),
        "B": pd.DataFrame({"ticker": ["X2", "X3"]}),
    }
    assert cl.where_is(lists, "X2", "B") == "B"
    assert cl.where_is(lists, "X2", "A") == "A"
    assert cl.where_is(lists, "X3", "A") == "B"
    assert cl.where_is(lists, "ZZ") is None


def test_neighbour_wraps_and_handles_missing():
    t = ["X1", "X2", "X3"]
    assert cl.neighbour(t, "X3", 1) == "X1"
    assert cl.neighbour(t, "X1", -1) == "X3"
    assert cl.neighbour(t, "typed", 1) == "X1"
    assert cl.neighbour(t, "typed", -1) == "X3"
    assert cl.neighbour([], "X1", 1) is None


def test_with_prices_and_labels():
    rows = pd.DataFrame({"ticker": ["X1", "X2"], "setup": ["EP", ""], "grade": ["A", ""]})
    snap = pd.DataFrame({"ticker": ["X1"], "close": [12.5], "chg_pct": [-1.25]})
    out = cl.with_prices(rows, snap)
    assert list(out.columns) == cl.COLUMNS
    first, second = out.to_dict("records")
    assert ":red[-1.2%]" in cl.row_label(first) or ":red[-1.3%]" in cl.row_label(first)
    assert "EP A" in cl.row_label(first)
    assert cl.row_label(second) == "**X2**"
    assert cl.row_label(first, chips=True).startswith("**X1**")
    assert cl.with_prices(rows, None)["close"].isna().all()


def test_hit_rows_order_by_grade_then_pushed(tmp_path):
    from types import SimpleNamespace

    frames = {
        "f": pd.DataFrame(
            {
                "ticker": ["U1", "B1", "A1", "P1", "NP", "AP"],
                "scan": ["ep"] * 6,
                "tier": ["alert"] * 6,
                "grade": [None, "B", "A", "C", "C", "A+"],
                "pushed": [False, False, False, True, False, False],
            }
        )
    }
    runs = [SimpleNamespace(session="d", candidates="f")]
    out = cl.hit_rows(runs, lambda k: frames[k])
    assert list(out["ticker"]) == ["AP", "A1", "B1", "P1", "NP", "U1"]
