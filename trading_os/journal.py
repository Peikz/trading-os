"""Trade journal from broker fills (SPEC §9, Phase 4). LOCAL USE ONLY: journal content never
goes to the public repo or its Actions logs.

- Fills are the source of truth and are append-only (data/journal/fills/). Re-importing the
  same export never duplicates: each fill gets a stable id.
- Trades are derived from all fills: a trade runs from flat to flat in one ticker (longs and
  shorts), with average entry/exit, P&L after fees, and the R-multiple when an initial stop
  is known. Each import writes a fresh snapshot (data/journal/journal_<timestamp>.parquet);
  the newest one is the journal.
- The initial stop comes from the signal the trade is linked to (its order_stop), or from an
  optional stops CSV (ticker, entry_date, stop) for trades without one.

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
from trading_os.store import PARQUET_OPTIONS

FILL_COLUMNS = ["fill_id", "trade_date", "ticker", "side", "quantity", "price", "fees"]
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
        return pd.DataFrame(columns=FILL_COLUMNS)
    fills = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    fills["trade_date"] = pd.to_datetime(fills["trade_date"]).dt.date
    return fills


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
        out.at[i, "order_stop"] = best.get("order_stop")
    return out


def add_r_multiples(trades: pd.DataFrame, stops: pd.DataFrame | None = None) -> pd.DataFrame:
    """R = P&L / (initial risk per share × entry quantity); NaN without a usable stop."""
    out = trades.copy()
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
    path = folder / f"{stamp:%Y-%m-%dT%H%M%S}.parquet"
    fills.to_parquet(path, **PARQUET_OPTIONS)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import broker fills into the trade journal")
    parser.add_argument("--csv", type=Path, required=True, help="broker fills export")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--stops", type=Path, help="optional CSV: ticker, entry_date, stop")
    args = parser.parse_args(argv)

    cfg = load_config()
    rules = cfg.journal
    stamp = dt.datetime.now(dt.UTC)
    existing = load_fills(args.data_dir)
    added = new_fills(existing, read_fills(args.csv, rules))
    write_fills(args.data_dir, added, stamp)
    fills = pd.concat([existing, added], ignore_index=True)
    trades, open_positions = build_trades(fills)
    if trades.empty:
        print(f"Journal: {len(added)} new fills, no closed trades yet")
        return 0
    lookback = rules["signal_lookback_sessions"]
    windows = {
        day: clock.sessions_back(cfg.schedule, day, lookback) for day in set(trades["entry_date"])
    }
    trades = link_signals(
        trades, outcomes.load_candidates(args.data_dir), list(rules["signal_scans"]), windows
    )
    stops = None
    if args.stops:
        stops = pd.read_csv(args.stops)
        stops["entry_date"] = pd.to_datetime(stops["entry_date"]).dt.date
        stops["ticker"] = stops["ticker"].map(normalize_ticker)
    trades = add_r_multiples(trades, stops)
    path = write_snapshot(args.data_dir, trades, stamp)
    with_r = trades["r_multiple"].dropna()
    print(
        f"Journal: {len(added)} new fills, {len(trades)} closed trades "
        f"({len(with_r)} with R, mean R {with_r.mean():.2f}), {len(open_positions)} open; "
        f"saved {path.name}"
    )
    return 0
