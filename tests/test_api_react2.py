"""React dashboard round 2: conviction on the grading form, the broker export preview, today's
note and the Practice routes, over a synthetic data repo. Synthetic data only: tickers are
built from letters, signals and bars are made up."""

import base64

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import A, B  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401
from tests.test_api_pages import data  # noqa: E402, F401
from trading_os import daily_notes, dashboard, journal, practice  # noqa: E402

ENTRY = "2024-05-24"  # a Friday and an NYSE session


@pytest.fixture
def client(data, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TRADING_OS_NO_LIVE", "1")
    return TestClient(create_app(data))


def export_practice(data_dir) -> None:
    folder = practice.folder(data_dir)
    folder.mkdir(parents=True)
    rows = [
        {"signal_id": "p1", "pool": "practice", "ticker": A, "setup_name": "ep_day",
         "grade": "A", "net_r": 3.0, "entry_date": pd.Timestamp(ENTRY), "hold_days": 5,
         "price": 20.0, "stop_pct": 7.0, "price_band": "10-30"},
        {"signal_id": "x1", "pool": "exam", "ticker": B, "setup_name": "ep_day",
         "grade": "B", "net_r": -1.0, "entry_date": pd.Timestamp(ENTRY), "hold_days": 3,
         "price": 40.0, "stop_pct": 5.0, "price_band": "30-50"},
    ]  # fmt: skip
    pd.DataFrame(rows).to_parquet(folder / "signals.parquet")
    bars = []
    for row in rows:
        for rel in range(-30, 8):
            base = 100.0 + rel * 0.5
            bars.append({"signal_id": row["signal_id"], "rel_day": rel, "open": base,
                         "high": base + 1, "low": base - 1, "close": base + 0.2,
                         "volume": 1e6 + rel})  # fmt: skip
    pd.DataFrame(bars).to_parquet(folder / "bars.parquet")


def test_conviction_is_saved_with_the_grade_and_shows_in_closed_trades(data, client):  # noqa: F811
    body = {"grade": "A", "notes": "n", "tags": "", "conviction": 3}
    out = client.put("/api/grades/trade/t-1", json=body).json()
    assert out["conviction"] == 3 and out["convictions"] == [1, 2, 3]
    assert client.get("/api/grades/trade/t-1").json()["conviction"] == 3
    state = dashboard.notes_state(data)
    assert int(state[state["ref_id"] == "t-1"].iloc[0]["conviction"]) == 3  # the same file
    cleared = client.put("/api/grades/trade/t-1", json={**body, "conviction": None}).json()
    assert cleared["conviction"] is None
    assert client.put("/api/grades/trade/t-1", json={**body, "conviction": 4}).status_code == 400


def test_the_export_preview_changes_nothing_and_import_skips_known_fills(data, client):  # noqa: F811
    csv = (
        "trade_date,ticker,side,quantity,price,fees\n"
        f"2026-06-01,{A},buy,100,10.0,1\n2026-06-10,{A},sell,100,11.0,1\n"
    )
    body = {"name": "fills.csv", "data": base64.b64encode(csv.encode()).decode()}
    seen = client.post("/api/journal/import/preview", json=body).json()
    assert seen["ok"] and seen["new"] == 2 and seen["existing"] == 0
    assert seen["first_date"] == "2026-06-01" and seen["last_date"] == "2026-06-10"
    assert any("2 new fills" in line for line in seen["lines"])
    assert len(journal.load_fills(data)) == 0  # a preview writes nothing
    assert client.post("/api/journal/import", json=body).status_code == 200
    assert len(journal.load_fills(data)) == 2
    again = client.post("/api/journal/import/preview", json=body).json()
    assert again["new"] == 0 and again["existing"] == 2  # the same dedup as Streamlit
    bad = client.post(
        "/api/journal/import/preview", json={"name": "y.csv", "content": "a,b\n1,2\n"}
    )
    assert bad.json()["ok"] is False and "missing columns" in bad.json()["error"]
    wrong = {"name": "y.txt", "content": "x"}
    assert client.post("/api/journal/import/preview", json=wrong).json()["ok"] is False
    junk = {"name": "z.csv", "data": "%%"}
    assert client.post("/api/journal/import", json=junk).status_code == 400


def test_todays_note_is_read_and_saved_through_save_for_day(data, client):  # noqa: F811
    assert client.get("/api/journal/daily-notes/today").json()["text"] == ""
    out = client.put("/api/journal/daily-notes/today", json={"text": f"Quiet. ${A} held"}).json()
    assert out["text"] == f"Quiet. ${A} held" and out["note_id"]
    again = client.put("/api/journal/daily-notes/today", json={"text": "Edited"}).json()
    assert again["note_id"] == out["note_id"]  # the day's note is edited, not duplicated
    assert len(daily_notes.current(data)) == 1
    assert client.put("/api/journal/daily-notes/today", json={"text": "  "}).status_code == 400


def test_practice_is_absent_without_its_export(client):
    assert client.get("/api/practice").json()["available"] is False
    assert client.get("/api/practice/next").status_code == 404


def test_practice_blind_signal_hides_the_entry_bar_and_the_stock(data, client):  # noqa: F811
    export_practice(data)
    state = client.get("/api/practice").json()
    assert state["available"] and state["stats"]["practice"]["pool_size"] == 1
    assert client.get("/api/practice/next?pool=practice").json() == {"signal_id": "p1"}
    sig = client.get("/api/practice/signal/p1").json()
    assert sig["ticker"] is None and sig["answered"] is False and sig["result"] is None
    chart = sig["chart"]
    assert len(chart["candles"]) == 30  # rel_day -30..-1: nothing from the entry session on
    assert chart["labels"][chart["candles"][-1]["time"]] == "day -1"
    assert [lv["name"] for lv in chart["levels"]] == ["entry", "stop"]
    assert chart["levels"][0]["price"] == 100.0 and chart["levels"][1]["price"] == 93.0
    assert chart["markers"] == [] and chart["ticker"] == ""
    assert {k["label"] for k in sig["facts"]} >= {"Setup", "Grade", "Stop distance"}
    assert A not in str(sig["facts"])


def test_practice_shown_uses_real_dates_and_dollars(data, client):  # noqa: F811
    export_practice(data)
    sig = client.get("/api/practice/signal/p1?shown=true&lines=MA10").json()
    assert sig["ticker"] == A and sig["chart"]["labels"] is None
    assert sig["chart"]["candles"][-1]["time"] == "2024-05-23"
    assert sig["chart"]["levels"][0]["price"] == pytest.approx(20.0)  # the entry price
    assert [x["name"] for x in sig["chart"]["lines"]] == ["MA 10"]


def test_practice_answer_is_appended_once_and_reveals_the_trade(data, client):  # noqa: F811
    export_practice(data)
    body = {"signal_id": "p1", "pool": "practice", "choice": "3", "note": "clean", "shown": False}
    out = client.post("/api/practice/answer", json=body).json()["result"]
    assert out["net_r"] == 3.0 and out["pick_r"] == pytest.approx(4.5) and out["ticker"] == A
    assert out["note"] == "clean" and out["hold_days"] == 5
    again = client.post("/api/practice/answer", json={**body, "choice": "skip"}).json()["result"]
    assert again["choice"] == "3"  # a double click: the first answer stands
    assert len(list(practice.answers_folder(data).glob("*.parquet"))) == 1
    after = client.get("/api/practice/signal/p1").json()
    assert len(after["chart"]["candles"]) == 38 and after["answered"] is True
    assert [m["text"] for m in after["chart"]["markers"]] == ["entry", "exit"]
    assert client.get("/api/practice/next?pool=practice").json() == {"signal_id": None}
    assert client.put("/api/practice/note", json={"signal_id": "p1", "note": "later"}).json()
    assert client.get("/api/practice/answers").json()[0]["note"] == "later"
    stats = client.get("/api/practice").json()["stats"]["practice"]
    assert stats["answered"] == 1 and stats["picks_r"] == pytest.approx(4.5)
    bad = {**body, "signal_id": "x1", "choice": "9"}
    assert client.post("/api/practice/answer", json=bad).status_code == 400
    wrong_pool = {**body, "signal_id": "x1"}
    assert client.post("/api/practice/answer", json=wrong_pool).status_code == 400
    unanswered = {"signal_id": "x1", "note": "n"}
    assert client.put("/api/practice/note", json=unanswered).status_code == 400
    assert client.get("/api/practice/signal/nope").status_code == 404


def test_blind_dates_keep_the_bars_in_order():
    rels = list(range(-130, 64))
    days = np.busday_offset("2000-01-03", [r + 400 for r in rels])
    assert all(a < b for a, b in zip(days, days[1:], strict=False))
