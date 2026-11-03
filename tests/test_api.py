"""The React dashboard's API (`api/main.py`) over a synthetic data repo. Synthetic data only:
the tickers are built from letters so no real symbol appears here."""

import datetime as dt

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from trading_os import remote_data, screens  # noqa: E402

A, B, C, D = ("".join([x, "Z", "Q", x]) for x in "WXYV")
SESSION = dt.date(2026, 10, 30)


def candidates() -> pd.DataFrame:
    base = {
        "tier": "alert",
        "plan_entry": 10.0,
        "plan_stop": 9.0,
        "plan_shares": 100,
        "plan_position_usd": 1000.0,
        "plan_risk_usd": 100.0,
        "plan_stop_basis": "day low",
    }
    rows = [
        {**base, "scan": "ep_ah", "ticker": A, "grade": "A", "grade_score": 0.4},
        {**base, "scan": "ep_ah", "ticker": B, "grade": "A+", "grade_score": 0.6},
        {**base, "scan": "ep_ah", "ticker": C, "grade": "C", "grade_score": -0.1},
        {**base, "scan": "ep_day", "ticker": D, "grade": "B", "tier": "log"},  # not pushed
    ]
    return pd.DataFrame(rows)


def universe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [A, B, C, D],
            "exchange": ["NASDAQ", "NYSE", "NASDAQ", "NYSE"],
            "sector": ["Tech", "Finance", "Tech", "Materials"],
            "industry": ["Software", "Banks", "Software", "Mining"],
            "float_shares": [5e7, 1e8, 2e7, 3e7],
            "earnings_date_next": pd.to_datetime(["2026-11-20"] * 4),
            "close": [10.0, 20.0, 30.0, 40.0],
            "adr20_pct": [5.0, 3.0, 8.0, 6.0],
            "rs_pct": [90, 50, 70, 99],
            "market_cap": [2e9, 5e8, 1e9, 3e9],
        }
    )


@pytest.fixture
def data(tmp_path, monkeypatch):
    year = tmp_path / "data" / "candidates" / "2026"
    year.mkdir(parents=True)
    candidates().to_parquet(year / f"{SESSION}_eod.parquet")
    (tmp_path / "data" / "universe" / "2026").mkdir(parents=True)
    universe().to_parquet(tmp_path / "data" / "universe" / "2026" / f"{SESSION}_eod.parquet")
    (tmp_path / "data" / "breadth" / "2026").mkdir(parents=True)
    breadth = {"session_date": SESSION, "qqq_light": "GREEN", "spy_close": 500.0,
               "spy_chg_pct": 0.5, "vix_close": 15.0, "vix_chg_pct": -2.0}  # fmt: skip
    pd.DataFrame([breadth]).to_parquet(
        tmp_path / "data" / "breadth" / "2026" / f"{SESSION}_eod.parquet"
    )
    # Daily bars: the compact bars-2y file in the cache, no GitHub call
    cache = tmp_path / "cache"
    (cache / "bars-2y").mkdir(parents=True)
    days = pd.bdate_range("2026-06-01", periods=80)
    bars = pd.DataFrame(
        {
            "ticker": A,
            "session_date": days.date,
            "open": [10 + i * 0.1 for i in range(80)],
            "high": [10.5 + i * 0.1 for i in range(80)],
            "low": [9.5 + i * 0.1 for i in range(80)],
            "close": [10.2 + i * 0.1 for i in range(80)],
            "volume": [1000 + i for i in range(80)],
        }
    )
    first = A[0]
    bars.to_parquet(cache / "bars-2y" / f"bars_2y_{SESSION}_{first}.parquet")
    monkeypatch.setattr(remote_data, "CACHE", cache)
    monkeypatch.setattr(remote_data, "fetch", lambda *a, **k: [])
    return tmp_path


@pytest.fixture
def client(data):
    return TestClient(create_app(data))


def test_runs_are_listed_newest_first_with_stable_ids(client):
    runs = client.get("/api/runs").json()
    assert [r["id"] for r in runs] == [f"{SESSION}_eod"]
    assert runs[0]["has_universe"] and runs[0]["has_breadth"]


def test_a_runs_scans_carry_their_grades_best_first(client):
    out = client.get(f"/api/runs/{SESSION}_eod/scans").json()["scans"]
    assert out["ep_ah"]["pushed"] and not out["ep_day"]["pushed"]
    assert [h["ticker"] for h in out["ep_ah"]["hits"]] == [B, A, C]
    assert [h["grade"] for h in out["ep_ah"]["hits"]] == ["A+", "A", "C"]
    assert client.get("/api/runs/1999-01-01_eod/scans").status_code == 404


def test_today_shows_the_graded_queue_and_hides_c(client):
    out = client.get("/api/today").json()
    assert [r["ticker"] for r in out["rows"]] == [B, A]
    assert out["hidden_c"] == 1
    row = out["rows"][0]
    assert row["exchange"] == "NYSE" and row["industry"] == "Banks"
    assert row["levels"] == {"entry": 10.0, "stop": 9.0}
    assert any("100 sh" in f for f in row["facts"])  # the plan: shares and risk
    assert {"label": "Industry", "value": "Banks"} in row["stats"]
    pushed = client.get("/api/today?scope=pushed").json()
    assert [r["ticker"] for r in pushed["rows"]] == [B, A, C]
    every = client.get("/api/today?scope=all").json()
    assert D in [r["ticker"] for r in every["rows"]]
    push = client.get(f"/api/today?t={C},{A}").json()  # a push link: its stocks, its order
    assert [r["ticker"] for r in push["rows"]] == [C, A]


