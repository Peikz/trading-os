"""The Chart workspace's lists (`api/lists.py`) over a synthetic data repo. Synthetic data only:
the tickers are built from letters so no real symbol appears here."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import A, B, C, D  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401
from trading_os import my_watchlists  # noqa: E402


@pytest.fixture
def client(base_data):  # noqa: F811
    my_watchlists.add(base_data, "Mine", [D, A])
    return TestClient(create_app(base_data))


def test_the_catalog_names_every_list_with_its_size(client):
    lists = {x["id"]: x for x in client.get("/api/chart-lists").json()["lists"]}
    assert lists["hits"]["label"] == "Today's hits"
    assert lists["hits"]["count"] == 2  # A+ and A; the C is not graded
    assert lists["wl:Mine"]["count"] == 2
    assert lists["pos"]["count"] == 0
    assert lists["scan:ep_ah"]["group"].startswith("Scan hits")


def test_todays_hits_come_best_grade_first_with_the_snapshot_numbers(client):
    rows = client.get("/api/chart-lists/hits").json()["rows"]
    assert [r["ticker"] for r in rows] == [B, A]
    assert [r["grade"] for r in rows] == ["A+", "A"]
    assert rows[0]["last"] == 20.0
    assert rows[0]["setup"]
    keys = {"ticker", "grade", "setup", "last", "chg_pct", "rvol", "signal_id", "runs"}
    assert set(rows[0]) == keys


def test_a_watchlist_shows_a_grade_only_for_stocks_that_hit_today(client):
    rows = {r["ticker"]: r for r in client.get("/api/chart-lists/wl:Mine").json()["rows"]}
    assert set(rows) == {A, D}
    assert rows[A]["grade"] == "A"
    assert rows[D]["grade"] == ""


def test_a_scan_lists_all_its_hits_and_unknown_lists_are_404(client):
    rows = client.get("/api/chart-lists/scan:ep_ah").json()["rows"]
    assert [r["ticker"] for r in rows] == [B, A, C]
    assert client.get("/api/chart-lists/scan:nope").status_code == 404
    assert client.get("/api/chart-lists/other").status_code == 404
    assert client.get("/api/chart-lists/pos").json()["rows"] == []
