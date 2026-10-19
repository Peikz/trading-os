"""Smoke test of the dashboard: every page renders without an exception on a small data repo.

Needs the `app` dependency group (Streamlit); skipped otherwise (e.g. in CI).
"""

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
PAGES = [
    "Today",
    "Screens",
    "Watchlists",
    "Journal",
    "Graded signals",
    "Market",
    "Stats",
    "Validation",
]


@pytest.fixture()
def data_repo(tmp_path):
    root = tmp_path / "trading-os-data"
    cands = pd.DataFrame(
        {
            "signal_id": ["s1"],
            "session_date": [pd.Timestamp("2026-10-19")],
            "slot": ["eod"],
            "scan": ["ep_day"],
            "ticker": ["AAA"],
            "rank": [1],
            "tier": ["alert"],
            "pushed": [True],
            "gap_pct": [12.0],
            "rvol50": [4.0],
        }
    )
    path = root / "data" / "candidates" / "2026" / "2026-10-19_eod.parquet"
    path.parent.mkdir(parents=True)
    cands.to_parquet(path)
    uni = root / "data" / "universe" / "2026" / "2026-10-19_eod.parquet"
    uni.parent.mkdir(parents=True)
    pd.DataFrame({"ticker": ["AAA"], "gap_pct": [12.0]}).to_parquet(uni)
    return root


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(data_repo, monkeypatch, page):
    monkeypatch.setenv("TRADING_OS_DATA", str(data_repo))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, at.exception
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.header[0].value  # each page has a header
