"""Phase 2a of the React dashboard's API (`api/pages.py`): the ticket, Notes & alerts, the
grading form, Journal, Positions and Watchlists, over a synthetic data repo. Synthetic data
only: the tickers are built from letters so no real symbol appears here."""

import base64
import datetime as dt

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from tests.test_api import SESSION, A, B, C, D, candidates  # noqa: E402
from tests.test_api import data as base_data  # noqa: E402, F401
from trading_os import alerts, my_watchlists, plans, stock_notes  # noqa: E402

UNKNOWN = "".join(["Q", "Z", "Q", "Z", "Q"])


@pytest.fixture
def data(base_data):  # noqa: F811
    """The phase-1 repo, its run with the columns a real run has (the journal links them)."""
    path = base_data / "data" / "candidates" / "2026" / f"{SESSION}_eod.parquet"
    cands = candidates()
    cands = cands.assign(
        session_date=SESSION, slot="eod", rank=range(1, len(cands) + 1),
        signal_id=[f"sig-{i}" for i in range(len(cands))],
    )  # fmt: skip
    cands.to_parquet(path)
    return base_data


@pytest.fixture
def client(data):
    return TestClient(create_app(data))


@pytest.fixture
def account(data):
    (data / "settings").mkdir()
    (data / "settings" / "account.yaml").write_text(
        "currency: USD\nsize: 100000\nrisk_pct: 0.5\nmax_position_pct: 100\n"
    )
    return data


def board_row(client, ticker):
    return next(r for r in client.get("/api/today").json()["rows"] if r["ticker"] == ticker)


def test_rows_carry_the_alert_default(client):
    assert board_row(client, A)["alert_default"] == 10.0  # no pivot: the plan's entry


def test_the_ticket_sizes_at_the_grades_risk(account, client):
    row = board_row(client, B)  # A+: 2 x the 500 USD risk per trade
    out = client.post("/api/ticket", json={"row": row}).json()
    assert out["kind"] == out["default"] == "market"
    assert out["price_label"] == "Expected price (sizing)" and out["plan_price"] == 10.0
    t = out["ticket"]
    assert t["shares"] == 1000 and t["stop"] == 9.0 and t["risk_usd"] == pytest.approx(1000)
    lines = {x["label"]: x["value"] for x in t["lines"]}
    assert lines["Buy"] == "1000" and lines["Stop loss (own order, GTC)"] == "9.00"
    assert "Risk 1,000 USD" in t["caption"]
    # An own limit price recomputes the shares; under the stop there is no ticket
    own = client.post("/api/ticket", json={"row": row, "kind": "limit", "price": 9.5}).json()
    assert own["ticket"]["shares"] == 2000 and own["ticket"]["limit"] == 9.5
    bad = client.post("/api/ticket", json={"row": row, "kind": "limit", "price": 8.0}).json()
    assert bad["ticket"] is None and bad["error"]
    assert client.post("/api/ticket", json={"row": row, "kind": "x"}).status_code == 400


def test_an_ungraded_row_is_sized_as_a_b_and_without_account_there_is_no_size(account, client):
    row = board_row(client, A) | {"grade": "C", "grade_risk_mult": None}
    out = client.post("/api/ticket", json={"row": row}).json()
    assert out["note"].startswith("Not graded") and out["ticket"]["shares"] == 500
    (account / "settings" / "account.yaml").unlink()
    plain = TestClient(create_app(account)).post("/api/ticket", json={"row": row}).json()
    assert plain["ticket"] is None and "account.yaml" in plain["note"]


def test_placed_in_saxo_saves_a_plan_for_the_next_session(account, client):
    row = board_row(client, B)
    out = client.post("/api/ticket/place", json={"row": row, "kind": "stop"}).json()
    saved = plans.load(account)
    assert len(saved) == 1 and saved.iloc[0]["plan_id"] == out["plan_id"]
    plan = saved.iloc[0]
    assert plan["ticker"] == B and plan["shares"] == 1000 and plan["setup"] == "ep_ah"
    assert plan["session_date"] > SESSION  # an EOD find trades the next session
    listed = client.get("/api/journal/plans").json()
    assert listed["plans"][0]["status"] == "open"


