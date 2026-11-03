"""Phase 2b of the React dashboard's API (`api/chart.py`, `api/research.py`): the Chart page,
Research, Live results, System health, the Scans editor and Pull / Save & push, over a
synthetic data repo. Synthetic data only: the tickers are built from letters so no real
symbol appears here."""

import datetime as dt
import shutil

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import SESSION, A, B, C  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401
from tests.test_api_pages import data  # noqa: E402, F401
from trading_os import chart_marks, health, remote_data, stock_notes  # noqa: E402
from trading_os.config import DEFAULT_PATH  # noqa: E402

DAYS = pd.bdate_range("2026-06-01", periods=80)


@pytest.fixture
def config(tmp_path):
    """A copy of the config, so the Scans editor never touches the real one."""
    path = tmp_path / "cfg" / "config" / "scans.yaml"
    path.parent.mkdir(parents=True)
    shutil.copy(DEFAULT_PATH, path)
    return path


@pytest.fixture
def client(data, config):  # noqa: F811
    return TestClient(create_app(data, config))


def test_the_chart_has_bars_lines_levels_and_fills(client):
    fill = {"date": "2026-06-10", "ticker": A, "side": "buy", "shares": 10, "price": 11.0}
    client.post("/api/journal/fills", json=fill)
    out = client.get(f"/api/chart/{A}?span=3M&lines=MA10,EMA21").json()
    assert len(out["candles"]) == 80 and out["candles"][0]["time"] == "2026-06-01"
    assert [x["name"] for x in out["lines"]] == ["MA 10", "EMA 21"]
    assert out["visible"] == {"from": out["candles"][-63]["time"], "to": out["candles"][-1]["time"]}
    [marker] = out["markers"]
    assert marker == {"time": "2026-06-10", "position": "belowBar", "shape": "arrowUp",
                      "color": "#3fb950", "text": "buy 11.00"}  # fmt: skip
    assert set(out["quick_anchors"]) == {"highest high", "lowest low", "year start"}
    assert out["tradingview"].endswith(f"NASDAQ%3A{A}")
    assert out["dates"][0] == out["candles"][-1]["time"]  # newest first, for the forms
    weekly = client.get(f"/api/chart/{A}?timeframe=Weekly").json()
    assert len(weekly["candles"]) == 16 and weekly["trend"] == []
    assert client.get("/api/chart/1x").status_code == 400


def test_trend_lines_draw_move_and_erase(data, client):  # noqa: F811
    line = {"x0": "2026-06-01", "y0": 10.0, "x1": "2026-06-11", "y1": 11.0, "extend": True}
    mark_id = client.post(f"/api/chart/{A}/lines", json=line).json()["mark_id"]
    [trend] = client.get(f"/api/chart/{A}").json()["trend"]
    assert trend["id"] == mark_id and trend["pts"][0] == {"time": "2026-06-01", "value": 10.0}
    # Extended to the last bar: 1 over 8 sessions, so 79 sessions on it is 10 + 79 / 8
    assert trend["pts"][1]["time"] == "2026-09-18"
    assert trend["pts"][1]["value"] == pytest.approx(19.875)
    moved = {**line, "y1": 12.0, "label": "ignored"}
    new_id = client.put(f"/api/chart/{A}/lines/{mark_id}", json=moved).json()["mark_id"]
    [after] = client.get(f"/api/chart/{A}").json()["trend"]
    assert after["id"] == new_id != mark_id and after["y1"] == 12.0
    assert client.delete(f"/api/chart/{A}/marks/{new_id}").json() == {"removed": new_id}
    assert client.get(f"/api/chart/{A}").json()["trend"] == []
    assert client.delete(f"/api/chart/{A}/marks/{new_id}").status_code == 404
    same_day = {**line, "x1": "2026-06-01"}
    assert client.post(f"/api/chart/{A}/lines", json=same_day).status_code == 400
    assert chart_marks.current(data, A).empty


