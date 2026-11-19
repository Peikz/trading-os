"""Every scan run of the day (`api/today_runs.py`) and the symbol list (`api/symbols.py`) over a
synthetic data repo. Synthetic data only: the tickers are built from letters."""

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import SESSION, A, B, C, D, candidates  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401

E = "".join(["U", "Z", "Q", "U"])


@pytest.fixture
def data(base_data):  # noqa: F811
    """The EOD run of the base repo plus an earlier 10:15 run that found A (again) and E."""
    early = candidates()
    early = early[early["ticker"].isin([A, C])].copy()
    extra = early.iloc[[0]].assign(ticker=E, grade="B", grade_score=0.1)
    pd.concat([early, extra]).to_parquet(
        base_data / "data" / "candidates" / "2026" / f"{SESSION}_am.parquet"
    )
    return base_data


@pytest.fixture
def client(data):
    return TestClient(create_app(data))


def test_the_runs_of_the_day_come_in_the_order_they_ran_with_their_hit_counts(client):
    out = client.get("/api/today-runs").json()
    assert out["session"] == SESSION.isoformat()
    assert [r["slot"] for r in out["runs"]] == ["am", "eod"]
    am, eod = out["runs"]
    assert am["id"] == f"{SESSION}_am" and am["name"] == "10:15"
    assert am["ny"] and am["cph"] and am["ny"] != am["cph"]
    assert (am["count"], eod["count"]) == (2, 2)  # am: A and E (the C is not graded)
    assert out["all"] == {"id": "all", "label": "All today", "count": 3}  # A, B and E


def test_all_today_is_deduplicated_best_grade_first_and_tagged_with_its_runs(client):
    rows = client.get("/api/today?run=all").json()["rows"]
    assert [r["ticker"] for r in rows] == [B, A, E]
    tags = {r["ticker"]: r["runs"] for r in rows}
    assert tags[A] == ["am", "eod"] and tags[B] == ["eod"] and tags[E] == ["am"]


def test_one_run_shows_only_its_own_hits_and_an_unknown_run_is_404(client):
    rows = client.get(f"/api/today?run={SESSION}_am").json()["rows"]
    assert sorted(r["ticker"] for r in rows) == sorted([A, E])
    assert all(r["runs"] == ["am"] for r in rows)
    assert client.get("/api/today?run=1999-01-01_am").status_code == 404
    body = client.get(f"/api/today?run={SESSION}_eod&scope=pushed").json()
    assert body["rows"][-1]["ticker"] == C  # the C setup, with scope pushed


def test_the_chart_has_one_list_per_run_of_today(client):
    lists = {x["id"]: x for x in client.get("/api/chart-lists").json()["lists"]}
    assert lists["hits"]["count"] == 3
    assert lists[f"run:{SESSION}_am"]["label"].startswith("10:15")
    assert lists[f"run:{SESSION}_am"]["count"] == 2
    assert lists[f"run:{SESSION}_eod"]["group"] == "Today"
    am = client.get(f"/api/chart-lists/run:{SESSION}_am").json()
    assert sorted(r["ticker"] for r in am["rows"]) == sorted([A, E])
    assert client.get("/api/chart-lists/run:nope").status_code == 404
    hits = client.get("/api/chart-lists/hits").json()["rows"]
    assert {r["ticker"]: r["runs"] for r in hits}[A] == ["am", "eod"]


def test_symbols_are_the_universe_with_names_where_the_data_repo_has_them(data):
    names = pd.DataFrame(
        {"ticker": [A, B, A], "name": ["Alpha Corp", "Beta Inc", "Old Alpha"],
         "active": [True, True, False]}
    )  # fmt: skip
    folder = data / "data" / "ep_enrich"
    folder.mkdir(parents=True)
    names.to_parquet(folder / "tickers.parquet")
    out = TestClient(create_app(data)).get("/api/symbols").json()
    assert out["asof"] == SESSION.isoformat()
    found = {t: n for t, n in out["symbols"]}
    assert found[A] == "Alpha Corp" and found[B] == "Beta Inc"
    assert found[C] == "" and set(found) == {A, B, C, D}


def test_symbols_without_a_name_table_still_list_the_tickers(client):
    out = client.get("/api/symbols").json()
    assert {t for t, _ in out["symbols"]} == {A, B, C, D}


def test_scan_hits_list_every_scan_and_tier_per_stock_and_scan_with_their_runs(client):
    out = client.get("/api/scan-hits?run=all").json()
    assert out["label"] == "All today"
    rows = {(r["ticker"], r["scan"]): r for r in out["rows"]}
    assert (D, "ep_day") in rows  # a saved-only scan and tier are here too
    assert rows[(A, "ep_ah")]["runs"] == ["am", "eod"] and rows[(A, "ep_ah")]["sector"] == "Tech"
    assert rows[(B, "ep_ah")]["levels"] == {"entry": 10.0, "stop": 9.0}
    assert [r["grade"] for r in out["rows"]][:2] == ["A+", "A"]  # best grade first
    assert {s["id"] for s in out["scans"]} == {"ep_ah", "ep_day"}
    one = client.get(f"/api/scan-hits?run={SESSION}_am").json()
    assert {r["ticker"] for r in one["rows"]} == {A, C, E}
    assert client.get("/api/scan-hits?run=nope").status_code == 404


def test_the_screener_brings_back_extra_fields_on_request(client):
    body = {"source": "all", "filters": [], "more": ["ret_22", "nope"]}
    out = client.post("/api/screener/run", json=body).json()
    assert "ticker" in out["columns"] and "nope" not in out["columns"]