def test_flags_go_to_watchlists_and_show_in_the_my_watchlists_scope(data, client):
    assert client.post("/api/flags", json={"ticker": A}).json()["message"] == f"{A} → Flag green"
    assert client.post("/api/flags", json={"ticker": A, "name": "Other"}).status_code == 400
    members = my_watchlists.current(my_watchlists.load(data))
    assert list(members["list"]) == ["Flag green"]
    out = client.get("/api/today?scope=watchlists").json()
    assert [r["ticker"] for r in out["rows"]] == [A]
    assert out["rows"][0]["exchange"] == "NASDAQ" and out["rows"][0]["grade"] == "–"
    # One list by name (Emil, 4 Nov 2026)
    assert [
        r["ticker"] for r in client.get("/api/today?scope=watchlists&wl=Flag green").json()["rows"]
    ] == [A]
    assert client.get("/api/today?scope=watchlists&wl=Nope").json()["rows"] == []


def test_a_screen_flips_through_on_today(client):
    out = client.get(f"/api/today?screen=Mine&t={D},{A}").json()
    assert out["scope"] == "screen" and [r["ticker"] for r in out["rows"]] == [D, A]
    assert out["rows"][0]["run_label"] == "screen: Mine"


def test_stock_notes_newest_first(data, client):
    client.post(f"/api/stock-notes/{A}", json={"text": "first"})
    out = client.post(f"/api/stock-notes/{A}", json={"text": "second"}).json()
    assert [n["text"] for n in out] == ["second", "first"]
    assert len(stock_notes.current(data, A)) == 2
    assert client.post(f"/api/stock-notes/{A}", json={"text": " "}).status_code == 400


def test_price_alerts_add_list_remove(data, client):
    out = client.post("/api/alerts", json={"ticker": A.lower(), "level": 12.5}).json()
    assert out["message"] == f"Alert set: {A} above 12.50."
    [alert] = out["alerts"]
    assert alert["ticker"] == A and alert["level"] == 12.5
    assert client.post("/api/alerts", json={"ticker": "1x", "level": 1}).status_code == 400
    assert client.delete(f"/api/alerts/{alert['alert_id']}").json()["alerts"] == []
    assert alerts.current(data).empty
    assert client.delete("/api/alerts/nope").status_code == 404


def test_the_grading_form_saves_grade_notes_and_screenshots(client):
    shot = {"name": "a.png", "data": base64.b64encode(b"\x89PNG fake").decode()}
    body = {"grade": "A", "notes": "clean", "tags": "x", "screenshots": [shot]}
    out = client.put("/api/grades/signal/s-1", json=body).json()
    assert out["grade"] == "A" and out["notes"] == "clean" and len(out["attachments"]) == 1
    again = client.get("/api/grades/signal/s-1").json()
    assert again["attachments"] == out["attachments"]
    assert client.get(f"/api/attachments/{out['attachments'][0]}").content == b"\x89PNG fake"
    assert client.get("/api/attachments/settings/account.yaml").status_code == 404
    assert client.get("/api/attachments/../../etc/passwd").status_code == 404
    assert client.put("/api/grades/signal/s-1", json={"grade": "Z"}).status_code == 400
    bad = {"screenshots": [{"name": "a.exe", "data": shot["data"]}]}
    assert client.put("/api/grades/signal/s-1", json=bad).status_code == 400


def test_journal_fills_open_positions_and_closed_trades(account, client):
    day, later = "2026-06-01", "2026-06-10"
    fills = [
        {"date": day, "ticker": A, "side": "buy", "shares": 100, "price": 10.0,
         "setup": "ep_day", "stop": 9.5},
        {"date": later, "ticker": A, "side": "sell", "shares": 100, "price": 11.0},
        {"date": "2026-06-12", "ticker": A, "side": "buy", "shares": 50, "price": 11.0,
         "stop": 10.0},
    ]  # fmt: skip
    for f in fills:
        assert client.post("/api/journal/fills", json=f).status_code == 200
    closed = client.get("/api/journal/closed").json()
    assert closed["stats"]["trades"] == 1 and closed["stats"]["win_rate"] == 100.0
    assert closed["stats"]["avg_r"] == pytest.approx(2.0)  # +1.00 on a 0.50 risk
    assert closed["curve"] == [{"time": "2026-06-10", "value": 2.0}]
    trade = closed["trades"][0]
    assert trade["mfe_r"] is not None and trade["label"].startswith(f"{A} 2026-06-01")
    opened = client.get("/api/journal/open").json()
    assert opened["totals"]["positions"] == 1
    assert opened["rows"][0]["last_close"] == pytest.approx(18.1)  # the newest bar's close
    assert opened["plan"] and opened["plan_day"] == SESSION.isoformat()
    bad = {"date": day, "ticker": A, "side": "buy", "shares": 0, "price": 1}
    assert client.post("/api/journal/fills", json=bad).status_code == 400