def test_anchored_vwaps_quick_and_saved(client):
    quick = client.get(f"/api/chart/{A}?anchors=lowest%20low").json()
    assert [v["name"] for v in quick["avwaps"]] == ["AVWAP lowest low"]
    client.post(f"/api/chart/{A}/anchors", json={"day": "2026-07-01", "label": "base"})
    saved = client.get(f"/api/chart/{A}").json()
    [avwap] = saved["avwaps"]
    assert avwap["name"] == "AVWAP base" and avwap["pts"][0]["time"] == "2026-07-01"
    assert saved["marks"][0]["kind"] == "anchor"


def test_chart_notes_add_edit_delete_and_daily_notes(data, client):  # noqa: F811
    out = client.post(f"/api/chart/{A}/notes", json={"text": "first", "day": "2026-10-01"}).json()
    [note] = out["notes"]
    assert note["note_date"] == "2026-10-01" and note["edited"] is None
    body = {"text": "changed", "day": "2026-10-02"}
    edited = client.put(f"/api/chart/{A}/notes/{note['note_id']}", json=body).json()
    assert edited["notes"][0]["text"] == "changed"
    assert client.delete(f"/api/chart/{A}/notes/{note['note_id']}").json()["notes"] == []
    assert client.put(f"/api/chart/{A}/notes/nope", json=body).status_code == 404
    from trading_os import daily_notes

    daily_notes.add(data, f"watching ${A} and ${B}", dt.date(2026, 10, 3))
    [tagged] = client.get(f"/api/chart/{A}/notes").json()["daily"]
    assert tagged["also"] == [B]
    assert len(stock_notes.events(data)) == 3  # add, edit, remove: kept for good


