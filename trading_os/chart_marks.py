"""Your saved chart drawings (Emil, 20 Oct 2026): trend lines and anchored-VWAP anchors per
ticker, kept in the private data repo (data/chart_marks/) as an append-only event log: every
add and remove is a new row; a mark is current while its latest event is an add.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from trading_os.journal import normalize_ticker
from trading_os.store import PARQUET_OPTIONS, unique_stamp

COLUMNS = [
    "mark_id",
    "action",
    "kind",
    "ticker",
    "label",
    "x0",
    "y0",
    "x1",
    "y1",
    "extend",
    "anchor",
    "saved_ts",
]


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "chart_marks"


def _write(data_dir: Path, row: dict) -> None:
    out = folder(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=COLUMNS)
    frame.to_parquet(out / f"{row['saved_ts']:%Y%m%dT%H%M%S%f}.parquet", **PARQUET_OPTIONS)


def _new_id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def add_line(data_dir, ticker, x0, y0: float, x1, y1: float, label="", extend=True) -> str:
    """Save a trend line through two (date, price) points; returns its id."""
    stamp = unique_stamp()
    ticker = normalize_ticker(ticker)
    mark_id = _new_id("line", ticker, x0, y0, x1, y1, stamp.isoformat())
    _write(
        data_dir,
        {
            "mark_id": mark_id,
            "action": "add",
            "kind": "line",
            "ticker": ticker,
            "label": label,
            "x0": pd.Timestamp(x0).date(),
            "y0": float(y0),
            "x1": pd.Timestamp(x1).date(),
            "y1": float(y1),
            "extend": bool(extend),
            "saved_ts": stamp,
        },
    )
    return mark_id


def add_anchor(data_dir, ticker, anchor, label="") -> str:
    """Save an anchored-VWAP anchor date; returns its id."""
    stamp = unique_stamp()
    ticker = normalize_ticker(ticker)
    mark_id = _new_id("anchor", ticker, anchor, stamp.isoformat())
    _write(
        data_dir,
        {
            "mark_id": mark_id,
            "action": "add",
            "kind": "anchor",
            "ticker": ticker,
            "label": label,
            "anchor": pd.Timestamp(anchor).date(),
            "saved_ts": stamp,
        },
    )
    return mark_id


def remove(data_dir, mark_id: str) -> None:
    _write(data_dir, {"mark_id": mark_id, "action": "remove", "saved_ts": unique_stamp()})


def current(data_dir, ticker: str) -> pd.DataFrame:
    """The ticker's marks whose latest event is an add."""
    files = sorted(folder(data_dir).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    events = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    latest = events.sort_values("saved_ts").drop_duplicates("mark_id", keep="last")
    adds = events[events["action"] == "add"].drop_duplicates("mark_id")
    alive = set(latest.loc[latest["action"] == "add", "mark_id"])
    out = adds[adds["mark_id"].isin(alive) & (adds["ticker"] == normalize_ticker(ticker))]
    return out.reset_index(drop=True)


def _same(a: dict, b: dict, tol: float = 1e-4) -> bool:
    return (
        str(a["x0"]) == str(b["x0"])
        and str(a["x1"]) == str(b["x1"])
        and abs(float(a["y0"]) - float(b["y0"])) <= tol * max(1.0, abs(float(b["y0"])))
        and abs(float(a["y1"]) - float(b["y1"])) <= tol * max(1.0, abs(float(b["y1"])))
    )


def drawn_changes(rendered: dict, shapes: list[dict]):
    """What you changed with the chart's pen. `rendered`: saved line id -> its points as the
    chart drew them; `shapes`: the chart's lines now ({id or None, x0, y0, x1, y1, past_end}).
    Returns (new lines, erased ids, moved: id -> new points). A line with both ends on one day
    has no slope and is left out."""
    shapes = [s for s in shapes if str(s["x0"]) != str(s["x1"])]
    new = [s for s in shapes if not s.get("id")]
    now = {s["id"]: s for s in shapes if s.get("id")}
    erased = [i for i in rendered if i not in now]
    moved = {i: s for i, s in now.items() if i in rendered and not _same(s, rendered[i])}
    return new, erased, moved


def apply_drawn(data_dir, ticker: str, report: dict, saved: pd.DataFrame) -> dict[str, int]:
    """Save the chart's report (see `drawn_changes`): new lines are added (extended to today
    when drawn past the last bar), erased ones removed, moved ones replaced keeping their name
    and extension. `saved`: the ticker's current marks. Returns counts."""
    if normalize_ticker(report.get("ticker", "")) != normalize_ticker(ticker):
        return {"added": 0, "removed": 0, "moved": 0}
    new, erased, moved = drawn_changes(report.get("rendered") or {}, report.get("shapes") or [])
    known = saved.set_index("mark_id") if len(saved) else pd.DataFrame()
    for s in new:
        add_line(data_dir, ticker, s["x0"], s["y0"], s["x1"], s["y1"], "", bool(s["past_end"]))
    for mark_id in erased:
        remove(data_dir, mark_id)
    for mark_id, s in moved.items():
        old = known.loc[mark_id] if mark_id in known.index else {}
        label = old.get("label") if isinstance(old.get("label"), str) else ""
        extend = bool(old.get("extend") == 1) or bool(s["past_end"])  # NaN/None: not extended
        remove(data_dir, mark_id)
        add_line(data_dir, ticker, s["x0"], s["y0"], s["x1"], s["y1"], label, extend)
    return {"added": len(new), "removed": len(erased), "moved": len(moved)}
