"""Trade journal from broker fills (SPEC §9, Phase 4). LOCAL USE ONLY: journal content never
goes to the public repo or its Actions logs.

- Fills are the source of truth and are append-only (data/journal/fills/). Re-importing the
  same export never duplicates: each fill gets a stable id.
- Trades are derived from all fills: a trade runs from flat to flat in one ticker (longs and
  shorts), with average entry/exit, P&L after fees, and the R-multiple when an initial stop
  is known. Each import writes a fresh snapshot (data/journal/journal_<timestamp>.parquet);
  the newest one is the journal.
- The initial stop comes from the stop you logged (dashboard), the signal the trade is linked
  to (its order_stop), or an optional stops CSV (ticker, entry_date, stop), in that order.
- Trades logged by hand (dashboard, Emil 20 Oct 2026) are fills with `source = manual` and a
  setup tag. When a broker export later brings the same fill (same day, ticker, side and
  quantity, price within 1 %), the broker fill wins and the manual one is ignored.

Limitation: a single fill that flips a position through zero (long to short) is treated as
one trade; split such fills in the export if they ever happen.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trading_os import clock, outcomes
from trading_os.config import load_config
from trading_os.store import PARQUET_OPTIONS, unique_stamp

FILL_COLUMNS = ["fill_id", "trade_date", "ticker", "side", "quantity", "price", "fees"]
EXTRA_FILL_COLUMNS = ["source", "setup"]  # manual fills carry both; broker fills: source only
TWIN_PRICE_TOLERANCE = 0.01
EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "CBOE", "OTC"}


def normalize_ticker(raw: str) -> str:
    """`NASDAQ:AAPL` and broker-style `AAPL:xnas` both become `AAPL`."""
    parts = str(raw).strip().split(":")
    if len(parts) == 2:
        return parts[1].upper() if parts[0].upper() in EXCHANGES else parts[0].upper()
    return parts[0].upper()


def read_fills(csv_path: Path, rules: Mapping[str, Any]) -> pd.DataFrame:
    """A broker export mapped to the standard fill columns (mapping in config)."""
    raw = pd.read_csv(csv_path)
    mapping = {source: target for target, source in rules["csv_columns"].items()}
    missing = [s for s in mapping if s not in raw.columns]
    if missing:
        raise ValueError(f"export is missing columns {missing}; adjust journal.csv_columns")
    df = raw.rename(columns=mapping)[list(mapping.values())]
    if "fees" not in df:
        df["fees"] = 0.0
    df["trade_date"] = pd.to_datetime(df["trade_date"], format=rules["date_format"]).dt.date
    df["ticker"] = df["ticker"].map(normalize_ticker)
    side = df["side"].astype(str).str.strip().str.lower()
    buys, sells = set(rules["buy_values"]), set(rules["sell_values"])
    if not side.isin(buys | sells).all():
        bad = sorted(set(side) - buys - sells)
        raise ValueError(f"unknown side values {bad}; adjust journal.buy_values/sell_values")
    df["side"] = np.where(side.isin(buys), "buy", "sell")
    df["quantity"] = df["quantity"].abs().astype(float)
    df["price"] = df["price"].astype(float)
    df["fees"] = df["fees"].fillna(0).abs().astype(float)
    df["fill_id"] = _fill_ids(df)
    return df[FILL_COLUMNS]


def _fill_ids(df: pd.DataFrame) -> list[str]:
    """Stable id per fill; identical fills on the same day are told apart by their order."""
    seen: dict[str, int] = {}
    ids = []
    for r in df.itertuples():
        key = f"{r.trade_date}|{r.ticker}|{r.side}|{r.quantity:g}|{r.price:g}"
        seen[key] = seen.get(key, 0) + 1
        ids.append(hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:16])
    return ids


def load_fills(data_dir: Path) -> pd.DataFrame:
    files = sorted((Path(data_dir) / "data" / "journal" / "fills").glob("*/*.parquet"))
    if not files:
        return pd.DataFrame(columns=FILL_COLUMNS + EXTRA_FILL_COLUMNS)
    fills = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    fills["trade_date"] = pd.to_datetime(fills["trade_date"]).dt.date
    if "source" not in fills:
        fills["source"] = "broker"
    fills["source"] = fills["source"].fillna("broker")
    if "setup" not in fills:
        fills["setup"] = None
    return fills


def manual_fill(
    trade_date: dt.date,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    fees: float = 0.0,
    setup: str | None = None,
    stamp: dt.datetime | None = None,
) -> pd.DataFrame:
    """One fill typed in by hand. Its id includes the time it was logged, so two identical
    fills on one day stay two fills."""
    stamp = stamp or unique_stamp()
    ticker = normalize_ticker(ticker)
    side = side.lower()
    if side not in ("buy", "sell") or not quantity > 0 or not price > 0:
        raise ValueError("a fill needs side buy/sell, a quantity and a price above 0")
    key = f"manual|{trade_date}|{ticker}|{side}|{quantity:g}|{price:g}|{stamp.isoformat()}"
    return pd.DataFrame(
        [
            {
                "fill_id": hashlib.sha1(key.encode()).hexdigest()[:16],
                "trade_date": trade_date,
                "ticker": ticker,
                "side": side,
                "quantity": float(quantity),
                "price": float(price),
                "fees": float(fees),
                "source": "manual",
                "setup": setup or None,
            }
        ]
    )


def reconcile(fills: pd.DataFrame) -> pd.DataFrame:
    """Drop manual fills that a broker fill now covers (the broker export is the record)."""
    if fills.empty or "source" not in fills or not (fills["source"] == "manual").any():
        return fills
    broker = fills[fills["source"] != "manual"]
    keep = []
    for row in fills.to_dict("records"):
        if row["source"] == "manual" and len(broker):
            twin = broker[
                (broker["trade_date"] == row["trade_date"])
                & (broker["ticker"] == row["ticker"])
                & (broker["side"] == row["side"])
                & np.isclose(broker["quantity"], row["quantity"])
                & ((broker["price"] / row["price"] - 1).abs() <= TWIN_PRICE_TOLERANCE)
            ]
            if len(twin):
                continue
        keep.append(row)
    return pd.DataFrame(keep, columns=fills.columns)


def stops_path(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "journal" / "stops"


def save_stop(data_dir: Path, ticker: str, entry_date: dt.date, stop: float) -> Path:
    """Append the initial stop of a trade (the newest entry per ticker and date wins)."""
    stamp = unique_stamp()
    folder = stops_path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp:%Y%m%dT%H%M%S%f}.parquet"
    row = {
        "ticker": normalize_ticker(ticker),
        "entry_date": entry_date,
        "stop": float(stop),
        "saved_ts": stamp,
    }
    pd.DataFrame([row]).to_parquet(path, **PARQUET_OPTIONS)
    return path


def load_stops(data_dir: Path) -> pd.DataFrame:
    files = sorted(stops_path(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=["ticker", "entry_date", "stop"])
    stops = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    stops["entry_date"] = pd.to_datetime(stops["entry_date"]).dt.date
    stops = stops.sort_values("saved_ts").drop_duplicates(["ticker", "entry_date"], keep="last")
    return stops[["ticker", "entry_date", "stop"]].reset_index(drop=True)


def new_fills(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    return incoming[~incoming["fill_id"].isin(set(existing["fill_id"]))].reset_index(drop=True)


def build_trades(fills: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(closed trades, open positions) from all fills, flat to flat per ticker."""
    trades, open_rows = [], []
    ordered = fills.sort_values(["ticker", "trade_date", "fill_id"], kind="stable")
    for ticker, group in ordered.groupby("ticker"):
        position, legs = 0.0, []
        for fill in group.to_dict("records"):
            signed = fill["quantity"] if fill["side"] == "buy" else -fill["quantity"]
            if position == 0:
                legs = []
            legs.append(fill)
            position += signed
            if abs(position) < 1e-9:
                trades.append(_trade(ticker, legs))
                position = 0.0
        if legs and abs(position) > 1e-9:
            open_rows.append(_trade(ticker, legs) | {"open_quantity": position})
    return pd.DataFrame(trades), pd.DataFrame(open_rows)


