"""The board's cards and tiles render without errors (Streamlit's AppTest, synthetic data).
Skipped where the dashboard's packages aren't installed (CI installs the core only)."""

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _run(body: str) -> AppTest:
    script = "import sys; sys.path.insert(0, 'app')\nimport pandas as pd\nimport board\n" + body
    at = AppTest.from_string(script, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_position_cards_render():
    at = _run(
        "view = pd.DataFrame([{'ticker': 'AAA', 'setup': 'ep_am', 'direction': 'long',"
        " 'entry_avg': 20.0, 'order_stop': 18.0, 'open_quantity': 100, 'last_close': 22.0,"
        " 'entry_date': '2026-10-20'}])\n"
        "plan = pd.DataFrame([{'ticker': 'AAA', 'rule': 'hold', 'held': 5, 'hold': 21,"
        " 'action': '', 'earnings': None}])\n"
        "board.position_cards(view, plan, {'AAA': 23.0}, 'test', lambda t: None)\n"
    )
    labels = [m.label for m in at.metric]
    assert labels == ["Price", "Open R", "To stop"]
    assert at.metric[1].value == "+1.50R"


def test_market_tiles_render():
    at = _run(
        "board.market_tiles({'qqq_light': 'RED', 'spy_close': 700.0, 'spy_chg_pct': -0.5},"
        " {'state': 'correction', 'dist_count': 7}, 'Warm market')\n"
    )
    assert {m.label for m in at.metric} == {"QQQ light", "Market heat", "IBD market", "SPY"}


def test_lightweight_chart_page_has_the_data_and_levels():
    import sys

    import pandas as pd

    sys.path.insert(0, "app")
    import lwchart

    bars = pd.DataFrame(
        {
            "session_date": pd.date_range("2026-01-01", periods=60, freq="B"),
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 1e6,
        }
    )
    page = lwchart.html(bars, {"entry": 10.6, "stop": 9.4, "pivot": None}, 400)
    assert "lightweight-charts@4.1.3" in page and '"title": "stop"' in page
    assert '"title": "pivot"' not in page and page.count('"open": 10.0') == 60
    bench = bars.assign(close=5.0)
    lines = lwchart.indicator_lines(
        bars.assign(time=bars.session_date.dt.strftime("%Y-%m-%d")),
        ["MA 10", "AVWAP (signal day)", "RS vs QQQ"],
        anchor=bars.session_date.iloc[30],
        bench=bench,
    )
    names = {line["name"]: line for line in lines}
    assert len(names["MA 10"]["pts"]) == 51 and len(names["AVWAP (signal day)"]["pts"]) == 30
    assert names["RS vs QQQ"]["scale"] == "rs" and names["RS vs QQQ"]["pts"][0]["value"] == 2.1
    week = lwchart.weekly(bars)  # 1 Jan 2026 is a Thursday: a 2-day first week
    assert len(week) == 13 and week["volume"].iloc[0] == 2e6
