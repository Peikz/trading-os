"""Saxo, read-only: positions and stop orders from the OpenAPI's shapes, and the broker's stop
winning over the logged one (synthetic data only)."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import saxo

A, B = "".join(["S", "R", "F"]), "".join(["K", "L", "M"])
POSITIONS = [
    {"PositionBase": {"Amount": 300, "OpenPrice": 10.5, "AssetType": "Stock",
                      "ExecutionTimeOpen": "2026-10-20T14:31:00Z"},
     "PositionView": {"CurrentPrice": 11.2},
     "DisplayAndFormat": {"Symbol": f"{A}:xnas"}},
    {"PositionBase": {"Amount": -100, "OpenPrice": 40.0, "AssetType": "Stock"},
     "DisplayAndFormat": {"Symbol": f"{B}:xnys"}},
]  # fmt: skip
ORDERS = [
    {"OrderType": "StopIfTraded", "BuySell": "Sell", "Price": 9.9, "Amount": 300,
     "DisplayAndFormat": {"Symbol": f"{A}:xnas"}},
    {"OrderType": "Limit", "BuySell": "Sell", "Price": 14.0, "Amount": 100,
     "DisplayAndFormat": {"Symbol": f"{A}:xnas"}},
    {"OrderType": "Stop", "BuySell": "Buy", "Price": 42.0, "Amount": 100,
     "DisplayAndFormat": {"Symbol": f"{B}:xnys"}},
]  # fmt: skip


def test_positions_and_stop_orders_from_saxo_shapes():
    pos = saxo.positions_frame(POSITIONS).set_index("ticker")
    assert pos.loc[A, "direction"] == "long" and pos.loc[A, "quantity"] == 300
    assert pos.loc[B, "direction"] == "short" and pos.loc[B, "entry_avg"] == 40.0
    stops = saxo.stop_orders(ORDERS)
    assert len(stops) == 2  # the take-profit limit is not a stop
    assert set(stops["side"]) == {"sell", "buy"}


def test_the_saxo_stop_wins_over_the_logged_one():
    mine = pd.DataFrame(
        {"ticker": [A, B, "OTHER"], "direction": ["long", "short", "long"],
         "order_stop": [9.5, 43.0, 5.0]}
    )  # fmt: skip
    out = saxo.with_broker_stops(mine, saxo.stop_orders(ORDERS)).set_index("ticker")
    assert out.loc[A, "order_stop"] == 9.9 and out.loc[A, "stop_source"] == "Saxo"
    assert out.loc[B, "order_stop"] == 42.0
    assert out.loc["OTHER", "order_stop"] == 5.0  # no Saxo stop: the logged one stays


def test_saved_stops_are_used_only_while_fresh(tmp_path):
    stops = saxo.stop_orders(ORDERS)
    saxo.save(tmp_path / "new", saxo.positions_frame(POSITIONS), stops, dt.datetime.now())
    assert len(saxo.latest_stops(tmp_path / "new")) == 2
    saxo.save(tmp_path / "old", saxo.positions_frame(POSITIONS), stops, dt.datetime(2020, 1, 1))
    assert saxo.latest_stops(tmp_path / "old").empty


def test_the_client_only_reads():
    calls = []

    class Session:
        def get(self, url, params, headers, timeout):
            calls.append(url)

            class R:
                ok, status_code, content = True, 200, b"{}"

                def json(self):
                    return {"Data": ORDERS}

            return R()

    client = saxo.SaxoClient("token", saxo.SIM, session=Session())
    assert len(client.orders()) == 3 and calls[0].startswith(saxo.SIM)
    assert not any(hasattr(client, m) for m in ("post", "put", "delete", "place_order"))
    with pytest.raises(ValueError):
        saxo.SaxoClient("")