def _trade(ticker: str, legs: list[dict[str, Any]]) -> dict[str, Any]:
    direction = "long" if legs[0]["side"] == "buy" else "short"
    entry_side = "buy" if direction == "long" else "sell"
    entries = [f for f in legs if f["side"] == entry_side]
    exits = [f for f in legs if f["side"] != entry_side]
    entry_qty = sum(f["quantity"] for f in entries)
    exit_qty = sum(f["quantity"] for f in exits)
    entry_avg = sum(f["quantity"] * f["price"] for f in entries) / entry_qty
    exit_avg = sum(f["quantity"] * f["price"] for f in exits) / exit_qty if exit_qty else np.nan
    fees = sum(f["fees"] for f in legs)
    sign = 1 if direction == "long" else -1
    pnl = sign * (exit_avg - entry_avg) * exit_qty - fees if exit_qty else np.nan
    trade_id = hashlib.sha1("|".join(f["fill_id"] for f in legs).encode()).hexdigest()[:16]
    setups = [f.get("setup") for f in legs if f.get("setup") and not pd.isna(f.get("setup"))]
    return {
        "trade_id": trade_id,
        "ticker": ticker,
        "direction": direction,
        "entry_date": legs[0]["trade_date"],
        "exit_date": exits[-1]["trade_date"] if exits else None,
        "entry_avg": entry_avg,
        "exit_avg": exit_avg,
        "quantity": entry_qty,
        "fees": fees,
        "pnl": pnl,
        "fills": len(legs),
        "setup": setups[0] if setups else None,
        "manual": any(f.get("source") == "manual" for f in legs),
    }