def test_positions_cards(account, client, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    fill = {"date": "2026-06-01", "ticker": A, "side": "buy", "shares": 100, "price": 10.0,
            "setup": "ep_day", "stop": 9.0}  # fmt: skip
    client.post("/api/journal/fills", json=fill)
    out = client.get("/api/positions").json()
    assert "not live" in out["source"]
    [card] = out["cards"]
    assert card["price"] == pytest.approx(18.1) and card["open_r"] == pytest.approx(8.1)
    assert card["pnl"] == pytest.approx(810) and card["to_stop_pct"] == pytest.approx(50.28, 0.01)
    assert any(f.startswith("Plan: sell at the close after") for f in card["facts"])


def test_plans_suggest_create_and_cancel(account, client):
    s = client.get("/api/journal/plans/suggest?entry=10&stop=9").json()
    assert s["suggestion"]["shares"] == 500 and s["text"].startswith("Suggested: 500 shares")
    body = {"session": "2026-11-02", "ticker": A, "entry": 10, "stop": 9, "shares": 500}
    out = client.post("/api/journal/plans", json=body).json()
    plan_id = out["plan_id"]
    assert out["hits"][0]["label"].startswith(f"{B} · ep_ah") or out["hits"]
    assert client.post("/api/journal/plans", json=body | {"stop": 11}).status_code == 400
    after = client.post(f"/api/journal/plans/{plan_id}/cancel").json()
    assert after["plans"][0]["status"] == "cancelled"
    assert client.post(f"/api/journal/plans/{plan_id}/cancel").status_code == 404


def test_watchlist_add_checks_each_ticker(data, client):
    out = client.post("/api/watchlists/Mine/add", json={"text": f"{A}, {UNKNOWN}"}).json()
    assert out["kind"] == "warning" and out["added"] == [A] and out["unknown"] == [UNKNOWN]
    export = f"###Section\nNYSE:{B},NASDAQ:{A}"
    again = client.post("/api/watchlists/Mine/add", json={"export_text": export}).json()
    assert again["added"] == [B] and again["already"] == [A] and again["kind"] == "success"
    assert client.post("/api/watchlists/Mine/add", json={}).json()["kind"] == "warning"
    assert client.post("/api/watchlists/%20/add", json={"text": A}).json()["kind"] == "error"
    assert client.get("/api/watchlists").json()["lists"] == ["Mine"]
    shown = client.get("/api/watchlists/Mine").json()
    assert [r["ticker"] for r in shown["rows"]] == [A, B]
    assert shown["rows"][0]["close"] == 10.0 and shown["rows"][0]["in_scans"] == "ep_ah"
    assert shown["tv_list"] == f"NASDAQ:{A},NYSE:{B}"
    left = client.post("/api/watchlists/Mine/remove", json={"tickers": [A]}).json()
    assert [r["ticker"] for r in left["rows"]] == [B]


def test_scan_watchlists_are_empty_until_the_jobs_fill_them(client):
    out = client.get("/api/scan-watchlists").json()
    assert out["bo_watch"] == {"label": "BO-Watch", "rows": []}


def test_the_screener_gives_flip_tickers_and_a_tradingview_list(client):
    out = client.post("/api/screener/run", json={"filters": [], "sort": "rs_pct"}).json()
    assert out["tickers"] == [D, A, C, B]  # RS highest first
    assert out["tv_list"] == f"NYSE:{D},NASDAQ:{A},NASDAQ:{C},NYSE:{B}"


def test_fired_alerts_show_for_today(data, client, monkeypatch):
    from trading_os import journal_view

    today = dt.date(2026, 10, 30)
    monkeypatch.setattr(journal_view, "ny_today", lambda cfg: today)
    alerts.record(data, today, {"kind": "own", "ticker": A, "level": 11.0, "price": 11.1})
    fired = client.get("/api/alerts").json()["fired"]
    assert fired[0]["ticker"] == A and fired[0]["price"] == 11.1


def test_scan_hits_carry_their_signal_ids_for_the_grading_form(client):
    body = {"source": "hits", "run": f"{SESSION}_eod", "scan": "ep_ah", "filters": []}
    out = client.post("/api/screener/run", json=body).json()
    assert out["tickers"] == [B, A, C]
    assert out["signal_ids"] == {A: "sig-0", B: "sig-1", C: "sig-2"}
