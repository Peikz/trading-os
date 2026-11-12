import pandas as pd

from trading_os import board_data, float_size, live_tracking


def test_band_and_tag():
    assert float_size.band(150e6) == "<300M"
    assert float_size.band(1e9) == "300M-2B"
    assert float_size.band(5e9) == ">2B"
    assert float_size.band(None) is None and float_size.band(0) is None
    assert float_size.tag(180e6).startswith("🔸 Small float $180M")
    assert float_size.tag(1e9) is None


def test_attach_adds_columns_only_where_float_and_price_exist():
    hits = pd.DataFrame(
        {"ticker": ["A", "B"], "float_shares": [10e6, 500e6], "close": [15.0, 20.0]}
    )
    other = pd.DataFrame({"ticker": ["C"], "close": [5.0]})
    out = float_size.attach({"ep": hits, "x": other, "empty": pd.DataFrame()})
    assert list(out["ep"]["float_usd"]) == [150e6, 10e9]
    assert list(out["ep"]["float_band"]) == ["<300M", ">2B"]
    assert out["ep"]["float_tag"].iloc[0].startswith("🔸")
    assert pd.isna(out["ep"]["float_tag"].iloc[1])
    assert "float_usd" not in out["x"]


def test_card_shows_the_tag_and_the_float_in_dollars():
    row = {"float_shares": 10e6, "float_usd": 150e6, "float_tag": float_size.tag(150e6)}
    assert any(t.startswith("🔸 Small float") for t in board_data.tags(row))
    chips = dict(board_data.key_stats(row))
    assert chips["Float"] == "10M · $150M"
    assert dict(board_data.key_stats({"float_shares": 10e6}))["Float"] == "10M"  # older rows


def test_live_check_splits_closed_trades_by_float_band():
    res = pd.DataFrame(
        {
            "grade_strategy": ["ep9m"] * 4,
            "grade": ["A+"] * 4,
            "status": ["closed", "closed", "closed", "open"],
            "r_net": [1.0, -1.0, 2.0, 5.0],
            "float_band": ["<300M", "<300M", None, ">2B"],
        }
    )
    out = live_tracking.by_float(res).set_index("float_band")
    assert out.loc["<300M", "closed"] == 2 and out.loc["<300M", "live_mean_r"] == 0.0
    assert out.loc["unknown", "closed"] == 1
    assert ">2B" not in out.index  # still open
