import datetime as dt

import pandas as pd
import pytest

from trading_os import cats
from trading_os.config import load_config


@pytest.fixture(scope="module")
def rules():
    return load_config().cats


def row(ticker, **kw):
    base = {
        "ticker": ticker,
        "avg_volume_30d_tv": 1_000_000.0,
        "avg_volume_90d_tv": 800_000.0,
        "dist_ma10_adr": 1.0,
    }
    return base | kw


def test_components_add_up(rules):
    hits = pd.DataFrame(
        [
            row("ALL"),  # growth + recent + rising volume, not extended: 3
            row("EXT", dist_ma10_adr=5.0),  # 2 ADR beyond the free 3: −1.0, volume +1
            row("NONE", avg_volume_30d_tv=700_000.0),
        ]
    )
    out = cats.add_cats(hits, {"ALL"}, {"ALL"}, rules).set_index("ticker")
    assert out.loc["ALL", "cats"] == pytest.approx(3.0)
    assert out.loc["EXT", "cats"] == pytest.approx(1.0 - 1.0)
    assert out.loc["EXT", "cats_extension"] == pytest.approx(-1.0)
    assert out.loc["NONE", "cats"] == pytest.approx(0.0)


def test_empty_hits_keep_columns(rules):
    out = cats.add_cats(pd.DataFrame(columns=["ticker"]), set(), set(), rules)
    assert out.empty and "cats" in out.columns


def test_recent_signal_window():
    d = [dt.date(2026, 10, 14), dt.date(2026, 10, 15), dt.date(2026, 10, 16)]
    candidates = pd.DataFrame(
        {"scan": ["mb_up", "ep_day", "mb_down"], "ticker": ["A", "B", "C"], "session_date": d}
    )
    assert cats.recent_signal_tickers(candidates, ["mb_up", "ep_day"], d[1:]) == {"B"}
    assert cats.recent_signal_tickers(pd.DataFrame(), ["mb_up"], d) == set()