def test_minute_bars_from_the_study_and_live_needs_keys(data, client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    day = dt.date(2026, 9, 18)
    folder = remote_data.CACHE / "intraday-minutes"
    folder.mkdir(parents=True)
    pd.DataFrame({"session_date": [day], "ticker": [A]}).to_parquet(folder / "minute_index.parquet")
    ts = pd.date_range("2026-09-18 13:25", periods=10, freq="min", tz="UTC")  # 09:25-09:34 NY
    minutes = pd.DataFrame({
        "ticker": A, "session_date": day, "ts": ts, "open": 10.0, "high": 10.5, "low": 9.5,
        "close": [10.0 + i * 0.1 for i in range(10)], "volume": 100.0, "vwap": 10.0,
    })  # fmt: skip
    minutes.to_parquet(folder / "2026-09_a.parquet")
    days = client.get(f"/api/chart/{A}/intraday-days").json()
    assert days["study_days"] == ["2026-09-18"] and days["live"] is False
    out = client.get(f"/api/chart/{A}/intraday?day=2026-09-18&every=5").json()
    # 09:25-09:29 pre-market, 09:30-09:34 the open: two 5-minute candles
    assert [c["extended"] for c in out["candles"]] == [True, False]
    assert out["candles"][1]["close"] == pytest.approx(10.9)
    assert len(out["vwap"]) == 1  # from the 09:30 open only
    assert {"name": "prior close", "price": pytest.approx(18.0), "colour": "#8b949e"} in out[
        "levels"
    ]
    live = client.get(f"/api/chart/{A}/intraday?day=2026-09-18&source=live")
    assert live.status_code == 400 and "Alpaca" in live.json()["detail"]


def test_chart_picks_list_todays_hits_then_watchlists(client):
    client.post("/api/flags", json={"ticker": C})
    picks = client.get("/api/chart/picks").json()
    assert {p["ticker"] for p in picks} >= {A, B, C}
    assert picks[0]["where"].startswith("EP-AH")


# --- Research and Live results


def test_strategy_rules_how_tested_grades_and_notes(data, client):  # noqa: F811
    rules = client.get("/api/research/strategy-rules").json()
    assert rules["label"] == rules["labels"][0] and rules["rules"] and rules["settings"]
    other = client.get("/api/research/strategy-rules", params={"label": rules["labels"][-1]})
    assert other.json()["heading"].startswith(("Live scan", "Tested in the study only"))
    tested = client.get("/api/research/how-tested").json()
    assert tested["setups"] and "Size per grade" in tested["caption"]
    assert tested["write_up"] is None
    grades = client.get("/api/research/grades").json()
    assert [r["Grade"] for r in grades["sizes"]][:2] == ["A+", "A"]
    assert grades["strategies"] and len(grades["costs"]) == 3
    (data / "docs" / "research").mkdir(parents=True)
    (data / "docs" / "research" / "2026-10-20-study.md").write_text("# A study\n")
    (data / "docs" / "research" / "how-we-test.md").write_text("# How\n")
    found = client.get("/api/research/notes").json()
    assert found["names"] == ["2026-10-20-study", "how-we-test"]
    assert found["text"] == "# A study\n"
    assert client.get("/api/research/how-tested").json()["write_up"] == "# How\n"


def history_rows() -> pd.DataFrame:
    rows = []
    for i, day in enumerate(DAYS[:20]):
        rows.append({
            "strategy": "mb_up" if i % 2 else "qm_gainers", "side": "long",
            "session_date": day.date(), "ticker": [A, B, C][i % 3], "entry": 10.0, "stop": 9.0,
            "stop_adr": 1.0, "close": 10.0 + i, "chg_pct": 1.0, "mkt_breadth_state": "strong",
            "mkt_qqq_trend": "up", "above_ma200": True, "pnl_1d": 1.0 - i % 3, "pnl_5d": 2.0,
            "pnl_21d": 3.0, "pnl_63d": 4.0, "r_5d": 0.5, "r_21d": 1.0 - i % 2, "r_63d": 1.5,
            "stop_hit_5d": False, "r_trail_ma20": 0.8, "r_trail_ema9": 0.4,
        })  # fmt: skip
    return pd.DataFrame(rows)


def test_history_filters_splits_and_events(data, client):  # noqa: F811
    build = data / "data" / "strategy_history" / "2026-10-30"
    build.mkdir(parents=True)
    history_rows().to_parquet(build / "all.parquet")
    body = {"period": "2y", "split": "year", "one": "mb_up"}
    out = client.post("/api/research/history", json=body).json()
    assert out["strategies"] == ["mb_up", "qm_gainers"] and out["count"] == 20
    assert out["split"] == "year" and "year" in out["summary"]["columns"]
    assert out["events"]["total"] == 10
    assert out["events"]["rows"][0]["session_date"] == str(DAYS[19].date())
    narrow = client.post("/api/research/history", json={"period": "2y", "strategies": ["mb_up"]})
    assert narrow.json()["count"] == 10
    event = client.get(
        "/api/research/history/event",
        params={"ticker": A, "day": "2026-07-01", "strategy": "mb_up", "period": "2y", "stop": 9},
    ).json()
    assert event["markers"][0]["text"] == "mb_up" and event["levels"][0]["name"] == "stop"
    assert len(event["candles"]) == 80  # 23 up to the day, 57 after (fewer than 63)


def test_unpublished_studies_say_so(client, monkeypatch):
    monkeypatch.setattr(remote_data, "fetch", lambda *a, **k: [])
    assert client.get("/api/research/entries").json() == {"published": False}
    assert client.get("/api/research/entries?period=2y").json() == {"published": False}
    assert client.get("/api/research/regime").json() == {"published": False}
    empty = client.post("/api/research/history", json={"period": "10y"}).json()
    assert empty["empty"] is True and empty["graded"]["summary"]["rows"] == []


def test_entries_two_years_published(client):
    folder = remote_data.CACHE / "intraday-2y"
    folder.mkdir(parents=True)
    summary = pd.DataFrame({
        "strategy": ["ep", "ep", "breakout"], "entry": ["open", "t_1030", "open"],
        "stop_rule": ["lod", "adr", "lod"], "trades": [120, 80, 60],
        "stopped_same_day%": [10.0, 5.0, 8.0], "R_hold_5d": [0.3, 0.5, 0.1],
        "win_hold_5d%": [50.0, 55.0, 40.0], "R_hold_21d": [0.4, 0.2, 0.0],
        "win_hold_21d%": [45.0, 50.0, 30.0],
    })  # fmt: skip
    summary.to_parquet(folder / "summary_none.parquet")
    out = client.get("/api/research/entries?period=2y&min_trades=70").json()
    assert out["splits"] == ["none"] and out["shown"] == ["hold_5d", "hold_21d"]
    assert out["table"]["total"] == 2  # the 60-trade group is under the minimum
    assert out["best"]["rows"]


def test_live_results(client):
    grades = client.get("/api/live/grades").json()  # the run's A+ / A / B, by their plan
    assert {r["grade"] for r in grades["compare"]["rows"]} == {"A+", "A", "B"}
    assert "too few trades yet" in grades["caption"] and grades["gaps"]["rows"] == []
    stats = client.get("/api/live/stats").json()
    assert stats["total"] == 0 and stats["table"]["rows"] == []
    assert client.get("/api/live/graded").json()["rows"] == []
    client.put("/api/grades/signal/sig-1", json={"grade": "A", "notes": "n"})
    [graded] = client.get("/api/live/graded").json()["rows"]
    assert graded["ref_id"] == "sig-1" and graded["ticker"] == B


# --- System health, Scans, Pull / Save & push


def test_system_health(client, monkeypatch):
    monkeypatch.setattr(health, "run_list", lambda *a, **k: pd.DataFrame())
    jobs = client.get("/api/system/jobs").json()
    assert jobs["grid"]["rows"] and "used_gb" in jobs["cache"]
    assert client.get("/api/system/github").json() == {"answered": False}
    assert client.post("/api/system/cache/clear").json()["message"].startswith("Emptied")


def test_validation_against_a_tradingview_export(data, client):  # noqa: F811
    runs = client.get("/api/system/validation/runs").json()
    assert runs["runs"][0]["id"] == f"{SESSION}_eod"
    body = {"run": f"{SESSION}_eod", "scan": "ep_day", "csv_text": f"Symbol\nNASDAQ:{A}\n"}
    out = client.post("/api/system/validation", json=body).json()
    assert out["total"] >= 1 and A in [r["ticker"] for r in out["rows"]]
    assert client.post("/api/system/validation", json={**body, "scan": "x"}).status_code == 400
    client.post("/api/system/validation/append", json=body)
    assert (data / "docs" / "validation.md").read_text().strip()


def test_scans_table_form_and_a_checked_save(client, config):
    out = client.get("/api/scans").json()
    assert out["rows"] and out["writable"] is True and out["checkout"] is False
    assert out["note"].startswith("Saved here, but Commit & push")
    name = next(
        n["key"]
        for n in out["names"]
        if client.get(f"/api/scans/{n['key']}/form").json()["numbers"]
    )
    form = client.get(f"/api/scans/{name}/form").json()
    field = form["numbers"][0]
    same = client.post(f"/api/scans/{name}", json={"values": {field["key"]: field["value"]}})
    assert same.json() == {"saved": False, "message": "Nothing changed.", "diff": ""}
    before = config.read_text()
    bumped = field["value"] + 1
    saved = client.post(f"/api/scans/{name}", json={"values": {field["key"]: bumped}}).json()
    assert saved["saved"] and f"{field['key']}" in saved["diff"]
    assert config.read_text() != before  # the copy, never the real config
    committed = client.post(f"/api/scans/{name}/commit").json()
    assert committed["ok"] is False and "git checkout" in committed["message"]
    config.chmod(0o444)
    try:
        refused = client.post(f"/api/scans/{name}", json={"values": {field["key"]: bumped + 1}})
        assert refused.status_code == 409 or refused.json().get("saved") is not None
    finally:
        config.chmod(0o644)


def test_pull_and_save_push_report_git_errors(client):
    pulled = client.post("/api/sync/pull").json()
    assert pulled["ok"] is False and pulled["message"]
    pushed = client.post("/api/sync/push").json()
    assert set(pushed) == {"ok", "message"}


def test_strategy_rules_serialize_numpy_numbers():
    import numpy as np

    from api.serialize import scalar

    found = {"rows": [{"trades": np.int64(3), "mean_r": np.float64(0.5)}], "n": np.int32(2)}
    assert scalar(found) == {"rows": [{"trades": 3, "mean_r": 0.5}], "n": 2}
