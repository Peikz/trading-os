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