def link_signals(
    trades: pd.DataFrame,
    candidates: pd.DataFrame,
    scans: list[str],
    sessions_before: dict[dt.date, list[dt.date]],
) -> pd.DataFrame:
    """Attach the latest qualifying signal (pushed first) from the sessions before entry."""
    out = trades.copy()
    for column in ("signal_id", "signal_scan", "signal_date", "order_stop"):
        out[column] = None
    if candidates.empty or trades.empty:
        return out
    pool = candidates[candidates["scan"].isin(scans)]
    for i, trade in out.iterrows():
        window = sessions_before.get(trade["entry_date"], [])
        match = pool[(pool["ticker"] == trade["ticker"]) & pool["session_date"].isin(window)]
        if match.empty:
            continue
        best = match.sort_values(["pushed", "session_date"], ascending=[False, False]).iloc[0]
        out.at[i, "signal_id"] = best["signal_id"]
        out.at[i, "signal_scan"] = best["scan"]
        out.at[i, "signal_date"] = best["session_date"]
        stop = best.get("order_stop")
        if stop is None or pd.isna(stop):  # EP signals: the planned stop from the alert
            stop = best.get("plan_stop")
        out.at[i, "order_stop"] = stop
    return out


def add_r_multiples(trades: pd.DataFrame, stops: pd.DataFrame | None = None) -> pd.DataFrame:
    """R = P&L / (initial risk per share × entry quantity); NaN without a usable stop."""
    out = trades.copy()
    if "order_stop" not in out:
        out["order_stop"] = None
    if stops is not None and not stops.empty and not out.empty:
        manual = {(r["ticker"], r["entry_date"]): r["stop"] for r in stops.to_dict("records")}
        fill = [manual.get((t, d)) for t, d in zip(out["ticker"], out["entry_date"], strict=True)]
        out["order_stop"] = [
            m if (o is None or pd.isna(o)) else o
            for o, m in zip(out["order_stop"], fill, strict=True)
        ]
    stop = pd.to_numeric(out.get("order_stop"), errors="coerce")
    sign = np.where(out["direction"] == "long", 1, -1) if len(out) else []
    risk = (out["entry_avg"] - stop) * sign
    out["initial_risk"] = (risk * out["quantity"]).where(risk > 0)
    out["r_multiple"] = out["pnl"] / out["initial_risk"]
    return out


