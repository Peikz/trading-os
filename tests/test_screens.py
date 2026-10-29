"""Your own screens (Emil, 29 Oct 2026): filters over the universe and saved screens.
Synthetic data only."""

import pandas as pd
import pytest

from trading_os import screens

A, B, C = ("".join(x) for x in (["A", "A", "A"], ["B", "B", "B"], ["C", "C", "C"]))


def universe():
    return pd.DataFrame(
        {
            "ticker": [A, B, C, A],  # a repeated row is shown once
            "close": [10.0, 50.0, 3.0, 10.0],
            "adr20_pct": [5.0, 2.0, 8.0, 5.0],
            "ret_63": [80.0, 10.0, None, 80.0],
            "above_ma20": [True, False, True, True],
            "sector": ["Tech", "Health", "Tech", "Tech"],
        }
    )


def test_filters_combine_and_a_missing_value_never_passes():
    out = screens.run(universe(), [
        {"field": "adr20_pct", "op": ">=", "value": 4},
        {"field": "ret_63", "op": ">=", "value": 50},
    ])  # fmt: skip
    assert out["ticker"].tolist() == [A]  # C has ADR 8 but no 3-month return


def test_between_yes_no_and_one_of():
    df = universe()
    between = screens.run(df, [{"field": "close", "op": "between", "value": [5, 60]}], "close")
    assert between["ticker"].tolist() == [B, A]  # highest first
    assert screens.run(df, [{"field": "above_ma20", "op": "is no"}])["ticker"].tolist() == [B]
    tech = screens.run(df, [{"field": "sector", "op": "is not one of", "value": ["Tech"]}])
    assert tech["ticker"].tolist() == [B]
    open_end = screens.run(df, [{"field": "close", "op": "between", "value": [None, 9]}])
    assert open_end["ticker"].tolist() == [C]


def test_unknown_fields_or_operators_are_refused():
    with pytest.raises(ValueError):
        screens.run(universe(), [{"field": "nope", "op": ">=", "value": 1}])
    with pytest.raises(ValueError):
        screens.run(universe(), [{"field": "sector", "op": ">=", "value": 1}])


def test_saved_screens_round_trip(tmp_path):
    filters = [{"field": "adr20_pct", "op": ">=", "value": 4, "_id": 3}]
    screens.save(tmp_path, "  Fast movers ", filters, "ret_63")
    saved = screens.load(tmp_path)
    assert saved == {"Fast movers": {"filters": [{"field": "adr20_pct", "op": ">=", "value": 4}],
                                     "sort": "ret_63", "descending": True}}  # fmt: skip
    screens.delete(tmp_path, "Fast movers")
    assert screens.load(tmp_path) == {}
    with pytest.raises(ValueError):
        screens.save(tmp_path, " ", filters, None)


def test_the_examples_use_known_fields_and_read_well():
    for spec in screens.EXAMPLES.values():
        screens.check(spec["filters"])
    assert screens.describe({"field": "adr20_pct", "op": ">=", "value": 4}) == "ADR % (20d) >= 4"
    assert screens.describe({"field": "above_ma20", "op": "is yes"}) == "Above MA20 yes"
