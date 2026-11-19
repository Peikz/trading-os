"""UX round 4 (`api/round4.py`) over a synthetic data repo: search, All scans, a level at a
price, manual test runs, the settings and the Chart's last-screener list. Synthetic data only:
the tickers are built from letters."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import SESSION, A, B, C, D, candidates  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401
from trading_os import alerts, daily_notes, my_watchlists, stock_notes  # noqa: E402


@pytest.fixture
def data(base_data):  # noqa: F811
    return base_data


@pytest.fixture
def client(data):
    return TestClient(create_app(data))


def test_settings_show_the_data_folder(client, data):
    assert client.get("/api/settings").json() == {"data_folder": str(data)}


def test_manual_test_runs_follow_the_browsers_header(data):
    folder = data / "data" / "manual" / f"{SESSION}_am_101500"
    folder.mkdir(parents=True)
    candidates().to_parquet(folder / "candidates.parquet")
    client = TestClient(create_app(data))
    plain = client.get("/api/runs").json()
    assert [r["kind"] for r in plain] == ["scheduled"]
    shown = client.get("/api/runs", headers={"X-Manual-Runs": "1"}).json()
    assert sorted(r["kind"] for r in shown) == ["manual", "scheduled"]
    off = client.get("/api/runs", headers={"X-Manual-Runs": "0"}).json()
    assert len(off) == 1
    # the other routes list runs the same way (a manual run is a run)
    assert client.get("/api/health", headers={"X-Manual-Runs": "1"}).json()["runs"] == 2


def test_a_ticker_search_gathers_its_hits_lists_alerts_and_notes(client, data):
    my_watchlists.add(data, "Leaders", [A])
    alerts.add(data, A, 12.5, "above", "")
    stock_notes.add(data, A, "a base forming")
    daily_notes.add(data, f"day note on ${A}")
    out = client.get(f"/api/search/ticker/${A.lower()}").json()
    assert out["ticker"] == A and out["runs_searched"] == 1
    assert [h["grade"] for h in out["hits"]] == ["A"]
    assert out["hits"][0]["scan"] and out["hits"][0]["run"]
    assert "your list Leaders" in out["places"]
    assert any(p.startswith("price alert above 12.50") for p in out["places"])
    kinds = sorted(n["kind"] for n in out["notes"])
    assert kinds == ["daily note", "stock note"]
    assert client.get("/api/search/ticker/not%20one").status_code == 400
    empty = client.get(f"/api/search/ticker/{D}").json()
    assert empty["places"] == [] and empty["notes"] == []


def test_a_word_search_finds_notes_and_guide_lines(client, data, tmp_path):
    stock_notes.add(data, B, "gap and go setup")
    daily_notes.add(data, "gap down day, stood aside")
    out = client.get("/api/search/words", params={"q": "gap"}).json()
    assert [n["ticker"] for n in out["stock"]] == [B]
    assert len(out["daily"]) == 1
    assert client.get("/api/search/words", params={"q": "  "}).json()["stock"] == []
    guide = client.get("/api/search/words", params={"q": "grade"}).json()["guide"]
    assert all({"section", "line"} <= set(g) for g in guide)


def test_known_tells_a_stock_from_a_made_up_ticker(client):
    assert client.get(f"/api/known/{A}").json() == {"ticker": A, "known": True}
    assert client.get("/api/known/NOPEX").json()["known"] is False
    assert client.get("/api/known/12$").json()["known"] is False


def test_scan_tables_have_the_scans_own_columns_blocks_and_charts(client, data):
    run = f"{SESSION}_eod"
    charts = data / "data" / "charts" / "2026" / f"{SESSION}_eod"
    charts.mkdir(parents=True)
    (charts / f"ep_ah_{B}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    out = client.get("/api/scan-tables", params={"run": run}).json()
    assert out["run"] == run
    assert [s["scan"] for s in out["scans"]] == ["ep_ah"]  # ep_day is not pushed
    table = out["scans"][0]
    assert (table["shown"], table["total"]) == (3, 3)
    keys = [c["key"] for c in table["columns"]]
    assert keys[:3] == ["ticker", "grade", "grade_score"]  # no rank in this file
    assert "tradingview" in keys and "tier" in keys
    assert [r["ticker"] for r in table["rows"]] == [B, A, C]  # best grade first
    assert table["rows"][0]["tradingview"].startswith("https://www.tradingview.com/chart/")
    assert {b["ticker"] for b in table["blocks"]} <= {B, A}
    assert table["charts"] == [B]
    png = client.get(f"/api/run-chart/{run}/ep_ah/{B}")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert client.get(f"/api/run-chart/{run}/ep_ah/{A}").status_code == 404
    assert client.get(f"/api/run-chart/{run}/..%2Fx/{A}").status_code in (400, 404)
    assert client.get("/api/scan-tables", params={"run": "1999-01-01_eod"}).status_code == 404


def test_a_level_is_a_flat_line_with_the_same_checks_as_streamlit(client, data):
    ok = client.post(f"/api/chart/{A}/levels", json={"price": 12.5})
    assert ok.status_code == 200
    saved = client.get(f"/api/chart/{A}/saved").json()
    assert [m["text"] for m in saved] == ["Level 12.50"]
    assert client.post(f"/api/chart/{A}/levels", json={"price": 0}).status_code == 400
    same = {"price": 9.0, "start": "2026-08-03", "end": "2026-08-03"}
    assert client.post(f"/api/chart/{A}/levels", json=same).status_code == 400
    assert client.post(f"/api/chart/{D}/levels", json={"price": 9.0}).status_code == 400  # no bars
    gone = client.delete(f"/api/chart/{A}/marks/{saved[0]['mark_id']}")
    assert gone.status_code == 200 and client.get(f"/api/chart/{A}/saved").json() == []


def test_the_screeners_last_result_is_a_chart_list(client):
    out = client.get("/api/chart-lists/screen", params={"t": f"{B},{A}"}).json()
    assert out["label"] == "Last screener result"
    assert [r["ticker"] for r in out["rows"]] == [B, A]
    assert out["rows"][0]["last"] == 20.0


def test_screener_and_watchlist_rows_carry_their_tradingview_links(client, data):
    body = {"source": "all", "filters": [], "sort": "rs_pct", "descending": True}
    out = client.post("/api/screener/run", json=body).json()
    assert out["tv"][A].endswith("symbol=NASDAQ%3A" + A)
    my_watchlists.add(data, "Leaders", [B])
    wl = client.get("/api/watchlists/Leaders").json()
    assert wl["tv"][B].endswith("symbol=NYSE%3A" + B)
    hits = client.get("/api/scan-hits").json()["rows"]
    assert all(h["tv"].startswith("https://www.tradingview.com/") for h in hits)


def test_an_earlier_days_run_can_be_picked_on_today_and_in_the_chart_lists(data):
    early = data / "data" / "candidates" / "2026" / "2026-10-29_am.parquet"
    candidates().iloc[[1]].to_parquet(early)  # the A+ hit of an earlier day's 10:15 run
    client = TestClient(create_app(data))
    rows = client.get("/api/today", params={"run": "2026-10-29_am"}).json()["rows"]
    assert [r["ticker"] for r in rows] == [B]
    listed = client.get("/api/chart-lists/run:2026-10-29_am").json()
    assert [r["ticker"] for r in listed["rows"]] == [B] and "2026-10-29" in listed["label"]
    assert client.get("/api/today", params={"run": "2026-10-28_am"}).status_code == 404
    assert client.get("/api/chart-lists/run:2026-10-28_am").status_code == 404
    # today's own run chips still list only the newest session
    assert [r["slot"] for r in client.get("/api/today-runs").json()["runs"]] == ["eod"]


def test_one_scan_of_a_run_can_be_asked_for_even_when_it_is_not_pushed(client):
    run = f"{SESSION}_eod"
    out = client.get("/api/scan-tables", params={"run": run, "scan": "ep_day"}).json()
    assert [s["scan"] for s in out["scans"]] == ["ep_day"]
    assert [r["ticker"] for r in out["scans"][0]["rows"]] == [D]  # the log tier too
