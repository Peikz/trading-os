"""Price alerts during the session (Emil, 22 Oct 2026: "alerts when it hits something
specific"). Facts only: nothing here places an order.

Every minute of the regular session the watcher (`scripts/alert_watch.py`) reads live prices for
a short list and pushes one ntfy message per event, once:
- pivot: last close's BO-Watch and MA-surf names (alert tier) trading over their pivot, with
  the plan's stop;
- stop: an open position from the journal trading at or through its stop;
- yours: alerts added on the dashboard (ticker, price, above or below, note), kept as
  append-only events in the data repo under `data/my_alerts/`. They fire once and then end.

Prices: Alpaca's free real-time IEX feed (the latest trade), one request per 100 symbols.
IEX volume is a small slice of the market, so alerts are on price only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = ["alert_id", "ticker", "level", "direction", "note", "action", "saved_ts"]
DIRECTIONS = ("above", "below")
PIVOT_SCANS = {"breakout_watch": "BO-Watch", "ma_surf": "MA-surf"}
ITEM_COLUMNS = ["key", "kind", "ticker", "level", "direction", "note", "plan_stop"]
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "my_alerts"


# ---------------------------------------------------------------- your own alerts


def _write(data_dir: Path, rows: list[dict]) -> None:
    out = folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = rows[0]["saved_ts"]
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame.to_parquet(out / f"{stamp:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def add(data_dir: Path, ticker: str, level: float, direction: str, note: str = "") -> str:
    """A new alert; returns its id."""
    ticker = ticker.strip().upper()
    if not TICKER.match(ticker):
        raise ValueError(f"not a ticker: {ticker!r}")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    if not level > 0:
        raise ValueError("the price must be above 0")
    stamp = unique_stamp()
    alert_id = f"{stamp:%Y%m%dT%H%M%S%f}"
    row = {
        "alert_id": alert_id,
        "ticker": ticker,
        "level": float(level),
        "direction": direction,
        "note": note.strip(),
        "action": "add",
        "saved_ts": stamp,
    }
    _write(data_dir, [row])
    return alert_id


def end(data_dir: Path, alert_id: str, action: str = "remove") -> None:
    """Ends an alert: removed by you, or `fired` by the watcher."""
    row = dict.fromkeys(COLUMNS) | {"alert_id": alert_id, "action": action}
    _write(data_dir, [row | {"saved_ts": unique_stamp()}])


def events(data_dir: Path) -> pd.DataFrame:
    files = sorted(folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def current(data_dir: Path) -> pd.DataFrame:
    """Your alerts that are still on: added, not removed or fired."""
    ev = events(data_dir)
    if ev.empty:
        return pd.DataFrame(columns=COLUMNS[:5])
    ended = set(ev.loc[ev["action"] != "add", "alert_id"])
    live = ev[(ev["action"] == "add") & ~ev["alert_id"].isin(ended)]
    return live[COLUMNS[:5]].sort_values("ticker").reset_index(drop=True)


# ---------------------------------------------------------------- what fired today


def fired_path(data_dir: Path, session: dt.date) -> Path:
    return folder(data_dir) / "fired" / f"{session.isoformat()}.jsonl"


def fired(data_dir: Path, session: dt.date) -> list[dict]:
    path = fired_path(data_dir, session)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def record(data_dir: Path, session: dt.date, hit: dict) -> None:
    path = fired_path(data_dir, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(hit, default=str) + "\n")


# ---------------------------------------------------------------- the watch list


def pivot_items(candidates: pd.DataFrame, session: dt.date) -> pd.DataFrame:
    """Last close's BO-Watch and MA-surf hits (alert tier): over the pivot."""
    if candidates.empty or "scan" not in candidates:
        return pd.DataFrame(columns=ITEM_COLUMNS)
    rows = candidates[candidates["scan"].isin(PIVOT_SCANS)]
    if "tier" in rows:
        rows = rows[rows["tier"] == "alert"]
    rows = rows[rows["pivot"].notna()] if "pivot" in rows else rows.iloc[0:0]
    out = []
    for r in rows.to_dict("records"):
        stop = r.get("order_stop")
        out.append(
            {
                "key": f"pivot:{r['scan']}:{r['ticker']}:{session}",
                "kind": "pivot",
                "ticker": r["ticker"],
                "level": float(r["pivot"]),
                "direction": "above",
                "note": PIVOT_SCANS[r["scan"]],
                "plan_stop": float(stop) if stop is not None and not pd.isna(stop) else None,
            }
        )
    return pd.DataFrame(out, columns=ITEM_COLUMNS).drop_duplicates("key")


def stop_items(positions: pd.DataFrame, session: dt.date) -> pd.DataFrame:
    """Open positions at or through their stop (long: below it; short: above it)."""
    if positions.empty or "order_stop" not in positions:
        return pd.DataFrame(columns=ITEM_COLUMNS)
    out = []
    for r in positions.dropna(subset=["order_stop"]).to_dict("records"):
        short = str(r.get("direction", "long")).lower() in ("short", "-1")
        out.append(
            {
                "key": f"stop:{r['ticker']}:{r.get('entry_date')}:{session}",
                "kind": "stop",
                "ticker": r["ticker"],
                "level": float(r["order_stop"]),
                "direction": "above" if short else "below",
                "note": "your stop",
                "plan_stop": None,
            }
        )
    return pd.DataFrame(out, columns=ITEM_COLUMNS)


def own_items(mine: pd.DataFrame) -> pd.DataFrame:
    out = [
        {
            "key": f"mine:{r['alert_id']}",
            "kind": "mine",
            "ticker": r["ticker"],
            "level": float(r["level"]),
            "direction": r["direction"],
            "note": r.get("note") or "",
            "plan_stop": None,
        }
        for r in mine.to_dict("records")
    ]
    return pd.DataFrame(out, columns=ITEM_COLUMNS)


def hits(items: pd.DataFrame, prices: dict[str, float], done: set[str]) -> pd.DataFrame:
    """The items whose price crossed their level and haven't fired yet, with the price."""
    if items.empty:
        return items.assign(price=pd.Series(dtype=float))
    price = items["ticker"].map(prices)
    above = (items["direction"] == "above") & (price >= items["level"])
    below = (items["direction"] == "below") & (price <= items["level"])
    out = items[(above | below) & ~items["key"].isin(done)]
    return out.assign(price=price[out.index])


def message(hit: dict, when: str) -> tuple[str, str]:
    """(title, body) of one push."""
    t, level, price = hit["ticker"], hit["level"], hit["price"]
    if hit["kind"] == "pivot":
        title = f"🎯 {t} over its {hit['note']} pivot {level:.2f}"
        body = f"Now {price:.2f} · {when}"
        if hit.get("plan_stop"):
            body += f"\nPlan: buy · stop {hit['plan_stop']:.2f} (C, no grade)"
    elif hit["kind"] == "stop":
        title = f"🛑 {t} at your stop {level:.2f}"
        body = f"Now {price:.2f} · {when}"
    else:
        word = "over" if hit["direction"] == "above" else "under"
        title = f"🔔 {t} {word} {level:.2f}"
        body = f"Now {price:.2f} · {when}" + (f"\n{hit['note']}" if hit.get("note") else "")
    return title, body
