"""Price alerts: your own alerts, the watch list, hits that fire once, and the live prices.
Synthetic data only."""

import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from trading_os import alerts
from trading_os.alpaca import AlpacaClient
from trading_os.config import load_config

A, B = "".join(["S", "R", "F"]), "".join(["K", "L", "M"])
DAY = dt.date(2026, 10, 22)


def watcher():
    spec = importlib.util.spec_from_file_location(
        "alert_watch", Path(__file__).resolve().parents[1] / "scripts" / "alert_watch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_your_alerts_are_added_listed_and_ended(tmp_path):
    first = alerts.add(tmp_path, A.lower(), 15.3, "above", " breakout ")
    alerts.add(tmp_path, B, 8.0, "below")
    live = alerts.current(tmp_path)
    assert live["ticker"].tolist() == [B, A]
    assert live.set_index("ticker").loc[A, "note"] == "breakout"
    alerts.end(tmp_path, first)
    assert alerts.current(tmp_path)["ticker"].tolist() == [B]
    with pytest.raises(ValueError):
        alerts.add(tmp_path, A, 10, "sideways")


def test_the_watch_list_takes_pivots_stops_and_yours(tmp_path):
    cands = pd.DataFrame(
        {
            "scan": ["ma_surf", "breakout_watch", "ep9m", "ma_surf"],
            "ticker": [A, B, A, B],
            "tier": ["alert", "alert", "alert", "log"],
            "pivot": [10.4, 20.0, None, 5.0],
            "order_stop": [9.8, 19.0, None, 4.5],
        }
    )
    pivots = alerts.pivot_items(cands, DAY)
    assert sorted(pivots["ticker"]) == sorted([A, B])  # the log-tier MA-surf and EP9M are left out
    assert set(pivots["direction"]) == {"above"}
    positions = pd.DataFrame(
        {"ticker": [A, B], "direction": ["long", "short"], "order_stop": [9.0, 30.0],
         "entry_date": [DAY, DAY]}
    )  # fmt: skip
    stops = alerts.stop_items(positions, DAY).set_index("ticker")
    assert stops.loc[A, "direction"] == "below" and stops.loc[B, "direction"] == "above"


def test_hits_fire_once_on_the_right_side():
    items = pd.DataFrame(
        [
            {"key": "k1", "kind": "pivot", "ticker": A, "level": 10.4, "direction": "above",
             "note": "MA-surf", "plan_stop": 9.8},
            {"key": "k2", "kind": "stop", "ticker": B, "level": 8.0, "direction": "below",
             "note": "your stop", "plan_stop": None},
        ]
    )  # fmt: skip
    found = alerts.hits(items, {A: 10.5, B: 8.2}, done=set())
    assert found["key"].tolist() == ["k1"] and found.iloc[0]["price"] == 10.5
    assert alerts.hits(items, {A: 10.5, B: 7.9}, done={"k1"})["key"].tolist() == ["k2"]
    assert alerts.hits(items, {}, done=set()).empty  # no price, no alert
    title, body = alerts.message(found.iloc[0].to_dict(), "10:42 NY · 16:42 CPH")
    assert title == f"🎯 {A} over its MA-surf pivot 10.40"
    assert "stop 9.80" in body and "16:42 CPH" in body


def test_one_check_pushes_records_and_ends_your_alert(tmp_path):
    module = watcher()
    alert_id = alerts.add(tmp_path, A, 15.0, "above", "news day")
    items = alerts.own_items(alerts.current(tmp_path))
    sent = []

    class Prices:
        def latest_prices(self, symbols):
            return {A: 15.2}

    def push(title, body):
        sent.append((title, body))

    cfg = load_config()
    assert module.check(tmp_path, cfg, Prices(), DAY, items, push) == 1
    assert module.check(tmp_path, cfg, Prices(), DAY, items, push) == 0  # once only
    assert sent[0][0] == f"🔔 {A} over 15.00" and "news day" in sent[0][1]
    assert alerts.current(tmp_path).empty  # fired alerts end
    assert alerts.fired(tmp_path, DAY)[0]["key"] == f"mine:{alert_id}"


def test_latest_prices_ask_the_iex_feed_in_batches():
    calls = []

    class Response:
        ok, status_code = True, 200

        def __init__(self, symbols):
            self._symbols = symbols

        def json(self):
            return {"trades": {s: {"p": 1.5, "t": "x"} for s in self._symbols}}

    class Session:
        def get(self, url, params, headers, timeout):
            calls.append(params)
            return Response(params["symbols"].split(","))

    client = AlpacaClient("id", "secret", session=Session(), sleep=lambda s: None)
    symbols = [f"S{i:03d}" for i in range(150)]
    prices = client.latest_prices(symbols)
    assert len(prices) == 150 and len(calls) == 2
    assert all(c["feed"] == "iex" for c in calls)


def test_once_builds_the_watch_list_at_once_on_a_fresh_machine(tmp_path, monkeypatch, capsys):
    module = watcher()
    alerts.add(tmp_path, A, 99.0, "above")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setattr(module.time, "monotonic", lambda: 12.0)  # booted 12 seconds ago
    monkeypatch.setattr(module.dashboard, "pull", lambda d: (True, ""))
    monkeypatch.setattr(module.AlpacaClient, "latest_prices", lambda self, s: {A: 10.0})
    assert module.main(["--data-dir", str(tmp_path), "--once", "--no-push"]) == 0
    assert "watching 1" in capsys.readouterr().out