def write_snapshot(data_dir: Path, trades: pd.DataFrame, stamp: dt.datetime) -> Path:
    path = Path(data_dir) / "data" / "journal" / f"journal_{stamp:%Y%m%dT%H%M%S}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(path, **PARQUET_OPTIONS)
    return path


def write_fills(data_dir: Path, fills: pd.DataFrame, stamp: dt.datetime) -> Path | None:
    if fills.empty:
        return None
    folder = Path(data_dir) / "data" / "journal" / "fills" / str(stamp.year)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp:%Y-%m-%dT%H%M%S%f}.parquet"  # two fills in one second
    fills.to_parquet(path, **PARQUET_OPTIONS)
    return path


def rebuild(data_dir: Path, cfg, stamp: dt.datetime, extra_stops=None) -> tuple:
    """Trades and open positions from every fill, with signals, stops, setups and R; writes
    `journal_<stamp>.parquet` (closed) and `positions_<stamp>.parquet` (open)."""
    rules = cfg.journal
    fills = reconcile(load_fills(data_dir))
    trades, open_positions = build_trades(fills)
    logged = load_stops(data_dir)
    if extra_stops is not None and not extra_stops.empty:
        logged = pd.concat([logged, extra_stops], ignore_index=True)
    own = {(r["ticker"], r["entry_date"]): r["stop"] for r in logged.to_dict("records")}
    candidates = outcomes.load_candidates(data_dir)
    lookback = rules["signal_lookback_sessions"]
    built = []
    for frame in (trades, open_positions):
        if frame.empty:
            built.append(frame)
            continue
        windows = {
            day: clock.sessions_back(cfg.schedule, day, lookback)
            for day in set(frame["entry_date"])
        }
        frame = link_signals(frame, candidates, list(rules["signal_scans"]), windows)
        # A stop you logged wins over the signal's.
        keys = zip(frame["ticker"], frame["entry_date"], frame["order_stop"], strict=True)
        frame["order_stop"] = [own.get((t, d), o) for t, d, o in keys]
        frame["setup"] = frame["setup"].where(frame["setup"].notna(), frame["signal_scan"])
        built.append(add_r_multiples(frame))
    trades, open_positions = built
    folder = Path(data_dir) / "data" / "journal"
    folder.mkdir(parents=True, exist_ok=True)
    write_snapshot(data_dir, trades, stamp)
    open_positions.to_parquet(
        folder / f"positions_{stamp:%Y%m%dT%H%M%S}.parquet", **PARQUET_OPTIONS
    )
    return trades, open_positions


def log_manual(data_dir: Path, cfg, fill: pd.DataFrame, stop: float | None = None) -> tuple:
    """Save a hand-typed fill (and the trade's initial stop for an entry), then rebuild."""
    stamp = unique_stamp()
    write_fills(data_dir, fill, stamp)
    row = fill.iloc[0]
    if stop is not None and stop > 0:
        save_stop(data_dir, row["ticker"], row["trade_date"], stop)
    return rebuild(data_dir, cfg, stamp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import broker fills into the trade journal")
    parser.add_argument("--csv", type=Path, required=True, help="broker fills export")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--stops", type=Path, help="optional CSV: ticker, entry_date, stop")
    args = parser.parse_args(argv)

    cfg = load_config()
    stamp = unique_stamp()
    existing = load_fills(args.data_dir)
    added = new_fills(existing, read_fills(args.csv, cfg.journal).assign(source="broker"))
    write_fills(args.data_dir, added, stamp)
    stops = None
    if args.stops:
        stops = pd.read_csv(args.stops)
        stops["entry_date"] = pd.to_datetime(stops["entry_date"]).dt.date
        stops["ticker"] = stops["ticker"].map(normalize_ticker)
    trades, open_positions = rebuild(args.data_dir, cfg, stamp, stops)
    if trades.empty:
        print(f"Journal: {len(added)} new fills, no closed trades yet, {len(open_positions)} open")
        return 0
    with_r = trades["r_multiple"].dropna()
    print(
        f"Journal: {len(added)} new fills, {len(trades)} closed trades "
        f"({len(with_r)} with R, mean R {with_r.mean():.2f}), {len(open_positions)} open"
    )
    return 0