def test_a_row_missing_plan_fields_still_shows(data):
    path = data / "data" / "candidates" / "2026" / f"{SESSION}_eod.parquet"
    odd = candidates().assign(grade_stat_trades=10.0, grade_stat_mean_r=0.1)  # no median, win %
    odd.to_parquet(path)
    out = TestClient(create_app(data)).get("/api/today").json()
    assert [r["ticker"] for r in out["rows"]] == [B, A]
    assert out["rows"][0]["facts"] == []


def test_market_tiles(client):
    tiles = {t["label"]: t for t in client.get("/api/market").json()["tiles"]}
    assert tiles["QQQ light"]["value"] == "🟢 GREEN"
    assert tiles["SPY"] == {"label": "SPY", "value": "500.00", "delta": "+0.5%"}
    assert tiles["IBD market"]["value"] == "n/a"  # no SPY history in this repo


def test_bars_with_moving_averages_and_weekly(client):
    out = client.get(f"/api/bars/{A}").json()
    assert len(out["candles"]) == 80
    assert out["candles"][0]["volume"] == 1000.0
    ma10 = next(line for line in out["lines"] if line["name"] == "MA 10")
    # MA 10 starts at the 10th bar: the mean of closes 10.2 .. 11.1
    assert ma10["pts"][0]["value"] == pytest.approx(10.65)
    assert len(ma10["pts"]) == 71
    weekly = client.get(f"/api/bars/{A}?tf=1W&indicators=MA%2010").json()
    assert len(weekly["candles"]) == 16
    assert client.get(f"/api/bars/{B}").json()["candles"] == []


def test_screener_all_stocks_and_scan_hits(client):
    meta = client.get("/api/screener/meta").json()
    assert set(meta["examples"]) == set(screens.EXAMPLES)
    assert meta["fields"]["adr20_pct"]["kind"] == "pct"
    body = {"filters": [{"field": "adr20_pct", "op": ">=", "value": 5}], "sort": "rs_pct"}
    out = client.post("/api/screener/run", json=body).json()
    assert [r["ticker"] for r in out["rows"]] == [D, A, C]  # by RS, highest first
    assert out["count"] == 3 and "ADR % (20d) >= 5" in out["summary"]
    hits = client.post(
        "/api/screener/run",
        json={**body, "source": "hits", "run": f"{SESSION}_eod", "scan": "ep_ah"},
    ).json()
    assert [r["ticker"] for r in hits["rows"]] == [A, C]  # best study grade first
    assert hits["rows"][0]["grade"] == "A"
    bad = client.post("/api/screener/run", json={"filters": [{"field": "nope", "op": ">="}]})
    assert bad.status_code == 400
    assert client.get("/api/screener/options/industry").json() == ["Banks", "Mining", "Software"]


def test_screens_save_and_delete_in_the_data_repo(client, data):
    spec = {"filters": [{"field": "close", "op": ">=", "value": 5}], "sort": "close"}
    assert "Mine" in client.put("/api/screens/Mine", json=spec).json()
    assert screens.load(data)["Mine"]["sort"] == "close"
    assert client.delete("/api/screens/Mine").json() == {}
    assert client.put("/api/screens/%20", json=spec).status_code == 400


def test_no_data_folder_is_a_clear_error(tmp_path):
    out = TestClient(create_app(tmp_path / "missing")).get("/api/runs")
    assert out.status_code == 503


def test_today_rows_carry_the_decision_and_why_and_the_next_scan(client):
    out = client.get("/api/today").json()
    row = out["rows"][0]  # an A+ without an entry rule: the study's plan, no time
    assert row["decision"]["text"] == "Buy by the study's plan"
    assert row["decision"]["session"] > str(SESSION)  # an EOD find trades the next session
    assert row["why"] == {"summary": None, "points": [], "lines": []}
    assert out["next_scan"] is None or out["next_scan"]["when"].count("New York") == 1


def test_market_carries_one_word_with_its_reasons(client):
    mood = client.get("/api/market").json()["mood"]
    assert mood["level"] == "green" and mood["word"] == "Healthy market"
    assert mood["reasons"] == [{"level": "green", "text": "QQQ light is green."}]
    assert [q["label"] for q in mood["quotes"]] == ["SPY", "VIX"]


def test_sparks_give_many_stocks_last_candles(client):
    out = client.get(f"/api/sparks?t={A},{B}&n=20").json()
    assert len(out[A]) == 20 and set(out[A][0]) == {"time", "open", "high", "low", "close"}
    assert out[B] == []  # no bars for this one


def test_a_screen_over_one_of_your_lists(data, client):
    from trading_os import my_watchlists

    my_watchlists.add(data, "Leaders", [A, C])
    out = client.post(
        "/api/screener/run",
        json={"source": "list", "watchlist": "Leaders", "filters": [
            {"field": "adr20_pct", "op": ">=", "value": 6}]},
    ).json()  # fmt: skip
    assert out["tickers"] == [C] and out["count"] == 1
    every = client.post("/api/screener/run", json={"source": "list", "watchlist": "Leaders"}).json()
    assert sorted(every["tickers"]) == sorted([A, C])
    missing = client.post("/api/screener/run", json={"source": "list", "watchlist": "Nope"})
    assert missing.status_code == 404


def test_status_dot(client):
    out = client.get("/api/system/status").json()
    assert out["level"] in ("ok", "warn", "error") and out["text"]
