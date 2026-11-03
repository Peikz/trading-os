"""Phase 3 of the React dashboard's API: the Market page, the Guide, the Journal's broker CSV
import and Daily notes, and the live intraday chart's 10:30 mark, over a synthetic data repo.
Synthetic data only: the tickers are built from letters so no real symbol appears here."""

import datetime as dt

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import SESSION, A, B  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401
from tests.test_api_pages import data  # noqa: E402, F401
from trading_os import chart_view, daily_notes, dashboard, journal  # noqa: E402


@pytest.fixture
def client(data, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TRADING_OS_NO_LIVE", "1")  # no TradingView fetch for the sectors
    return TestClient(create_app(data))


def test_the_market_page_without_breadth(tmp_path):
    (tmp_path / "data").mkdir()
    out = TestClient(create_app(tmp_path)).get("/api/market/page").json()
    assert out == {"empty": True}


def test_the_market_page(data, client):  # noqa: F811
    folder = data / "data" / "industries" / "2026"
    folder.mkdir(parents=True)
    for i in range(7):  # a week's moves need 6 saved runs
        ranks = [1, 2] if i < 6 else [2, 1]
        pd.DataFrame({
            "industry": ["Software", "Banks"], "sector": ["Tech", "Finance"],
            "industry_rank": ranks, "med_ret_22": [5.0, 3.0], "med_ret_63": [9.0, 6.0],
            "members": [10, 8],
        }).to_parquet(folder / f"2026-10-{20 + i:02d}_eod.parquet")  # fmt: skip
    out = client.get("/api/market/page").json()
    tiles = {t["label"]: t for t in out["tiles"]}
    assert tiles["QQQ light"]["value"] == "🟢 GREEN" and tiles["SPY"]["delta"] == "+0.5%"
    assert out["heat"] is None  # no heat stats in this repo
    assert out["sectors"] is None and "not available" in out["sector_caption"]
    climbing = out["industries"]["climbing"]["rows"]
    assert climbing[0]["industry"] == "Banks" and climbing[0]["moved (1 week)"] == 1
    assert out["breadth"]["rows"][0]["session_date"] == SESSION.isoformat()
    assert out["ratios"][0]["time"] == SESSION.isoformat()
    month = client.get("/api/market/page?back=1%20month").json()
    assert month["back"] == "1 month" and "moved (1 month)" in month["industries"]["top"]["columns"]


def test_the_market_page_with_saved_sectors(data, client):  # noqa: F811
    folder = data / "data" / "sectors" / "2026"
    folder.mkdir(parents=True)
    rows = [  # SPY is the yardstick the rotation measures against
        ("SPY", "S&P 500", "Index", 1.0, 2.0), ("XZQX", "Synthetic", "Sector", 3.0, -1.0),
    ]  # fmt: skip
    pd.DataFrame([
        {"symbol": f"AMEX:{t}", "ticker": t, "name": n, "group": g, "chg_pct": 0.5,
         "ret_1w": w, "ret_1m": m, "ret_3m": 4.0, "ret_ytd": 9.0, "close": 10.0, "sma50": 9.0,
         "sma200": 8.0, "rvol": 1.1}
        for t, n, g, w, m in rows
    ]).to_parquet(folder / f"{SESSION}_eod.parquet")  # fmt: skip
    out = client.get("/api/market/page?period=1%20week&groups=Sector").json()
    assert out["sector_caption"].startswith(f"saved {SESSION}")
    assert [r["ticker"] for r in out["sectors"]["rows"]] == ["XZQX"]
    [point] = out["rotation"]
    assert point["ticker"] == "XZQX" and point["x"] == pytest.approx(-3.0)  # 1 month vs SPY


def test_the_guide(client):
    text = client.get("/api/guide").json()["text"]
    assert "## 11. The dashboard, page by page" in text
    assert not text.startswith("# Trading OS")  # the page has its own title


def test_the_broker_csv_import_and_its_errors(data, client):  # noqa: F811
    csv = (
        "trade_date,ticker,side,quantity,price,fees\n"
        f"2026-06-01,{A},buy,100,10.0,1\n2026-06-10,{A},sell,100,11.0,1\n"
    )
    out = client.post("/api/journal/import", json={"name": "../../x.csv", "content": csv})
    assert out.status_code == 200 and out.json()["message"]
    assert len(journal.load_fills(data)) == 2
    assert len(dashboard.latest_journal(data)) == 1  # one closed trade
    assert not list((data / "data" / "journal").glob("_upload_*"))  # the upload is removed
    bad = client.post("/api/journal/import", json={"name": "y.csv", "content": "a,b\n1,2\n"})
    assert bad.status_code == 400 and "missing columns" in bad.json()["detail"]


def test_daily_notes_add_edit_filter_and_delete(data, client):  # noqa: F811
    today = dt.date.today()
    nid = client.post(
        "/api/journal/daily-notes", json={"text": f"Watching ${A}", "day": str(today)}
    ).json()["note_id"]
    client.post("/api/journal/daily-notes", json={"text": "Quiet day", "tags": B})
    out = client.get("/api/journal/daily-notes").json()
    assert {n["text"] for n in out["notes"]} == {f"Watching ${A}", "Quiet day"}
    assert out["tags"] == sorted([A, B]) and out["days"][-1] == 3650
    only = client.get(f"/api/journal/daily-notes?tag={A}").json()["notes"]
    assert [n["tags"] for n in only] == [[A]]
    old = str(today - dt.timedelta(days=60))
    client.put(f"/api/journal/daily-notes/{nid}", json={"text": "Moved back", "day": old})
    assert len(client.get("/api/journal/daily-notes?days=30").json()["notes"]) == 1
    assert len(client.get("/api/journal/daily-notes?days=90").json()["notes"]) == 2
    assert client.delete(f"/api/journal/daily-notes/{nid}").json() == {"removed": nid}
    assert client.delete(f"/api/journal/daily-notes/{nid}").status_code == 404
    assert client.post("/api/journal/daily-notes", json={"text": " "}).status_code == 400
    assert len(daily_notes.events(data)) == 4  # add, add, edit, remove: kept for good


def test_the_live_intraday_chart_marks_1030():
    ts = pd.date_range("2026-10-30 14:25", periods=10, freq="min", tz="UTC")  # 10:25-10:34 NY
    ts = ts.tz_convert("America/New_York")
    minutes = pd.DataFrame({
        "ts": ts, "minute": ts.hour * 60 + ts.minute, "open": 1.0, "high": 1.0, "low": 1.0,
        "close": 1.0, "volume": 1.0,
    })  # fmt: skip
    out = chart_view.intraday_payload(minutes, 1, None, None, chart_view.LIVE_MARKS)
    [mark] = out["markers"]
    assert mark["text"] == "10:30" and mark["time"] == out["candles"][5]["time"]
    assert chart_view.intraday_payload(minutes)["markers"] == []
