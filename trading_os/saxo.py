"""Saxo Bank OpenAPI, read-only (Emil, 22 Oct 2026): your open positions and your working stop
orders, so the journal and the position manager match the broker. Nothing here places, changes
or cancels an order: the client only sends GET requests.

Status: written from Saxo's public OpenAPI reference; not yet run against Emil's account, which
needs his developer app (docs/SAXO.md). `scripts/saxo_sync.py --check` is the first real test.
Token: SAXO_TOKEN in the environment (an access token from the app's sign-in); SAXO_ENV=sim
uses Saxo's simulation gateway.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from trading_os.journal import normalize_ticker
from trading_os.store import PARQUET_OPTIONS

LIVE = "https://gateway.saxobank.com/openapi"
SIM = "https://gateway.saxobank.com/sim/openapi"
STOP_TYPES = {"Stop", "StopIfTraded", "StopIfBid", "StopIfOffered", "TrailingStopIfTraded"}


class SaxoClient:
    """GET-only access to one's own account."""

    def __init__(self, token: str, base: str = LIVE, session: requests.Session | None = None):
        if not token:
            raise ValueError("Saxo token is empty")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._base = base.rstrip("/")
        self._http = session or requests.Session()

    def _get(self, path: str, params: dict | None = None) -> dict:
        reply = self._http.get(
            self._base + path, params=params or {}, headers=self._headers, timeout=30
        )
        if not reply.ok:
            # Never the body: it could hold account details, and job logs are public.
            raise requests.HTTPError(f"Saxo HTTP {reply.status_code}", response=reply)
        return reply.json() if reply.content else {}

    def me(self) -> dict:
        return self._get("/port/v1/users/me")

    def positions(self) -> list[dict]:
        groups = "PositionBase,PositionView,DisplayAndFormat"
        return self._get("/port/v1/positions/me", {"FieldGroups": groups}).get("Data", [])

    def orders(self) -> list[dict]:
        return self._get("/port/v1/orders/me", {"FieldGroups": "DisplayAndFormat"}).get("Data", [])


def _symbol(item: dict) -> str:
    raw = (item.get("DisplayAndFormat") or {}).get("Symbol") or item.get("Symbol") or ""
    return normalize_ticker(raw)


def positions_frame(data: list[dict]) -> pd.DataFrame:
    """Saxo positions → ticker, direction, quantity, entry_avg, entry_ts, current, asset_type."""
    rows = []
    for item in data:
        base = item.get("PositionBase") or {}
        view = item.get("PositionView") or {}
        amount = float(base.get("Amount") or 0)
        if not amount:
            continue
        rows.append(
            {
                "ticker": _symbol(item),
                "direction": "long" if amount > 0 else "short",
                "quantity": abs(amount),
                "entry_avg": float(base.get("OpenPrice") or 0) or None,
                "entry_ts": base.get("ExecutionTimeOpen"),
                "current": view.get("CurrentPrice"),
                "asset_type": base.get("AssetType"),
            }
        )
    cols = ["ticker", "direction", "quantity", "entry_avg", "entry_ts", "current", "asset_type"]
    return pd.DataFrame(rows, columns=cols)


def stop_orders(data: list[dict]) -> pd.DataFrame:
    """Working stop orders → ticker, side, stop, amount, order_type."""
    rows = [
        {
            "ticker": _symbol(o),
            "side": str(o.get("BuySell", "")).lower(),
            "stop": float(o["Price"]),
            "amount": float(o.get("Amount") or 0),
            "order_type": o.get("OrderType"),
        }
        for o in data
        if o.get("OrderType") in STOP_TYPES and o.get("Price") is not None
    ]
    return pd.DataFrame(rows, columns=["ticker", "side", "stop", "amount", "order_type"])


def with_broker_stops(positions: pd.DataFrame, stops: pd.DataFrame) -> pd.DataFrame:
    """Your journal positions with the stop from Saxo where a working stop order protects
    them (a sell stop for a long, a buy stop for a short); the logged stop otherwise."""
    if positions.empty or stops.empty:
        return positions
    out = positions.copy()
    for i, p in out.iterrows():
        side = "sell" if str(p.get("direction", "long")) == "long" else "buy"
        mine = stops[(stops["ticker"] == p["ticker"]) & (stops["side"] == side)]
        if len(mine):
            # Several stops (scaled exits): the one closest to the price protects first.
            out.at[i, "order_stop"] = mine["stop"].max() if side == "sell" else mine["stop"].min()
            out.at[i, "stop_source"] = "Saxo"
    return out


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "journal" / "broker"


def save(data_dir: Path, positions: pd.DataFrame, stops: pd.DataFrame, when: dt.datetime) -> None:
    out = folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    positions.to_parquet(out / f"saxo_positions_{when:%Y%m%dT%H%M%S}.parquet", **PARQUET_OPTIONS)
    stops.to_parquet(out / f"saxo_stops_{when:%Y%m%dT%H%M%S}.parquet", **PARQUET_OPTIONS)


def latest_stops(data_dir: Path, max_age_days: int = 3) -> pd.DataFrame:
    """The newest saved Saxo stop orders, if recent enough to trust."""
    files = sorted(folder(data_dir).glob("saxo_stops_*.parquet"))
    if not files:
        return pd.DataFrame(columns=["ticker", "side", "stop", "amount", "order_type"])
    stamp = dt.datetime.strptime(files[-1].stem.removeprefix("saxo_stops_"), "%Y%m%dT%H%M%S")
    if dt.datetime.now() - stamp > dt.timedelta(days=max_age_days):
        return pd.DataFrame(columns=["ticker", "side", "stop", "amount", "order_type"])
    return pd.read_parquet(files[-1])


def client_from_env(env: dict[str, Any]) -> SaxoClient:
    base = SIM if str(env.get("SAXO_ENV", "")).lower() == "sim" else LIVE
    return SaxoClient(str(env.get("SAXO_TOKEN", "")), base)
